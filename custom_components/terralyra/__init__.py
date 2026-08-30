"""TerraLyra integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACTIVE_FIRE_PROVIDER,
    CONF_ENABLE_FIRMS,
    CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
    CONF_FIRMS_MAP_KEY,
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_PASSWORD,
    CONF_RADIUS_KM,
    CONF_RESOLVE_PLACE_NAMES,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    CONF_USERNAME,
    DEFAULT_ACTIVE_FIRE_PROVIDER,
    DEFAULT_ENABLE_FIRMS,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_RADIUS_KM,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TerraLyraCoordinator
from .fire_risk_coordinator import FireRiskCoordinator
from .geocoding import PlaceNameResolver
from .lst_coordinator import LandSurfaceTemperatureCoordinator
from .monitoring import monitored_location_from_center, resolve_monitoring_center
from .products.fire_risk import FireRiskClient
from .products.firms import FirmsClient
from .products.lst import LandSurfaceTemperatureClient
from .providers.factory import build_primary_provider
from .providers.firms import FirmsMultiSatelliteProvider, monitoring_bounds


@dataclass
class RuntimeData:
    """Runtime data for one TerraLyra config entry."""

    coordinator: TerraLyraCoordinator
    fire_risk_coordinator: FireRiskCoordinator
    fire_risk_client: FireRiskClient
    place_name_resolver: PlaceNameResolver | None
    lst_coordinator: LandSurfaceTemperatureCoordinator


type TerraLyraConfigEntry = ConfigEntry[RuntimeData]


async def async_migrate_entry(
    hass: HomeAssistant, entry: TerraLyraConfigEntry
) -> bool:
    """Migrate the single-center v1 config into the local location list."""
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True

    options = dict(entry.options)
    if CONF_MONITORED_LOCATIONS not in options:
        center = resolve_monitoring_center(hass, entry)
        radius_km = float(options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        options[CONF_MONITORED_LOCATIONS] = [
            monitored_location_from_center(
                center,
                radius_km,
                manual_id=f"manual-{entry.entry_id}",
            ).as_dict()
        ]
    for legacy_key in (
        CONF_USE_CUSTOM_MONITORING_CENTER,
        CONF_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE,
        CONF_MONITORING_LONGITUDE,
    ):
        options.pop(legacy_key, None)

    hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TerraLyraConfigEntry) -> bool:
    """Set up TerraLyra from a config entry."""
    session = async_get_clientsession(hass)
    monitoring_center = resolve_monitoring_center(hass, entry)
    primary_provider = build_primary_provider(
        session,
        hass.async_add_executor_job,
        provider_name=str(
            entry.data.get(CONF_ACTIVE_FIRE_PROVIDER, DEFAULT_ACTIVE_FIRE_PROVIDER)
        ),
        latitude=monitoring_center.latitude,
        longitude=monitoring_center.longitude,
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
    )
    resolver = None
    if entry.options.get(CONF_RESOLVE_PLACE_NAMES, DEFAULT_RESOLVE_PLACE_NAMES):
        resolver = PlaceNameResolver(hass)
        await resolver.async_setup()
    corroboration_provider = None
    if entry.options.get(CONF_ENABLE_FIRMS, DEFAULT_ENABLE_FIRMS):
        bounds = monitoring_bounds(
            monitoring_center.latitude,
            monitoring_center.longitude,
            float(entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)),
        )
        corroboration_provider = FirmsMultiSatelliteProvider(
            FirmsClient(session, str(entry.data.get(CONF_FIRMS_MAP_KEY, ""))),
            west=bounds[0],
            south=bounds[1],
            east=bounds[2],
            north=bounds[3],
        )
    coordinator = TerraLyraCoordinator(
        hass,
        entry,
        primary_provider,
        resolver,
        monitoring_center=monitoring_center,
        corroboration_provider=corroboration_provider,
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
