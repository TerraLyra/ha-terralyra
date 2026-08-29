"""Tests for the bounded direct-h5py GOES FDCF decoder."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import h5py
import numpy as np
import pytest

from custom_components.terralyra.models import ProviderStatus
from custom_components.terralyra.products.goes import parse_catalogue
from custom_components.terralyra.products.goes_decoder import (
    GoesDecodeError,
    decode_goes_fdc,
)
from custom_components.terralyra.providers.goes_active import GoesActiveFireProvider
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


class _Content:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, _size: int):
        yield self._payload


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.status = 200
        self.content_length = len(payload)
        self.content = _Content(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Session:
    def __init__(self, payload: bytes) -> None:
        self._response = _Response(payload)

    def get(self, _url: str, **_kwargs):
        return self._response


async def _executor(function, *args):
    return function(*args)


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


@pytest.mark.asyncio
async def test_provider_downloads_decodes_and_normalizes_tiny_product(
    tmp_path: Path,
) -> None:
    """Exercise the bounded GOES runtime without NOAA or Home Assistant."""
    fixture_path = tmp_path / FILENAME
    _fixture(fixture_path)
    payload = fixture_path.read_bytes()
    prefix = "ABI-L2-FDCF/2026/240/12/"
    catalogue = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Contents><Key>{prefix}{FILENAME}</Key><Size>{len(payload)}</Size></Contents>"
        "</ListBucketResult>"
    ).encode()
    (item,) = parse_catalogue(catalogue, satellite="G19", prefix=prefix)
    session = _Session(payload)
    now = item.metadata.observation_end.replace(minute=15)
    provider = GoesActiveFireProvider(
        session,
        _executor,
        latitude=40.71,
        longitude=-74.01,
        now=lambda: now,
    )
    download_directory = tmp_path / "downloads"
    download_directory.mkdir()
    provider._products._temp_directory = str(download_directory)
    provider._discovery.async_latest = AsyncMock(return_value=item)

    snapshot = await provider.async_fetch_latest()

    assert snapshot.status is ProviderStatus.AVAILABLE
    assert snapshot.provider == "noaa_goes"
    assert snapshot.satellite == "G19"
    assert snapshot.product == "ABI-L2-FDCF"
    assert len(snapshot.detections) == 4
    assert all(detection.provider == "noaa_goes" for detection in snapshot.detections)
    assert list(download_directory.iterdir()) == []


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
