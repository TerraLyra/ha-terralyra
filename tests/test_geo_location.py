"""Tests for TerraLyra map entities and cluster metadata."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.terralyra.activity import ActivitySummary
from custom_components.terralyra.const import (
    ATTR_ACTIVITY_TREND,
    ATTR_DISTANCE_TREND,
    ATTR_LATITUDE,
    ATTR_DETECTIONS_TOTAL,
    ATTR_DURATION_MINUTES,
    ATTR_FRP_TREND,
    ATTR_LIFECYCLE,
    ATTR_LOCATION_DESCRIPTION,
    ATTR_LONGITUDE,
    ATTR_NEAREST_SETTLEMENT,
    ATTR_PEAK_FRP_MW,
    ATTR_PRODUCT_TIME,
    ATTR_SOURCE_URL,
    ATTR_TRACK_ID,
    DOMAIN,
)
from custom_components.terralyra.coordinator import (
    CoordinatorData,
    FireCluster,
    _tracked_fire_clusters,
)
from custom_components.terralyra.models import (
    DistanceTrend,
    FireLifecycle,
    MetricTrend,
    ProviderStatus,
)
from custom_components.terralyra.situation import assess_situation
from custom_components.terralyra.geo_location import (
    TerraLyraFireLocation,
    _async_remove_expired_entity,
)


def _cluster(**changes) -> FireCluster:
    values = {
        "latitude": 46.253,
        "longitude": 20.141,
        "distance_km": 12.34,
        "confidence": 0.91,
        "frp_mw": 42.5,
        "acquired": datetime(2026, 8, 25, 20, 20, tzinfo=UTC),
        "pixel_count": 2,
        "track_id": "abcdef123456",
        "peak_frp_mw": 51.0,
        "lifecycle": FireLifecycle.CONTINUING,
        "first_seen": datetime(2026, 8, 25, 20, 0, tzinfo=UTC),
        "last_seen": datetime(2026, 8, 25, 20, 20, tzinfo=UTC),
        "detections_total": 5,
        "frp_trend": MetricTrend.INCREASING,
        "activity_trend": MetricTrend.STABLE,
        "distance_trend": DistanceTrend.APPROACHING,
        "trend_samples": 4,
        "trend_window_minutes": 30,
    }
    values.update(changes)
    return FireCluster(**values)


def _entity(cluster: FireCluster) -> TerraLyraFireLocation:
    entity = object.__new__(TerraLyraFireLocation)
    entity._cluster = cluster
    entity.coordinator = SimpleNamespace(
        data=CoordinatorData(
            product_time=datetime(2026, 8, 25, 20, 30, tzinfo=UTC),
            source_url="https://datalsasaf.lsasvcs.ipma.pt/product.csv.gz",
            filename="product.csv.gz",
            active_clusters=[cluster],
            tracked_fires=[cluster],
            new_fires=[],
            trend_events=[],
            raw_pixels_in_radius=2,
            activity=ActivitySummary(),
            situation=assess_situation(
                [cluster],
                provider_status=ProviderStatus.AVAILABLE,
                product_time=datetime(2026, 8, 25, 20, 30, tzinfo=UTC),
                now=datetime(2026, 8, 25, 20, 30, tzinfo=UTC),
            ),
        )
    )
    return entity


def test_cluster_attributes_include_tracking_metadata() -> None:
    attrs = _cluster().attrs()

    assert attrs[ATTR_TRACK_ID] == "abcdef123456"
    assert attrs[ATTR_PEAK_FRP_MW] == 51.0
    assert attrs[ATTR_LIFECYCLE] == "continuing"
    assert attrs[ATTR_DURATION_MINUTES] == 20.0
    assert attrs[ATTR_DETECTIONS_TOTAL] == 5
    assert attrs[ATTR_FRP_TREND] == "increasing"
    assert attrs[ATTR_ACTIVITY_TREND] == "stable"
    assert attrs[ATTR_DISTANCE_TREND] == "approaching"


def test_map_entity_exposes_location_distance_and_details() -> None:
    entity = _entity(_cluster())

    assert entity.source == DOMAIN
    assert entity.latitude == 46.253
    assert entity.longitude == 20.141
    assert entity.distance == 12.34
    assert entity.state == 12.3
    assert entity.extra_state_attributes[ATTR_TRACK_ID] == "abcdef123456"
    assert entity.extra_state_attributes[ATTR_PEAK_FRP_MW] == 51.0
    assert entity.extra_state_attributes[ATTR_PRODUCT_TIME] == "2026-08-25T20:30:00+00:00"
    assert entity.extra_state_attributes[ATTR_SOURCE_URL].startswith("https://datalsasaf.")


def test_map_entity_updates_existing_track_without_changing_identity() -> None:
    entity = _entity(_cluster())
    entity.async_write_ha_state = Mock()
    updated = _cluster(
        latitude=46.5,
        longitude=20.5,
        distance_km=31.0,
        frp_mw=60.0,
        nearest_settlement="Szeged",
        location_description="Szeged közelében észlelt tűz",
    )

    entity.set_cluster(updated)

    assert entity.latitude == 46.5
    assert entity.longitude == 20.5
    assert entity.distance == 31.0
    assert entity.name == "Szeged közelében észlelt tűz"
    assert entity.extra_state_attributes[ATTR_LATITUDE] == 46.5
    assert entity.extra_state_attributes[ATTR_LONGITUDE] == 20.5
    assert entity.extra_state_attributes[ATTR_NEAREST_SETTLEMENT] == "Szeged"
    assert (
        entity.extra_state_attributes[ATTR_LOCATION_DESCRIPTION]
        == "Szeged közelében észlelt tűz"
    )


def test_recent_tracks_become_separate_map_markers() -> None:
    tracks = [
        {
            "track_id": "first",
            "latitude": 46.253,
            "longitude": 20.141,
            "last_seen": "2026-08-25T20:20:00+00:00",
            "confidence": 0.91,
            "frp_mw": 42.5,
            "peak_frp_mw": 51.0,
            "pixel_count": 2,
        },
        {
            "track_id": "second",
            "latitude": 47.0,
            "longitude": 21.0,
            "last_seen": "2026-08-25T20:30:00+00:00",
            "confidence": 0.67,
            "frp_mw": 13.97,
            "peak_frp_mw": 13.97,
            "pixel_count": 1,
        },
    ]

    markers = _tracked_fire_clusters(tracks, 46.2, 20.1)

    assert {marker.track_id for marker in markers} == {"first", "second"}
    assert all(marker.distance_km > 0 for marker in markers)
    recent_only = _tracked_fire_clusters(
        tracks,
        46.2,
        20.1,
        visible_since=datetime(2026, 8, 25, 20, 25, tzinfo=UTC),
    )
    assert [marker.track_id for marker in recent_only] == ["second"]


def test_legacy_track_without_map_metadata_is_ignored() -> None:
    legacy_track = {
        "track_id": "legacy",
        "latitude": 46.253,
        "longitude": 20.141,
        "last_seen": "2026-08-25T20:20:00+00:00",
        "peak_frp_mw": 51.0,
    }

    assert _tracked_fire_clusters([legacy_track], 46.2, 20.1) == []


def test_expired_map_entity_is_removed_from_registry() -> None:
    hass = Mock()
    registry = Mock()
    registry.async_get.return_value = object()
    entity = SimpleNamespace(entity_id="geo_location.expired_fire")

    _async_remove_expired_entity(hass, registry, entity)

    registry.async_remove.assert_called_once_with("geo_location.expired_fire")
    hass.async_create_task.assert_not_called()


def test_unregistered_expired_map_entity_is_removed_from_platform() -> None:
    hass = Mock()
    registry = Mock()
    registry.async_get.return_value = None
    entity = SimpleNamespace(
        entity_id="geo_location.expired_fire",
        async_remove=Mock(return_value="remove-task"),
    )

    _async_remove_expired_entity(hass, registry, entity)

    registry.async_remove.assert_not_called()
    entity.async_remove.assert_called_once_with(force_remove=True)
    hass.async_create_task.assert_called_once_with("remove-task")
