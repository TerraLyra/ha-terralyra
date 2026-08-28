"""Coordinator for the daily LSA SAF FRMv3 forecast."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_FIRE_RISK_RADIUS_KM, CONF_RADIUS_KM, DEFAULT_RADIUS_KM, DOMAIN
from .products.fire_risk import (
    FireRiskClient,
    FireRiskError,
    FireRiskForecast,
    analyze_risk_map,
    map_bounds,
)

_LOGGER = logging.getLogger(__name__)


class FireRiskCoordinator(DataUpdateCoordinator[FireRiskForecast]):
    """Retrieve the demonstration FRMv3 product independently of active fires."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: FireRiskClient
    ) -> None:
        self.entry = entry
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_fire_risk",
            update_interval=_staggered_interval(entry.entry_id),
        )

    async def _async_update_data(self) -> FireRiskForecast:
        try:
            latitude = float(self.hass.config.latitude)
            longitude = float(self.hass.config.longitude)
            radius = float(
                self.entry.options.get(
                    CONF_FIRE_RISK_RADIUS_KM,
                    self.entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                )
            )
            forecast = await self.client.async_forecast(latitude, longitude, radius)
            bbox = map_bounds(latitude, longitude, radius)
            image = await self.client.async_map(bbox, forecast.days[0].valid_date)
            level, area_latitude, area_longitude = await self.hass.async_add_executor_job(
                analyze_risk_map, image, bbox, latitude, longitude, radius
            )
            return replace(
                forecast,
                area_level=level,
                area_latitude=area_latitude,
                area_longitude=area_longitude,
            )
        except FireRiskError as err:
            raise UpdateFailed(str(err)) from err


def _staggered_interval(entry_id: str) -> timedelta:
    """Spread installations over a one-hour window around twelve hours."""
    digest = hashlib.sha256(entry_id.encode()).digest()
    offset_seconds = int.from_bytes(digest[:2]) % 3601 - 1800
    return timedelta(hours=12, seconds=offset_seconds)
