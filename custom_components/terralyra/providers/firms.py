"""NASA FIRMS polar-orbiting provider adapter for the active-fire model."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from ..products.firms import (
    FirmsAuthenticationError,
    FirmsClient,
    FirmsError,
    FirmsInvalidResponseError,
    FirmsRateLimitError,
    FirmsTemporaryServiceError,
    FirmsTimeoutError,
)
from .base import (
    ActiveFireProviderError,
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

PROVIDER = "nasa_firms"
PRODUCTS = {
    "VIIRS_NOAA20_NRT": ("VIIRS active fire NRT", 0.375),
    "VIIRS_NOAA21_NRT": ("VIIRS active fire NRT", 0.375),
    "MODIS_NRT": ("MODIS active fire NRT", 1.0),
}
DELAY_THRESHOLD = timedelta(hours=6)
PUBLIC_SOURCE_URL = "https://firms.modaps.eosdis.nasa.gov/"
SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
SATELLITE_SUMMARY = "NOAA-20/NOAA-21 VIIRS + Terra/Aqua MODIS"
PRODUCT_SUMMARY = "VIIRS and MODIS active fire NRT"
MIN_REFRESH_INTERVAL = timedelta(minutes=15)
MAX_MONITORING_AREAS = 10


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
        except FirmsRateLimitError as err:
            raise ProviderRateLimitError(str(err), retry_after=err.retry_after) from err
        except FirmsTimeoutError as err:
            raise ProviderTimeoutError(str(err)) from err
        except FirmsTemporaryServiceError as err:
            raise ProviderUnavailableError(
                str(err), retry_after=err.retry_after
            ) from err
        except FirmsInvalidResponseError as err:
            raise ProviderInvalidResponseError(str(err)) from err
        except FirmsError as err:
            raise ProviderUnavailableError(str(err)) from err

        received = datetime.now(UTC)
        product_name, source_resolution_km = PRODUCTS[self._source]
        product_time = max(
            (record.acquired for record in records),
            default=received,
        )
        detections = tuple(
            FireDetection(
                provider=PROVIDER,
                satellite=record.satellite,
                product=f"{product_name} ({record.source})",
                timestamp=record.acquired,
                latitude=record.latitude,
                longitude=record.longitude,
                frp_mw=record.frp_mw,
                # Confidence semantics differ between FIRMS products; preserve
                # the source token instead of fabricating one probability.
                confidence=None,
                classification=record.confidence_category,
                source_resolution_km=source_resolution_km,
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
            satellite="VIIRS" if self._source.startswith("VIIRS_") else "MODIS",
            product=f"{product_name} ({self._source})",
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
    """Fetch supported VIIRS and MODIS feeds as one cached provider snapshot."""

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
        """Return successful polar observations without double counting sources."""
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
        snapshots = [
            result for result in results if isinstance(result, ProviderSnapshot)
        ]
        auth_errors = [
            result
            for result in results
            if isinstance(result, ProviderAuthenticationError)
        ]
        if auth_errors:
            raise auth_errors[0]
        if not snapshots:
            errors = [result for result in results if isinstance(result, Exception)]
            normalized = next(
                (
                    error
                    for error in errors
                    if isinstance(error, ActiveFireProviderError)
                ),
                None,
            )
            if normalized is not None:
                raise normalized
            detail = str(errors[0]) if errors else "NASA FIRMS returned no snapshot"
            raise ProviderUnavailableError(detail)
        detections = tuple(
            sorted(
                (
                    detection
                    for snapshot in snapshots
                    for detection in snapshot.detections
                ),
                key=lambda detection: (
                    detection.timestamp,
                    detection.satellite,
                    detection.source_detection_id or "",
                ),
            )
        )
        snapshot = ProviderSnapshot(
            provider=PROVIDER,
            satellite=SATELLITE_SUMMARY,
            product=PRODUCT_SUMMARY,
            product_timestamp=max(snapshot.product_timestamp for snapshot in snapshots),
            received_timestamp=max(
                snapshot.received_timestamp for snapshot in snapshots
            ),
            status=(
                ProviderStatus.AVAILABLE
                if any(
                    snapshot.status is ProviderStatus.AVAILABLE
                    for snapshot in snapshots
                )
                else ProviderStatus.DELAYED
            ),
            source_url=PUBLIC_SOURCE_URL,
            filename="firms-viirs-modis-area.csv",
            detections=detections,
        )
        self._cached_snapshot = snapshot
        self._cached_at = now
        return snapshot


class FirmsMultiAreaProvider:
    """Fetch bounded FIRMS observations for multiple monitored areas."""

    def __init__(
        self,
        client: FirmsClient,
        bounds: tuple[tuple[float, float, float, float], ...],
    ) -> None:
        planned = merge_monitoring_bounds(bounds)
        if not planned or len(planned) > MAX_MONITORING_AREAS:
            raise ValueError("FIRMS monitoring-area count is out of range")
        self._providers = tuple(
            FirmsMultiSatelliteProvider(
                client,
                west=west,
                south=south,
                east=east,
                north=north,
            )
            for west, south, east, north in planned
        )
        self._cached_snapshot: ProviderSnapshot | None = None
        self._cached_at: datetime | None = None

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Return one deduplicated snapshot spanning every planned area."""
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
        snapshots = [
            result for result in results if isinstance(result, ProviderSnapshot)
        ]
        auth_errors = [
            result
            for result in results
            if isinstance(result, ProviderAuthenticationError)
        ]
        if not snapshots:
            if auth_errors:
                raise auth_errors[0]
            errors = [result for result in results if isinstance(result, Exception)]
            normalized = next(
                (
                    error
                    for error in errors
                    if isinstance(error, ActiveFireProviderError)
                ),
                None,
            )
            if normalized is not None:
                raise normalized
            detail = str(errors[0]) if errors else "NASA FIRMS returned no snapshot"
            raise ProviderUnavailableError(detail)

        detections_by_id: dict[str, FireDetection] = {}
        for snapshot in snapshots:
            for detection in snapshot.detections:
                detection_id = detection.source_detection_id or (
                    f"{detection.provider}:{detection.satellite}:"
                    f"{detection.timestamp.isoformat()}:{detection.latitude:.5f}:"
                    f"{detection.longitude:.5f}"
                )
                detections_by_id[detection_id] = detection
        snapshot = ProviderSnapshot(
            provider=PROVIDER,
            satellite=SATELLITE_SUMMARY,
            product=PRODUCT_SUMMARY,
            product_timestamp=max(item.product_timestamp for item in snapshots),
            received_timestamp=max(item.received_timestamp for item in snapshots),
            status=(
                ProviderStatus.AVAILABLE
                if any(item.status is ProviderStatus.AVAILABLE for item in snapshots)
                else ProviderStatus.DELAYED
            ),
            source_url=PUBLIC_SOURCE_URL,
            filename=f"firms-polar-{len(self._providers)}-areas.csv",
            detections=tuple(
                sorted(
                    detections_by_id.values(),
                    key=lambda detection: (
                        detection.timestamp,
                        detection.satellite,
                        detection.source_detection_id or "",
                    ),
                )
            ),
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


def merge_monitoring_bounds(
    bounds: tuple[tuple[float, float, float, float], ...],
) -> tuple[tuple[float, float, float, float], ...]:
    """Merge overlapping safe boxes while keeping distant requests separate."""
    if len(bounds) > MAX_MONITORING_AREAS:
        raise ValueError("Too many FIRMS monitoring areas")
    planned: list[tuple[float, float, float, float]] = []
    for candidate in sorted(bounds):
        west, south, east, north = candidate
        if (
            not all(math.isfinite(value) for value in candidate)
            or not -180 <= west < east <= 180
            or not -90 <= south < north <= 90
            or east - west > 20
            or north - south > 20
        ):
            raise ValueError("FIRMS monitoring bounds are invalid")
        merged = False
        for index, existing in enumerate(planned):
            if not _bounds_overlap(existing, candidate):
                continue
            union = (
                min(existing[0], west),
                min(existing[1], south),
                max(existing[2], east),
                max(existing[3], north),
            )
            if union[2] - union[0] <= 20 and union[3] - union[1] <= 20:
                planned[index] = union
                merged = True
                break
        if not merged:
            planned.append(candidate)
    return tuple(planned)


def _bounds_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    """Return whether two non-wrapping boxes overlap or touch."""
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )
