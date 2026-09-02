"""Safe client and models for the public LSA SAF FRMv3 WMS."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
import json
import math
import re
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from PIL import Image, UnidentifiedImageError

PRODUCT_ID = "FRMv3"
LSA_ID = "LSA-504.3"
WMS_DATASET = "MSG-FRMv3"
WMS_URL = "https://adaguc.lsasvcs.ipma.pt/adaguc-server"
FORECAST_DAYS = 10
TIMEOUT = ClientTimeout(total=20, connect=5, sock_read=15)
MAX_JSON_BYTES = 32 * 1024
MAX_MAP_BYTES = 2 * 1024 * 1024
MAX_ERROR_BYTES = 1024
USER_AGENT = "ha-terralyra/0.3.1 (https://github.com/TerraLyra/ha-terralyra)"
EUROPE_BOUNDS = (-9.975, 34.475, 45.525, 69.975)
LOCAL_SAMPLE_RADIUS_KM = 10.0

RISK_NAMES = {1: "low", 2: "moderate", 3: "high", 4: "very_high", 5: "extreme"}
RISK_PATTERN = re.compile(r"^(?:[a-z_ ]+)\(([1-5])\)$", re.IGNORECASE)
RISK_RGB = {
    (1, 230, 255): 1,
    (8, 248, 64): 2,
    (255, 245, 0): 3,
    (255, 129, 0): 4,
    (255, 3, 0): 5,
}


class FireRiskError(Exception):
    """An FRMv3 request or response was invalid."""


class FireRiskHTTPError(FireRiskError):
    """A non-2xx FRMv3 HTTP response with optional status code details."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class FireRiskDay:
    """One daily FRMv3 forecast value."""

    valid_date: date
    level: int | None

    @property
    def risk(self) -> str:
        return RISK_NAMES.get(self.level, "unknown")


@dataclass(frozen=True, slots=True)
class FireRiskForecast:
    """Local ten-day forecast plus today's maximum in the monitoring area."""

    latitude: float
    longitude: float
    generated_at: datetime
    days: tuple[FireRiskDay, ...]
    area_level: int | None
    area_latitude: float
    area_longitude: float
    radius_km: float

    @property
    def area_risk(self) -> str:
        return RISK_NAMES.get(self.area_level, "unknown")


