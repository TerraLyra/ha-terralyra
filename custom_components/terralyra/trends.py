"""Noise-resistant trend analysis for tracked fire incidents."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Any

from .models import DistanceTrend, FireCluster, MetricTrend

TREND_WINDOW = timedelta(minutes=90)
MIN_TREND_SAMPLES = 3
MIN_TREND_SPAN = timedelta(minutes=20)
MAX_STORED_SAMPLES = 37


def add_observation_and_update_trends(
    incident: dict[str, Any], cluster: FireCluster
) -> None:
    """Append one unique observation and update bounded incident trends."""
    samples = _valid_samples(incident.get("samples"))
    timestamp = cluster.acquired.astimezone(UTC)
    if not samples or _parse_dt(samples[-1]["timestamp"]) < timestamp:
        samples.append(
            {
                "timestamp": timestamp.isoformat(),
                "frp_mw": cluster.frp_mw,
                "pixel_count": cluster.pixel_count,
                "distance_km": cluster.distance_km,
            }
        )
    incident["samples"] = samples[-MAX_STORED_SAMPLES:]

    window_start = timestamp - TREND_WINDOW
    window = [
        sample
        for sample in incident["samples"]
        if _parse_dt(sample["timestamp"]) >= window_start
    ]
    incident["trend_sample_count"] = len(window)
    incident["trend_window_minutes"] = _span_minutes(window)
    if len(window) < MIN_TREND_SAMPLES or _span(window) < MIN_TREND_SPAN:
        incident["frp_trend"] = MetricTrend.UNKNOWN.value
        incident["activity_trend"] = MetricTrend.UNKNOWN.value
        incident["distance_trend"] = DistanceTrend.UNKNOWN.value
        return

    frp_values = [float(sample["frp_mw"]) for sample in window]
    pixel_values = [float(sample["pixel_count"]) for sample in window]
    distance_values = [float(sample["distance_km"]) for sample in window]
    frp_tolerance = max(2.0, fmean(frp_values) * 0.15)
    activity_tolerance = max(1.0, fmean(pixel_values) * 0.20)

    incident["frp_trend"] = _metric_trend(
        _regression_change(window, frp_values),
        frp_tolerance,
        str(incident.get("frp_trend", MetricTrend.UNKNOWN.value)),
    ).value
    incident["activity_trend"] = _metric_trend(
        _regression_change(window, pixel_values),
        activity_tolerance,
        str(incident.get("activity_trend", MetricTrend.UNKNOWN.value)),
    ).value
    incident["distance_trend"] = _distance_trend(
        _regression_change(window, distance_values),
        1.0,
        str(incident.get("distance_trend", DistanceTrend.UNKNOWN.value)),
    ).value


def ensure_trend_state(incident: dict[str, Any]) -> None:
    """Migrate a legacy incident to a bounded one-sample trend history."""
    incident.setdefault("frp_trend", MetricTrend.UNKNOWN.value)
    incident.setdefault("activity_trend", MetricTrend.UNKNOWN.value)
    incident.setdefault("distance_trend", DistanceTrend.UNKNOWN.value)
    samples = _valid_samples(incident.get("samples"))
    if (
        not samples
        and incident.get("last_seen")
        and incident.get("distance_km") is not None
    ):
        samples = [
            {
                "timestamp": str(incident["last_seen"]),
                "frp_mw": float(incident.get("frp_mw", 0)),
                "pixel_count": int(incident.get("pixel_count", 0)),
                "distance_km": float(incident["distance_km"]),
            }
        ]
    incident["samples"] = samples[-MAX_STORED_SAMPLES:]
    incident.setdefault("trend_sample_count", len(samples))
    incident.setdefault("trend_window_minutes", _span_minutes(samples))


def _metric_trend(change: float, tolerance: float, previous: str) -> MetricTrend:
    if change > tolerance:
        return MetricTrend.INCREASING
    if change < -tolerance:
        return MetricTrend.DECREASING
    if previous == MetricTrend.INCREASING.value and change > tolerance * 0.5:
        return MetricTrend.INCREASING
    if previous == MetricTrend.DECREASING.value and change < -tolerance * 0.5:
        return MetricTrend.DECREASING
    return MetricTrend.STABLE


def _distance_trend(
    change: float, tolerance: float, previous: str
) -> DistanceTrend:
    if change < -tolerance:
        return DistanceTrend.APPROACHING
    if change > tolerance:
        return DistanceTrend.RECEDING
    if previous == DistanceTrend.APPROACHING.value and change < -tolerance * 0.5:
        return DistanceTrend.APPROACHING
    if previous == DistanceTrend.RECEDING.value and change > tolerance * 0.5:
        return DistanceTrend.RECEDING
    return DistanceTrend.STABLE


def _regression_change(samples: list[dict[str, Any]], values: list[float]) -> float:
    start = _parse_dt(samples[0]["timestamp"])
    times = [
        (_parse_dt(sample["timestamp"]) - start).total_seconds() / 60
        for sample in samples
    ]
    mean_time = fmean(times)
    mean_value = fmean(values)
    denominator = sum((value - mean_time) ** 2 for value in times)
    if denominator <= 0:
        return 0.0
    slope = sum(
        (time - mean_time) * (value - mean_value)
        for time, value in zip(times, values, strict=True)
    ) / denominator
    return slope * (times[-1] - times[0])


def _valid_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for sample in value:
        if not isinstance(sample, dict):
            continue
        try:
            parsed = {
                "timestamp": _parse_dt(sample["timestamp"]).isoformat(),
                "frp_mw": float(sample["frp_mw"]),
                "pixel_count": int(sample["pixel_count"]),
                "distance_km": float(sample["distance_km"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        result.append(parsed)
    return sorted(result, key=lambda sample: sample["timestamp"])


def _span(samples: list[dict[str, Any]]) -> timedelta:
    if len(samples) < 2:
        return timedelta()
    return _parse_dt(samples[-1]["timestamp"]) - _parse_dt(samples[0]["timestamp"])


def _span_minutes(samples: list[dict[str, Any]]) -> float:
    return max(0.0, _span(samples).total_seconds() / 60)


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
