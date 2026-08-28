"""Explainable spatial and temporal correlation of provider detections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math

from .clustering import haversine_km
from .models import FireDetection

DEFAULT_CORRELATION_DISTANCE_KM = 5.0
DEFAULT_CORRELATION_WINDOW = timedelta(hours=6)
MAX_CORRELATION_DISTANCE_KM = 25.0
MAX_CORRELATION_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class DetectionMatch:
    """One secondary detection that corroborates a primary detection."""

    detection: FireDetection
    distance_km: float
    time_difference: timedelta


@dataclass(frozen=True, slots=True)
class CorrelatedDetection:
    """A primary detection with zero or more independent provider matches."""

    primary: FireDetection
    matches: tuple[DetectionMatch, ...]

    @property
    def providers(self) -> tuple[str, ...]:
        """Return unique providers in stable display order."""
        return tuple(
            dict.fromkeys(
                (self.primary.provider, *(match.detection.provider for match in self.matches))
            )
        )

    @property
    def is_multi_source(self) -> bool:
        """Return whether an independent provider corroborated the detection."""
        return len(self.providers) > 1


def correlate_detections(
    primary: tuple[FireDetection, ...],
    secondary: tuple[FireDetection, ...],
    *,
    max_distance_km: float = DEFAULT_CORRELATION_DISTANCE_KM,
    max_time_difference: timedelta = DEFAULT_CORRELATION_WINDOW,
) -> tuple[CorrelatedDetection, ...]:
    """Match detections without merging or discarding source observations.

    Every primary detection is retained. Secondary detections qualify only when
    they come from an independent provider and satisfy both explicit gates.
    Matches are ordered nearest first and then by time difference so the result
    remains deterministic and explainable.
    """
    _validate_thresholds(max_distance_km, max_time_difference)
    correlated: list[CorrelatedDetection] = []
    for detection in primary:
        _validate_timestamp(detection)
        matches: list[DetectionMatch] = []
        for candidate in secondary:
            _validate_timestamp(candidate)
            if candidate.provider == detection.provider:
                continue
            time_difference = abs(candidate.timestamp - detection.timestamp)
            if time_difference > max_time_difference:
                continue
            distance_km = haversine_km(
                detection.latitude,
                detection.longitude,
                candidate.latitude,
                candidate.longitude,
            )
            if distance_km <= max_distance_km:
                matches.append(
                    DetectionMatch(
                        detection=candidate,
                        distance_km=distance_km,
                        time_difference=time_difference,
                    )
                )
        matches.sort(
            key=lambda match: (
                match.distance_km,
                match.time_difference,
                match.detection.provider,
                match.detection.source_detection_id or "",
            )
        )
        correlated.append(CorrelatedDetection(detection, tuple(matches)))
    return tuple(correlated)


def _validate_thresholds(distance_km: float, window: timedelta) -> None:
    if (
        not math.isfinite(distance_km)
        or distance_km <= 0
        or distance_km > MAX_CORRELATION_DISTANCE_KM
    ):
        raise ValueError("Correlation distance is outside the safety bounds")
    if window <= timedelta(0) or window > MAX_CORRELATION_WINDOW:
        raise ValueError("Correlation time window is outside the safety bounds")


def _validate_timestamp(detection: FireDetection) -> None:
    if detection.timestamp.tzinfo is None:
        raise ValueError("Detection timestamp must include a timezone")