class FireRiskClient:
    """Read bounded FRMv3 values and map images from the official WMS host."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._map_cache_key: tuple[tuple[float, float, float, float], date] | None = None
        self._map_cache_value: bytes | None = None
        self._map_cache_time: datetime | None = None

    async def async_forecast(
        self, latitude: float, longitude: float, radius_km: float
    ) -> FireRiskForecast:
        """Retrieve the near-Home forecast with a conservative area fallback."""
        _validate_coordinate(latitude, longitude)
        if not math.isfinite(radius_km) or not 1 <= radius_km <= 500:
            raise FireRiskError("Fire-risk radius is outside the valid range")
        dates = _forecast_dates(datetime.now(UTC))
        local: tuple[float, float, int] | None = None
        for sample_lat, sample_lon in _sample_points(
            latitude, longitude, min(radius_km, LOCAL_SAMPLE_RADIUS_KM)
        ):
            level = await self._async_point(sample_lat, sample_lon, dates[0])
            if level is not None:
                local = (sample_lat, sample_lon, level)
                break
        if local is None:
            values = [None] * len(dates)
            local_latitude, local_longitude = latitude, longitude
        else:
            values = [local[2]]
            for valid_date in dates[1:]:
                values.append(await self._async_point(local[0], local[1], valid_date))
            local_latitude, local_longitude = local[0], local[1]
        area_latitude = local[0] if local else latitude
        area_longitude = local[1] if local else longitude
        area_level = local[2] if local else None
        return FireRiskForecast(
            local_latitude, local_longitude, datetime.now(UTC),
            tuple(FireRiskDay(value, level) for value, level in zip(dates, values, strict=True)),
            area_level, area_latitude, area_longitude, radius_km,
        )

    async def _async_point(self, latitude: float, longitude: float, valid_date: date) -> int | None:
        delta = 0.05
        try:
            payload = await self._async_get(
                {
                    "DATASET": WMS_DATASET, "SERVICE": "WMS", "VERSION": "1.1.1",
                    "REQUEST": "GetFeatureInfo", "LAYERS": "Risk", "QUERY_LAYERS": "Risk",
                    "STYLES": "risk_map_style/nearest", "SRS": "EPSG:4326",
                    "BBOX": f"{longitude-delta},{latitude-delta},{longitude+delta},{latitude+delta}",
                    "WIDTH": "101", "HEIGHT": "101", "X": "50", "Y": "50",
                    "TIME": f"{valid_date.isoformat()}T12:00:00Z",
                    "INFO_FORMAT": "application/json", "FORMAT": "image/png",
                },
                MAX_JSON_BYTES,
            )
        except FireRiskHTTPError as err:
            if err.status == 404 and valid_date > datetime.now(UTC).date():
                return None
            raise
        return parse_feature_info(payload, valid_date)

    async def async_map(self, bbox: tuple[float, float, float, float], valid_date: date) -> bytes:
        """Download one bounded forecast map image."""
        west, south, east, north = bbox
        if not (west < east and south < north):
            raise FireRiskError("Invalid fire-risk map bounds")
        key = (bbox, valid_date)
        if (
            self._map_cache_key == key
            and self._map_cache_value is not None
            and self._map_cache_time is not None
            and datetime.now(UTC) - self._map_cache_time < timedelta(hours=1)
        ):
            return self._map_cache_value
        image = await self._async_get(
            {
                "DATASET": WMS_DATASET, "SERVICE": "WMS", "VERSION": "1.1.1",
                "REQUEST": "GetMap", "LAYERS": "Risk", "STYLES": "risk_map_style/nearest",
                "SRS": "EPSG:4326", "BBOX": f"{west},{south},{east},{north}",
                "WIDTH": "768", "HEIGHT": "512", "TRANSPARENT": "TRUE",
                "TIME": f"{valid_date.isoformat()}T12:00:00Z", "FORMAT": "image/png",
            },
            MAX_MAP_BYTES,
        )
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FireRiskError("FRMv3 map response is not a PNG image")
        self._map_cache_key = key
        self._map_cache_value = image
        self._map_cache_time = datetime.now(UTC)
        return image

    async def _async_get(self, params: dict[str, str], limit: int) -> bytes:
        try:
            async with self._session.get(
                WMS_URL, params=params, headers={"User-Agent": USER_AGENT},
                allow_redirects=False, timeout=TIMEOUT,
            ) as response:
                if response.status != 200:
                    detail: str | None = None
                    if response.content_length != 0:
                        chunks = bytearray()
                        async for chunk in response.content.iter_chunked(16 * 1024):
                            chunks.extend(chunk)
                            if len(chunks) >= MAX_ERROR_BYTES:
                                break
                        detail = chunks.decode(errors="replace").strip()[:MAX_ERROR_BYTES]
                    raise FireRiskHTTPError(
                        f"FRMv3 service returned an error ({response.status})"
                        + (f": {detail}" if detail else ""),
                        response.status,
                    )
                if response.content_length is not None and response.content_length > limit:
                    raise FireRiskError("FRMv3 response exceeds the safety limit")
                data = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise FireRiskError("FRMv3 response exceeds the safety limit")
                return bytes(data)
        except FireRiskError:
            raise
        except (ClientError, TimeoutError) as err:
            raise FireRiskError("FRMv3 service is unavailable") from err


def parse_feature_info(payload: bytes, valid_date: date) -> int | None:
    """Parse the small ADAGUC JSON response without trusting human labels."""
    try:
        parsed: Any = json.loads(payload)
        raw = parsed[0]["data"][f"{valid_date.isoformat()}T12:00:00Z"]
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError, KeyError, TypeError) as err:
        raise FireRiskError("FRMv3 response has an unexpected shape") from err
    if raw == "nodata":
        return None
    if not isinstance(raw, str) or not (match := RISK_PATTERN.fullmatch(raw.strip())):
        raise FireRiskError("FRMv3 response contains an unknown risk level")
    return int(match.group(1))


def analyze_risk_map(
    image_bytes: bytes,
    bbox: tuple[float, float, float, float],
    home_latitude: float,
    home_longitude: float,
    radius_km: float,
) -> tuple[int | None, float, float]:
    """Find the true maximum rendered risk inside the circular monitoring area."""
    _validate_coordinate(home_latitude, home_longitude)
    if not math.isfinite(radius_km) or not 1 <= radius_km <= 500:
        raise FireRiskError("Fire-risk analysis radius is outside the valid range")
    west, south, east, north = bbox
    if not all(math.isfinite(value) for value in bbox) or not (
        west < east and south < north
    ):
        raise FireRiskError("FRMv3 analysis bounds are invalid")
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if source.format != "PNG" or source.width > 1024 or source.height > 1024:
                raise FireRiskError("FRMv3 analysis image has unexpected dimensions")
            source.load()
            image = source.convert("RGB")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as err:
        raise FireRiskError("FRMv3 analysis image could not be decoded") from err

    width, height = image.size
    if width < 2 or height < 2:
        raise FireRiskError("FRMv3 analysis image is too small")
    cosine = max(0.2, abs(math.cos(math.radians(home_latitude))))
    x_distances = tuple(
        ((west + x / (width - 1) * (east - west) - home_longitude) * 111.320 * cosine)
        ** 2
        for x in range(0, width, 2)
    )
    y_distances = tuple(
        ((north - y / (height - 1) * (north - south) - home_latitude) * 110.574)
        ** 2
        for y in range(0, height, 2)
    )
    radius_squared = radius_km * radius_km
    pixels = image.load()
    best_level: int | None = None
    best_x = best_y = 0
    for y_index, y in enumerate(range(0, height, 2)):
        for x_index, x in enumerate(range(0, width, 2)):
            if x_distances[x_index] + y_distances[y_index] > radius_squared:
                continue
            level = RISK_RGB.get(pixels[x, y])
            if level is not None and (best_level is None or level > best_level):
                best_level, best_x, best_y = level, x, y
                if level == 5:
                    break
        if best_level == 5:
            break
    if best_level is None:
        return None, home_latitude, home_longitude
    latitude = north - best_y / (height - 1) * (north - south)
    longitude = west + best_x / (width - 1) * (east - west)
    return best_level, latitude, longitude


def _forecast_dates(now: datetime) -> tuple[date, ...]:
    return tuple(now.date() + timedelta(days=offset) for offset in range(FORECAST_DAYS))


def _sample_points(
    latitude: float, longitude: float, radius_km: float
) -> tuple[tuple[float, float], ...]:
    """Return a bounded center-and-compass sample without leaving Europe."""
    distance = radius_km * 0.7
    lat_delta = distance / 110.574
    lon_delta = distance / (
        111.320 * max(0.2, abs(math.cos(math.radians(latitude))))
    )
    offsets = (
        (0, 0), (lat_delta, 0), (-lat_delta, 0), (0, lon_delta), (0, -lon_delta),
        (lat_delta, lon_delta), (lat_delta, -lon_delta),
        (-lat_delta, lon_delta), (-lat_delta, -lon_delta),
    )
    return tuple(
        (
            max(-90.0, min(90.0, latitude + dy)),
            ((longitude + dx + 180) % 360) - 180,
        )
        for dy, dx in offsets
    )


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise FireRiskError("Latitude is outside the valid range")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise FireRiskError("Longitude is outside the valid range")


def map_bounds(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Build Europe-clamped WMS bounds around Home."""
    _validate_coordinate(latitude, longitude)
    if not math.isfinite(radius_km) or not 1 <= radius_km <= 500:
        raise FireRiskError("Fire-risk radius is outside the valid range")
    west_limit, south_limit, east_limit, north_limit = EUROPE_BOUNDS
    lat_delta = radius_km / 110.574
    lon_delta = radius_km / (
        111.320 * max(0.2, abs(math.cos(math.radians(latitude))))
    )
    bounds = (
        max(west_limit, longitude - lon_delta),
        max(south_limit, latitude - lat_delta),
        min(east_limit, longitude + lon_delta),
        min(north_limit, latitude + lat_delta),
    )
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise FireRiskError("Home is outside the FRMv3 European coverage")
    return bounds
