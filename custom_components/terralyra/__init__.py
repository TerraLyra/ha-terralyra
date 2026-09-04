"""TerraLyra integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CONFIG_ENTRY_ID,
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
    DEFAULT_ENABLE_FIRMS,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_RADIUS_KM,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DOMAIN,
    LEGACY_CUSTOM_LOCATION_ID,
    PLATFORMS,
    SERVICE_PROBE_MSG_IODC,
)
from .coordinator import TerraLyraCoordinator
from .fire_risk_coordinator import FireRiskCoordinator
from .geocoding import PlaceNameResolver
from .lst_coordinator import LandSurfaceTemperatureCoordinator
from .monitoring import (
    monitored_location_from_center,
    resolve_monitored_locations,
    resolve_monitoring_center,
)
from .products.fire_risk import FireRiskClient
from .products.lst import LandSurfaceTemperatureClient
from .products.msg_iodc import (
    MsgIodcAuthenticationError,
    MsgIodcSchemaError,
    MsgIodcUnavailableError,
    async_fetch_latest_list_product,
    inspect_list_product_schema,
)
from .providers.factory import build_provider_pool
from .repairs import async_sync_coverage_issue


@dataclass
class RuntimeData:
    """Runtime data for one TerraLyra config entry."""

    coordinator: TerraLyraCoordinator
    fire_risk_coordinator: FireRiskCoordinator
    fire_risk_client: FireRiskClient
    place_name_resolver: PlaceNameResolver | None
    lst_coordinator: LandSurfaceTemperatureCoordinator


type TerraLyraConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register explicit, response-only diagnostic actions."""

    async def async_probe_msg_iodc(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                "The selected TerraLyra entry was not found"
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("The selected TerraLyra entry is not loaded")
        username = entry.data.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD)
        if not username or not password:
            raise ServiceValidationError(
                "The selected TerraLyra entry has no LSA SAF credentials"
            )
        try:
            async with asyncio.timeout(60):
                filename, payload = await async_fetch_latest_list_product(
                    async_get_clientsession(hass), username, password
                )
            schema = await hass.async_add_executor_job(
                inspect_list_product_schema, filename, payload
            )
        except TimeoutError as err:
            raise ServiceValidationError(
                "The MSG-IODC compatibility check timed out"
            ) from err
        except MsgIodcAuthenticationError as err:
            raise ServiceValidationError(
                "LSA SAF rejected the saved credentials"
            ) from err
        except MsgIodcUnavailableError as err:
            raise ServiceValidationError(
                "No current MSG-IODC List Product could be retrieved"
            ) from err
        except MsgIodcSchemaError as err:
            raise ServiceValidationError(
                "The MSG-IODC product did not pass the bounded schema check"
            ) from err
        return {
            "status": "compatible",
            "provider": "EUMETSAT LSA SAF",
            "satellite": "Meteosat-9",
            "product": "MSG-IODC FRP-PIXEL List Product",
            "schema": schema,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE_MSG_IODC,
        async_probe_msg_iodc,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): str}),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: TerraLyraConfigEntry
) -> bool:
    """Migrate the single-center v1 config into the local location list."""
    if entry.version > 3:
        return False
    if entry.version == 3:
        return True

    if entry.version == 2:
        data = dict(getattr(entry, "data", {}))
        data.pop("active_fire_provider", None)
        hass.config_entries.async_update_entry(entry, data=data, version=3)
        return True

    options = dict(entry.options)
    if CONF_MONITORED_LOCATIONS not in options:
        center = resolve_monitoring_center(hass, entry)
        radius_km = float(options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        options[CONF_MONITORED_LOCATIONS] = [
            monitored_location_from_center(
                center,
                radius_km,
                manual_id=LEGACY_CUSTOM_LOCATION_ID,
            ).as_dict()
        ]
    for legacy_key in (
        CONF_USE_CUSTOM_MONITORING_CENTER,
        CONF_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE,
        CONF_MONITORING_LONGITUDE,
    ):
        options.pop(legacy_key, None)

    data = dict(getattr(entry, "data", {}))
    data.pop("active_fire_provider", None)
    hass.config_entries.async_update_entry(entry, data=data, options=options, version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TerraLyraConfigEntry) -> bool:
    """Set up TerraLyra from a config entry."""
    session = async_get_clientsession(hass)
    monitored_locations = resolve_monitored_locations(hass, entry)
    monitoring_center = resolve_monitoring_center(hass, entry)
    provider_pool, coverage_plans = build_provider_pool(
        session,
        hass.async_add_executor_job,
        locations=monitored_locations,
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        firms_enabled=entry.options.get(CONF_ENABLE_FIRMS, DEFAULT_ENABLE_FIRMS),
        firms_map_key=entry.data.get(CONF_FIRMS_MAP_KEY),
    )
    async_sync_coverage_issue(
        hass,
        entry,
        coverage_plans,
    )
    resolver = None
    if entry.options.get(CONF_RESOLVE_PLACE_NAMES, DEFAULT_RESOLVE_PLACE_NAMES):
        resolver = PlaceNameResolver(hass)
        await resolver.async_setup()
    coordinator = TerraLyraCoordinator(
        hass,
        entry,
        provider_pool,
        resolver,
        monitoring_center=monitoring_center,
        monitored_locations=monitored_locations,
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
