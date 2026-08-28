"""Bounded client and parser for the official NASA FIRMS Area API."""
from __future__ import annotations

import csv
from datetime import UTC, datetime
import io
import math
import re
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

FIRMS_HOST = "firms.modaps.eosdis.nasa.gov"
FIRMS_BASE_URL = f"https://{FIRMS_HOST}/api/area/csv"
ALLOWED_SOURCES = frozenset({"VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"})
TIMEOUT = ClientTimeout(total=30, connect=8, sock_read=20)
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 20_000
MAX_LINE_BYTES = 4096
MAX_BBOX_SPAN_DEGREES = 20.0
USER_AGENT = "ha-terralyra (https://github.com/TerraLyra/ha-terralyra)"
_MAP_KEY_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_REQUIRED_FIELDS = frozenset(
    {
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "frp",
    }
)


class FirmsError(Exception):
    """A FIRMS request or response was invalid."""


class FirmsAuthenticationError(FirmsError):
    """The FIRMS MAP_KEY was rejected."""


class FirmsClient:
    """Fetch a small, recent FIRMS CSV area response from a fixed host."""

    def __init__(self, session: ClientSession, map_key: str) -> None:
        if not _MAP_KEY_RE.fullmatch(map_key):
            raise FirmsAuthenticationError("FIRMS MAP_KEY has an invalid format")
        self._session = session
        self._map_key = map_key

    async def async_area(
        self,
        *,
        source: str,
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> tuple[FirmsDetection, ...]:
        """Return at most one day of detections inside a validated bounding box."""
        _validate_request(source, west, south, east, north)
        area = ",".join(_format_coordinate(value) for value in (west, south, east, north))
        url = "/".join(
            (
                FIRMS_BASE_URL,
                quote(self._map_key, safe=""),
                source,
                area,
                "1",
            )
        )
        payload = await self._async_get(url)
        return parse_firms_csv(payload, source=source)

    async def _async_get(self, url: str) -> bytes:
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise FirmsAuthenticationError("FIRMS MAP_KEY was rejected")
                if response.status != 200:
                    raise FirmsError("FIRMS service returned an error")
                if (
                    response.content_length is not None
                    and response.content_length > MAX_CSV_BYTES
                ):
                    raise FirmsError("FIRMS response exceeds the safety limit")
                data = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_CSV_BYTES:
                        raise FirmsError("FIRMS response exceeds the safety limit")
                return bytes(data)
        except (FirmsAuthenticationError, FirmsError):
            raise
        except (ClientError, TimeoutError) as err:
            raise FirmsError("FIRMS service is unavailable") from err


class FirmsDetection:
    """One validated FIRMS active-fire record."""

    __slots__ = (
        "acquired",
        "confidence_category",
        "frp_mw",
        "instrument",
        "latitude",
        "longitude",
        "satellite",
        "source",
    )

    def __init__(
        self,
        *,
        source: str,
        latitude: float,
        longitude: float,
        acquired: datetime,
        satellite: str,
        instrument: str,
        confidence_category: str,
        frp_mw: float,
    ) -> None:
        self.source = source
        self.latitude = latitude
        self.longitude = longitude
        self.acquired = acquired
        self.satellite = satellite
        self.instrument = instrument
        self.confidence_category = confidence_category
        self.frp_mw = frp_mw


def parse_firms_csv(payload: bytes, *, source: str) -> tuple[FirmsDetection, ...]:
    """Parse a bounded UTF-8 FIRMS CSV without inventing confidence scores."""
    if source not in ALLOWED_SOURCES:
        raise FirmsError("Unsupported FIRMS source")
    if len(payload) > MAX_CSV_BYTES:
        raise FirmsError("FIRMS response exceeds the safety limit")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as err:
        raise FirmsError("FIRMS response is not valid UTF-8") from err
    if any(len(line.encode("utf-8")) > MAX_LINE_BYTES for line in text.splitlines()):
        raise FirmsError("FIRMS CSV line exceeds the safety limit")

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None or not _REQUIRED_FIELDS.issubset(reader.fieldnames):
            raise FirmsError("FIRMS CSV is missing required fields")
        detections: list[FirmsDetection] = []
        for index, row in enumerate(reader, start=1):
            if index > MAX_CSV_ROWS:
                raise FirmsError("FIRMS CSV contains too many rows")
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
            frp_mw = float(row["frp"])
            _validate_coordinate(latitude, longitude)
            if not math.isfinite(frp_mw) or frp_mw < 0 or frp_mw > 1_000_000:
                raise ValueError
            acquired = _parse_acquired(row["acq_date"], row["acq_time"])
            satellite = _safe_token(row["satellite"], 16)
            instrument = _safe_token(row["instrument"], 16)
            confidence = _safe_token(row["confidence"], 16).lower()
            detections.append(
                FirmsDetection(
                    source=source,
                    latitude=latitude,
                    longitude=longitude,
                    acquired=acquired,
                    satellite=satellite,
                    instrument=instrument,
                    confidence_category=confidence,
                    frp_mw=frp_mw,
                )
            )
    except FirmsError:
        raise
    except (KeyError, TypeError, ValueError, csv.Error) as err:
        raise FirmsError("FIRMS CSV has an unexpected shape") from err
    return tuple(detections)


def _validate_request(
    source: str, west: float, south: float, east: float, north: float
) -> None:
    if source not in ALLOWED_SOURCES:
        raise FirmsError("Unsupported FIRMS source")
    _validate_coordinate(south, west)
    _validate_coordinate(north, east)
    if west >= east or south >= north:
        raise FirmsError("FIRMS bounding box is invalid")
    if east - west > MAX_BBOX_SPAN_DEGREES or north - south > MAX_BBOX_SPAN_DEGREES:
        raise FirmsError("FIRMS bounding box is too large")


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise FirmsError("FIRMS coordinate is not finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise FirmsError("FIRMS coordinate is out of range")


def _parse_acquired(date_value: str, time_value: str) -> datetime:
    compact_time = time_value.strip().zfill(4)
    if len(compact_time) != 4 or not compact_time.isdigit():
        raise ValueError
    return datetime.strptime(
        f"{date_value.strip()} {compact_time}", "%Y-%m-%d %H%M"
    ).replace(tzinfo=UTC)


def _safe_token(value: str, maximum: int) -> str:
    token = value.strip()
    if not token or len(token) > maximum or not token.isprintable():
        raise ValueError
    return token


def _format_coordinate(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")
