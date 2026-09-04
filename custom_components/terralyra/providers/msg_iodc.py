"""MSG Indian Ocean Data Coverage selection and active-fire provider."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientSession

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from ..products.msg_iodc import (
    MsgIodcAuthenticationError,
    MsgIodcNoDataError,
    MsgIodcRateLimitError,
    MsgIodcSchemaError,
    MsgIodcTimeoutError,
    MsgIodcUnavailableError,
    async_fetch_latest_list_product,
    decode_list_product,
)
from .base import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderNoDataError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

# Meteosat-9 currently provides the MSG IODC service from 45.5 degrees east.
# The 70-degree limit is deliberately stricter than the geometric horizon.
# The decoder separately validates product identity, quality and pixel coordinates.
MSG_IODC_SUB_SATELLITE_LONGITUDE = 45.5
MAX_USABLE_CENTRAL_ANGLE_DEGREES = 70.0
PROVIDER = "eumetsat_lsa_saf_iodc"
SATELLITE = "Meteosat-9 IODC"
PRODUCT = "FRPPixel IODC"
SOURCE_FAMILY = "lsa_saf_frp_pixel"
SOURCE_RESOLUTION_KM = 3.1
DELAY_THRESHOLD = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class MsgIodcCoverage:
    """Selected IODC satellite and its geometric viewing angle."""

    satellite: str
    central_angle_degrees: float


class MsgIodcActiveFireProvider:
    """Download and normalize Meteosat-9 IODC FRP-PIXEL observations."""

    def __init__(
        self,
        session: ClientSession,
        run_in_executor: Callable[..., Awaitable[Any]],
        *,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._run_in_executor = run_in_executor
        self._username = username
        self._password = password

    async def async_fetch_latest(self) -> ProviderSnapshot:
        """Fetch the latest IODC product and convert it to the shared model."""
        try:
            filename, payload = await async_fetch_latest_list_product(
                self._session, self._username, self._password
            )
            product = await self._run_in_executor(
                decode_list_product, filename, payload
            )
        except MsgIodcAuthenticationError as err:
            raise ProviderAuthenticationError(str(err)) from err
        except MsgIodcNoDataError as err:
            raise ProviderNoDataError(str(err)) from err
        except MsgIodcRateLimitError as err:
            raise ProviderRateLimitError(
                str(err), retry_after=err.retry_after
            ) from err
        except MsgIodcTimeoutError as err:
            raise ProviderTimeoutError(str(err)) from err
        except MsgIodcUnavailableError as err:
            raise ProviderUnavailableError(
                str(err), retry_after=err.retry_after
            ) from err
        except MsgIodcSchemaError as err:
            raise ProviderInvalidResponseError(str(err)) from err

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
                    f"{pixel.acquired.isoformat()}:{pixel.abs_line}:{pixel.abs_pixel}"
                    if pixel.abs_line is not None and pixel.abs_pixel is not None
                    else None
                ),
                source_family=SOURCE_FAMILY,
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


def select_msg_iodc_satellite(
    latitude: float, longitude: float
) -> MsgIodcCoverage | None:
    """Return Meteosat-9 when a location is conservatively visible.

    This is a pre-download gate only. Product identity, quality and decoded
    pixel coordinates remain authoritative during each bounded update.
    """
    _validate_coordinate(latitude, longitude)
    central_angle = _central_angle(latitude, longitude)
    if central_angle > MAX_USABLE_CENTRAL_ANGLE_DEGREES:
        return None
    return MsgIodcCoverage("Meteosat-9 IODC", central_angle)


def _central_angle(latitude: float, longitude: float) -> float:
    latitude_radians = math.radians(latitude)
    longitude_delta = math.radians(
        longitude - MSG_IODC_SUB_SATELLITE_LONGITUDE
    )
    cosine = math.cos(latitude_radians) * math.cos(longitude_delta)
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("MSG-IODC coverage coordinates must be finite")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError("MSG-IODC coverage coordinates are out of range")
