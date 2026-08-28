"""Tests for noise-resistant fire incident trends."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.terralyra.models import FireCluster
from custom_components.terralyra.trends import (
    MAX_STORED_SAMPLES,
    _distance_trend,
    _metric_trend,
    add_observation_and_update_trends,
)

BASE = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


def _cluster(minutes: int, frp: float, pixels: int, distance: float) -> FireCluster:
    return FireCluster(
        latitude=46.0,
        longitude=20.0,
        distance_km=distance,
        confidence=0.8,
        frp_mw=frp,
        acquired=BASE + timedelta(minutes=minutes),
        pixel_count=pixels,
    )


def test_trends_require_three_samples_and_twenty_minutes() -> None:
    incident: dict = {}
    add_observation_and_update_trends(incident, _cluster(0, 10, 2, 30))
    add_observation_and_update_trends(incident, _cluster(10, 30, 5, 20))

    assert incident["frp_trend"] == "unknown"
    assert incident["activity_trend"] == "unknown"
    assert incident["distance_trend"] == "unknown"


def test_increasing_activity_and_approaching_distance_are_detected() -> None:
    incident: dict = {}
    for cluster in (
        _cluster(0, 10, 1, 30),
        _cluster(30, 20, 3, 27),
        _cluster(60, 35, 5, 24),
    ):
        add_observation_and_update_trends(incident, cluster)

    assert incident["frp_trend"] == "increasing"
    assert incident["activity_trend"] == "increasing"
    assert incident["distance_trend"] == "approaching"
    assert incident["trend_sample_count"] == 3
    assert incident["trend_window_minutes"] == 60


def test_small_fluctuations_are_stable() -> None:
    incident: dict = {}
    for cluster in (
        _cluster(0, 10.0, 3, 30.0),
        _cluster(30, 10.8, 3, 29.7),
        _cluster(60, 9.7, 3, 30.2),
    ):
        add_observation_and_update_trends(incident, cluster)

    assert incident["frp_trend"] == "stable"
    assert incident["activity_trend"] == "stable"
    assert incident["distance_trend"] == "stable"


def test_decreasing_activity_and_receding_distance_are_detected() -> None:
    incident: dict = {}
    for cluster in (
        _cluster(0, 40, 6, 20),
        _cluster(30, 25, 4, 24),
        _cluster(60, 10, 1, 29),
    ):
        add_observation_and_update_trends(incident, cluster)

    assert incident["frp_trend"] == "decreasing"
    assert incident["activity_trend"] == "decreasing"
    assert incident["distance_trend"] == "receding"


def test_hysteresis_retains_direction_until_half_threshold() -> None:
    assert _metric_trend(1.2, 2.0, "increasing").value == "increasing"
    assert _metric_trend(0.8, 2.0, "increasing").value == "stable"
    assert _distance_trend(-0.6, 1.0, "approaching").value == "approaching"
    assert _distance_trend(-0.4, 1.0, "approaching").value == "stable"


def test_stored_history_is_bounded() -> None:
    incident: dict = {}
    for index in range(MAX_STORED_SAMPLES + 10):
        add_observation_and_update_trends(
            incident,
            _cluster(index * 10, 10 + index, 2, 30 - index * 0.1),
        )

    assert len(incident["samples"]) == MAX_STORED_SAMPLES
