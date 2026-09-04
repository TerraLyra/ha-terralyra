"""Safe client and models for the public LSA SAF FRMv3 WMS."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from PIL import Image, UnidentifiedImageError

from .http import parse_retry_after

PRODUCT_ID = "FRMv3"
LSA_ID = "LSA-504.3"
WMS_DATASET = "MSG-FRMv3"
WMS_URL = "https://adaguc.lsasvcs.ipma.pt/adaguc-server"
FORECAST_DAYS = 10
TIMEOUT = ClientTimeout(total=20, connect=5, sock_read=15)
MAX_JSON_BYTES = 32 * 1024
MAX_MAP_BYTES = 2 * 1024 * 1024
MAX_ERROR_BYTES = 1024
MAP_CACHE_TTL = timedelta(hours=1)
MAP_STALE_TTL = timedelta(hours=24)
USER_AGENT = "ha-terralyra (https://github.com/TerraLyra/ha-terralyra)"
EUROPE_BOUNDS = (-9.975, 34.475, 45.525, 69.975)
LOCAL_SAMPLE_RADIUS_KM = 10.0

_LOGGER = logging.getLogger(__name__)

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


class FireRiskAuthenticationError(FireRiskHTTPError):
    """The FRMv3 endpoint rejected credentials or access."""


class FireRiskRateLimitError(FireRiskHTTPError):
    """FRMv3 denied requests due to rate limiting."""

    def __init__(self, message: str, status: int, retry_after: timedelta | None = None) -> None:
        super().__init__(message, status)
        self.retry_after = retry_after


class FireRiskTemporaryServiceError(FireRiskHTTPError):
    """Transient FRMv3 service error where retrying is expected."""

    def __init__(self, message: str, status: int, retry_after: timedelta | None = None) -> None:
        super().__init__(message, status)
        self.retry_after = retry_after


class FireRiskServiceUnavailableError(FireRiskError):
    """A transient FRMv3 connectivity issue occurred."""

    retry_after: timedelta | None = None


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

    def export_map_cache(self) -> dict[str, Any] | None:
        """Return a bounded, version-independent cache payload for HA storage."""
        if (
            self._map_cache_key is None
            or self._map_cache_value is None
            or self._map_cache_time is None
            or len(self._map_cache_value) > MAX_MAP_BYTES
            or not self._map_cache_value.startswith(b"\x89PNG\r\n\x1a\n")
            or datetime.now(UTC) - self._map_cache_time >= MAP_STALE_TTL
        ):
            return None
        bbox, valid_date = self._map_cache_key
        return {
            "bounds": list(bbox),
            "valid_date": valid_date.isoformat(),
            "cached_at": self._map_cache_time.isoformat(),
            "png": base64.b64encode(self._map_cache_value).decode("ascii"),
        }

    def import_map_cache(self, payload: object) -> bool:
        """Restore only a recent, valid and size-bounded PNG cache payload."""
        try:
            if not isinstance(payload, dict):
                return False
            raw_bounds = payload["bounds"]
            encoded = payload["png"]
            if (
                not isinstance(raw_bounds, list)
                or len(raw_bounds) != 4
                or not isinstance(encoded, str)
                or len(encoded) > ((MAX_MAP_BYTES + 2) // 3) * 4 + 4
            ):
                return False
            bbox = tuple(float(value) for value in raw_bounds)
            west, south, east, north = bbox
            if (
                not all(math.isfinite(value) for value in bbox)
                or not -180 <= west < east <= 180
                or not -90 <= south < north <= 90
            ):
                return False
            valid_date = date.fromisoformat(str(payload["valid_date"]))
            cached_at = datetime.fromisoformat(str(payload["cached_at"]))
            if cached_at.tzinfo is None or cached_at.utcoffset() is None:
                return False
            cached_at = cached_at.astimezone(UTC)
            age = datetime.now(UTC) - cached_at
            if age < timedelta(0) or age >= MAP_STALE_TTL:
                return False
            image = base64.b64decode(encoded, validate=True)
            if len(image) > MAX_MAP_BYTES or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                return False
        except (KeyError, TypeError, ValueError, binascii.Error):
            return False

        self._map_cache_key = (bbox, valid_date)
        self._map_cache_value = image
        self._map_cache_time = cached_at
        return True

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
            and datetime.now(UTC) - self._map_cache_time < MAP_CACHE_TTL
        ):
            return self._map_cache_value
        try:
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
        except (
            FireRiskRateLimitError,
            FireRiskTemporaryServiceError,
            FireRiskServiceUnavailableError,
        ) as err:
            if (
                self._map_cache_key == key
                and self._map_cache_value is not None
                and self._map_cache_time is not None
                and datetime.now(UTC) - self._map_cache_time < MAP_STALE_TTL
            ):
                _LOGGER.debug(
                    "Using stale cached FRMv3 map for %s after fetch failure: %s",
                    valid_date,
                    err,
                )
                return self._map_cache_value
            raise
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
                retry_after = _parse_retry_after(
                    getattr(response, "headers", {}).get("Retry-After")
                )
                if response.status != 200:
                    detail: str | None = None
                    chunks = bytearray()
                    async for chunk in response.content.iter_chunked(16 * 1024):
                        chunks.extend(chunk[: MAX_ERROR_BYTES - len(chunks)])
                        if len(chunks) >= MAX_ERROR_BYTES:
                            break
                    if chunks:
                        detail = _safe_error_detail(bytes(chunks))
                    if response.status in (401, 403, 407):
                        raise FireRiskAuthenticationError(
                            f"FRMv3 service authentication failed ({response.status})"
                            + (f": {detail}" if detail else ""),
                            response.status,
                        )
                    if response.status == 429:
                        raise FireRiskRateLimitError(
                            f"FRMv3 service rate limited ({response.status})"
                            + (f": {detail}" if detail else ""),
                            response.status,
                            retry_after,
                        )
                    if 500 <= response.status <= 599:
                        raise FireRiskTemporaryServiceError(
                            f"FRMv3 service temporarily unavailable ({response.status})"
                            + (f": {detail}" if detail else ""),
                            response.status,
                            retry_after,
                        )
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
            raise FireRiskServiceUnavailableError("FRMv3 service is unavailable") from err


def _parse_retry_after(value: str | None) -> timedelta | None:
    """Retain the public test seam while sharing the hardened parser."""
    return parse_retry_after(value)


def _safe_error_detail(payload: bytes) -> str | None:
    """Return a bounded, single-line server error suitable for logs and repairs."""
    detail = " ".join(payload.decode(errors="replace").split())
    return detail[:MAX_ERROR_BYTES] or None


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
