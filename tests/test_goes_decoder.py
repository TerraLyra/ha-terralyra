"""Tests for the bounded direct-h5py GOES FDCF decoder."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from custom_components.terralyra.products.goes_decoder import (
    GoesDecodeError,
    decode_goes_fdc,
)
from custom_components.terralyra.providers.goes_spike import parse_fdc_filename

FILENAME = (
    "OR_ABI-L2-FDCF-M6_G19_s20262401200200_"
    "e20262401209508_c20262401210123.nc"
)
SOURCE_URL = f"https://noaa-goes19.s3.amazonaws.com/ABI-L2-FDCF/{FILENAME}"


def _fixture(path: Path) -> None:
    with h5py.File(path, "w") as product:
        mask = product.create_dataset(
            "Mask", data=np.array([[0, 10, 30], [15, 9, 11]], dtype="u1"), chunks=(1, 3)
        )
        mask.attrs["_FillValue"] = np.uint8(255)
        for name, data, units in (
            ("Power", [[0, 25, 30], [40, 0, -9]], "MW"),
            ("Temp", [[0, 300, 310], [320, 0, 65535]], "K"),
            ("Area", [[0, 2_000_000, 3_000_000], [4_000_000, 0, 65535]], "m2"),
        ):
            dtype = "f4" if name == "Power" else "u4"
            dataset = product.create_dataset(
                name, data=np.array(data, dtype=dtype), chunks=(1, 3)
            )
            dataset.attrs["units"] = units
            dataset.attrs["_FillValue"] = -9.0 if name == "Power" else np.uint32(65535)
            dataset.attrs["valid_range"] = np.array([0, 10_000_000], dtype="f8")
            dataset.attrs["scale_factor"] = 1.0
            dataset.attrs["add_offset"] = 0.0
        dqf = product.create_dataset(
            "DQF", data=np.array([[0, 0, 1], [2, 0, 255]], dtype="u1"), chunks=(1, 3)
        )
        dqf.attrs["_FillValue"] = np.uint8(255)
        x = product.create_dataset("x", data=np.array([-0.01, 0.0, 0.01], dtype="f4"))
        y = product.create_dataset("y", data=np.array([0.01, -0.01], dtype="f4"))
        for dataset in (x, y):
            dataset.attrs["units"] = "rad"
            dataset.attrs["scale_factor"] = 1.0
            dataset.attrs["add_offset"] = 0.0
        projection = product.create_dataset("goes_imager_projection", data=np.uint8(0))
        projection.attrs["grid_mapping_name"] = "geostationary"
        projection.attrs["sweep_angle_axis"] = "x"
        projection.attrs["perspective_point_height"] = 35_786_023.0
        projection.attrs["semi_major_axis"] = 6_378_137.0
        projection.attrs["semi_minor_axis"] = 6_356_752.31414
        projection.attrs["longitude_of_projection_origin"] = -75.0


def _decode(path: Path):
    return decode_goes_fdc(
        path,
        parse_fdc_filename(FILENAME),
        source_url=SOURCE_URL,
        received_at=datetime(2026, 8, 28, 12, 15, tzinfo=UTC),
    )


def test_decode_tiny_product_preserves_quality_and_optional_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / FILENAME
    _fixture(path)

    snapshot = _decode(path)

    assert snapshot.satellite == "G19"
    assert len(snapshot.detections) == 4
    by_class = {
        detection.classification: detection
        for detection in snapshot.detections
        if not detection.temporal_filtered
    }
    assert by_class["good"].frp_mw == 25.0
    assert by_class["good"].fire_temperature_k == 300.0
    assert by_class["good"].fire_area_km2 == 2.0
    assert by_class["low_probability"].quality == 2
    saturated = by_class["saturated"]
    assert saturated.frp_mw is None
    assert saturated.fire_temperature_k is None
    assert saturated.fire_area_km2 is None
    temporal = next(d for d in snapshot.detections if d.temporal_filtered)
    assert temporal.classification == "good"
    assert temporal.confidence is None
    assert all(
        -90 <= detection.latitude <= 90
        and -180 <= detection.longitude <= 180
        for detection in snapshot.detections
    )
    assert len({d.source_detection_id for d in snapshot.detections}) == 4


@pytest.mark.parametrize("mask_value", [1, 9, 16, 29, 36, 255])
def test_non_fire_mask_categories_are_rejected(tmp_path: Path, mask_value: int) -> None:
    path = tmp_path / FILENAME
    _fixture(path)
    with h5py.File(path, "r+") as product:
        product["Mask"][:] = mask_value

    assert _decode(path).detections == ()


def test_reject_mismatched_science_dimensions(tmp_path: Path) -> None:
    path = tmp_path / FILENAME
    _fixture(path)
    with h5py.File(path, "r+") as product:
        del product["Power"]
        product.create_dataset("Power", data=np.zeros((1, 3)), chunks=(1, 3))

    with pytest.raises(GoesDecodeError, match="inconsistent dimensions"):
        _decode(path)


def test_reject_unallowlisted_source(tmp_path: Path) -> None:
    path = tmp_path / FILENAME
    _fixture(path)

    with pytest.raises(GoesDecodeError, match="not allowlisted"):
        decode_goes_fdc(
            path,
            parse_fdc_filename(FILENAME),
            source_url="https://example.com/product.nc",
        )


def test_off_disk_navigation_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / FILENAME
    _fixture(path)
    with h5py.File(path, "r+") as product:
        product["x"][1] = 0.19

    snapshot = _decode(path)

    assert len(snapshot.detections) < 4


def test_reject_invalid_projection_metadata(tmp_path: Path) -> None:
    path = tmp_path / FILENAME
    _fixture(path)
    with h5py.File(path, "r+") as product:
        product["goes_imager_projection"].attrs["sweep_angle_axis"] = "y"

    with pytest.raises(GoesDecodeError, match="sweep axis"):
        _decode(path)
