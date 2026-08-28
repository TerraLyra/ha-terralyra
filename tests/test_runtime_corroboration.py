"""Tests for runtime multi-source fire corroboration metadata."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.terralyra.correlation import correlate_detections
from custom_components.terralyra.coordinator import (
    _annotate_corroboration,
    _firms_only_clusters,
)
from custom_components.terralyra.models import (
    ConfirmationLevel,
    FireCluster,
    FireDetection,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _detection(provider: str, latitude: float, longitude: float) -> FireDetection:
    return FireDetection(
        provider=provider,
        satellite="test",
        product="test",
        timestamp=NOW,
        latitude=latitude,
        longitude=longitude,
        frp_mw=10,
        confidence=0.8 if provider == "eumetsat_lsa_saf" else None,
        source_detection_id=f"{provider}:{latitude}:{longitude}",
    )


def _cluster() -> FireCluster:
    return FireCluster(
        latitude=47.5,
        longitude=19.0,
        distance_km=10,
        confidence=0.8,
        frp_mw=10,
        acquired=NOW,
        pixel_count=1,
    )


def test_nearby_independent_detection_marks_multi_source() -> None:
    primary = _detection("eumetsat_lsa_saf", 47.5, 19.0)
    secondary = _detection("nasa_firms", 47.51, 19.0)
    cluster = _cluster()

    level, count = _annotate_corroboration(
        [cluster],
        correlate_detections((primary,), (secondary,)),
        provider_enabled=True,
        provider_available=True,
        cluster_radius_km=2,
    )

    assert level is ConfirmationLevel.MULTI_SOURCE
    assert count == 1
    assert cluster.providers == ("eumetsat_lsa_saf", "nasa_firms")
    assert cluster.attrs()["confirmation_level"] == "multi_source"


def test_distant_or_old_detection_stays_single_source() -> None:
    primary = _detection("eumetsat_lsa_saf", 47.5, 19.0)
    secondary = _detection("nasa_firms", 48.0, 19.0)
    secondary = replace(secondary, timestamp=NOW - timedelta(hours=7))
    cluster = _cluster()

    level, count = _annotate_corroboration(
        [cluster],
        correlate_detections((primary,), (secondary,)),
        provider_enabled=True,
        provider_available=True,
        cluster_radius_km=2,
    )

    assert level is ConfirmationLevel.SINGLE_SOURCE
    assert count == 0


def test_secondary_outage_is_not_misreported_as_single_source() -> None:
    cluster = _cluster()

    level, count = _annotate_corroboration(
        [cluster],
        (),
        provider_enabled=True,
        provider_available=False,
        cluster_radius_km=2,
    )

    assert level is ConfirmationLevel.NOT_AVAILABLE
    assert count == 0
    assert cluster.confirmation_level is ConfirmationLevel.NOT_AVAILABLE


def test_firms_only_detection_becomes_supplemental_map_cluster() -> None:
    primary = _detection("eumetsat_lsa_saf", 47.5, 19.0)
    matched = _detection("nasa_firms", 47.51, 19.0)
    firms_only = _detection("nasa_firms", 47.8, 19.2)

    clusters = _firms_only_clusters(
        correlate_detections((primary,), (matched, firms_only)),
        (matched, firms_only),
        home_lat=47.5,
        home_lon=19.0,
        cluster_radius_km=2.0,
    )

    assert len(clusters) == 1
    assert clusters[0].latitude == firms_only.latitude
    assert clusters[0].providers == ("nasa_firms",)
    assert clusters[0].confirmation_level is ConfirmationLevel.SINGLE_SOURCE


def test_all_correlated_firms_detections_are_removed_from_supplemental_map() -> None:
    primary = _detection("eumetsat_lsa_saf", 47.5, 19.0)
    matched = _detection("nasa_firms", 47.51, 19.0)

    assert _firms_only_clusters(
        correlate_detections((primary,), (matched,)),
        (matched,),
        home_lat=47.5,
        home_lon=19.0,
        cluster_radius_km=2.0,
    ) == []
