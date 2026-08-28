"""Explainable Active Fire Situation assessment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .models import DistanceTrend, FireCluster, MetricTrend, ProviderStatus

MAX_PRODUCT_AGE = timedelta(minutes=60)


class SituationLevel(StrEnum):
    """Integration-calculated active-fire situation level."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SituationAssessment:
    """Bounded and automation-friendly situation result."""

    level: SituationLevel
    score: int
    reasons: tuple[str, ...]
    active_incidents: int
    nearest_distance_km: float | None
    highest_frp_mw: float | None
    approaching_incidents: int
    increasing_intensity_incidents: int
    increasing_activity_incidents: int
    assessed_at: datetime


def assess_situation(
    clusters: list[FireCluster],
    *,
    provider_status: ProviderStatus,
    product_time: datetime,
    now: datetime,
) -> SituationAssessment:
    """Assess current detected activity without claiming an emergency level."""
    now = now.astimezone(UTC)
    product_time = product_time.astimezone(UTC)
    if (
        provider_status is not ProviderStatus.AVAILABLE
        or now - product_time > MAX_PRODUCT_AGE
    ):
        return SituationAssessment(
            level=SituationLevel.UNKNOWN,
            score=0,
            reasons=("current_satellite_data_unavailable",),
            active_incidents=len(clusters),
            nearest_distance_km=_nearest_distance(clusters),
            highest_frp_mw=_highest_frp(clusters),
            approaching_incidents=_count_distance_trend(
                clusters, DistanceTrend.APPROACHING
            ),
            increasing_intensity_incidents=_count_metric_trend(
                clusters, "frp_trend", MetricTrend.INCREASING
            ),
            increasing_activity_incidents=_count_metric_trend(
                clusters, "activity_trend", MetricTrend.INCREASING
            ),
            assessed_at=now,
        )

    if not clusters:
        return SituationAssessment(
            level=SituationLevel.NORMAL,
            score=0,
            reasons=("no_current_detections",),
            active_incidents=0,
            nearest_distance_km=None,
            highest_frp_mw=None,
            approaching_incidents=0,
            increasing_intensity_incidents=0,
            increasing_activity_incidents=0,
            assessed_at=now,
        )

    nearest = min(cluster.distance_km for cluster in clusters)
    highest_frp = max(cluster.frp_mw for cluster in clusters)
    approaching = _count_distance_trend(clusters, DistanceTrend.APPROACHING)
    intensity_up = _count_metric_trend(
        clusters, "frp_trend", MetricTrend.INCREASING
    )
    activity_up = _count_metric_trend(
        clusters, "activity_trend", MetricTrend.INCREASING
    )
    score = 0
    reasons: list[str] = []

    if nearest <= 10:
        score += 5
        reasons.append("detection_within_10_km")
    elif nearest <= 25:
        score += 4
        reasons.append("detection_within_25_km")
    elif nearest <= 50:
        score += 3
        reasons.append("detection_within_50_km")
    elif nearest <= 100:
        score += 2
        reasons.append("detection_within_100_km")
    elif nearest <= 250:
        score += 1
        reasons.append("detection_within_250_km")
    else:
        reasons.append("detection_beyond_250_km")

    if len(clusters) >= 5:
        score += 2
        reasons.append("five_or_more_active_incidents")
    elif len(clusters) >= 2:
        score += 1
        reasons.append("multiple_active_incidents")
    if highest_frp >= 100:
        score += 2
        reasons.append("very_high_observed_frp")
    elif highest_frp >= 30:
        score += 1
        reasons.append("high_observed_frp")
    if approaching:
        score += 2
        reasons.append("detected_activity_approaching_home")
    if intensity_up:
        score += 1
        reasons.append("observed_frp_increasing")
    if activity_up:
        score += 1
        reasons.append("detection_activity_increasing")

    if nearest <= 25 and score >= 7:
        level = SituationLevel.CRITICAL
    elif nearest <= 100 and score >= 5:
        level = SituationLevel.HIGH
    else:
        level = SituationLevel.ELEVATED
    return SituationAssessment(
        level=level,
        score=score,
        reasons=tuple(reasons),
        active_incidents=len(clusters),
        nearest_distance_km=nearest,
        highest_frp_mw=highest_frp,
        approaching_incidents=approaching,
        increasing_intensity_incidents=intensity_up,
        increasing_activity_incidents=activity_up,
        assessed_at=now,
    )


def _nearest_distance(clusters: list[FireCluster]) -> float | None:
    return min((cluster.distance_km for cluster in clusters), default=None)


def _highest_frp(clusters: list[FireCluster]) -> float | None:
    return max((cluster.frp_mw for cluster in clusters), default=None)


def _count_distance_trend(
    clusters: list[FireCluster], trend: DistanceTrend
) -> int:
    return sum(cluster.distance_trend is trend for cluster in clusters)


def _count_metric_trend(
    clusters: list[FireCluster], field: str, trend: MetricTrend
) -> int:
    return sum(getattr(cluster, field, None) is trend for cluster in clusters)
