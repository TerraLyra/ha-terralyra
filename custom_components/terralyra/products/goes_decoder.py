"""Bounded decoder for NOAA GOES ABI full-disk fire products.

This module performs synchronous native-file work and must only be called from
Home Assistant's executor. It is deliberately not wired into the integration
until the optional GOES provider and its download lifecycle are complete.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import math
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import h5py
import numpy as np

from ..models import FireDetection, ProviderSnapshot, ProviderStatus
from ..providers.goes_spike import GoesObjectMetadata
from .goes import MAX_OBJECT_BYTES

PROVIDER = "noaa_goes"
PRODUCT = "ABI-L2-FDCF"
FIRE_MASK_VALUES = frozenset(range(10, 16)) | frozenset(range(30, 36))
MASK_CLASSIFICATIONS = {
    10: "good",
    11: "saturated",
    12: "cloud_contaminated",
    13: "high_probability",
    14: "medium_probability",
    15: "low_probability",
}
MAX_GRID_SIDE = 6000
MAX_GRID_PIXELS = 36_000_000
MAX_CHUNK_PIXELS = 1_000_000
MAX_FIRE_PIXELS = 50_000
STRIPE_ROWS = 24
EARTH_RADIUS_TOLERANCE = (6_000_000.0, 7_000_000.0)
SATELLITE_HEIGHT_TOLERANCE = (35_000_000.0, 36_500_000.0)


class GoesDecodeError(Exception):
    """A GOES file failed bounded structural or data validation."""


def decode_goes_fdc(
    path: str | Path,
    metadata: GoesObjectMetadata,
    *,
    source_url: str,
    received_at: datetime | None = None,
) -> ProviderSnapshot:
    """Decode one validated GOES FDCF object with bounded memory use.

    The caller must run this function in an executor. Full two-dimensional
    science arrays are never loaded together: the mask is scanned by stripes
    and detail values are read only for accepted fire pixels.
    """
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError as err:
        raise GoesDecodeError("GOES product file is unavailable") from err
    if size <= 0 or size > MAX_OBJECT_BYTES:
        raise GoesDecodeError("GOES product file exceeds the safety limit")
    if metadata.satellite not in {"G18", "G19"} or metadata.sector != "F":
        raise GoesDecodeError("GOES product identity is unsupported")
    parsed_url = urlsplit(source_url)
    expected_host = f"noaa-goes{metadata.satellite[1:]}.s3.amazonaws.com"
    decoded_path = unquote(parsed_url.path)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != expected_host
        or parsed_url.query
        or parsed_url.fragment
        or not decoded_path.startswith(f"/{PRODUCT}/")
        or PurePosixPath(decoded_path).name != metadata.filename
    ):
        raise GoesDecodeError("GOES product source is not allowlisted")

    try:
        with h5py.File(file_path, "r") as product:
            detections = _decode_product(product, metadata)
    except GoesDecodeError:
        raise
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as err:
        raise GoesDecodeError("GOES product is malformed or unreadable") from err

    received = received_at or datetime.now(UTC)
    if received.tzinfo is None or received.utcoffset() is None:
        raise GoesDecodeError("GOES receive time must include a timezone")
    return ProviderSnapshot(
        provider=PROVIDER,
        satellite=metadata.satellite,
        product=PRODUCT,
        product_timestamp=metadata.observation_end,
        received_timestamp=received.astimezone(UTC),
        status=ProviderStatus.AVAILABLE,
        source_url=source_url,
        filename=metadata.filename,
        detections=detections,
    )


def _decode_product(
    product: h5py.File, metadata: GoesObjectMetadata
) -> tuple[FireDetection, ...]:
    required = ("Mask", "Power", "Temp", "Area", "DQF", "x", "y")
    datasets = {name: _dataset(product, name) for name in required}
    projection = _dataset(product, "goes_imager_projection")
    shape = datasets["Mask"].shape
    if (
        len(shape) != 2
        or not all(0 < side <= MAX_GRID_SIDE for side in shape)
        or shape[0] * shape[1] > MAX_GRID_PIXELS
    ):
        raise GoesDecodeError("GOES fire grid dimensions are unsafe")
    for name in ("Power", "Temp", "Area", "DQF"):
        if datasets[name].shape != shape:
            raise GoesDecodeError("GOES science arrays have inconsistent dimensions")
    if datasets["x"].shape != (shape[1],) or datasets["y"].shape != (shape[0],):
        raise GoesDecodeError("GOES navigation arrays have inconsistent dimensions")
    for name in ("Mask", "Power", "Temp", "Area", "DQF"):
        chunks = datasets[name].chunks
        if chunks is None or len(chunks) != 2 or math.prod(chunks) > MAX_CHUNK_PIXELS:
            raise GoesDecodeError("GOES science-array chunks are unsafe")
    if not np.issubdtype(datasets["Mask"].dtype, np.integer):
        raise GoesDecodeError("GOES fire mask has an unexpected data type")

    navigation = _projection_parameters(projection.attrs)
    x_values = _scaled_vector(datasets["x"], expected_units="rad")
    y_values = _scaled_vector(datasets["y"], expected_units="rad")
    fire_pixels = _scan_fire_pixels(datasets["Mask"])

    detections: list[FireDetection] = []
    for row, column, mask_value in fire_pixels:
        latitude, longitude = _navigate(
            float(x_values[column]), float(y_values[row]), navigation
        )
        if latitude is None or longitude is None:
            continue
        base_mask = mask_value - 20 if mask_value >= 30 else mask_value
        classification = MASK_CLASSIFICATIONS[base_mask]
        frp = _science_value(datasets["Power"], row, column, expected_units={"MW"})
        temperature = _science_value(
            datasets["Temp"], row, column, expected_units={"K"}
        )
        area_m2 = _science_value(
            datasets["Area"], row, column, expected_units={"m2", "m^2"}
        )
        quality = _integer_value(datasets["DQF"], row, column, minimum=0, maximum=5)
        identity_source = (
            f"{metadata.satellite}|{metadata.observation_end.isoformat()}|"
            f"{row}|{column}"
        )
        identity = hashlib.sha256(identity_source.encode()).hexdigest()[:24]
        detections.append(
            FireDetection(
                provider=PROVIDER,
                satellite=metadata.satellite,
                product=PRODUCT,
                timestamp=metadata.observation_end,
                latitude=latitude,
                longitude=longitude,
                frp_mw=frp,
                confidence=None,
                classification=classification,
                quality=quality,
                fire_temperature_k=temperature,
                fire_area_km2=None if area_m2 is None else area_m2 / 1_000_000.0,
                temporal_filtered=mask_value >= 30,
                source_resolution_km=2.0,
                source_detection_id=identity,
            )
        )
    return tuple(detections)


def _dataset(product: h5py.File, name: str) -> h5py.Dataset:
    value = product.get(name)
    if not isinstance(value, h5py.Dataset):
        raise GoesDecodeError(f"GOES product is missing required dataset: {name}")
    return value


def _scan_fire_pixels(mask: h5py.Dataset) -> tuple[tuple[int, int, int], ...]:
    found: list[tuple[int, int, int]] = []
    for start in range(0, mask.shape[0], STRIPE_ROWS):
        stripe = np.asarray(mask[start : start + STRIPE_ROWS, :])
        accepted = np.isin(stripe, tuple(FIRE_MASK_VALUES))
        rows, columns = np.nonzero(accepted)
        if len(found) + len(rows) > MAX_FIRE_PIXELS:
            raise GoesDecodeError("GOES product contains too many fire pixels")
        found.extend(
            (start + int(row), int(column), int(stripe[row, column]))
            for row, column in zip(rows, columns, strict=True)
        )
    return tuple(found)


def _scaled_vector(dataset: h5py.Dataset, *, expected_units: str) -> np.ndarray:
    if _text_attr(dataset.attrs, "units") != expected_units:
        raise GoesDecodeError("GOES navigation units are unexpected")
    raw = np.asarray(dataset[:], dtype=np.float64)
    fill = _number_attr(dataset.attrs, "_FillValue", required=False)
    if fill is not None and np.any(raw == fill):
        raise GoesDecodeError("GOES navigation contains fill values")
    result = raw * _number_attr(dataset.attrs, "scale_factor", default=1.0)
    result += _number_attr(dataset.attrs, "add_offset", default=0.0)
    if not np.all(np.isfinite(result)) or np.any(np.abs(result) > 0.2):
        raise GoesDecodeError("GOES navigation coordinates are unsafe")
    return result


def _science_value(
    dataset: h5py.Dataset,
    row: int,
    column: int,
    *,
    expected_units: set[str],
) -> float | None:
    if _text_attr(dataset.attrs, "units") not in expected_units:
        raise GoesDecodeError("GOES science units are unexpected")
    raw = float(dataset[row, column])
    fill = _number_attr(dataset.attrs, "_FillValue", required=False)
    if fill is not None and raw == fill:
        return None
    valid = dataset.attrs.get("valid_range")
    if valid is not None:
        values = np.asarray(valid, dtype=np.float64).reshape(-1)
        if values.size != 2 or raw < values[0] or raw > values[1]:
            return None
    value = raw * _number_attr(dataset.attrs, "scale_factor", default=1.0)
    value += _number_attr(dataset.attrs, "add_offset", default=0.0)
    return value if math.isfinite(value) and value >= 0 else None


def _integer_value(
    dataset: h5py.Dataset, row: int, column: int, *, minimum: int, maximum: int
) -> int | None:
    raw = int(dataset[row, column])
    fill = _number_attr(dataset.attrs, "_FillValue", required=False)
    if fill is not None and raw == int(fill):
        return None
    return raw if minimum <= raw <= maximum else None


def _projection_parameters(
    attrs: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    if _text_attr(attrs, "grid_mapping_name") != "geostationary":
        raise GoesDecodeError("GOES projection type is unsupported")
    if _text_attr(attrs, "sweep_angle_axis") != "x":
        raise GoesDecodeError("GOES projection sweep axis is unsupported")
    height = _number_attr(attrs, "perspective_point_height")
    semi_major = _number_attr(attrs, "semi_major_axis")
    semi_minor = _number_attr(attrs, "semi_minor_axis")
    longitude = _number_attr(attrs, "longitude_of_projection_origin")
    if not SATELLITE_HEIGHT_TOLERANCE[0] <= height <= SATELLITE_HEIGHT_TOLERANCE[1]:
        raise GoesDecodeError("GOES satellite height is unsafe")
    if not all(
        EARTH_RADIUS_TOLERANCE[0] <= value <= EARTH_RADIUS_TOLERANCE[1]
        for value in (semi_major, semi_minor)
    ):
        raise GoesDecodeError("GOES Earth geometry is unsafe")
    if not -180.0 <= longitude <= 180.0:
        raise GoesDecodeError("GOES projection longitude is unsafe")
    return height, semi_major, semi_minor, math.radians(longitude)


def _navigate(
    x: float,
    y: float,
    parameters: tuple[float, float, float, float],
) -> tuple[float | None, float | None]:
    height, semi_major, semi_minor, origin = parameters
    satellite_distance = height + semi_major
    sin_x, cos_x = math.sin(x), math.cos(x)
    sin_y, cos_y = math.sin(y), math.cos(y)
    radius_ratio = (semi_major * semi_major) / (semi_minor * semi_minor)
    a = sin_x * sin_x + cos_x * cos_x * (cos_y * cos_y + radius_ratio * sin_y * sin_y)
    b = -2.0 * satellite_distance * cos_x * cos_y
    c = satellite_distance * satellite_distance - semi_major * semi_major
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0 or not math.isfinite(discriminant):
        return None, None
    distance = (-b - math.sqrt(discriminant)) / (2.0 * a)
    sx = distance * cos_x * cos_y
    sy = -distance * sin_x
    sz = distance * cos_x * sin_y
    longitude = origin - math.atan2(sy, satellite_distance - sx)
    latitude = math.atan2(
        radius_ratio * sz,
        math.hypot(satellite_distance - sx, sy),
    )
    latitude_deg = math.degrees(latitude)
    longitude_deg = math.degrees(longitude)
    if not (-90.0 <= latitude_deg <= 90.0 and -180.0 <= longitude_deg <= 180.0):
        return None, None
    return latitude_deg, longitude_deg


def _text_attr(attrs: Mapping[str, Any], name: str) -> str:
    value = attrs.get(name)
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as err:
            raise GoesDecodeError(f"GOES attribute {name} is invalid") from err
    if isinstance(value, str):
        return value
    raise GoesDecodeError(f"GOES attribute {name} is missing or invalid")


def _number_attr(
    attrs: Mapping[str, Any],
    name: str,
    *,
    required: bool = True,
    default: float | None = None,
) -> float | None:
    value = attrs.get(name)
    if value is None:
        if required:
            raise GoesDecodeError(f"GOES attribute {name} is missing")
        return default
    values = np.asarray(value).reshape(-1)
    if values.size != 1:
        raise GoesDecodeError(f"GOES attribute {name} is invalid")
    number = float(values[0])
    if not math.isfinite(number):
        raise GoesDecodeError(f"GOES attribute {name} is invalid")
    return number
