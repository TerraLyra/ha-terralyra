"""Bounded retrieval, inspection and decoding of MSG-IODC FRP List Products."""
from __future__ import annotations

import io
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import h5py
import numpy as np
from aiohttp import BasicAuth, ClientError, ClientSession, ClientTimeout

from .http import parse_retry_after

BASE_URL = "https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG-IODC/FRP-PIXEL/HDF5"
FILE_PREFIX = "HDF5_LSASAF_MSG-IODC_FRP-PIXEL-ListProduct_IODC-Disk_"  # pragma: allowlist secret
FILE_PATTERN = re.compile(
    rf"^{re.escape(FILE_PREFIX)}(?P<stamp>\d{{12}})$"
)
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_HDF5_OBJECTS = 256
MAX_DATASET_RANK = 4
MAX_DATASET_ELEMENTS = 5_000_000
MAX_ATTRIBUTES_PER_OBJECT = 128
MAX_ATTRIBUTE_ELEMENTS = 64
MAX_TEXT_LENGTH = 512
MAX_FIRE_PIXELS = 100_000
TIMEOUT = ClientTimeout(total=30, connect=5, sock_read=25)
USER_AGENT = "ha-terralyra/msg-iodc-schema-probe"


class MsgIodcSchemaError(Exception):
    """An MSG-IODC schema probe failed a bounded validation rule."""


class MsgIodcAuthenticationError(MsgIodcSchemaError):
    """The configured LSA SAF credentials were rejected."""


