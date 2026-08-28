"""NASA FIRMS VIIRS provider adapter for the common active-fire model."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import math

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from ..products.firms import (
    FirmsAuthenticationError,
    FirmsClient,
    FirmsError,
)
from .base import ProviderAuthenticationError, ProviderUnavailableError

PROVIDER = "nasa_firms"
PRODUCT = "VIIRS active fire NRT"
SOURCE_RESOLUTION_KM = 0.375
DELAY_THRESHOLD = timedelta(hours=6)
PUBLIC_SOURCE_URL = "https://firms.modaps.eosdis.nasa.gov/"
SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
MIN_REFRESH_INTERVAL = timedelta(minutes=15)


class FirmsActiveFireProvider:
    """Normalize a bounded FIRMS VIIRS area query."""

    def __init__(
        self,
        client: FirmsClient,
        *,
        source: str,
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> None:
        self._client = client
        self._source = source
        self._bounds = (west, south, east, north)

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Fetch and normalize the latest bounded FIRMS response."""
        try:
            records = await self._client.async_area(
                source=self._source,
                west=self._bounds[0],
                south=self._bounds[1],
                east=self._bounds[2],
                north=self._bounds[3],
            )
        except FirmsAuthenticationError as err:
            raise ProviderAuthenticationError(str(err)) from err
        except FirmsError as err:
            raise ProviderUnavailableError(str(err)) from err

        received = datetime.now(UTC)
        product_time = max(
            (record.acquired for record in records),
            default=received,
        )
        detections = tuple(
            FireDetection(
                provider=PROVIDER,
                satellite=record.satellite,
                product=f"{PRODUCT} ({record.source})",
                timestamp=record.acquired,
                latitude=record.latitude,
                longitude=record.longitude,
                frp_mw=record.frp_mw,
                # FIRMS VIIRS confidence is categorical; preserve it instead
                # of presenting a fabricated probability to Home Assistant.
                confidence=None,
                classification=record.confidence_category,
                source_resolution_km=SOURCE_RESOLUTION_KM,
                source_detection_id=(
                    f"{record.source}:{record.satellite}:"
                    f"{record.acquired.isoformat()}:{record.latitude:.5f}:"
                    f"{record.longitude:.5f}"
                ),
            )
            for record in records
        )
        return ProviderSnapshot(
            provider=PROVIDER,
            satellite="viirs",
            product=f"{PRODUCT} ({self._source})",
            product_timestamp=product_time,
            received_timestamp=received,
            status=(
                ProviderStatus.DELAYED
                if records and received - product_time > DELAY_THRESHOLD
                else ProviderStatus.AVAILABLE
            ),
            # Never expose the credential-bearing request URL.
            source_url=PUBLIC_SOURCE_URL,
            filename=f"firms-{self._source.lower()}-area.csv",
            detections=detections,
        )


class FirmsMultiSatelliteProvider:
    """Fetch both supported VIIRS feeds as one independent provider snapshot."""

    def __init__(
        self,
        client: FirmsClient,
        *,
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> None:
        self._providers = tuple(
            FirmsActiveFireProvider(
                client,
                source=source,
                west=west,
                south=south,
                east=east,
                north=north,
            )
            for source in SOURCES
        )
        self._cached_snapshot: ProviderSnapshot | None = None
        self._cached_at: datetime | None = None

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Return all successful NOAA-20/21 observations without double counting sources."""
        now = datetime.now(UTC)
        if (
            self._cached_snapshot is not None
            and self._cached_at is not None
            and now - self._cached_at < MIN_REFRESH_INTERVAL
        ):
            return self._cached_snapshot
        results = await asyncio.gather(
            *(provider.async_fetch_latest() for provider in self._providers),
            return_exceptions=True,
        )
        snapshots = [result for result in results if isinstance(result, ProviderSnapshot)]
        auth_errors = [
            result for result in results if isinstance(result, ProviderAuthenticationError)
        ]
        if auth_errors:
            raise auth_errors[0]
        if not snapshots:
            errors = [result for result in results if isinstance(result, Exception)]
            detail = str(errors[0]) if errors else "NASA FIRMS returned no snapshot"
            raise ProviderUnavailableError(detail)
        detections = tuple(
            sorted(
                (detection for snapshot in snapshots for detection in snapshot.detections),
                key=lambda detection: (
                    detection.timestamp,
                    detection.satellite,
                    detection.source_detection_id or "",
                ),
            )
        )
        snapshot = ProviderSnapshot(
            provider=PROVIDER,
            satellite="NOAA-20/NOAA-21 VIIRS",
            product="VIIRS active fire NRT",
            product_timestamp=max(snapshot.product_timestamp for snapshot in snapshots),
            received_timestamp=max(snapshot.received_timestamp for snapshot in snapshots),
            status=(
                ProviderStatus.AVAILABLE
                if any(snapshot.status is ProviderStatus.AVAILABLE for snapshot in snapshots)
                else ProviderStatus.DELAYED
            ),
            source_url=PUBLIC_SOURCE_URL,
            filename="firms-viirs-noaa20-noaa21-area.csv",
            detections=detections,
        )
        self._cached_snapshot = snapshot
        self._cached_at = now
        return snapshot


def monitoring_bounds(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Build a bounded, non-wrapping FIRMS box around Home."""
    if not all(math.isfinite(value) for value in (latitude, longitude, radius_km)):
        raise ValueError("FIRMS monitoring bounds must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Home coordinates are out of range")
    if radius_km <= 0 or radius_km > 500:
        raise ValueError("FIRMS monitoring radius is out of range")
    latitude_delta = radius_km / 110.574
    cosine = max(0.1, abs(math.cos(math.radians(latitude))))
    longitude_delta = min(9.9, radius_km / (111.320 * cosine))
    south = max(-90.0, latitude - latitude_delta)
    north = min(90.0, latitude + latitude_delta)
    west = max(-180.0, longitude - longitude_delta)
    east = min(180.0, longitude + longitude_delta)
    if west >= east or south >= north:
        raise ValueError("FIRMS monitoring bounds cannot cross the antimeridian")
    return west, south, east, north
