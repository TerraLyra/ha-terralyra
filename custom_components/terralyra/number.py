"""Adjustable monitoring radius entity."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import (
    CONF_FIRE_RISK_RADIUS_KM,
    CONF_FIRE_HISTORY_HOURS,
    CONF_RADIUS_KM,
    DEFAULT_FIRE_RISK_RADIUS_KM,
    DEFAULT_FIRE_HISTORY_HOURS,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
)
from .entity import TerraLyraEntity, TerraLyraFireRiskEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TerraLyraConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        [
            MonitoringRadiusNumber(entry),
            FireRiskRadiusNumber(entry),
            FireHistoryHoursNumber(entry),
        ]
    )


class MonitoringRadiusNumber(TerraLyraEntity, NumberEntity):
    """Monitoring radius that can be put directly on a dashboard."""

    _attr_translation_key = "monitoring_radius"
    _attr_native_min_value = MIN_RADIUS_KM
    _attr_native_max_value = MAX_RADIUS_KM
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "km"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:radius-outline"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_monitoring_radius"

    @property
    def native_value(self) -> float:
        return float(self.entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self.entry.options)
        options[CONF_RADIUS_KM] = float(value)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.coordinator.async_request_refresh()
        self.entry.async_create_background_task(
            self.hass,
            self.entry.runtime_data.fire_risk_coordinator.async_request_refresh(),
            f"{DOMAIN} refresh FRMv3 after radius change",
        )
        self.async_write_ha_state()


class FireRiskRadiusNumber(TerraLyraFireRiskEntity, NumberEntity):
    """Independent radius used for the FRMv3 map and regional maximum."""

    _attr_translation_key = "fire_risk_radius"
    _attr_native_min_value = MIN_RADIUS_KM
    _attr_native_max_value = MAX_RADIUS_KM
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "km"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        TerraLyraFireRiskEntity.__init__(self, entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_radius"

    @property
    def native_value(self) -> float:
        return float(
            self.entry.options.get(
                CONF_FIRE_RISK_RADIUS_KM,
                self.entry.options.get(CONF_RADIUS_KM, DEFAULT_FIRE_RISK_RADIUS_KM),
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self.entry.options)
        options[CONF_FIRE_RISK_RADIUS_KM] = float(value)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()


class FireHistoryHoursNumber(TerraLyraEntity, NumberEntity):
    """How long inactive incident markers remain visible on the map."""

    _attr_translation_key = "fire_history_hours"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 48.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "h"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:map-clock-outline"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_history_hours"

    @property
    def native_value(self) -> float:
        return float(
            self.entry.options.get(
                CONF_FIRE_HISTORY_HOURS, DEFAULT_FIRE_HISTORY_HOURS
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        options = dict(self.entry.options)
        options[CONF_FIRE_HISTORY_HOURS] = int(value)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
