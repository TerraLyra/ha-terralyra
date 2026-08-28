"""Tests for MTLST response validation and opt-in refresh scheduling."""
from __future__ import annotations

import json

import pytest

from custom_components.terralyra.lst_coordinator import _staggered_interval
from custom_components.terralyra.products.lst import (
    LandSurfaceTemperatureError,
    parse_feature_info,
)


def _payload(
    temperature: str = "304.829987",
    quality: str = "102:land clear nominal (102)",
    uncertainty: str = "1.210000",
) -> bytes:
    return json.dumps(
        [
            {
                "name": "LST",
                "units": "K",
                "point": {"SRS": "EPSG:4326", "coords": "18.999010,47.000990"},
                "data": {"2026-08-28T10:00:00Z": temperature},
            },
            {
                "name": "LST",
                "units": "UNITLESS",
                "point": {"SRS": "EPSG:4326", "coords": "18.999010,47.000990"},
                "data": {"2026-08-28T10:00:00Z": quality},
            },
            {
                "name": "LST",
                "units": "K",
                "point": {"SRS": "EPSG:4326", "coords": "18.999010,47.000990"},
                "data": {"2026-08-28T10:00:00Z": uncertainty},
            },
        ]
    ).encode()


def test_parse_live_mtlst_shape() -> None:
    observation = parse_feature_info(_payload())

    assert observation.temperature_kelvin == pytest.approx(304.829987)
    assert observation.temperature_celsius == pytest.approx(31.679987)
    assert observation.uncertainty_kelvin == pytest.approx(1.21)
    assert observation.quality == "102:land clear nominal (102)"
    assert observation.latitude == pytest.approx(47.000990)
    assert observation.longitude == pytest.approx(18.999010)


def test_parse_nodata_preserves_quality_and_time() -> None:
    observation = parse_feature_info(_payload(temperature="nodata"))

    assert observation.temperature_kelvin is None
    assert observation.temperature_celsius is None
    assert observation.quality == "102:land clear nominal (102)"


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        _payload(temperature="401"),
        _payload(uncertainty="nan"),
    ],
)
def test_parse_rejects_malformed_or_unsafe_values(payload: bytes) -> None:
    with pytest.raises(LandSurfaceTemperatureError):
        parse_feature_info(payload)


def test_lst_refresh_interval_is_staggered_and_bounded() -> None:
    first = _staggered_interval("entry-one")
    second = _staggered_interval("entry-one")

    assert first == second
    assert 12.5 * 60 <= first.total_seconds() <= 17.5 * 60
