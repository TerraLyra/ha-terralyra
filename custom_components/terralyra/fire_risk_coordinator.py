"""Coordinator for the daily LSA SAF FRMv3 forecast."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_FIRE_RISK_RADIUS_KM, CONF_RADIUS_KM, DEFAULT_RADIUS_KM, DOMAIN
from .products.fire_risk import (
    FireRiskClient,
    FireRiskError,
    FireRiskForecast,
    FireRiskRateLimitError,
    FireRiskServiceUnavailableError,
    FireRiskTemporaryServiceError,
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
            try:
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
            except FireRiskError as err:
                _LOGGER.debug("FRMv3 map analysis was not available: %s", err)
                result = forecast
            self._consecutive_failures = 0
            self.update_interval = self._normal_interval
            async_set_fire_risk_outage_issue(
                self.hass, self.entry, consecutive_failures=0, reason=None
            )
            return result
        except FireRiskError as err:
            self._consecutive_failures += 1
            self.update_interval = _retry_interval(
                self._consecutive_failures, error=err
            )
            async_set_fire_risk_outage_issue(
                self.hass,
                self.entry,
                consecutive_failures=self._consecutive_failures,
                reason=str(err),
            )
            raise UpdateFailed(str(err)) from err


def _staggered_interval(entry_id: str) -> timedelta:
    """Spread installations over a one-hour window around twelve hours."""
    digest = hashlib.sha256(entry_id.encode()).digest()
    offset_seconds = int.from_bytes(digest[:2]) % 3601 - 1800
    return timedelta(hours=12, seconds=offset_seconds)


def _retry_interval(
    consecutive_failures: int,
    *,
    error: FireRiskError | None = None,
) -> timedelta:
    """Return a bounded exponential retry interval for FRMv3 failures."""
    if isinstance(error, (FireRiskRateLimitError, FireRiskTemporaryServiceError)):
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return min(max(retry_after, FIRE_RISK_RETRY_BASE), FIRE_RISK_RETRY_MAX)
    if isinstance(error, FireRiskServiceUnavailableError):
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return min(max(retry_after, FIRE_RISK_RETRY_BASE), FIRE_RISK_RETRY_MAX)

    failures = max(1, consecutive_failures)
    seconds = FIRE_RISK_RETRY_BASE.total_seconds() * (2 ** (failures - 1))
    return min(timedelta(seconds=seconds), FIRE_RISK_RETRY_MAX)
