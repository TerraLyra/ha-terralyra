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
from .repairs import async_set_fire_risk_outage_issue

_LOGGER = logging.getLogger(__name__)
FIRE_RISK_RETRY_BASE = timedelta(minutes=15)
FIRE_RISK_RETRY_MAX = timedelta(hours=1)


class FireRiskCoordinator(DataUpdateCoordinator[FireRiskForecast]):
    """Retrieve the demonstration FRMv3 product independently of active fires."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: FireRiskClient
    ) -> None:
        self.entry = entry
        self.client = client
        self._normal_interval = _staggered_interval(entry.entry_id)
        self._consecutive_failures = 0
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_fire_risk",
            update_interval=self._normal_interval,
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
            result = replace(
                forecast,
                area_level=level,
                area_latitude=area_latitude,
                area_longitude=area_longitude,
            )
            self._consecutive_failures = 0
            self.update_interval = self._normal_interval
            async_set_fire_risk_outage_issue(
                self.hass, self.entry, consecutive_failures=0
            )
            return result
        except FireRiskError as err:
            self._consecutive_failures += 1
            self.update_interval = _retry_interval(self._consecutive_failures)
            async_set_fire_risk_outage_issue(
                self.hass,
                self.entry,
                consecutive_failures=self._consecutive_failures,
            )
            raise UpdateFailed(str(err)) from err


def _staggered_interval(entry_id: str) -> timedelta:
    """Spread installations over a one-hour window around twelve hours."""
    digest = hashlib.sha256(entry_id.encode()).digest()
    offset_seconds = int.from_bytes(digest[:2]) % 3601 - 1800
    return timedelta(hours=12, seconds=offset_seconds)


def _retry_interval(consecutive_failures: int) -> timedelta:
    """Return a bounded exponential retry interval for FRMv3 failures."""
    failures = max(1, consecutive_failures)
    seconds = FIRE_RISK_RETRY_BASE.total_seconds() * (2 ** (failures - 1))
    return min(timedelta(seconds=seconds), FIRE_RISK_RETRY_MAX)
