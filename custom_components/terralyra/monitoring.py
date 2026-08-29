"""Resolve the active-fire monitoring center independently from Home."""
from __future__ import annotations

from dataclasses import dataclass
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    DEFAULT_MONITORING_CENTER_NAME,
    DEFAULT_USE_CUSTOM_MONITORING_CENTER,
)


@dataclass(frozen=True, slots=True)
class MonitoringCenter:
    """One validated center used by active-fire providers and calculations."""

    name: str
    latitude: float
    longitude: float
    custom: bool

    @property
    def storage_key(self) -> str:
        """Stable key used to prevent tracks crossing between centers."""
        return f"{self.latitude:.6f}:{self.longitude:.6f}"


def resolve_monitoring_center(
    hass: HomeAssistant, entry: ConfigEntry
) -> MonitoringCenter:
    """Return Home or a validated custom active-fire monitoring center."""
    custom = bool(
        entry.options.get(
            CONF_USE_CUSTOM_MONITORING_CENTER,
            DEFAULT_USE_CUSTOM_MONITORING_CENTER,
        )
    )
    if custom:
        latitude = float(entry.options[CONF_MONITORING_LATITUDE])
        longitude = float(entry.options[CONF_MONITORING_LONGITUDE])
        name = str(
            entry.options.get(
                CONF_MONITORING_CENTER_NAME,
                DEFAULT_MONITORING_CENTER_NAME,
            )
        ).strip()
    else:
        latitude = float(hass.config.latitude)
        longitude = float(hass.config.longitude)
        name = DEFAULT_MONITORING_CENTER_NAME
    validate_monitoring_center(latitude, longitude, name)
    return MonitoringCenter(name=name, latitude=latitude, longitude=longitude, custom=custom)


def validate_monitoring_center(latitude: float, longitude: float, name: str) -> None:
    """Reject unsafe coordinates and unusable labels."""
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("Monitoring-center coordinates must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Monitoring-center coordinates are out of range")
    if not name.strip() or len(name.strip()) > 64:
        raise ValueError("Monitoring-center name must contain 1 to 64 characters")
