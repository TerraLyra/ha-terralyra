"""Tests for explainable, non-authoritative fire evidence strength."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.terralyra.evidence import assess_fire_evidence
from custom_components.terralyra.models import ConfirmationLevel, FireCluster

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _cluster(**changes) -> FireCluster:
    values = {
        "latitude": 46.0,
        "longitude": 19.0,
        "distance_km": 20.0,
        "confidence": 0.9,
        "frp_mw": 15.0,
        "acquired": NOW,
        "pixel_count": 2,
    }
    values.update(changes)
    return FireCluster(**values)


def test_no_active_fire_has_no_evidence_score() -> None:
    result = assess_fire_evidence(None, product_time=NOW, now=NOW)
    assert result.level == "no_active_fire"
    assert result.score == 0


def test_multi_source_recent_detection_is_strong() -> None:
    result = assess_fire_evidence(
        _cluster(confirmation_level=ConfirmationLevel.MULTI_SOURCE),
        product_time=NOW - timedelta(minutes=10),
        now=NOW,
        secondary_available=True,
    )
    assert result.level == "strong"
    assert "independent_satellite_corroboration" in result.factors
    assert not result.cautions


def test_weak_single_pixel_detection_is_limited_and_explained() -> None:
    result = assess_fire_evidence(
        _cluster(confidence=0.3, frp_mw=1.0, pixel_count=1),
        product_time=NOW - timedelta(minutes=15),
        now=NOW,
        secondary_available=True,
    )
    assert result.level == "limited"
    assert result.cautions == (
        "not_seen_by_independent_satellite",
        "low_primary_detection_confidence",
        "low_fire_radiative_power",
        "single_primary_fire_pixel",
    )


def test_stale_product_reduces_evidence_strength() -> None:
    result = assess_fire_evidence(
        _cluster(),
        product_time=NOW - timedelta(hours=2),
        now=NOW,
    )
    assert result.level == "limited"
    assert "stale_satellite_observation" in result.cautions
