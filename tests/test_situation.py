"""Tests for explainable Active Fire Situation assessment."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.terralyra.models import (
    DistanceTrend,
    FireCluster,
    MetricTrend,
    ProviderStatus,
)
from custom_components.terralyra.situation import SituationLevel, assess_situation

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _cluster(distance: float, frp: float = 10, **changes) -> FireCluster:
    values = {
        "latitude": 46.0,
        "longitude": 20.0,
        "distance_km": distance,
        "confidence": 0.8,
        "frp_mw": frp,
        "acquired": NOW,
        "pixel_count": 1,
    }
    values.update(changes)
    return FireCluster(**values)


def _assess(clusters, status=ProviderStatus.AVAILABLE, age_minutes=10):
    return assess_situation(
        clusters,
        provider_status=status,
        product_time=NOW - timedelta(minutes=age_minutes),
        now=NOW,
    )


def test_no_current_detections_is_normal_with_fresh_data() -> None:
    result = _assess([])

    assert result.level is SituationLevel.NORMAL
    assert result.reasons == ("no_current_detections",)


def test_distant_detection_is_elevated_not_high() -> None:
    result = _assess([_cluster(300, 150)])

    assert result.level is SituationLevel.ELEVATED
    assert result.score == 2


def test_nearby_multi_signal_activity_is_critical() -> None:
    clusters = [
        _cluster(
            8,
            120,
            distance_trend=DistanceTrend.APPROACHING,
            frp_trend=MetricTrend.INCREASING,
            activity_trend=MetricTrend.INCREASING,
        ),
        _cluster(15, 40),
    ]

    result = _assess(clusters)

    assert result.level is SituationLevel.CRITICAL
    assert result.score == 12
    assert result.approaching_incidents == 1


def test_near_detection_without_corroborating_signals_is_high() -> None:
    result = _assess([_cluster(9)])

    assert result.level is SituationLevel.HIGH
    assert result.score == 5


def test_stale_or_failed_provider_is_unknown_never_normal() -> None:
    assert _assess([], age_minutes=61).level is SituationLevel.UNKNOWN
    assert (
        _assess([], status=ProviderStatus.OUTAGE).level
        is SituationLevel.UNKNOWN
    )
