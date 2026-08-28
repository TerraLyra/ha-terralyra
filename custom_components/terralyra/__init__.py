"""TerraLyra integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
    CONF_PASSWORD,
    CONF_RESOLVE_PLACE_NAMES,
    CONF_USERNAME,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TerraLyraCoordinator
from .fire_risk_coordinator import FireRiskCoordinator
from .geocoding import PlaceNameResolver
from .lst_coordinator import LandSurfaceTemperatureCoordinator
from .products.fire import ActiveFireClient
from .products.fire_risk import FireRiskClient
from .products.lst import LandSurfaceTemperatureClient
from .providers.mtg import MtgActiveFireProvider


@dataclass
class RuntimeData:
    """Runtime data for one TerraLyra config entry."""

    coordinator: TerraLyraCoordinator
    fire_risk_coordinator: FireRiskCoordinator
    fire_risk_client: FireRiskClient
    place_name_resolver: PlaceNameResolver | None
    lst_coordinator: LandSurfaceTemperatureCoordinator


type TerraLyraConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TerraLyraConfigEntry) -> bool:
    """Set up TerraLyra from a config entry."""
    session = async_get_clientsession(hass)
    client = ActiveFireClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    resolver = None
    if entry.options.get(CONF_RESOLVE_PLACE_NAMES, DEFAULT_RESOLVE_PLACE_NAMES):
        resolver = PlaceNameResolver(hass)
        await resolver.async_setup()
    coordinator = TerraLyraCoordinator(
        hass, entry, MtgActiveFireProvider(client), resolver
    )
    await coordinator.async_config_entry_first_refresh()
    fire_risk_client = FireRiskClient(session)
    fire_risk_coordinator = FireRiskCoordinator(hass, entry, fire_risk_client)
    lst_coordinator = LandSurfaceTemperatureCoordinator(
        hass, entry, LandSurfaceTemperatureClient(session)
    )
    entry.runtime_data = RuntimeData(
        coordinator=coordinator,
        fire_risk_coordinator=fire_risk_coordinator,
        fire_risk_client=fire_risk_client,
        place_name_resolver=resolver,
        lst_coordinator=lst_coordinator,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass,
        fire_risk_coordinator.async_refresh(),
        f"{DOMAIN} initial FRMv3 forecast",
    )
    if entry.options.get(
        CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
        DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    ):
        entry.async_create_background_task(
            hass,
            lst_coordinator.async_refresh(),
            f"{DOMAIN} initial MTLST observation",
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TerraLyraConfigEntry) -> bool:
    """Unload a TerraLyra config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
