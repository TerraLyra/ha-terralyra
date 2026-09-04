"""Tests for the production-safe MSG-IODC coverage foundation."""

from __future__ import annotations

import pytest

from custom_components.terralyra.providers.msg_iodc import (
    MAX_USABLE_CENTRAL_ANGLE_DEGREES,
    select_msg_iodc_satellite,
)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (0.35, 32.58),  # Kampala
        (-1.29, 36.82),  # Nairobi
        (25.20, 55.27),  # Dubai
        (28.61, 77.21),  # Delhi
        (47.50, 19.04),  # Budapest, in the overlap with the prime service
    ],
)
def test_selects_msg_iodc_for_safe_locations(
    latitude: float, longitude: float
) -> None:
    coverage = select_msg_iodc_satellite(latitude, longitude)
    assert coverage is not None
    assert coverage.satellite == "Meteosat-9 IODC"
    assert coverage.central_angle_degrees <= MAX_USABLE_CENTRAL_ANGLE_DEGREES


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (34.05, -118.24),  # Los Angeles
        (35.68, 139.69),  # Tokyo
        (-33.87, 151.21),  # Sydney
        (64.84, -147.72),  # Fairbanks
    ],
)
def test_excludes_locations_outside_conservative_msg_iodc_coverage(
    latitude: float, longitude: float
) -> None:
    assert select_msg_iodc_satellite(latitude, longitude) is None


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (float("nan"), 45.5),
        (91.0, 45.5),
        (0.0, 181.0),
    ],
)
def test_rejects_invalid_coordinates(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError):
        select_msg_iodc_satellite(latitude, longitude)
