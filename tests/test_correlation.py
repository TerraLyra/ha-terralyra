"""Tests for explainable multi-provider active-fire correlation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.terralyra.correlation import correlate_detections
from custom_components.terralyra.models import FireDetection

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _detection(
    provider: str,
    *,
    latitude: float = 46.0,
    longitude: float = 19.0,
    timestamp: datetime = NOW,
    detection_id: str = "id",
    source_family: str | None = None,
) -> FireDetection:
    return FireDetection(
        provider=provider,
        satellite="satellite",
        product="product",
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        source_detection_id=detection_id,
        source_family=source_family,
    )


def test_nearby_independent_detection_is_multi_source() -> None:
    primary = _detection("eumetsat_lsa_saf")
    secondary = _detection(
        "nasa_firms",
        latitude=46.01,
        timestamp=NOW - timedelta(hours=2),
    )

    result = correlate_detections((primary,), (secondary,))

    assert len(result) == 1
    assert result[0].is_multi_source
    assert result[0].providers == ("eumetsat_lsa_saf", "nasa_firms")
    assert result[0].matches[0].distance_km == pytest.approx(1.111, rel=0.01)
    assert result[0].matches[0].time_difference == timedelta(hours=2)


def test_distance_and_time_are_independent_hard_gates() -> None:
    primary = _detection("eumetsat_lsa_saf")
    too_far = _detection("nasa_firms", latitude=46.1, detection_id="far")
    too_old = _detection(
        "nasa_firms",
        timestamp=NOW - timedelta(hours=7),
        detection_id="old",
    )

    result = correlate_detections((primary,), (too_far, too_old))

    assert not result[0].is_multi_source
    assert result[0].matches == ()


def test_same_provider_does_not_self_correlate() -> None:
    primary = _detection("nasa_firms", detection_id="one")
    duplicate = _detection("nasa_firms", detection_id="two")

    result = correlate_detections((primary,), (duplicate,))

    assert result[0].providers == ("nasa_firms",)
    assert not result[0].is_multi_source


def test_same_source_family_does_not_create_false_independent_confirmation() -> None:
    primary = _detection(
        "lsa_saf_mtg",
        detection_id="mtg",
        source_family="lsa_saf_frp_pixel",
    )
    iodc = _detection(
        "lsa_saf_msg_iodc",
        detection_id="iodc",
        source_family="lsa_saf_frp_pixel",
    )

    result = correlate_detections((primary,), (iodc,))

    assert result[0].matches == ()
    assert not result[0].is_multi_source


def test_all_primary_detections_are_retained_and_matches_are_stable() -> None:
    primary = (
        _detection("eumetsat_lsa_saf", detection_id="one"),
        _detection("eumetsat_lsa_saf", latitude=47, detection_id="two"),
    )
    farther = _detection("nasa_firms", latitude=46.02, detection_id="farther")
    nearer = _detection("nasa_firms", latitude=46.01, detection_id="nearer")

    result = correlate_detections(primary, (farther, nearer))

    assert tuple(item.primary.source_detection_id for item in result) == ("one", "two")
    assert tuple(
        item.detection.source_detection_id for item in result[0].matches
    ) == ("nearer", "farther")
    assert result[1].matches == ()


@pytest.mark.parametrize(
    ("distance", "window"),
    [
        (0, timedelta(hours=1)),
        (26, timedelta(hours=1)),
        (float("nan"), timedelta(hours=1)),
        (5, timedelta(0)),
        (5, timedelta(hours=25)),
    ],
)
def test_rejects_unsafe_thresholds(distance: float, window: timedelta) -> None:
    with pytest.raises(ValueError):
        correlate_detections(
            (),
            (),
            max_distance_km=distance,
            max_time_difference=window,
        )


def test_rejects_naive_timestamps() -> None:
    naive = _detection("eumetsat_lsa_saf", timestamp=NOW.replace(tzinfo=None))

    with pytest.raises(ValueError):
        correlate_detections((naive,), ())
