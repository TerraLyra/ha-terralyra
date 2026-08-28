"""Coordinator for the optional LSA SAF MTLST product."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .products.lst import (
    LandSurfaceTemperature,
    LandSurfaceTemperatureClient,
    LandSurfaceTemperatureError,
)

_LOGGER = logging.getLogger(__name__)


class LandSurfaceTemperatureCoordinator(
    DataUpdateCoordinator[LandSurfaceTemperature]
):
    """Retrieve MTLST independently from active-fire and fire-risk data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LandSurfaceTemperatureClient,
    ) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_land_surface_temperature",
            update_interval=_staggered_interval(entry.entry_id),
        )

    async def _async_update_data(self) -> LandSurfaceTemperature:
        try:
            return await self.client.async_point(
                float(self.hass.config.latitude),
                float(self.hass.config.longitude),
            )
        except LandSurfaceTemperatureError as err:
            raise UpdateFailed(str(err)) from err


def _staggered_interval(entry_id: str) -> timedelta:
    """Spread installations across five minutes around a 15-minute refresh."""
    digest = hashlib.sha256(f"lst:{entry_id}".encode()).digest()
    offset_seconds = int.from_bytes(digest[:2]) % 301 - 150
    return timedelta(minutes=15, seconds=offset_seconds)
