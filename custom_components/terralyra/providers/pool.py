"""Equal-peer active-fire provider pool selected from monitored locations."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from .base import (
    ActiveFireProviderError,
    ActiveFireProvider,
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNoDataError,
    ProviderUnavailableError,
)

PROVIDER_RETRY_BASE = timedelta(minutes=5)
PROVIDER_RETRY_MAX = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """One provider instance and the monitored locations it can observe."""

    provider_id: str
    label: str
    satellite: str
    location_ids: tuple[str, ...]
    provider: ActiveFireProvider


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Bounded status information for one equal provider."""

    provider_id: str
    label: str
    satellite: str
    location_ids: tuple[str, ...]
    status: ProviderStatus
    failure_type: str | None = None
    consecutive_failures: int = 0
    retry_at: datetime | None = None

    def attrs(self) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "name": self.label,
            "satellite": self.satellite,
            "location_ids": list(self.location_ids),
            "status": self.status.value,
            "failure_type": self.failure_type,
            "consecutive_failures": self.consecutive_failures,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
        }


@dataclass(frozen=True, slots=True)
class _DeferredProvider:
    """A provider still inside its bounded retry window."""

    error: ActiveFireProviderError


class MultiProviderPool:
    """Fetch all geographically relevant providers as equal peers."""

    def __init__(
        self,
        bindings: tuple[ProviderBinding, ...],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not bindings:
            raise ValueError("No active-fire source is configured for any enabled location")
        self.bindings = bindings
        self._now = now or (lambda: datetime.now(UTC))
        self._failure_counts: dict[str, int] = {}
        self._retry_at: dict[str, datetime] = {}
        self._last_errors: dict[str, ActiveFireProviderError] = {}
        self.health: tuple[ProviderHealth, ...] = tuple(
            ProviderHealth(
                binding.provider_id,
                binding.label,
                binding.satellite,
                binding.location_ids,
                ProviderStatus.INITIALIZING,
            )
            for binding in bindings
        )

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Merge every successful provider; one outage never blocks its peers."""
        results = await asyncio.gather(
            *(self._async_fetch_binding(binding) for binding in self.bindings),
            return_exceptions=True,
        )
        snapshots: list[ProviderSnapshot] = []
        health: list[ProviderHealth] = []
        for binding, result in zip(self.bindings, results, strict=True):
            if isinstance(result, ProviderSnapshot):
                snapshots.append(result)
                status = result.status
            else:
                error = result.error if isinstance(result, _DeferredProvider) else result
                status = self._status_for_error(error)
            failure_count = self._failure_counts.get(binding.provider_id, 0)
            last_error = self._last_errors.get(binding.provider_id)
            health.append(
                ProviderHealth(
                    binding.provider_id,
                    binding.label,
                    binding.satellite,
                    binding.location_ids,
                    status,
                    last_error.failure_type if last_error else None,
                    failure_count,
                    self._retry_at.get(binding.provider_id),
                )
            )
        self.health = tuple(health)

        if not snapshots:
            errors = [
                result.error if isinstance(result, _DeferredProvider) else result
                for result in results
                if isinstance(result, (Exception, _DeferredProvider))
            ]
            retry_after = self._earliest_retry()
            if errors and all(isinstance(error, ProviderAuthenticationError) for error in errors):
                raise ProviderAuthenticationError(
                    "All assigned active-fire sources rejected authentication",
                    retry_after=retry_after,
                )
            if errors and all(isinstance(error, ProviderNoDataError) for error in errors):
                raise ProviderNoDataError(
                    "No assigned active-fire source has a current product",
                    retry_after=retry_after,
                )
            raise ProviderUnavailableError(
                "All assigned active-fire sources are unavailable",
                retry_after=retry_after,
            )

        detections: dict[tuple[Any, ...], FireDetection] = {}
        for snapshot in snapshots:
            for detection in snapshot.detections:
                key = (
                    detection.provider,
                    detection.satellite,
                    detection.source_detection_id
                    or (
                        detection.timestamp,
                        round(detection.latitude, 5),
                        round(detection.longitude, 5),
                    ),
                )
                detections[key] = detection

        provider_names = sorted({snapshot.provider for snapshot in snapshots})
        satellites = sorted({snapshot.satellite for snapshot in snapshots})
        return ProviderSnapshot(
            provider="+".join(provider_names),
            satellite=" / ".join(satellites),
            product="TerraLyra automatic multi-source active fire",
            product_timestamp=max(snapshot.product_timestamp for snapshot in snapshots),
            received_timestamp=max(snapshot.received_timestamp for snapshot in snapshots),
            status=(
                ProviderStatus.AVAILABLE
                if any(snapshot.status is ProviderStatus.AVAILABLE for snapshot in snapshots)
                else ProviderStatus.DELAYED
            ),
            source_url="https://github.com/TerraLyra/ha-terralyra",
            filename="terralyra-multi-source",
            detections=tuple(
                sorted(
                    detections.values(),
                    key=lambda detection: (
                        detection.timestamp,
                        detection.provider,
                        detection.satellite,
                        detection.source_detection_id or "",
                    ),
                )
            ),
        )

    async def _async_fetch_binding(
        self, binding: ProviderBinding
    ) -> ProviderSnapshot | _DeferredProvider:
        """Fetch one peer unless its last failure still requires backoff."""
        now = self._now()
        retry_at = self._retry_at.get(binding.provider_id)
        if retry_at is not None and now < retry_at:
            return _DeferredProvider(self._last_errors[binding.provider_id])

        try:
            snapshot = await binding.provider.async_fetch_latest()
        except ActiveFireProviderError as err:
            self._record_failure(binding.provider_id, err, now)
            return err
        except Exception:
            error = ProviderInvalidResponseError(
                "Provider raised an unexpected error while fetching data"
            )
            self._record_failure(binding.provider_id, error, now)
            return error

        self._failure_counts.pop(binding.provider_id, None)
        self._retry_at.pop(binding.provider_id, None)
        self._last_errors.pop(binding.provider_id, None)
        return snapshot

    def _record_failure(
        self,
        provider_id: str,
        error: ActiveFireProviderError,
        now: datetime,
    ) -> None:
        failure_count = self._failure_counts.get(provider_id, 0) + 1
        self._failure_counts[provider_id] = failure_count
        self._last_errors[provider_id] = error
        delay = error.retry_after or self._retry_delay(failure_count)
        self._retry_at[provider_id] = now + min(delay, PROVIDER_RETRY_MAX)

    @staticmethod
    def _retry_delay(failure_count: int) -> timedelta:
        multiplier = 2 ** max(0, failure_count - 1)
        return min(PROVIDER_RETRY_BASE * multiplier, PROVIDER_RETRY_MAX)

    @staticmethod
    def _status_for_error(error: object) -> ProviderStatus:
        if isinstance(error, ProviderAuthenticationError):
            return ProviderStatus.AUTH_ERROR
        if isinstance(error, ProviderNoDataError):
            return ProviderStatus.NO_PRODUCT
        return ProviderStatus.OUTAGE

    def _earliest_retry(self) -> timedelta | None:
        """Return a bounded delay until the first assigned peer may be retried."""
        now = self._now()
        delays = [retry_at - now for retry_at in self._retry_at.values() if retry_at > now]
        return min(delays) if delays else None
