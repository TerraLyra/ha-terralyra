"""Provider adapter for optional NOAA GOES active-fire observations."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientSession

from ..models import ProviderSnapshot, ProviderStatus
from ..products.goes import (
    GoesDiscoveryClient,
    GoesDiscoveryError,
    GoesProductClient,
    GoesProductError,
)
from .base import ProviderNoDataError, ProviderUnavailableError
from .goes import GoesCoverage, select_goes_satellite

DELAYED_AFTER = timedelta(minutes=30)
STALE_AFTER = timedelta(hours=2)


class GoesActiveFireProvider:
    """Discover, download and normalize the best GOES full-disk product."""

    def __init__(
        self,
        session: ClientSession,
        run_in_executor: Callable[..., Awaitable[Any]],
        *,
        latitude: float,
        longitude: float,
        decoder: Callable[..., Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        coverage = select_goes_satellite(latitude, longitude)
        if coverage is None:
            raise ValueError("Home location is outside safe GOES coverage")
        self.coverage: GoesCoverage = coverage
        self._discovery = GoesDiscoveryClient(session)
        self._products = GoesProductClient(
            session,
            run_in_executor,
            decoder=decoder,
        )
        self._now = now or (lambda: datetime.now(UTC))

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Return the newest safe GOES snapshot with explicit freshness."""
        current = self._now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ProviderUnavailableError("GOES provider clock is invalid")
        current = current.astimezone(UTC)
        try:
            item = await self._discovery.async_latest(
                self.coverage.satellite,
                now=current,
            )
            if item is None:
                raise ProviderNoDataError("No recent GOES fire product is available")
            age = current - item.metadata.observation_end
            if age < timedelta(0) or age > STALE_AFTER:
                raise ProviderNoDataError("No current GOES fire product is available")
            snapshot = await self._products.async_fetch(item)
        except ProviderNoDataError:
            raise
        except (GoesDiscoveryError, GoesProductError) as err:
            raise ProviderUnavailableError(
                "GOES active-fire data is temporarily unavailable"
            ) from err
        if not isinstance(snapshot, ProviderSnapshot):
            raise ProviderUnavailableError("GOES decoder returned invalid data")
        expected = item.metadata
        if (
            snapshot.provider != "noaa_goes"
            or snapshot.satellite != self.coverage.satellite
            or snapshot.product != "ABI-L2-FDCF"
            or snapshot.product_timestamp != expected.observation_end
            or snapshot.filename != expected.filename
            or snapshot.source_url != item.public_url
        ):
            raise ProviderUnavailableError("GOES decoder identity mismatch")
        status = (
            ProviderStatus.DELAYED
            if current - snapshot.product_timestamp > DELAYED_AFTER
            else ProviderStatus.AVAILABLE
        )
        return replace(snapshot, status=status)
