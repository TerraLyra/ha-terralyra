"""Safe point client for the public MTG Land Surface Temperature WMS."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

PRODUCT_ID = "MTLST"
LSA_ID = "LSA-007"
WMS_DATASET = "MTG-LST"
WMS_URL = "https://adaguc.lsasvcs.ipma.pt//adagucserver"
TEMPORAL_RESOLUTION_MINUTES = 10
SPATIAL_RESOLUTION_KM = 2
TIMEOUT = ClientTimeout(total=20, connect=5, sock_read=15)
MAX_JSON_BYTES = 32 * 1024
USER_AGENT = "ha-terralyra/0.7.0 (https://github.com/TerraLyra/ha-terralyra)"
WMS_BOUNDS = (-73.113074, -74.196257, 73.113074, 74.196257)


class LandSurfaceTemperatureError(Exception):
    """An MTLST request or response was invalid."""


@dataclass(frozen=True, slots=True)
class LandSurfaceTemperature:
    """One validated MTLST value at the Home location."""

    temperature_kelvin: float | None
    uncertainty_kelvin: float | None
    quality: str | None
    observed_at: datetime
    latitude: float
    longitude: float

    @property
    def temperature_celsius(self) -> float | None:
        if self.temperature_kelvin is None:
            return None
        return self.temperature_kelvin - 273.15


class LandSurfaceTemperatureClient:
    """Read a bounded MTLST point value from the official WMS host."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_point(
        self, latitude: float, longitude: float
    ) -> LandSurfaceTemperature:
        """Retrieve the latest published value at one validated coordinate."""
        _validate_coordinate(latitude, longitude)
        delta = 0.1
        params = {
            "DATASET": WMS_DATASET,
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetFeatureInfo",
            "LAYERS": "LST",
            "QUERY_LAYERS": "LST",
            "CRS": "EPSG:4326",
            # WMS 1.3.0 uses latitude,longitude axis order for EPSG:4326.
            "BBOX": (
                f"{latitude-delta},{longitude-delta},"
                f"{latitude+delta},{longitude+delta}"
            ),
            "WIDTH": "101",
            "HEIGHT": "101",
            "I": "50",
            "J": "50",
            "INFO_FORMAT": "application/json",
            "FEATURE_COUNT": "3",
        }
        return parse_feature_info(await self._async_get(params))

    async def _async_get(self, params: dict[str, str]) -> bytes:
        try:
            async with self._session.get(
                WMS_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise LandSurfaceTemperatureError(
                        "MTLST service returned an error"
                    )
                if (
                    response.content_length is not None
                    and response.content_length > MAX_JSON_BYTES
                ):
                    raise LandSurfaceTemperatureError(
                        "MTLST response exceeds the safety limit"
                    )
                data = bytearray()
                async for chunk in response.content.iter_chunked(8 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_JSON_BYTES:
                        raise LandSurfaceTemperatureError(
                            "MTLST response exceeds the safety limit"
                        )
                return bytes(data)
        except LandSurfaceTemperatureError:
            raise
        except (ClientError, TimeoutError) as err:
            raise LandSurfaceTemperatureError(
                "MTLST service is unavailable"
            ) from err


def parse_feature_info(payload: bytes) -> LandSurfaceTemperature:
    """Parse the bounded ADAGUC response by units and validate every value."""
    try:
        parsed: Any = json.loads(payload)
        if not isinstance(parsed, list) or not parsed:
            raise TypeError
        observed_at: datetime | None = None
        latitude: float | None = None
        longitude: float | None = None
        kelvin_values: list[float | None] = []
        quality: str | None = None
        for item in parsed:
            if not isinstance(item, dict) or item.get("name") != "LST":
                continue
            item_longitude, item_latitude = map(
                float, item["point"]["coords"].split(",")
            )
            data = item["data"]
            if not isinstance(data, dict) or len(data) != 1:
                raise TypeError
            raw_time, raw_value = next(iter(data.items()))
            if not isinstance(raw_time, str) or not raw_time.endswith("Z"):
                raise TypeError
            item_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if observed_at is not None and item_time != observed_at:
                raise TypeError
            if latitude is not None and (
                item_latitude != latitude or item_longitude != longitude
            ):
                raise TypeError
            observed_at = item_time
            latitude, longitude = item_latitude, item_longitude
            if item.get("units") == "K":
                if raw_value == "nodata":
                    kelvin_values.append(None)
                else:
                    value = float(raw_value)
                    if not math.isfinite(value):
                        raise ValueError
                    kelvin_values.append(value)
            elif item.get("units") == "UNITLESS":
                quality = str(raw_value).strip()[:128]
                if not quality or not quality.isprintable():
                    raise ValueError
        if (
            observed_at is None
            or latitude is None
            or longitude is None
            or not kelvin_values
        ):
            raise TypeError
        _validate_coordinate(latitude, longitude)
        if kelvin_values[0] is not None and not 150 <= kelvin_values[0] <= 400:
            raise ValueError
        if (
            len(kelvin_values) > 1
            and kelvin_values[1] is not None
            and not 0 <= kelvin_values[1] <= 50
        ):
            raise ValueError
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as err:
        raise LandSurfaceTemperatureError(
            "MTLST response has an unexpected shape"
        ) from err

    return LandSurfaceTemperature(
        temperature_kelvin=kelvin_values[0],
        uncertainty_kelvin=(kelvin_values[1] if len(kelvin_values) > 1 else None),
        quality=quality,
        observed_at=observed_at,
        latitude=latitude,
        longitude=longitude,
    )


def _validate_coordinate(latitude: float, longitude: float) -> None:
    west, south, east, north = WMS_BOUNDS
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise LandSurfaceTemperatureError("MTLST coordinate is not finite")
    if not south <= latitude <= north or not west <= longitude <= east:
        raise LandSurfaceTemperatureError(
            "Home location is outside the MTLST coverage"
        )
