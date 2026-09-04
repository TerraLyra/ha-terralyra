"""Tests for the production-safe Himawari coverage foundation."""

from __future__ import annotations

import pytest

from custom_components.terralyra.providers.himawari import (
    MAX_USABLE_CENTRAL_ANGLE_DEGREES,
    select_himawari_satellite,
)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (35.68, 139.69),  # Tokyo
        (-33.87, 151.21),  # Sydney
        (1.35, 103.82),  # Singapore
        (28.61, 77.21),  # Delhi, deliberately near the western safe edge
    ],
)
def test_selects_himawari_for_safe_asia_pacific_locations(
    latitude: float, longitude: float
) -> None:
    coverage = select_himawari_satellite(latitude, longitude)
    assert coverage is not None
    assert coverage.satellite == "Himawari-9"
    assert coverage.central_angle_degrees <= MAX_USABLE_CENTRAL_ANGLE_DEGREES


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (47.50, 19.04),  # Budapest
        (34.05, -118.24),  # Los Angeles
        (0.35, 32.58),  # Kampala
        (64.84, -147.72),  # Fairbanks, high-latitude/edge geometry
    ],
)
def test_excludes_locations_outside_conservative_himawari_coverage(
    latitude: float, longitude: float
) -> None:
    assert select_himawari_satellite(latitude, longitude) is None


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (float("nan"), 140.7),
        (91.0, 140.7),
        (0.0, 181.0),
    ],
)
def test_rejects_invalid_coordinates(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError):
        select_himawari_satellite(latitude, longitude)
