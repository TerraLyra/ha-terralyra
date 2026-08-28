"""Constants for the TerraLyra integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "terralyra"
NAME = "TerraLyra"
MANUFACTURER = "TerraLyra open-source project"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PRODUCTS = "products"
CONF_RADIUS_KM = "radius_km"
CONF_MIN_CONFIDENCE = "min_confidence"
CONF_MIN_FRP_MW = "min_frp_mw"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_DEDUP_RADIUS_KM = "dedup_radius_km"
CONF_DEDUP_HOURS = "dedup_hours"
CONF_FIRE_HISTORY_HOURS = "fire_history_hours"
CONF_RESOLVE_PLACE_NAMES = "resolve_place_names"
CONF_FIRE_RISK_DAY = "fire_risk_forecast_day"
CONF_FIRE_RISK_RADIUS_KM = "fire_risk_radius_km"
CONF_ENABLE_LAND_SURFACE_TEMPERATURE = "enable_land_surface_temperature"
CONF_ENABLE_FIRMS = "enable_firms"
CONF_FIRMS_MAP_KEY = "firms_map_key"

PRODUCT_ACTIVE_FIRE = "active_fire"
PRODUCT_FIRE_RISK = "fire_risk"
PRODUCT_LAND_SURFACE_TEMPERATURE = "land_surface_temperature"

SUPPORTED_PRODUCTS = (
    PRODUCT_ACTIVE_FIRE,
    PRODUCT_FIRE_RISK,
    PRODUCT_LAND_SURFACE_TEMPERATURE,
)
PLANNED_PRODUCTS: tuple[str, ...] = ()

DEFAULT_PRODUCTS = [PRODUCT_ACTIVE_FIRE]
DEFAULT_RADIUS_KM = 25.0
DEFAULT_MIN_CONFIDENCE = 0.0
DEFAULT_MIN_FRP_MW = 0.0
DEFAULT_SCAN_INTERVAL_MINUTES = 5
DEFAULT_DEDUP_RADIUS_KM = 3.0
DEFAULT_DEDUP_HOURS = 6
DEFAULT_FIRE_HISTORY_HOURS = 6
DEFAULT_RESOLVE_PLACE_NAMES = True
DEFAULT_FIRE_RISK_DAY = 0
DEFAULT_FIRE_RISK_RADIUS_KM = 100.0
DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE = False
DEFAULT_ENABLE_FIRMS = False
MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 500.0
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES)

PLATFORMS = ["sensor", "event", "number", "select", "camera", "calendar", "geo_location"]

EVENT_NEW_FIRE = "new_fire"
BUS_EVENT_NEW_FIRE = f"{DOMAIN}_new_fire"
EVENT_FIRE_RISK_INCREASE = "fire_risk_increase"
BUS_EVENT_FIRE_RISK_INCREASE = f"{DOMAIN}_fire_risk_increase"
EVENT_FIRE_INTENSITY_INCREASING = "fire_intensity_increasing"
EVENT_FIRE_ACTIVITY_INCREASING = "fire_activity_increasing"
EVENT_FIRE_ACTIVITY_DECREASING = "fire_activity_decreasing"
EVENT_FIRE_APPROACHING = "fire_approaching"
BUS_EVENT_FIRE_TREND = f"{DOMAIN}_fire_trend"

ATTR_DISTANCE_KM = "distance_km"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_FRP_MW = "frp_mw"
ATTR_CONFIDENCE = "confidence"
ATTR_ACQUIRED = "acquired"
ATTR_PIXEL_COUNT = "pixel_count"
ATTR_TRACK_ID = "track_id"
ATTR_SOURCE_URL = "source_url"
ATTR_PRODUCT_TIME = "product_time"
ATTR_PEAK_FRP_MW = "peak_frp_mw"
ATTR_PLACE_NAME = "place_name"
ATTR_NEAREST_SETTLEMENT = "nearest_settlement"
ATTR_LOCATION_DESCRIPTION = "location_description"
ATTR_PLACE_ATTRIBUTION = "place_attribution"
ATTR_NOTIFICATION_TITLE = "notification_title"
ATTR_NOTIFICATION_MESSAGE = "notification_message"
ATTR_INCIDENT_ID = "incident_id"
ATTR_LIFECYCLE = "lifecycle"
ATTR_FIRST_SEEN = "first_seen"
ATTR_LAST_SEEN = "last_seen"
ATTR_DURATION_MINUTES = "duration_minutes"
ATTR_MINIMUM_DISTANCE_KM = "minimum_distance_km"
ATTR_MAXIMUM_FRP_MW = "maximum_frp_mw"
ATTR_MAXIMUM_PIXEL_COUNT = "maximum_pixel_count"
ATTR_DETECTIONS_TOTAL = "detections_total"
ATTR_MAXIMUM_CONFIDENCE = "maximum_confidence"
ATTR_FRP_TREND = "frp_trend"
ATTR_ACTIVITY_TREND = "activity_trend"
ATTR_DISTANCE_TREND = "distance_trend"
ATTR_TREND_SAMPLES = "trend_samples"
ATTR_TREND_WINDOW_MINUTES = "trend_window_minutes"
ATTR_CONFIRMATION_LEVEL = "confirmation_level"
ATTR_PROVIDERS = "providers"
ATTR_CORROBORATING_DETECTIONS = "corroborating_detections"
