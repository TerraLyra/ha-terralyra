"""EUMETSAT MTG active-fire provider adapter."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..api import LsaSafAuthError, LsaSafError
from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from ..products.fire import ActiveFireClient, LsaSafNoDataError
from .base import (
    ProviderAuthenticationError,
    ProviderNoDataError,
    ProviderUnavailableError,
)

PROVIDER = "eumetsat_lsa_saf"
SATELLITE = "mtg"
PRODUCT = "MTFRPPixel"
SOURCE_RESOLUTION_KM = 1.0
DELAY_THRESHOLD = timedelta(minutes=60)


class MtgActiveFireProvider:
    """Normalize MTFRPPixel products for the common wildfire pipeline."""

    def __init__(self, client: ActiveFireClient) -> None:
        self._client = client

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Fetch the latest MTG product and normalize all valid pixels."""
        try:
            product = await self._client.async_fetch_latest()
        except LsaSafAuthError as err:
            raise ProviderAuthenticationError(str(err)) from err
        except LsaSafNoDataError as err:
            raise ProviderNoDataError(str(err)) from err
        except LsaSafError as err:
            raise ProviderUnavailableError(str(err)) from err
        received = datetime.now(UTC)
        detections = tuple(
            FireDetection(
                provider=PROVIDER,
                satellite=SATELLITE,
                product=PRODUCT,
                timestamp=pixel.acquired,
                latitude=pixel.latitude,
                longitude=pixel.longitude,
                frp_mw=pixel.frp_mw,
                frp_uncertainty_mw=pixel.frp_uncertainty_mw,
                confidence=pixel.confidence,
                fire_area_km2=pixel.pixel_size_km2,
                source_resolution_km=SOURCE_RESOLUTION_KM,
                source_detection_id=(
                    f"{pixel.acquired.isoformat()}:{pixel.abs_line}:{pixel.abs_samp}"
                    if pixel.abs_line is not None and pixel.abs_samp is not None
                    else None
                ),
            )
            for pixel in product.pixels
        )
        return ProviderSnapshot(
            provider=PROVIDER,
            satellite=SATELLITE,
            product=PRODUCT,
            product_timestamp=product.product_time,
            received_timestamp=received,
            status=(
                ProviderStatus.DELAYED
                if received - product.product_time > DELAY_THRESHOLD
                else ProviderStatus.AVAILABLE
            ),
            source_url=product.url,
            filename=product.filename,
            detections=detections,
        )
