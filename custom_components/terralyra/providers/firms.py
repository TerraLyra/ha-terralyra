"""NASA FIRMS VIIRS provider adapter for the common active-fire model."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
