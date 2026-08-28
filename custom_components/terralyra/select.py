"""Forecast-day selector for the FRMv3 map."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import CONF_FIRE_RISK_DAY, DEFAULT_FIRE_RISK_DAY
from .entity import TerraLyraFireRiskEntity

DAY_OPTIONS = ("today", "tomorrow", *(f"in_{day}_days" for day in range(2, 10)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraLyraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FireRiskForecastDaySelect(entry)])


class FireRiskForecastDaySelect(TerraLyraFireRiskEntity, SelectEntity):
    """Choose which daily forecast the map camera displays."""

    _attr_translation_key = "fire_risk_day"
    _attr_options = list(DAY_OPTIONS)
    _attr_icon = "mdi:calendar-range"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_day"

    @property
    def current_option(self) -> str:
        day = int(self.entry.options.get(CONF_FIRE_RISK_DAY, DEFAULT_FIRE_RISK_DAY))
        return DAY_OPTIONS[day] if 0 <= day < len(DAY_OPTIONS) else DAY_OPTIONS[0]

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError("Unsupported FRMv3 forecast day")
        options = dict(self.entry.options)
        options[CONF_FIRE_RISK_DAY] = DAY_OPTIONS.index(option)
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self.async_write_ha_state()
