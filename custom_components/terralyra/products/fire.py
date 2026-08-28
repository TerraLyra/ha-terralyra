"""MTG MTFRPPixel (LSA-509) client and CSV parser."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import csv
import gzip
import io
import math
import re
from typing import Any

from aiohttp import ClientError, ClientResponseError

from ..api import (
    REQUEST_TIMEOUT,
    LsaSafApi,
    LsaSafAuthError,
    LsaSafError,
    validate_service_url,
)
from ..clustering import haversine_km


class LsaSafNoDataError(LsaSafError):
    """No recent product was found."""


@dataclass(slots=True)
class FirePixel:
    """One detected fire pixel."""

    latitude: float
    longitude: float
    confidence: float
    frp_mw: float
    acquired: datetime
    pixel_size_km2: float | None
    frp_uncertainty_mw: float | None
    abs_line: int | None
    abs_samp: int | None


@dataclass(slots=True)
class Product:
    """Parsed MTFRPPixel list product."""

    filename: str
    url: str
    product_time: datetime
    pixels: list[FirePixel]


BASE_URL = "https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MTG/MTFRPPixel/NATIVE"
FILE_PREFIX = "LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_"
FILE_SUFFIX = ".csv.gz"
MAX_COMPRESSED_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_CSV_ROWS = 100_000
MAX_CSV_COLUMNS = 64


class ActiveFireClient(LsaSafApi):
    """Small async client for the LSA SAF HTTPS data service."""

    async def async_test_auth(self) -> None:
        """Validate credentials against an actual MTFRPPixel product request.

        The archive index may be browsable without authentication, so testing
        only the directory page is not sufficient. Fetching the newest product
        verifies the same authenticated path used during normal operation.
        """
        try:
            await self.async_fetch_latest()
        except LsaSafNoDataError:
            # A temporary gap in recent product availability is not an auth failure.
            # Individual probes still return 401/403 immediately when credentials
            # are rejected by the Data Service.
            return

    async def async_fetch_latest(self, now: datetime | None = None) -> Product:
        """Fetch the newest available 10-minute ListProduct.

        MTG products are nominally generated every 10 minutes but are published with
        some latency. We probe deterministic product names backwards in time. This is
        more robust than depending on the h5ai directory UI/HTML implementation.
        """
        now = (now or datetime.now(UTC)).astimezone(UTC)
        rounded = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)

        # Start one slot back; current-slot data cannot be complete yet. Search 4 hours.
        for step in range(1, 25):
            stamp = rounded - timedelta(minutes=10 * step)
            filename = f"{FILE_PREFIX}{stamp:%Y%m%d%H%M}{FILE_SUFFIX}"
            url = f"{BASE_URL}/{stamp:%Y/%m/%d}/{filename}"
            validate_service_url(url)
            try:
                async with self._session.get(
                    url,
                    headers=self._headers,
                    allow_redirects=False,
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    if response.status in (401, 403):
                        raise LsaSafAuthError("Invalid or expired LSA SAF credentials")
                    if response.status == 404:
                        continue
                    if 300 <= response.status < 400:
                        raise LsaSafError("Unexpected redirect from LSA SAF service")
                    try:
                        response.raise_for_status()
                    except ClientResponseError as err:
                        raise LsaSafError(f"LSA SAF HTTP error: {err.status}") from err
                    payload = await _read_limited(response)
                    return parse_product(filename, url, payload)
            except LsaSafError:
                raise
            except (ClientError, TimeoutError) as err:
                raise LsaSafError("Could not securely retrieve LSA SAF data") from err

        raise LsaSafNoDataError("No MTFRPPixel ListProduct found in the last 4 hours")


def parse_product(filename: str, url: str, payload: bytes) -> Product:
    """Parse a gzip-compressed MTFRPPixel ListProduct CSV."""
    match = re.search(r"_(\d{12})\.csv\.gz$", filename)
    if not match:
        raise LsaSafError(f"Unrecognized product filename: {filename}")
    product_time = datetime.strptime(match.group(1), "%Y%m%d%H%M").replace(tzinfo=UTC)

    try:
        if len(payload) > MAX_COMPRESSED_BYTES:
            raise LsaSafError("Compressed MTFRPPixel product exceeds the safety limit")
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
            raw = compressed.read(MAX_UNCOMPRESSED_BYTES + 1)
        if len(raw) > MAX_UNCOMPRESSED_BYTES:
            raise LsaSafError("Decompressed MTFRPPixel product exceeds the safety limit")
        text = raw.decode("utf-8-sig")
    except (EOFError, OSError, UnicodeDecodeError) as err:
        raise LsaSafError("Could not decompress/decode MTFRPPixel product") from err

    reader = csv.DictReader(io.StringIO(text))
    required = {"LATITUDE", "LONGITUDE", "FIRE_CONFIDENCE", "FRP", "ACQTIME"}
    if (
        not reader.fieldnames
        or len(reader.fieldnames) > MAX_CSV_COLUMNS
        or len(set(reader.fieldnames)) != len(reader.fieldnames)
        or not required.issubset(reader.fieldnames)
        or any(len(name) > 128 for name in reader.fieldnames)
    ):
        raise LsaSafError("Unexpected MTFRPPixel CSV columns")

    pixels: list[FirePixel] = []
    for row_number, row in enumerate(reader, start=1):
        if row_number > MAX_CSV_ROWS:
            raise LsaSafError("MTFRPPixel product contains too many rows")
        if None in row or any(value is not None and len(value) > 256 for value in row.values()):
            continue
        try:
            acquired = datetime.strptime(row["ACQTIME"], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            lat = _float_or_none(row.get("LATITUDE"))
            lon = _float_or_none(row.get("LONGITUDE"))
            confidence = float(row["FIRE_CONFIDENCE"])
            frp_mw = float(row["FRP"])
            if (
                lat is None
                or lon is None
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or not math.isfinite(frp_mw)
                or frp_mw < 0
                or abs(acquired - product_time) > timedelta(days=1)
            ):
                continue
            pixels.append(
                FirePixel(
                    latitude=lat,
                    longitude=lon,
                    confidence=confidence,
                    frp_mw=frp_mw,
                    acquired=acquired,
                    pixel_size_km2=_float_or_none(row.get("PIXEL_SIZE")),
                    frp_uncertainty_mw=_float_or_none(row.get("FRP_UNCERTAINTY")),
                    abs_line=_int_or_none(row.get("ABS_LINE")),
                    abs_samp=_int_or_none(row.get("ABS_SAMP")),
                )
            )
            # Store parallax coordinates on the object without growing the public dataclass.
            # Consumers can reparse them from rows only if needed; v0.1 uses native coords.
        except (TypeError, ValueError):
            continue

    return Product(filename=filename, url=url, product_time=product_time, pixels=pixels)


async def _read_limited(response: Any) -> bytes:
    """Read a response without trusting Content-Length or buffering unbounded data."""
    content_length = response.content_length
    if content_length is not None and content_length > MAX_COMPRESSED_BYTES:
        raise LsaSafError("Compressed MTFRPPixel product exceeds the safety limit")
    payload = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        payload.extend(chunk)
        if len(payload) > MAX_COMPRESSED_BYTES:
            raise LsaSafError("Compressed MTFRPPixel product exceeds the safety limit")
    return bytes(payload)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
