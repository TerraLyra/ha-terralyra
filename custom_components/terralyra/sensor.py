"""Sensors for TerraLyra."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfLength, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
    CONF_ACTIVE_FIRE_PROVIDER,
    CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_ACTIVE_FIRE_PROVIDER,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
)
from .coverage import assess_location_coverage, summarize_coverage
from .entity import (
    TerraLyraEntity,
    TerraLyraFireRiskEntity,
    TerraLyraLandSurfaceTemperatureEntity,
)
from .evidence import FireEvidenceAssessment, assess_fire_evidence
from .models import ProviderStatus
from .products.fire_risk import WMS_URL
from .products.lst import WMS_URL as LST_WMS_URL


async def async_setup_entry(
    hass: HomeAssistant, entry: TerraLyraConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    entities = [
        NearestFireSensor(entry),
        ActiveFireCountSensor(entry),
        RawPixelCountSensor(entry),
        ProductTimeSensor(entry),
        ProductAgeSensor(entry),
        ProviderStatusSensor(entry),
        ActiveFireProviderSensor(entry),
        ProviderCoverageSensor(entry),
        RecentDetectionsSensor(entry),
        FireActivityFrpChangeSensor(entry),
        NewIncidents24hSensor(entry),
        ActiveFireSituationSensor(entry),
        FireSourceConfirmationSensor(entry),
        NearestFireEvidenceSensor(entry),
        FireRiskTodaySensor(entry),
        FireRiskAreaMaximumSensor(entry),
        FireRiskUpdateSensor(entry),
    ]
    if entry.options.get(
        CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
        DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    ):
        entities.append(LandSurfaceTemperatureSensor(entry))
    async_add_entities(entities)


class LandSurfaceTemperatureSensor(
    TerraLyraLandSurfaceTemperatureEntity, SensorEntity
):
    """Latest satellite-observed radiative land-surface temperature at Home."""

    _attr_translation_key = "land_surface_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-lines"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_land_surface_temperature"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or data.temperature_celsius is None:
            return None
        return round(data.temperature_celsius, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {
                "product": "MTLST",
                "attribution": "EUMETSAT / LSA SAF, CC BY 4.0",
            }
        return {
            "observed_at": data.observed_at.isoformat(),
            "sample_latitude": round(data.latitude, 6),
            "sample_longitude": round(data.longitude, 6),
            "uncertainty_k": data.uncertainty_kelvin,
            "quality": data.quality,
            "product": "MTLST",
            "source_url": LST_WMS_URL,
            "attribution": "EUMETSAT / LSA SAF, CC BY 4.0",
            "measurement_note": "radiative_land_skin_temperature",
        }


class NearestFireSensor(TerraLyraEntity, SensorEntity):
    _attr_translation_key = "nearest_fire"
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:fire-alert"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_nearest_fire"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data or not data.active_clusters:
            return None
        return round(data.active_clusters[0].distance_km, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if not data or not data.active_clusters:
            return None
        return data.active_clusters[0].attrs() | {"source_url": data.source_url}


class ActiveFireCountSensor(TerraLyraEntity, SensorEntity):
    _attr_translation_key = "active_fire_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:fire"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_active_fire_count"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.active_clusters) if self.coordinator.data else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {
                "tracked_incidents": 0,
                "inactive_incidents": 0,
                "map_markers": 0,
                "map_source": "terralyra",
            }
        inactive = sum(
            cluster.lifecycle is not None and cluster.lifecycle.value == "inactive"
            for cluster in data.tracked_fires
        )
        return {
            "tracked_incidents": len(data.tracked_fires),
            "inactive_incidents": inactive,
            "map_markers": len(data.tracked_fires),
            "map_source": "terralyra",
        }


class RawPixelCountSensor(TerraLyraEntity, SensorEntity):
    _attr_translation_key = "raw_pixel_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:dots-hexagon"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_raw_pixel_count"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.raw_pixels_in_radius if self.coordinator.data else 0


class ProductTimeSensor(TerraLyraEntity, SensorEntity):
    _attr_translation_key = "product_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:satellite-variant"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_product_time"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.product_time if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return {"filename": self.coordinator.data.filename, "source_url": self.coordinator.data.source_url}


class ProductAgeSensor(TerraLyraEntity, SensorEntity):
    _attr_translation_key = "product_age"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:timer-sand"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_product_age"

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return max(0, (datetime.now(UTC) - self.coordinator.data.product_time).total_seconds() / 60)


class ProviderStatusSensor(TerraLyraEntity, SensorEntity):
    """Expose provider health even when the latest refresh failed."""

    _attr_translation_key = "provider_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in ProviderStatus]
    _attr_icon = "mdi:satellite-uplink"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_provider_status"

    @property
    def available(self) -> bool:
        """The health entity remains useful during provider failures."""
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.provider_status.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "provider": self.coordinator.provider_name,
            "satellite": self.coordinator.satellite,
            "product": self.coordinator.provider_product,
            "product_timestamp": (
                self.coordinator.product_timestamp.isoformat()
                if self.coordinator.product_timestamp
                else None
            ),
            "received_timestamp": (
                self.coordinator.received_timestamp.isoformat()
                if self.coordinator.received_timestamp
                else None
            ),
        }


class ActiveFireProviderSensor(TerraLyraEntity, SensorEntity):
    """Expose the configured primary provider independently of observations."""

    _attr_translation_key = "active_fire_provider"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        ACTIVE_FIRE_PROVIDER_LSA_SAF,
        ACTIVE_FIRE_PROVIDER_GOES,
        "unknown",
    ]
    _attr_icon = "mdi:satellite-variant"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_active_fire_provider"

    @property
    def native_value(self) -> str:
        provider = self.entry.data.get(
            CONF_ACTIVE_FIRE_PROVIDER, DEFAULT_ACTIVE_FIRE_PROVIDER
        )
        return provider if provider in self._attr_options else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        center = self.coordinator.monitoring_center
        return {
            "observed_provider": self.coordinator.provider_name,
            "corroborating_provider": (
                self.coordinator.corroboration_provider_name
            ),
            "satellite": self.coordinator.satellite,
            "product": self.coordinator.provider_product,
            "monitoring_center": center.name,
            "monitoring_latitude": round(center.latitude, 6),
            "monitoring_longitude": round(center.longitude, 6),
            "custom_monitoring_center": center.custom,
        }


class ProviderCoverageSensor(TerraLyraEntity, SensorEntity):
    """Expose provider health separately from geographic coverage."""

    _attr_translation_key = "provider_coverage"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["covered", "partial", "not_covered", "unknown"]
    _attr_icon = "mdi:map-marker-check-outline"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_provider_coverage"

    def _coverage(self):
        provider = str(
            self.entry.data.get(
                CONF_ACTIVE_FIRE_PROVIDER, DEFAULT_ACTIVE_FIRE_PROVIDER
            )
        )
        return provider, tuple(
            assess_location_coverage(provider, location)
            for location in self.coordinator.monitored_locations
            if location.enabled
        )

    @property
    def native_value(self) -> str:
        _, results = self._coverage()
        return summarize_coverage(results)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        provider, results = self._coverage()
        return {
            "configured_primary_provider": provider,
            "provider_status": self.coordinator.provider_status.value,
            "covered_locations": sum(result.covered for result in results),
            "uncovered_locations": sum(not result.covered for result in results),
            "locations": [result.attrs() for result in results],
            "assessment": "conservative_pre_download_geographic_gate",
        }


class RecentDetectionsSensor(TerraLyraEntity, SensorEntity):
    """Count provider detections in fixed recent windows."""

    _attr_translation_key = "recent_detections"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_recent_detections"

    @property
    def native_value(self) -> int:
        data = self.coordinator.data
        return data.activity.detections_1h if data else 0

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        data = self.coordinator.data
        if data is None:
            return {"detections_last_3h": 0, "detections_last_6h": 0}
        return {
            "detections_last_3h": data.activity.detections_3h,
            "detections_last_6h": data.activity.detections_6h,
            "history_samples_24h": data.activity.samples_24h,
        }


class FireActivityFrpChangeSensor(TerraLyraEntity, SensorEntity):
    """Change in total clustered FRP across recent product observations."""

    _attr_translation_key = "fire_activity_frp_change"
    _attr_native_unit_of_measurement = UnitOfPower.MEGA_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:trending-up"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_activity_frp_change"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return data.activity.frp_change_1h if data else None

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        data = self.coordinator.data
        return {
            "frp_change_last_3h": data.activity.frp_change_3h if data else None
        }


class NewIncidents24hSensor(TerraLyraEntity, SensorEntity):
    """Count newly created incidents during the last 24 hours."""

    _attr_translation_key = "new_incidents_24h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:fire-plus"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_new_incidents_24h"

    @property
    def native_value(self) -> int:
        data = self.coordinator.data
        return data.activity.new_incidents_24h if data else 0


class ActiveFireSituationSensor(TerraLyraEntity, SensorEntity):
    """Explainable integration-calculated current active-fire situation."""

    _attr_translation_key = "active_fire_situation"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["normal", "elevated", "high", "critical", "unknown"]
    _attr_icon = "mdi:fire-circle"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_active_fire_situation"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return data.situation.level.value if data else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {"score": 0, "reasons": ["data_not_loaded"]}
        situation = data.situation
        return {
            "score": situation.score,
            "reasons": list(situation.reasons),
            "active_incidents": situation.active_incidents,
            "nearest_distance_km": situation.nearest_distance_km,
            "highest_frp_mw": situation.highest_frp_mw,
            "approaching_incidents": situation.approaching_incidents,
            "increasing_intensity_incidents": (
                situation.increasing_intensity_incidents
            ),
            "increasing_activity_incidents": (
                situation.increasing_activity_incidents
            ),
            "assessed_at": situation.assessed_at.isoformat(),
            "classification": "integration_calculated_situation_indicator",
        }


class FireSourceConfirmationSensor(TerraLyraEntity, SensorEntity):
    """Expose whether an independent satellite source corroborates active fire."""

    _attr_translation_key = "fire_source_confirmation"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "disabled",
        "not_available",
        "no_active_fire",
        "single_source",
        "multi_source",
    ]
    _attr_icon = "mdi:satellite-uplink"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_source_confirmation"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return data.confirmation_level.value if data else "not_available"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "primary_provider": self.coordinator.provider_name,
            "secondary_provider": self.coordinator.corroboration_provider_name,
            "secondary_status": (
                self.coordinator.corroboration_status.value
                if self.coordinator.corroboration_status is not None
                else "disabled"
            ),
            "secondary_satellite": self.coordinator.corroboration_satellite,
            "secondary_product_timestamp": (
                self.coordinator.corroboration_product_timestamp.isoformat()
                if self.coordinator.corroboration_product_timestamp
                else None
            ),
            "corroborating_detections": (
                data.corroborating_detections if data else 0
            ),
            "correlation_distance_km": 5.0,
            "correlation_window_hours": 6,
            "classification": "independent_satellite_source_corroboration",
        }


class NearestFireEvidenceSensor(TerraLyraEntity, SensorEntity):
    """Explain the strength and limitations of the nearest fire evidence."""

    _attr_translation_key = "nearest_fire_evidence"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["no_active_fire", "limited", "moderate", "strong"]
    _attr_icon = "mdi:shield-search"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_nearest_fire_evidence"

    def _assessment(self) -> FireEvidenceAssessment:
        data = self.coordinator.data
        nearest = data.active_clusters[0] if data and data.active_clusters else None
        return assess_fire_evidence(
            nearest,
            product_time=data.product_time if data else None,
            secondary_available=(
                self.coordinator.corroboration_status is ProviderStatus.AVAILABLE
            ),
        )

    @property
    def native_value(self) -> str:
        return self._assessment().level

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        assessment = self._assessment()
        data = self.coordinator.data
        nearest = data.active_clusters[0] if data and data.active_clusters else None
        return {
            "score": assessment.score,
            "factors": list(assessment.factors),
            "cautions": list(assessment.cautions),
            "incident_id": nearest.track_id if nearest else None,
            "classification": "integration_calculated_evidence_strength",
            "not_an_emergency_confirmation": True,
        }


class FireRiskTodaySensor(TerraLyraFireRiskEntity, SensorEntity):
    """Near-Home FRMv3 risk with the ten-day outlook."""

    _attr_translation_key = "fire_risk_today"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["low", "moderate", "high", "very_high", "extreme", "unknown"]
    _attr_icon = "mdi:pine-tree-fire"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_today"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return data.days[0].risk if data and data.days else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {"forecast": [], "attribution": "EUMETSAT / LSA SAF, CC BY 4.0"}
        return {
            "risk_level": data.days[0].level,
            "scope": "near_home",
            "sample_latitude": data.latitude,
            "sample_longitude": data.longitude,
            "generated_at": data.generated_at.isoformat(),
            "forecast": [
                {"date": day.valid_date.isoformat(), "risk": day.risk, "level": day.level}
                for day in data.days
            ],
            "source_url": WMS_URL,
            "attribution": "EUMETSAT / LSA SAF, CC BY 4.0",
        }


class FireRiskAreaMaximumSensor(TerraLyraFireRiskEntity, SensorEntity):
    """Highest sampled risk in the configured monitoring area."""

    _attr_translation_key = "fire_risk_area_maximum"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["low", "moderate", "high", "very_high", "extreme", "unknown"]
    _attr_icon = "mdi:map-marker-alert"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_area_maximum"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return data.area_risk if data else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {"attribution": "EUMETSAT / LSA SAF, CC BY 4.0"}
        return {
            "risk_level": data.area_level,
            "scope": "monitoring_area",
            "monitoring_radius_km": data.radius_km,
            "sample_latitude": data.area_latitude,
            "sample_longitude": data.area_longitude,
            "sampling_method": "bounded_raster_scan",
            "valid_date": data.days[0].valid_date.isoformat(),
            "source_url": WMS_URL,
            "attribution": "EUMETSAT / LSA SAF, CC BY 4.0",
        }


class FireRiskUpdateSensor(TerraLyraFireRiskEntity, SensorEntity):
    """Expose successful FRMv3 refresh and validity metadata."""

    _attr_translation_key = "fire_risk_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_update"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.generated_at if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {"forecast_available": False}
        return {
            "forecast_available": True,
            "forecast_days": len(data.days),
            "valid_from": data.days[0].valid_date.isoformat(),
            "valid_until": data.days[-1].valid_date.isoformat(),
            "next_planned_update": (data.generated_at + timedelta(hours=12)).isoformat(),
            "source_url": WMS_URL,
        }
