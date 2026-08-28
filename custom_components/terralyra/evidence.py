"""Explainable evidence strength for the nearest active-fire incident."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .models import ConfirmationLevel, FireCluster


@dataclass(frozen=True, slots=True)
class FireEvidenceAssessment:
    """A bounded, non-authoritative explanation of satellite evidence."""

    level: str
    score: int
    factors: tuple[str, ...]
    cautions: tuple[str, ...]


def assess_fire_evidence(
    cluster: FireCluster | None,
    *,
    product_time: datetime | None,
    now: datetime | None = None,
    secondary_available: bool = False,
) -> FireEvidenceAssessment:
    """Assess evidence without claiming that a wildfire is confirmed."""
    if cluster is None:
        return FireEvidenceAssessment("no_active_fire", 0, (), ())

    assessed_at = now or datetime.now(UTC)
    score = 0
    factors: list[str] = []
    cautions: list[str] = []

    if cluster.confirmation_level is ConfirmationLevel.MULTI_SOURCE:
        score += 3
        factors.append("independent_satellite_corroboration")
    elif secondary_available:
        cautions.append("not_seen_by_independent_satellite")
    else:
        cautions.append("independent_source_not_available")

    if cluster.confidence >= 0.8:
        score += 1
        factors.append("high_primary_detection_confidence")
    elif cluster.confidence < 0.5:
        cautions.append("low_primary_detection_confidence")

    if cluster.frp_mw >= 10:
        score += 1
        factors.append("substantial_fire_radiative_power")
    elif cluster.frp_mw < 2:
        cautions.append("low_fire_radiative_power")

    if cluster.pixel_count >= 2:
        score += 1
        factors.append("multiple_primary_fire_pixels")
    else:
        cautions.append("single_primary_fire_pixel")

    if product_time is None:
        cautions.append("product_time_unavailable")
    else:
        age = max(timedelta(), assessed_at - product_time)
        if age <= timedelta(minutes=30):
            score += 1
            factors.append("recent_satellite_observation")
        elif age > timedelta(minutes=60):
            score = max(0, score - 2)
            cautions.append("stale_satellite_observation")

    if score >= 4:
        level = "strong"
    elif score >= 2:
        level = "moderate"
    else:
        level = "limited"
    return FireEvidenceAssessment(level, score, tuple(factors), tuple(cautions))
