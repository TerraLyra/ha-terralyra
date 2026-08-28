"""Tests for bounded active-fire activity aggregation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.terralyra.activity import (
    MAX_ACTIVITY_RECORDS,
    summarize_activity,
    update_activity_history,
)

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _add(
    history: list[dict], minutes: int, detections: int, frp: float, new: int = 0
) -> list[dict]:
    return update_activity_history(
        history,
        timestamp=BASE + timedelta(minutes=minutes),
        detections=detections,
        total_frp_mw=frp,
        new_incidents=new,
    )


def test_fixed_window_activity_summary() -> None:
    history: list[dict] = []
    history = _add(history, 0, 2, 10, 1)
    history = _add(history, 120, 3, 16, 0)
    history = _add(history, 330, 4, 12, 1)
    history = _add(history, 350, 5, 20, 0)

    summary = summarize_activity(history, now=BASE + timedelta(hours=6))

    assert summary.detections_1h == 9
    assert summary.detections_3h == 9
    assert summary.detections_6h == 14
    assert summary.frp_change_1h == 8
    assert summary.frp_change_3h == 8
    assert summary.new_incidents_24h == 2
    assert summary.samples_24h == 4


def test_duplicate_product_replaces_instead_of_double_counting() -> None:
    history = _add([], 0, 2, 10, 1)
    history = _add(history, 0, 3, 12, 0)

    summary = summarize_activity(history, now=BASE)

    assert len(history) == 1
    assert summary.detections_1h == 3
    assert summary.new_incidents_24h == 1


def test_history_is_time_and_size_bounded() -> None:
    history: list[dict] = []
    for index in range(MAX_ACTIVITY_RECORDS + 20):
        history = _add(history, index * 10, 1, 1)

    assert len(history) <= MAX_ACTIVITY_RECORDS
    newest = datetime.fromisoformat(history[-1]["timestamp"])
    oldest = datetime.fromisoformat(history[0]["timestamp"])
    assert newest - oldest <= timedelta(hours=24)


def test_frp_change_requires_two_samples() -> None:
    summary = summarize_activity(_add([], 0, 1, 5), now=BASE)

    assert summary.frp_change_1h is None
    assert summary.frp_change_3h is None
