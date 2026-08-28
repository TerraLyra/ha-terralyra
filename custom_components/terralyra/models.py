"""Provider-neutral active-fire data models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .const import (
    ATTR_ACQUIRED,
    ATTR_ACTIVITY_TREND,
    ATTR_CONFIDENCE,
    ATTR_DISTANCE_KM,
    ATTR_DISTANCE_TREND,
    ATTR_DURATION_MINUTES,
    ATTR_FIRST_SEEN,
    ATTR_FRP_MW,
    ATTR_FRP_TREND,
    ATTR_LATITUDE,
    ATTR_LOCATION_DESCRIPTION,
    ATTR_LONGITUDE,
    ATTR_NEAREST_SETTLEMENT,
    ATTR_DETECTIONS_TOTAL,
    ATTR_INCIDENT_ID,
    ATTR_LAST_SEEN,
    ATTR_LIFECYCLE,
    ATTR_MAXIMUM_CONFIDENCE,
    ATTR_MAXIMUM_FRP_MW,
    ATTR_MAXIMUM_PIXEL_COUNT,
    ATTR_MINIMUM_DISTANCE_KM,
    ATTR_PEAK_FRP_MW,
    ATTR_PIXEL_COUNT,
    ATTR_PLACE_ATTRIBUTION,
    ATTR_PLACE_NAME,
    ATTR_TRACK_ID,
    ATTR_TREND_SAMPLES,
    ATTR_TREND_WINDOW_MINUTES,
)


class ProviderStatus(StrEnum):
    """Availability state reported by an active-fire provider."""

    INITIALIZING = "initializing"
    AVAILABLE = "available"
    DELAYED = "delayed"
    NO_PRODUCT = "no_product"
    OUTAGE = "outage"
    AUTH_ERROR = "auth_error"


class FireLifecycle(StrEnum):
    """Lifecycle state of one tracked fire incident."""

    NEW = "new"
    CONTINUING = "continuing"
    INACTIVE = "inactive"
    ENDED = "ended"


class MetricTrend(StrEnum):
    """Trend direction for FRP and detection activity."""

    INCREASING = "increasing"
    STABLE = "stable"
    DECREASING = "decreasing"
    UNKNOWN = "unknown"


class DistanceTrend(StrEnum):
    """Trend of detected activity relative to Home."""

    APPROACHING = "approaching"
    STABLE = "stable"
    RECEDING = "receding"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FireDetection:
    """One provider-normalized satellite fire detection."""

    provider: str
    satellite: str
    product: str
    timestamp: datetime
    latitude: float
    longitude: float
    frp_mw: float | None = None
    frp_uncertainty_mw: float | None = None
    confidence: float | None = None
    classification: str | int | None = None
    quality: str | int | None = None
    fire_temperature_k: float | None = None
    fire_area_km2: float | None = None
    temporal_filtered: bool | None = None
    source_resolution_km: float | None = None
    source_detection_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """One complete provider product normalized for common processing."""

    provider: str
    satellite: str
    product: str
    product_timestamp: datetime
    received_timestamp: datetime
    status: ProviderStatus
    source_url: str
    filename: str
    detections: tuple[FireDetection, ...]


@dataclass(slots=True)
class FireCluster:
    """A spatial group of fire detections from one provider snapshot."""

    latitude: float
    longitude: float
    distance_km: float
    confidence: float
    frp_mw: float
    acquired: datetime
    pixel_count: int
    track_id: str | None = None
    peak_frp_mw: float | None = None
    place_name: str | None = None
    nearest_settlement: str | None = None
    location_description: str | None = None
    place_attribution: str | None = None
    lifecycle: FireLifecycle | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    minimum_distance_km: float | None = None
    maximum_frp_mw: float | None = None
    maximum_pixel_count: int | None = None
    detections_total: int | None = None
    maximum_confidence: float | None = None
    frp_trend: MetricTrend | None = None
    activity_trend: MetricTrend | None = None
    distance_trend: DistanceTrend | None = None
    trend_samples: int | None = None
    trend_window_minutes: float | None = None

    def attrs(self) -> dict[str, Any]:
        """Return bounded Home Assistant state attributes."""
        attrs = {
            ATTR_LATITUDE: round(self.latitude, 6),
            ATTR_LONGITUDE: round(self.longitude, 6),
            ATTR_DISTANCE_KM: round(self.distance_km, 2),
            ATTR_CONFIDENCE: round(self.confidence, 3),
            ATTR_FRP_MW: round(self.frp_mw, 2),
            ATTR_ACQUIRED: self.acquired.isoformat(),
            ATTR_PIXEL_COUNT: self.pixel_count,
        }
        if self.track_id is not None:
            attrs[ATTR_TRACK_ID] = self.track_id
            attrs[ATTR_INCIDENT_ID] = self.track_id
        if self.peak_frp_mw is not None:
            attrs[ATTR_PEAK_FRP_MW] = round(self.peak_frp_mw, 2)
        if self.place_name is not None:
            attrs[ATTR_PLACE_NAME] = self.place_name
        if self.nearest_settlement is not None:
            attrs[ATTR_NEAREST_SETTLEMENT] = self.nearest_settlement
        if self.location_description is not None:
            attrs[ATTR_LOCATION_DESCRIPTION] = self.location_description
        if self.place_attribution is not None:
            attrs[ATTR_PLACE_ATTRIBUTION] = self.place_attribution
        if self.lifecycle is not None:
            attrs[ATTR_LIFECYCLE] = self.lifecycle.value
        if self.first_seen is not None:
            attrs[ATTR_FIRST_SEEN] = self.first_seen.isoformat()
        if self.last_seen is not None:
            attrs[ATTR_LAST_SEEN] = self.last_seen.isoformat()
        if self.first_seen is not None and self.last_seen is not None:
            attrs[ATTR_DURATION_MINUTES] = round(
                max(0.0, (self.last_seen - self.first_seen).total_seconds() / 60), 1
            )
        if self.minimum_distance_km is not None:
            attrs[ATTR_MINIMUM_DISTANCE_KM] = round(self.minimum_distance_km, 2)
        if self.maximum_frp_mw is not None:
            attrs[ATTR_MAXIMUM_FRP_MW] = round(self.maximum_frp_mw, 2)
        if self.maximum_pixel_count is not None:
            attrs[ATTR_MAXIMUM_PIXEL_COUNT] = self.maximum_pixel_count
        if self.detections_total is not None:
            attrs[ATTR_DETECTIONS_TOTAL] = self.detections_total
        if self.maximum_confidence is not None:
            attrs[ATTR_MAXIMUM_CONFIDENCE] = round(self.maximum_confidence, 3)
        if self.frp_trend is not None:
            attrs[ATTR_FRP_TREND] = self.frp_trend.value
        if self.activity_trend is not None:
            attrs[ATTR_ACTIVITY_TREND] = self.activity_trend.value
        if self.distance_trend is not None:
            attrs[ATTR_DISTANCE_TREND] = self.distance_trend.value
        if self.trend_samples is not None:
            attrs[ATTR_TREND_SAMPLES] = self.trend_samples
        if self.trend_window_minutes is not None:
            attrs[ATTR_TREND_WINDOW_MINUTES] = round(self.trend_window_minutes, 1)
        return attrs
