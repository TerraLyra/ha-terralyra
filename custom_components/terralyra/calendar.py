"""Ten-day FRMv3 forecast calendar."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .entity import TerraLyraFireRiskEntity
from .products.fire_risk import FireRiskDay

RISK_LABELS = {
    "en": {
        "low": "Low", "moderate": "Moderate", "high": "High",
        "very_high": "Very high", "extreme": "Extreme", "unknown": "Unknown",
        "title": "Fire risk",
        "description": "LSA SAF FRMv3 fire-risk forecast near Home",
    },
    "hu": {
        "low": "Alacsony", "moderate": "Mérsékelt", "high": "Magas",
        "very_high": "Nagyon magas", "extreme": "Szélsőséges",
        "unknown": "Ismeretlen", "title": "Tűzkockázat",
        "description": "LSA SAF FRMv3 tűzkockázati előrejelzés az otthon közelében",
    },
    "de": {
        "low": "Niedrig", "moderate": "Mäßig", "high": "Hoch",
        "very_high": "Sehr hoch", "extreme": "Extrem", "unknown": "Unbekannt",
        "title": "Waldbrandgefahr",
        "description": "LSA SAF FRMv3-Waldbrandgefahrenvorhersage in der Nähe von Zuhause",
    },
    "es": {
        "low": "Bajo", "moderate": "Moderado", "high": "Alto",
        "very_high": "Muy alto", "extreme": "Extremo", "unknown": "Desconocido",
        "title": "Riesgo de incendio",
        "description": "Previsión LSA SAF FRMv3 del riesgo de incendio cerca de Casa",
    },
    "fr": {
        "low": "Faible", "moderate": "Modéré", "high": "Élevé",
        "very_high": "Très élevé", "extreme": "Extrême", "unknown": "Inconnu",
        "title": "Risque d’incendie",
        "description": "Prévision LSA SAF FRMv3 du risque d’incendie près du domicile",
    },
    "it": {
        "low": "Basso", "moderate": "Moderato", "high": "Alto",
        "very_high": "Molto alto", "extreme": "Estremo", "unknown": "Sconosciuto",
        "title": "Rischio di incendio",
        "description": "Previsione LSA SAF FRMv3 del rischio di incendio vicino a Casa",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraLyraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FireRiskForecastCalendar(entry)])


class FireRiskForecastCalendar(TerraLyraFireRiskEntity, CalendarEntity):
    """Expose all forecast days in Home Assistant's native calendar UI."""

    _attr_translation_key = "fire_risk_forecast"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        TerraLyraFireRiskEntity.__init__(self, entry)
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_forecast"

    @property
    def event(self) -> CalendarEvent | None:
        data = self.coordinator.data
        return self._calendar_event(data.days[0]) if data and data.days else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        data = self.coordinator.data
        if data is None:
            return []
        return [
            self._calendar_event(day)
            for day in data.days
            if day.valid_date < end_date.date()
            and day.valid_date + timedelta(days=1) > start_date.date()
        ]

    def _calendar_event(self, day: FireRiskDay) -> CalendarEvent:
        labels = RISK_LABELS.get(self.hass.config.language, RISK_LABELS["en"])
        return CalendarEvent(
            summary=f"{labels['title']}: {labels[day.risk]}",
            start=day.valid_date,
            end=day.valid_date + timedelta(days=1),
            description=labels["description"],
        )
