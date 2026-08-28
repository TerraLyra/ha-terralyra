"""Bounded provider-neutral active-fire activity history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

HISTORY_WINDOW = timedelta(hours=24)
MAX_ACTIVITY_RECORDS = 180


@dataclass(frozen=True, slots=True)
class ActivitySummary:
    """Small Recorder-friendly aggregates derived from bounded history."""

    detections_1h: int = 0
    detections_3h: int = 0
    detections_6h: int = 0
    frp_change_1h: float | None = None
    frp_change_3h: float | None = None
    new_incidents_24h: int = 0
    samples_24h: int = 0


def update_activity_history(
    history: list[dict[str, Any]],
    *,
    timestamp: datetime,
    detections: int,
    total_frp_mw: float,
    new_incidents: int,
) -> list[dict[str, Any]]:
    """Append or replace one product observation and keep only 24 hours."""
    timestamp = timestamp.astimezone(UTC)
    records = _valid_records(history)
    record = {
        "timestamp": timestamp.isoformat(),
        "detections": max(0, int(detections)),
        "total_frp_mw": max(0.0, float(total_frp_mw)),
        "new_incidents": max(0, int(new_incidents)),
    }
    previous = next(
        (item for item in records if item["timestamp"] == record["timestamp"]),
        None,
    )
    if previous is not None:
        record["new_incidents"] = max(
            record["new_incidents"], previous["new_incidents"]
        )
    records = [item for item in records if item["timestamp"] != record["timestamp"]]
    records.append(record)
    cutoff = timestamp - HISTORY_WINDOW
    return [
        item for item in sorted(records, key=lambda item: item["timestamp"])
        if _parse_dt(item["timestamp"]) >= cutoff
    ][-MAX_ACTIVITY_RECORDS:]


def summarize_activity(
    history: list[dict[str, Any]], *, now: datetime
) -> ActivitySummary:
    """Calculate fixed-window counters without exposing raw history to HA."""
    records = _valid_records(history)
    now = now.astimezone(UTC)

    def window(hours: int) -> list[dict[str, Any]]:
        cutoff = now - timedelta(hours=hours)
        return [item for item in records if _parse_dt(item["timestamp"]) >= cutoff]

    one_hour = window(1)
    three_hours = window(3)
    six_hours = window(6)
    day = window(24)
    return ActivitySummary(
        detections_1h=sum(item["detections"] for item in one_hour),
        detections_3h=sum(item["detections"] for item in three_hours),
        detections_6h=sum(item["detections"] for item in six_hours),
        frp_change_1h=_frp_change(one_hour),
        frp_change_3h=_frp_change(three_hours),
        new_incidents_24h=sum(item["new_incidents"] for item in day),
        samples_24h=len(day),
    )


def _frp_change(records: list[dict[str, Any]]) -> float | None:
    if len(records) < 2:
        return None
    return float(records[-1]["total_frp_mw"]) - float(records[0]["total_frp_mw"])


def _valid_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            result.append(
                {
                    "timestamp": _parse_dt(item["timestamp"]).isoformat(),
                    "detections": max(0, int(item["detections"])),
                    "total_frp_mw": max(0.0, float(item["total_frp_mw"])),
                    "new_incidents": max(0, int(item["new_incidents"])),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(result, key=lambda item: item["timestamp"])


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
