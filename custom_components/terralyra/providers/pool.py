"""Equal-peer active-fire provider pool selected from monitored locations."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from .base import (
    ActiveFireProvider,
    ProviderAuthenticationError,
    ProviderNoDataError,
    ProviderUnavailableError,
)


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

    def attrs(self) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "name": self.label,
            "satellite": self.satellite,
            "location_ids": list(self.location_ids),
            "status": self.status.value,
        }


class MultiProviderPool:
    """Fetch all geographically relevant providers as equal peers."""

    def __init__(self, bindings: tuple[ProviderBinding, ...]) -> None:
        if not bindings:
            raise ValueError("No active-fire source is configured for any enabled location")
        self.bindings = bindings
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
            *(binding.provider.async_fetch_latest() for binding in self.bindings),
            return_exceptions=True,
        )
        snapshots: list[ProviderSnapshot] = []
        health: list[ProviderHealth] = []
        for binding, result in zip(self.bindings, results, strict=True):
            if isinstance(result, ProviderSnapshot):
                snapshots.append(result)
                status = result.status
            elif isinstance(result, ProviderAuthenticationError):
                status = ProviderStatus.AUTH_ERROR
            elif isinstance(result, ProviderNoDataError):
                status = ProviderStatus.NO_PRODUCT
            else:
                status = ProviderStatus.OUTAGE
            health.append(
                ProviderHealth(
                    binding.provider_id,
                    binding.label,
                    binding.satellite,
                    binding.location_ids,
                    status,
                )
            )
        self.health = tuple(health)

        if not snapshots:
            errors = [result for result in results if isinstance(result, Exception)]
            if errors and all(isinstance(error, ProviderAuthenticationError) for error in errors):
                raise ProviderAuthenticationError("All assigned active-fire sources rejected authentication")
            if errors and all(isinstance(error, ProviderNoDataError) for error in errors):
                raise ProviderNoDataError("No assigned active-fire source has a current product")
            raise ProviderUnavailableError("All assigned active-fire sources are unavailable")

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
