"""Event entity for newly detected MTG fires."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import (
    BUS_EVENT_FIRE_RISK_INCREASE,
    EVENT_FIRE_ACTIVITY_DECREASING,
    EVENT_FIRE_ACTIVITY_INCREASING,
    EVENT_FIRE_APPROACHING,
    EVENT_FIRE_INTENSITY_INCREASING,
    EVENT_FIRE_RISK_INCREASE,
    EVENT_NEW_FIRE,
)
from .entity import TerraLyraEntity, TerraLyraFireRiskEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: TerraLyraConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        [
            NewFireEvent(entry),
            FireTrendEvent(entry),
            FireRiskIncreaseEvent(entry),
        ]
    )


class NewFireEvent(TerraLyraEntity, EventEntity):
    """Event emitted once for each newly deduplicated nearby fire."""

    _attr_translation_key = "new_fire"
    _attr_event_types = [EVENT_NEW_FIRE]
    _attr_icon = "mdi:fire-alert"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_new_fire"
        self._last_product_filename: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data and data.filename != self._last_product_filename:
            self._last_product_filename = data.filename
            for fire in data.new_fires:
                self._trigger_event(EVENT_NEW_FIRE, fire)
                self.async_write_ha_state()
        super()._handle_coordinator_update()


class FireTrendEvent(TerraLyraEntity, EventEntity):
    """Meaningful, cooldown-protected incident trend changes."""

    _attr_translation_key = "fire_trend"
    _attr_event_types = [
        EVENT_FIRE_INTENSITY_INCREASING,
        EVENT_FIRE_ACTIVITY_INCREASING,
        EVENT_FIRE_ACTIVITY_DECREASING,
        EVENT_FIRE_APPROACHING,
    ]
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_trend"
        self._last_product_filename: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data and data.filename != self._last_product_filename:
            self._last_product_filename = data.filename
            for event_data in data.trend_events:
                self._trigger_event(str(event_data["event_type"]), event_data)
                self.async_write_ha_state()
        super()._handle_coordinator_update()


class FireRiskIncreaseEvent(TerraLyraFireRiskEntity, EventEntity):
    """Event raised when today's FRMv3 risk increases to high or worse."""

    _attr_translation_key = "fire_risk_increase"
    _attr_event_types = [EVENT_FIRE_RISK_INCREASE]
    _attr_icon = "mdi:pine-tree-fire"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        TerraLyraFireRiskEntity.__init__(self, entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_increase"
        data = self.coordinator.data
        self._last_level = data.area_level if data else None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        level = data.area_level if data else None
        previous = self._last_level
        self._last_level = level
        if (
            level is not None
            and previous is not None
            and level >= 3
            and level > previous
        ):
            event_data = {
                "risk": data.area_risk,
                "level": level,
                "previous_level": previous,
                "valid_date": data.days[0].valid_date.isoformat(),
                "scope": "monitoring_area",
                "monitoring_radius_km": data.radius_km,
                "sample_latitude": data.area_latitude,
                "sample_longitude": data.area_longitude,
            }
            self._trigger_event(EVENT_FIRE_RISK_INCREASE, event_data)
            self.hass.bus.async_fire(BUS_EVENT_FIRE_RISK_INCREASE, event_data)
            self.async_write_ha_state()
        super()._handle_coordinator_update()
