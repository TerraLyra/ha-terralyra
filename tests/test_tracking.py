"""Tests for persistent fire incident lifecycle tracking."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.terralyra.const import (
    EVENT_FIRE_ACTIVITY_INCREASING,
    EVENT_FIRE_APPROACHING,
    EVENT_FIRE_INTENSITY_INCREASING,
)
from custom_components.terralyra.models import FireCluster, FireLifecycle
from custom_components.terralyra.tracking import _trend_events, update_incidents

BASE = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _cluster(at: datetime = BASE, **changes) -> FireCluster:
    values = {
        "latitude": 46.0,
        "longitude": 20.0,
        "distance_km": 25.0,
        "confidence": 0.8,
        "frp_mw": 10.0,
        "acquired": at,
        "pixel_count": 2,
    }
    values.update(changes)
    return FireCluster(**values)


def test_new_incident_has_stable_id_and_initial_aggregates() -> None:
    cluster = _cluster(satellites=("N20", "Terra"))

    result = update_incidents(
        [], [cluster], now=BASE, matching_radius_km=3.0, memory_hours=6
    )

    incident = result.incidents[0]
    assert len(result.new_incidents) == 1
    assert cluster.lifecycle is FireLifecycle.NEW
    assert cluster.track_id == incident["track_id"]
    assert incident["first_seen"] == BASE.isoformat()
    assert incident["minimum_distance_km"] == 25.0
    assert incident["maximum_frp_mw"] == 10.0
    assert incident["maximum_pixel_count"] == 2
    assert incident["detections_total"] == 2
    assert incident["frp_trend"] == "unknown"
    assert incident["trend_sample_count"] == 1
    assert incident["satellites"] == ["N20", "Terra"]


def test_continuing_incident_updates_current_and_maximum_values() -> None:
    first = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )
    incident_id = first.incidents[0]["track_id"]
    later = BASE + timedelta(minutes=10)
    cluster = _cluster(
        later,
        latitude=46.005,
        distance_km=23.0,
        confidence=0.9,
        frp_mw=25.0,
        pixel_count=4,
    )

    result = update_incidents(
        first.incidents,
        [cluster],
        now=later,
        matching_radius_km=3.0,
        memory_hours=6,
    )

    incident = result.incidents[0]
    assert result.new_incidents == []
    assert incident["track_id"] == incident_id
    assert cluster.lifecycle is FireLifecycle.CONTINUING
    assert incident["minimum_distance_km"] == 23.0
    assert incident["maximum_frp_mw"] == 25.0
    assert incident["maximum_confidence"] == 0.9
    assert incident["maximum_pixel_count"] == 4
    assert incident["detections_total"] == 6


def test_same_product_does_not_double_count_detections() -> None:
    first = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )

    repeated = update_incidents(
        first.incidents,
        [_cluster()],
        now=BASE + timedelta(minutes=5),
        matching_radius_km=3.0,
        memory_hours=6,
    )

    assert repeated.incidents[0]["detections_total"] == 2


def test_missing_detection_becomes_inactive_but_is_not_ended() -> None:
    first = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )

    result = update_incidents(
        first.incidents,
        [],
        now=BASE + timedelta(minutes=10),
        matching_radius_km=3.0,
        memory_hours=6,
    )

    assert result.incidents[0]["lifecycle"] == FireLifecycle.INACTIVE.value
    assert result.ended_incident_ids == []


def test_incident_ends_only_after_memory_window() -> None:
    first = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )

    result = update_incidents(
        first.incidents,
        [],
        now=BASE + timedelta(hours=6, seconds=1),
        matching_radius_km=3.0,
        memory_hours=6,
    )

    assert result.incidents == []
    assert result.ended_incident_ids


def test_history_can_outlive_dedup_without_suppressing_new_incident() -> None:
    first = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=2
    )

    result = update_incidents(
        first.incidents,
        [_cluster(acquired=BASE + timedelta(hours=3))],
        now=BASE + timedelta(hours=3),
        matching_radius_km=3.0,
        memory_hours=2,
        history_hours=12,
    )

    assert len(result.incidents) == 2
    assert len(result.new_incidents) == 1
    assert result.incidents[0]["lifecycle"] == FireLifecycle.INACTIVE.value
    assert result.incidents[1]["lifecycle"] == FireLifecycle.NEW.value


def test_legacy_persisted_track_is_migrated_and_continued() -> None:
    legacy = {
        "track_id": "legacy-id",
        "latitude": 46.0,
        "longitude": 20.0,
        "first_seen": BASE.isoformat(),
        "last_seen": BASE.isoformat(),
        "peak_frp_mw": 12.0,
        "frp_mw": 12.0,
        "confidence": 0.7,
        "pixel_count": 1,
    }
    later = BASE + timedelta(minutes=10)

    result = update_incidents(
        [legacy],
        [_cluster(later)],
        now=later,
        matching_radius_km=3.0,
        memory_hours=6,
    )

    incident = result.incidents[0]
    assert incident["track_id"] == "legacy-id"
    assert incident["lifecycle"] == FireLifecycle.CONTINUING.value
    assert incident["maximum_frp_mw"] == 12.0
    assert incident["detections_total"] == 3


def test_meaningful_trend_transitions_emit_incident_events() -> None:
    result = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )
    for minutes, frp, pixels, distance in (
        (10, 20.0, 4, 23.0),
        (20, 35.0, 7, 20.0),
    ):
        at = BASE + timedelta(minutes=minutes)
        result = update_incidents(
            result.incidents,
            [
                _cluster(
                    at,
                    latitude=46.0 + 0.001 * minutes,
                    frp_mw=frp,
                    pixel_count=pixels,
                    distance_km=distance,
                )
            ],
            now=at,
            matching_radius_km=3.0,
            memory_hours=6,
        )

    assert {event[0] for event in result.trend_events} == {
        EVENT_FIRE_INTENSITY_INCREASING,
        EVENT_FIRE_ACTIVITY_INCREASING,
        EVENT_FIRE_APPROACHING,
    }


def test_repeated_product_does_not_repeat_trend_events() -> None:
    result = update_incidents(
        [], [_cluster()], now=BASE, matching_radius_km=3.0, memory_hours=6
    )
    for minutes in (10, 20):
        at = BASE + timedelta(minutes=minutes)
        cluster = _cluster(
            at,
            latitude=46.0 + 0.001 * minutes,
            frp_mw=10 + minutes,
            pixel_count=2 + minutes,
            distance_km=25 - minutes / 5,
        )
        result = update_incidents(
            result.incidents,
            [cluster],
            now=at,
            matching_radius_km=3.0,
            memory_hours=6,
        )

    repeated = update_incidents(
        result.incidents,
        [cluster],
        now=BASE + timedelta(minutes=25),
        matching_radius_km=3.0,
        memory_hours=6,
    )

    assert repeated.trend_events == []


def test_trend_event_cooldown_survives_state_oscillation() -> None:
    incident = {"activity_trend": "increasing"}
    previous = {
        "frp_trend": "stable",
        "activity_trend": "stable",
        "distance_trend": "stable",
    }

    first = _trend_events(incident, BASE, previous)
    repeated = _trend_events(
        incident, BASE + timedelta(minutes=30), previous
    )

    assert first == [EVENT_FIRE_ACTIVITY_INCREASING]
    assert repeated == []
