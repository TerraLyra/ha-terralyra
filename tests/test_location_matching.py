"""Tests for incident-to-location relevance matching."""
from datetime import UTC, datetime

import pytest

from custom_components.terralyra.location_matching import (
    match_incident_to_locations,
)
from custom_components.terralyra.models import DistanceTrend, FireCluster
from custom_components.terralyra.monitoring import MonitoredLocation


def _location(
    location_id: str,
    name: str,
    latitude: float,
    longitude: float,
    radius_km: float,
    *,
    enabled: bool = True,
) -> MonitoredLocation:
    return MonitoredLocation(
        id=location_id,
        name=name,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        enabled=enabled,
        source="manual",
    )


def test_one_incident_matches_multiple_locations_independently() -> None:
    matches = match_incident_to_locations(
        "incident-1",
        47.0,
        19.0,
        (
            _location("near", "Near", 47.0, 18.9, 10),
            _location("far", "Far", 46.0, 19.0, 50),
            _location("disabled", "Disabled", 47.0, 19.0, 10, enabled=False),
        ),
    )

    assert [match.location_id for match in matches] == ["near", "far"]
    assert matches[0].inside_radius is True
    assert matches[1].inside_radius is False
    assert all(match.incident_id == "incident-1" for match in matches)


def test_distance_trends_are_per_location() -> None:
    matches = match_incident_to_locations(
        "incident-2",
        47.0,
        19.0,
        (
            _location("approach", "Approach", 47.0, 18.8, 50),
            _location("recede", "Recede", 47.0, 19.2, 50),
            _location("steady", "Steady", 46.9, 19.0, 50),
        ),
        previous_distances={"approach": 20.0, "recede": 10.0, "steady": 11.5},
    )
    trends = {match.location_id: match.distance_trend for match in matches}
    assert trends == {
        "approach": DistanceTrend.APPROACHING,
        "recede": DistanceTrend.RECEDING,
        "steady": DistanceTrend.STABLE,
    }


def test_direction_is_relative_to_each_location() -> None:
    matches = match_incident_to_locations(
        "incident-3",
        47.1,
        19.0,
        (_location("south", "South", 47.0, 19.0, 20),),
    )
    assert matches[0].direction == "N"


def test_matches_are_exposed_as_bounded_cluster_attributes() -> None:
    match = match_incident_to_locations(
        "incident-4",
        47.0,
        19.0,
        (_location("home", "Home", 47.0, 19.0, 10),),
    )[0]
    cluster = FireCluster(
        latitude=47.0,
        longitude=19.0,
        distance_km=0,
        confidence=0.8,
        frp_mw=5,
        acquired=datetime(2026, 8, 30, tzinfo=UTC),
        pixel_count=1,
        track_id="incident-4",
        location_matches=(match,),
    )
    attrs = cluster.attrs()
    assert attrs["location_matches"] == [
        {
            "incident_id": "incident-4",
            "location_id": "home",
            "location_name": "Home",
            "distance_km": 0.0,
            "location_radius_km": 10,
            "direction": "HERE",
            "inside_radius": True,
            "distance_trend": "unknown",
        }
    ]


@pytest.mark.parametrize("latitude,longitude", [(91, 0), (0, 181), (float("nan"), 0)])
def test_invalid_incident_coordinates_are_rejected(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(ValueError):
        match_incident_to_locations(
            "incident-5",
            latitude,
            longitude,
            (_location("home", "Home", 47.0, 19.0, 10),),
        )