class MsgIodcUnavailableError(MsgIodcSchemaError):
    """The bounded probe could not obtain a current List Product."""

    def __init__(
        self, message: str, *, retry_after: timedelta | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MsgIodcRateLimitError(MsgIodcUnavailableError):
    """The LSA SAF service asked the client to reduce its request rate."""


class MsgIodcTimeoutError(MsgIodcUnavailableError):
    """The bounded MSG-IODC request timed out."""


class MsgIodcNoDataError(MsgIodcUnavailableError):
    """No recent MSG-IODC List Product is currently published."""


@dataclass(frozen=True, slots=True)
class MsgIodcPixel:
    """One safely decoded MSG-IODC active-fire pixel."""

    latitude: float
    longitude: float
    confidence: float
    frp_mw: float
    acquired: datetime
    pixel_size_km2: float | None
    frp_uncertainty_mw: float | None
    abs_line: int | None
    abs_pixel: int | None


@dataclass(frozen=True, slots=True)
class MsgIodcProduct:
    """One validated MSG-IODC FRP-PIXEL List Product."""

    filename: str
    url: str
    product_time: datetime
    pixels: tuple[MsgIodcPixel, ...]


async def async_fetch_latest_list_product(
    session: ClientSession,
    username: str,
    password: str,
    *,
    now: datetime | None = None,
    lookback_slots: int = 32,
) -> tuple[str, bytes]:
    """Fetch one bounded List Product without following redirects."""
    if not username or not password:
        raise MsgIodcAuthenticationError("LSA SAF credentials are not configured")
    auth = BasicAuth(username, password)
    try:
        for filename, url in candidate_list_products(
            now or datetime.now(UTC), lookback_slots=lookback_slots
        ):
            async with session.get(
                url,
                auth=auth,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as response:
                if response.status == 404:
                    continue
                if response.status in (401, 403):
                    raise MsgIodcAuthenticationError(
                        "LSA SAF credentials were rejected"
                    )
                retry_after = parse_retry_after(
                    getattr(response, "headers", {}).get("Retry-After")
                )
                if response.status == 429:
                    raise MsgIodcRateLimitError(
                        "LSA SAF rate limited the MSG-IODC request",
                        retry_after=retry_after,
                    )
                if 500 <= response.status <= 599:
                    raise MsgIodcUnavailableError(
                        f"LSA SAF returned HTTP {response.status}",
                        retry_after=retry_after,
                    )
                if response.status != 200:
                    raise MsgIodcUnavailableError(
                        f"LSA SAF returned HTTP {response.status}"
                    )
                if (
                    response.content_length is not None
                    and response.content_length > MAX_DOWNLOAD_BYTES
                ):
                    raise MsgIodcSchemaError(
                        "MSG-IODC response exceeds the probe size limit"
                    )
                payload = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    payload.extend(chunk)
                    if len(payload) > MAX_DOWNLOAD_BYTES:
                        raise MsgIodcSchemaError(
                            "MSG-IODC response exceeds the probe size limit"
                        )
                return filename, bytes(payload)
    except MsgIodcSchemaError:
        raise
    except TimeoutError as err:
        raise MsgIodcTimeoutError("LSA SAF MSG-IODC request timed out") from err
    except ClientError as err:
        raise MsgIodcUnavailableError("LSA SAF service is unavailable") from err
    raise MsgIodcNoDataError(
        "No MSG-IODC List Product was found in the bounded lookback"
    )


def list_product_url(filename: str) -> str:
    """Return the fixed-host public path for one validated product name."""
    product_time = parse_list_product_filename(filename)
    return f"{BASE_URL}/{product_time:%Y/%m/%d}/{filename}"


def decode_list_product(filename: str, payload: bytes) -> MsgIodcProduct:
    """Decode bounded science arrays from one validated List Product."""
    product_time = parse_list_product_filename(filename)
    if not payload or len(payload) > MAX_DOWNLOAD_BYTES:
        raise MsgIodcSchemaError("MSG-IODC List Product exceeds the size limit")

    required = ("LATITUDE", "LONGITUDE", "FIRE_CONFIDENCE", "FRP", "ACQTIME")
    optional = ("PIXEL_SIZE", "FRP_UNCERTAINTY", "ABS_LINE", "ABS_PIXEL")
    try:
        with h5py.File(io.BytesIO(payload), "r") as product:
            _validate_product_identity(product.attrs)
            arrays = {
                name: _read_numeric_vector(product, name, required=True)
                for name in required
            }
            row_count = len(arrays[required[0]][0])
            if any(len(arrays[name][0]) != row_count for name in required):
                raise MsgIodcSchemaError(
                    "MSG-IODC required datasets have inconsistent lengths"
                )
            optional_arrays = {
                name: _read_numeric_vector(product, name, required=False)
                for name in optional
            }
            if any(
                value is not None and len(value[0]) != row_count
                for value in optional_arrays.values()
            ):
                raise MsgIodcSchemaError(
                    "MSG-IODC optional datasets have inconsistent lengths"
                )

            pixels: list[MsgIodcPixel] = []
            for index in range(row_count):
                latitude = _physical_value(arrays["LATITUDE"], index)
                longitude = _physical_value(arrays["LONGITUDE"], index)
                confidence = _physical_value(arrays["FIRE_CONFIDENCE"], index)
                frp_mw = _physical_value(arrays["FRP"], index)
                acqtime = _physical_value(arrays["ACQTIME"], index)
                if (
                    latitude is None
                    or longitude is None
                    or confidence is None
                    or frp_mw is None
                    or acqtime is None
                    or not -90.0 <= latitude <= 90.0
                    or not -180.0 <= longitude <= 180.0
                    or not 0.0 <= confidence <= 1.0
                    or frp_mw < 0.0
                ):
                    continue
                acquired = _parse_acquisition_time(product_time, acqtime)
                if acquired is None:
                    continue
                pixels.append(
                    MsgIodcPixel(
                        latitude=latitude,
                        longitude=longitude,
                        confidence=confidence,
                        frp_mw=frp_mw,
                        acquired=acquired,
                        pixel_size_km2=_optional_value(
                            optional_arrays["PIXEL_SIZE"], index, minimum=0.0
                        ),
                        frp_uncertainty_mw=_optional_value(
                            optional_arrays["FRP_UNCERTAINTY"], index, minimum=0.0
                        ),
                        abs_line=_optional_integer(
                            optional_arrays["ABS_LINE"], index
                        ),
                        abs_pixel=_optional_integer(
                            optional_arrays["ABS_PIXEL"], index
                        ),
                    )
                )
    except MsgIodcSchemaError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as err:
        raise MsgIodcSchemaError("MSG-IODC product is not safely decodable") from err

    return MsgIodcProduct(
        filename=filename,
        url=list_product_url(filename),
        product_time=product_time,
        pixels=tuple(pixels),
    )


def parse_list_product_filename(filename: str) -> datetime:
    """Validate a List Product filename and return its UTC product time."""
    match = FILE_PATTERN.fullmatch(filename)
    if match is None:
        raise MsgIodcSchemaError("Unrecognized MSG-IODC List Product filename")
    try:
        product_time = datetime.strptime(match.group("stamp"), "%Y%m%d%H%M").replace(
            tzinfo=UTC
        )
    except ValueError as err:
        raise MsgIodcSchemaError("Invalid MSG-IODC List Product timestamp") from err
    if product_time.minute % 15:
        raise MsgIodcSchemaError("MSG-IODC List Product is not on a 15-minute slot")
    return product_time


def candidate_list_products(
    now: datetime, *, lookback_slots: int = 32
) -> tuple[tuple[str, str], ...]:
    """Build deterministic newest-first 15-minute List Product candidates."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("MSG-IODC probe time must include a timezone")
    if not 1 <= lookback_slots <= 96:
        raise ValueError("MSG-IODC lookback must be between 1 and 96 slots")
    current = now.astimezone(UTC)
    rounded = current.replace(
        minute=(current.minute // 15) * 15, second=0, microsecond=0
    )
    candidates: list[tuple[str, str]] = []
    for offset in range(1, lookback_slots + 1):
        stamp = rounded - timedelta(minutes=15 * offset)
        filename = f"{FILE_PREFIX}{stamp:%Y%m%d%H%M}"
        candidates.append(
            (filename, f"{BASE_URL}/{stamp:%Y/%m/%d}/{filename}")
        )
    return tuple(candidates)


def inspect_list_product_schema(filename: str, payload: bytes) -> dict[str, Any]:
    """Return bounded HDF5 metadata without reading dataset values."""
    product_time = parse_list_product_filename(filename)
    if not payload or len(payload) > MAX_DOWNLOAD_BYTES:
        raise MsgIodcSchemaError("MSG-IODC List Product exceeds the probe size limit")

    try:
        with h5py.File(io.BytesIO(payload), "r") as product:
            objects: list[dict[str, Any]] = []

            def visitor(name: str, value: h5py.Group | h5py.Dataset) -> None:
                if len(objects) >= MAX_HDF5_OBJECTS:
                    raise MsgIodcSchemaError("MSG-IODC product has too many objects")
                record: dict[str, Any] = {
                    "path": f"/{name}",
                    "kind": "dataset" if isinstance(value, h5py.Dataset) else "group",
                    "attributes": _safe_attributes(value.attrs),
                }
                if isinstance(value, h5py.Dataset):
                    shape = tuple(int(side) for side in value.shape)
                    if (
                        len(shape) > MAX_DATASET_RANK
                        or any(side < 0 for side in shape)
                        or math.prod(shape) > MAX_DATASET_ELEMENTS
                    ):
                        raise MsgIodcSchemaError(
                            "MSG-IODC dataset dimensions exceed the probe limits"
                        )
                    record.update(
                        {
                            "dtype": str(value.dtype),
                            "shape": list(shape),
                            "chunks": None
                            if value.chunks is None
                            else [int(side) for side in value.chunks],
                            "compression": value.compression,
                        }
                    )
                objects.append(record)

            root_attributes = _safe_attributes(product.attrs)
            product.visititems(visitor)
    except MsgIodcSchemaError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as err:
        raise MsgIodcSchemaError("MSG-IODC product is not readable HDF5") from err

    return {
        "format": "terralyra-msg-iodc-schema-v1",
        "filename": filename,
        "product_time": product_time.isoformat(),
        "payload_bytes": len(payload),
        "root_attributes": root_attributes,
        "objects": objects,
    }


def _validate_product_identity(attributes: Mapping[str, Any]) -> None:
    """Reject HDF5 files that are not the expected healthy IODC List Product."""
    product = _attribute_text(attributes, "PRODUCT")
    region = _attribute_text(attributes, "REGION_NAME")
    quality = _attribute_text(attributes, "OVERALL_QUALITY_FLAG")
    if product != "FRPPixel" or not region.startswith("IODC"):
        raise MsgIodcSchemaError("Unexpected MSG-IODC product identity")
    if quality != "OK":
        raise MsgIodcSchemaError("MSG-IODC product quality flag is not OK")


def _attribute_text(attributes: Mapping[str, Any], name: str) -> str:
    if name not in attributes:
        raise MsgIodcSchemaError(f"MSG-IODC product is missing {name}")
    value = np.asarray(attributes[name])
    if value.size != 1:
        raise MsgIodcSchemaError(f"MSG-IODC attribute {name} is not scalar")
    scalar = value.reshape(-1)[0]
    if isinstance(scalar, (bytes, np.bytes_)):
        return bytes(scalar).decode("ascii", errors="strict").strip()
    return str(scalar).strip()


def _read_numeric_vector(
    product: h5py.File, name: str, *, required: bool
) -> tuple[np.ndarray, float, float, float | None] | None:
    """Read one bounded one-dimensional numeric dataset and its scale metadata."""
    if name not in product:
        if required:
            raise MsgIodcSchemaError(f"MSG-IODC product is missing {name}")
        return None
    dataset = product[name]
    if not isinstance(dataset, h5py.Dataset):
        raise MsgIodcSchemaError(f"MSG-IODC {name} is not a dataset")
    if (
        len(dataset.shape) != 1
        or dataset.shape[0] > MAX_FIRE_PIXELS
        or dataset.dtype.kind not in "iuf"
    ):
        raise MsgIodcSchemaError(f"MSG-IODC {name} has an unsafe shape or type")
    values = np.asarray(dataset[...])
    scale = _finite_scalar_attribute(dataset.attrs, "SCALING_FACTOR", 1.0)
    offset = _finite_scalar_attribute(dataset.attrs, "OFFSET", 0.0)
    missing = _finite_scalar_attribute(
        dataset.attrs, "MISSING_VALUE", None, required=False
    )
    if scale is None or scale <= 0.0:
        raise MsgIodcSchemaError(f"MSG-IODC {name} has an invalid scale")
    return values, scale, offset or 0.0, missing


def _finite_scalar_attribute(
    attributes: Mapping[str, Any],
    name: str,
    default: float | None,
    *,
    required: bool = True,
) -> float | None:
    if name not in attributes:
        if required:
            return default
        return default
    value = np.asarray(attributes[name])
    if value.size != 1:
        raise MsgIodcSchemaError(f"MSG-IODC attribute {name} is not scalar")
    parsed = float(value.reshape(-1)[0])
    if not math.isfinite(parsed):
        raise MsgIodcSchemaError(f"MSG-IODC attribute {name} is not finite")
    return parsed


def _physical_value(
    field: tuple[np.ndarray, float, float, float | None], index: int
) -> float | None:
    values, scale, offset, missing = field
    raw = float(values[index])
    if not math.isfinite(raw) or (missing is not None and raw == missing):
        return None
    value = raw / scale + offset
    return value if math.isfinite(value) else None


def _optional_value(
    field: tuple[np.ndarray, float, float, float | None] | None,
    index: int,
    *,
    minimum: float | None = None,
) -> float | None:
    if field is None:
        return None
    value = _physical_value(field, index)
    if value is None or (minimum is not None and value < minimum):
        return None
    return value


def _optional_integer(
    field: tuple[np.ndarray, float, float, float | None] | None, index: int
) -> int | None:
    value = _optional_value(field, index, minimum=0.0)
    if value is None or not value.is_integer():
        return None
    return int(value)


def _parse_acquisition_time(
    product_time: datetime, raw_time: float
) -> datetime | None:
    """Decode documented HHMM UTC and choose the date nearest the product slot."""
    if not raw_time.is_integer():
        return None
    encoded = int(raw_time)
    hour, minute = divmod(encoded, 100)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    base = product_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidates = (base - timedelta(days=1), base, base + timedelta(days=1))
    acquired = min(candidates, key=lambda item: abs(item - product_time))
    if abs(acquired - product_time) > timedelta(hours=2):
        return None
    return acquired


def _safe_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    names = sorted(str(name) for name in attributes)
    if len(names) > MAX_ATTRIBUTES_PER_OBJECT:
        raise MsgIodcSchemaError("MSG-IODC object has too many attributes")
    return {name: _safe_attribute_value(attributes[name]) for name in names}


def _safe_attribute_value(value: Any) -> Any:
    array = np.asarray(value)
    if array.size > MAX_ATTRIBUTE_ELEMENTS:
        return {
            "omitted": True,
            "dtype": str(array.dtype),
            "elements": int(array.size),
        }
    if array.ndim == 0:
        return _safe_scalar(array.item())
    return [_safe_scalar(item) for item in array.reshape(-1).tolist()]


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (bytes, np.bytes_)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value[:MAX_TEXT_LENGTH]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else str(parsed)
    if value is None:
        return None
    return str(value)[:MAX_TEXT_LENGTH]
