"""Tests for conservative active-fire provider coverage reporting."""
from __future__ import annotations

import pytest

from custom_components.terralyra.const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
    LOCATION_SOURCE_MANUAL,
)
from custom_components.terralyra.coverage import (
    _central_angle,
    assess_location_coverage,
    summarize_coverage,
)
from custom_components.terralyra.monitoring import MonitoredLocation


def _location(
    location_id: str, name: str, latitude: float, longitude: float
) -> MonitoredLocation:
    return MonitoredLocation(
        id=location_id,
        name=name,
        latitude=latitude,
        longitude=longitude,
        radius_km=100,
        enabled=True,
        source=LOCATION_SOURCE_MANUAL,
    )


def test_lsa_saf_covers_europe_but_not_california() -> None:
    budapest = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_LSA_SAF,
        _location("budapest", "Budapest", 47.4979, 19.0402),
    )
    california = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_LSA_SAF,
        _location("california", "California", 38.5618, -121.6263),
    )

    assert budapest.covered is True
    assert budapest.satellite == "MTG"
    assert california.covered is False
    assert california.recommended_provider == ACTIVE_FIRE_PROVIDER_GOES


def test_goes_covers_california_but_not_europe() -> None:
    california = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_GOES,
        _location("california", "California", 38.5618, -121.6263),
    )
    budapest = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_GOES,
        _location("budapest", "Budapest", 47.4979, 19.0402),
    )

    assert california.covered is True
    assert california.satellite == "G18"
    assert budapest.covered is False
    assert budapest.recommended_provider == ACTIVE_FIRE_PROVIDER_LSA_SAF


def test_unknown_provider_recommends_global_fallback_when_needed() -> None:
    result = assess_location_coverage(
        "unknown",
        _location("arctic", "Arctic", 89.0, 0.0),
    )

    assert result.covered is False
    assert result.recommended_provider == "nasa_firms"


def test_coverage_summary_distinguishes_partial_and_missing() -> None:
    covered = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_LSA_SAF,
        _location("europe", "Europe", 47.0, 19.0),
    )
    uncovered = assess_location_coverage(
        ACTIVE_FIRE_PROVIDER_LSA_SAF,
        _location("america", "America", 38.0, -121.0),
    )

    assert summarize_coverage(()) == "unknown"
    assert summarize_coverage((covered,)) == "covered"
    assert summarize_coverage((covered, uncovered)) == "partial"
    assert summarize_coverage((uncovered,)) == "not_covered"


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(float("nan"), 0), (91, 0), (0, 181)],
)
def test_coverage_rejects_invalid_coordinates(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(ValueError):
        _central_angle(latitude, longitude, 0)
