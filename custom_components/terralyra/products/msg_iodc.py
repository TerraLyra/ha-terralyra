"""Bounded schema inspection helpers for MSG-IODC FRP List Products.

This module deliberately does not decode fire observations yet.  It records a
small, deterministic description of an authenticated List Product without
reading science-array values or retaining the upstream file.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import io
import math
import re
from typing import Any

import h5py
import numpy as np

BASE_URL = "https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG-IODC/FRP-PIXEL/HDF5"
FILE_PREFIX = "HDF5_LSASAF_MSG-IODC_FRP-PIXEL-ListProduct_IODC-Disk_"
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


class MsgIodcSchemaError(Exception):
    """An MSG-IODC schema probe failed a bounded validation rule."""


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


def _safe_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    names = sorted(str(name) for name in attributes.keys())
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
