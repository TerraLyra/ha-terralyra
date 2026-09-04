"""Tests for bounded MSG-IODC schema discovery."""
from __future__ import annotations

from datetime import UTC, datetime
import io

import h5py
import numpy as np
import pytest

from custom_components.terralyra.products.msg_iodc import (
    FILE_PREFIX,
    MsgIodcSchemaError,
    candidate_list_products,
    inspect_list_product_schema,
    parse_list_product_filename,
)

FILENAME = f"{FILE_PREFIX}202609041815"


def _fixture() -> bytes:
    payload = io.BytesIO()
    with h5py.File(payload, "w") as product:
        product.attrs["platform"] = "Meteosat-9"
        fires = product.create_group("fires")
        latitude = fires.create_dataset(
            "latitude", data=np.array([1.25, 2.5], dtype="f4"), chunks=(2,)
        )
        latitude.attrs["units"] = "degrees_north"
        latitude.attrs["_FillValue"] = np.float32(-999.0)
    return payload.getvalue()


def test_schema_probe_records_metadata_without_values() -> None:
    schema = inspect_list_product_schema(FILENAME, _fixture())

    assert schema["product_time"] == "2026-09-04T18:15:00+00:00"
    latitude = next(
        item for item in schema["objects"] if item["path"] == "/fires/latitude"
    )
    assert latitude["dtype"] == "float32"
    assert latitude["shape"] == [2]
    assert latitude["attributes"]["units"] == "degrees_north"
    assert "values" not in latitude
    assert "1.25" not in str(schema)


def test_candidate_names_are_newest_first_and_bounded() -> None:
    candidates = candidate_list_products(
        datetime(2026, 9, 4, 18, 38, tzinfo=UTC), lookback_slots=2
    )

    assert candidates[0][0].endswith("202609041815")
    assert candidates[1][0].endswith("202609041800")
    assert "/2026/09/04/" in candidates[0][1]


@pytest.mark.parametrize(
    "filename",
    [
        "../product",
        f"{FILE_PREFIX}202609041817",
        f"{FILE_PREFIX}202613041815",
        f"{FILE_PREFIX.replace('ListProduct', 'QualityProduct')}202609041815",
    ],
)
def test_rejects_unknown_or_invalid_filename(filename: str) -> None:
    with pytest.raises(MsgIodcSchemaError):
        parse_list_product_filename(filename)


def test_rejects_non_hdf5_payload() -> None:
    with pytest.raises(MsgIodcSchemaError, match="not readable HDF5"):
        inspect_list_product_schema(FILENAME, b"not-hdf5")


def test_rejects_oversized_declared_dataset() -> None:
    payload = io.BytesIO()
    with h5py.File(payload, "w") as product:
        product.create_dataset("unsafe", shape=(5_000_001,), dtype="u1")

    with pytest.raises(MsgIodcSchemaError, match="dimensions"):
        inspect_list_product_schema(FILENAME, payload.getvalue())
