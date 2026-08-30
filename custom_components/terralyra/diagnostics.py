"""Privacy-safe diagnostics for the TerraLyra integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import TerraLyraConfigEntry
from .const import (
    CONF_FIRMS_MAP_KEY,
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_PASSWORD,
    CONF_USERNAME,
)

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_FIRMS_MAP_KEY,
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TerraLyraConfigEntry
) -> dict[str, Any]:
    """Return a bounded diagnostic summary without location or credentials."""
    active = entry.runtime_data.coordinator
    risk = entry.runtime_data.fire_risk_coordinator
    active_data = active.data
    risk_data = risk.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "active_fire": {
            "last_update_success": active.last_update_success,
            "provider_status": active.provider_status.value,
            "provider": active.provider_name,
            "satellite": active.satellite,
            "product": active.provider_product,
            "product_time": (
                active.product_timestamp.isoformat()
                if active.product_timestamp
                else None
            ),
            "received_time": (
                active.received_timestamp.isoformat()
                if active.received_timestamp
                else None
            ),
            "active_cluster_count": (
                len(active_data.active_clusters) if active_data else None
            ),
            "tracked_fire_count": (
                len(active_data.tracked_fires) if active_data else None
            ),
            "incident_lifecycle_counts": (
                {
                    state: sum(
                        getattr(cluster, "lifecycle", None) is not None
                        and cluster.lifecycle.value == state
                        for cluster in active_data.tracked_fires
                    )
                    for state in ("new", "continuing", "inactive")
                }
                if active_data
                else None
            ),
            "incident_trend_counts": (
                {
                    metric: {
                        state: sum(
                            getattr(cluster, metric, None) is not None
                            and getattr(cluster, metric).value == state
                            for cluster in active_data.tracked_fires
                        )
                        for state in (
                            ("approaching", "stable", "receding", "unknown")
                            if metric == "distance_trend"
                            else ("increasing", "stable", "decreasing", "unknown")
                        )
                    }
                    for metric in ("frp_trend", "activity_trend", "distance_trend")
                }
                if active_data
                else None
            ),
            "raw_pixels_in_radius": (
                active_data.raw_pixels_in_radius if active_data else None
            ),
            "activity_summary": (
                {
                    "detections_1h": active_data.activity.detections_1h,
                    "detections_3h": active_data.activity.detections_3h,
                    "detections_6h": active_data.activity.detections_6h,
                    "new_incidents_24h": active_data.activity.new_incidents_24h,
                    "history_samples_24h": active_data.activity.samples_24h,
                }
                if active_data and getattr(active_data, "activity", None)
                else None
            ),
            "situation": (
                {
                    "level": active_data.situation.level.value,
                    "score": active_data.situation.score,
                    "reasons": list(active_data.situation.reasons),
                    "active_incidents": active_data.situation.active_incidents,
                }
                if active_data and getattr(active_data, "situation", None)
                else None
            ),
        },
        "fire_risk": {
            "last_update_success": risk.last_update_success,
            "generated_at": (
                risk_data.generated_at.isoformat() if risk_data else None
            ),
            "forecast_days": len(risk_data.days) if risk_data else None,
            "near_home_risk": (
                risk_data.days[0].risk if risk_data and risk_data.days else None
            ),
            "area_risk": risk_data.area_risk if risk_data else None,
        },
        "place_names_enabled": entry.runtime_data.place_name_resolver is not None,
    }
