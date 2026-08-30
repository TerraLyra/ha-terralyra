"""Config flow for TerraLyra."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import LsaSafAuthError, LsaSafError
from .const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
    CONF_ACTIVE_FIRE_PROVIDER,
    CONF_DEDUP_HOURS,
    CONF_DEDUP_RADIUS_KM,
    CONF_ENABLE_FIRMS,
    CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
    CONF_FIRMS_MAP_KEY,
    CONF_FIRE_RISK_RADIUS_KM,
    CONF_FIRE_HISTORY_HOURS,
    CONF_MIN_CONFIDENCE,
    CONF_MIN_FRP_MW,
    CONF_MONITORED_LOCATIONS,
    CONF_MANAGE_MONITORED_LOCATIONS,
    CONF_LOCATION_ID,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_PASSWORD,
    CONF_RADIUS_KM,
    CONF_RESOLVE_PLACE_NAMES,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_USERNAME,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    DEFAULT_DEDUP_HOURS,
    DEFAULT_DEDUP_RADIUS_KM,
    DEFAULT_ENABLE_FIRMS,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_FIRE_RISK_RADIUS_KM,
    DEFAULT_FIRE_HISTORY_HOURS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP_MW,
    DEFAULT_MONITORING_CENTER_NAME,
    DEFAULT_RADIUS_KM,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_USE_CUSTOM_MONITORING_CENTER,
    DOMAIN,
    LOCATION_ENABLED,
    LOCATION_ID,
    LOCATION_LATITUDE,
    LOCATION_LONGITUDE,
    LOCATION_NAME,
    LOCATION_RADIUS_KM,
    LOCATION_SOURCE,
    LOCATION_SOURCE_HOME_ASSISTANT,
    MAX_RADIUS_KM,
    MAX_MONITORED_LOCATIONS,
    MIN_RADIUS_KM,
    LOCATION_SOURCE_MANUAL,
)
from .monitoring import (
    MonitoredLocation,
    MonitoringCenter,
    monitored_location_from_center,
    new_manual_location_id,
    resolve_monitored_locations,
    validate_monitored_locations,
    validate_monitoring_center,
)
from .products.fire import ActiveFireClient
from .products.firms import FirmsAuthenticationError, FirmsClient, FirmsError
from .providers.goes import select_goes_satellite

FIRMS_VALIDATION_SOURCE = "VIIRS_NOAA20_NRT"


class TerraLyraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a TerraLyra config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize temporary setup state."""
        super().__init__()
        self._selected_provider = ACTIVE_FIRE_PROVIDER_LSA_SAF
        self._monitoring_options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the primary active-fire provider."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._selected_provider = str(user_input[CONF_ACTIVE_FIRE_PROVIDER])
            return await self.async_step_monitoring_center()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACTIVE_FIRE_PROVIDER,
                        default=ACTIVE_FIRE_PROVIDER_LSA_SAF,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                ACTIVE_FIRE_PROVIDER_LSA_SAF,
                                ACTIVE_FIRE_PROVIDER_GOES,
                            ],
                            translation_key="active_fire_provider",
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_monitoring_center(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose Home or a custom center for active-fire monitoring."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                center = _monitoring_center_from_input(self.hass, user_input)
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_monitoring_center"
            else:
                if (
                    self._selected_provider == ACTIVE_FIRE_PROVIDER_GOES
                    and select_goes_satellite(center.latitude, center.longitude) is None
                ):
                    errors["base"] = "goes_not_available"
                else:
                    self._monitoring_options = {
                        CONF_USE_CUSTOM_MONITORING_CENTER: center.custom,
                        CONF_MONITORING_CENTER_NAME: center.name,
                        CONF_MONITORING_LATITUDE: center.latitude,
                        CONF_MONITORING_LONGITUDE: center.longitude,
                    }
                    if self._selected_provider == ACTIVE_FIRE_PROVIDER_LSA_SAF:
                        return await self.async_step_lsa_saf()
                    await self.async_set_unique_id(ACTIVE_FIRE_PROVIDER_GOES)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_entry_title(center),
                        data={CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
                        options=_default_options()
                        | _serialized_monitoring_options(
                            center, DEFAULT_RADIUS_KM
                        ),
                    )

        defaults = _home_monitoring_options(self.hass)
        if user_input is not None:
            defaults |= user_input
        return self.async_show_form(
            step_id="monitoring_center",
            data_schema=self.add_suggested_values_to_schema(
                _monitoring_center_schema(), defaults
            ),
            errors=errors,
        )

    async def async_step_lsa_saf(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect an LSA SAF account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = ActiveFireClient(
                async_get_clientsession(self.hass),
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_test_auth()
            except LsaSafAuthError:
                errors["base"] = "invalid_auth"
            except LsaSafError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_USERNAME].strip().lower())
                self._abort_if_unique_id_configured()
                center = _monitoring_center_from_options(
                    self.hass,
                    self._monitoring_options or _home_monitoring_options(self.hass),
                )
                return self.async_create_entry(
                    title=_entry_title(center),
                    data={
                        CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_LSA_SAF,
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options=_default_options()
                    | _serialized_monitoring_options(center, DEFAULT_RADIUS_KM),
                )

        return self.async_show_form(
            step_id="lsa_saf",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after a runtime authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate replacement credentials and update the existing entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            client = ActiveFireClient(
                async_get_clientsession(self.hass),
                username,
                password,
            )
            try:
                await client.async_test_auth()
            except LsaSafAuthError:
                errors["base"] = "invalid_auth"
            except LsaSafError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME,
                    default=entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return TerraLyraOptionsFlow()


class TerraLyraOptionsFlow(OptionsFlowWithReload):
    """Handle TerraLyra integration options."""

    def __init__(self) -> None:
        """Initialize location-management state."""
        self._selected_location_id: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options = dict(user_input)
            if options.pop(CONF_MANAGE_MONITORED_LOCATIONS, False):
                return await self.async_step_monitored_locations()
            try:
                center = _monitoring_center_from_input(self.hass, options)
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_monitoring_center"
                center = MonitoringCenter(
                    DEFAULT_MONITORING_CENTER_NAME,
                    float(self.hass.config.latitude),
                    float(self.hass.config.longitude),
                    False,
                )
            else:
                options[CONF_MONITORING_CENTER_NAME] = center.name
            if (
                not errors
                and self.config_entry.data.get(
                    CONF_ACTIVE_FIRE_PROVIDER,
                    ACTIVE_FIRE_PROVIDER_LSA_SAF,
                )
                == ACTIVE_FIRE_PROVIDER_GOES
                and select_goes_satellite(center.latitude, center.longitude) is None
            ):
                errors["base"] = "goes_not_available"
            submitted_key = str(options.pop(CONF_FIRMS_MAP_KEY, "")).strip()
            if not errors and options.get(CONF_ENABLE_FIRMS, DEFAULT_ENABLE_FIRMS):
                map_key = submitted_key or str(
                    self.config_entry.data.get(CONF_FIRMS_MAP_KEY, "")
                )
                if not map_key:
                    errors[CONF_FIRMS_MAP_KEY] = "firms_key_required"
                else:
                    west, south, east, north = _firms_validation_bounds(
                        center.latitude,
                        center.longitude,
                    )
                    try:
                        await FirmsClient(
                            async_get_clientsession(self.hass), map_key
                        ).async_area(
                            source=FIRMS_VALIDATION_SOURCE,
                            west=west,
                            south=south,
                            east=east,
                            north=north,
                        )
                    except FirmsAuthenticationError:
                        errors[CONF_FIRMS_MAP_KEY] = "invalid_firms_key"
                    except FirmsError:
                        errors["base"] = "firms_cannot_connect"
                    except Exception:  # noqa: BLE001
                        errors["base"] = "firms_cannot_connect"
                    else:
                        _replace_location_options(
                            options,
                            center,
                            manual_id=_existing_manual_location_id(
                                self.hass, self.config_entry
                            ),
                        )
                        if submitted_key:
                            self.hass.config_entries.async_update_entry(
                                self.config_entry,
                                data={
                                    **self.config_entry.data,
                                    CONF_FIRMS_MAP_KEY: submitted_key,
                                },
                            )
                        return self.async_create_entry(data=options)
            elif not errors:
                _replace_location_options(
                    options,
                    center,
                    manual_id=_existing_manual_location_id(
                        self.hass, self.config_entry
                    ),
                )
                return self.async_create_entry(data=options)

        current = _default_options() | dict(self.config_entry.options)
        current |= _monitoring_form_values(self.hass, self.config_entry)
        if user_input is not None:
            current |= {
                key: value
                for key, value in user_input.items()
                if key != CONF_FIRMS_MAP_KEY
            }
        schema = vol.Schema(
            {
                vol.Required(CONF_RADIUS_KM): NumberSelector(
                    NumberSelectorConfig(min=MIN_RADIUS_KM, max=MAX_RADIUS_KM, step=1, unit_of_measurement="km", mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_MANAGE_MONITORED_LOCATIONS, default=False
                ): bool,
                vol.Required(CONF_USE_CUSTOM_MONITORING_CENTER): bool,
                vol.Required(CONF_MONITORING_CENTER_NAME): TextSelector(
                    TextSelectorConfig()
                ),
                vol.Required(CONF_MONITORING_LATITUDE): NumberSelector(
                    NumberSelectorConfig(
                        min=-90,
                        max=90,
                        step="any",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_MONITORING_LONGITUDE): NumberSelector(
                    NumberSelectorConfig(
                        min=-180,
                        max=180,
                        step="any",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_FIRE_RISK_RADIUS_KM): NumberSelector(
                    NumberSelectorConfig(min=MIN_RADIUS_KM, max=MAX_RADIUS_KM, step=1, unit_of_measurement="km", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_MIN_CONFIDENCE): NumberSelector(
                    NumberSelectorConfig(min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Required(CONF_MIN_FRP_MW): NumberSelector(
                    NumberSelectorConfig(min=0, max=1000, step=1, unit_of_measurement="MW", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SCAN_INTERVAL_MINUTES): NumberSelector(
                    NumberSelectorConfig(min=2, max=30, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_DEDUP_RADIUS_KM): NumberSelector(
                    NumberSelectorConfig(min=0.5, max=20, step=0.5, unit_of_measurement="km", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_DEDUP_HOURS): NumberSelector(
                    NumberSelectorConfig(min=1, max=48, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_FIRE_HISTORY_HOURS): NumberSelector(
                    NumberSelectorConfig(min=1, max=48, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_RESOLVE_PLACE_NAMES): bool,
                vol.Required(CONF_ENABLE_LAND_SURFACE_TEMPERATURE): bool,
                vol.Required(CONF_ENABLE_FIRMS): bool,
                vol.Optional(CONF_FIRMS_MAP_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
        )

    async def async_step_monitored_locations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the available local location-management actions."""
        return self.async_show_menu(
            step_id="monitored_locations",
            menu_options=[
                "add_location",
                "edit_location",
                "toggle_location",
                "delete_location",
            ],
        )

    async def async_step_add_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add one manually configured monitored location."""
        errors: dict[str, str] = {}
        locations = list(resolve_monitored_locations(self.hass, self.config_entry))
        if user_input is not None:
            try:
                if len(locations) >= MAX_MONITORED_LOCATIONS:
                    raise OverflowError
                location = _manual_location_from_input(
                    user_input, new_manual_location_id()
                )
                _validate_provider_location(self.config_entry, location)
                validate_monitored_locations(tuple([*locations, location]))
            except OverflowError:
                errors["base"] = "too_many_locations"
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_monitored_location"
            else:
                return self._save_locations([*locations, location])
        return self.async_show_form(
            step_id="add_location",
            data_schema=self.add_suggested_values_to_schema(
                _location_schema(),
                {
                    LOCATION_NAME: "",
                    LOCATION_LATITUDE: float(self.hass.config.latitude),
                    LOCATION_LONGITUDE: float(self.hass.config.longitude),
                    LOCATION_RADIUS_KM: DEFAULT_RADIUS_KM,
                    LOCATION_ENABLED: True,
                },
            ),
            errors=errors,
        )

    async def async_step_edit_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select and edit an existing monitored location."""
        locations = list(resolve_monitored_locations(self.hass, self.config_entry))
        if self._selected_location_id is None:
            if user_input is not None:
                self._selected_location_id = str(user_input[CONF_LOCATION_ID])
                return await self.async_step_edit_location()
            return self._location_selector_form("edit_location", locations)
        location = _find_location(locations, self._selected_location_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                updated = _location_from_edit_input(user_input, location)
                _validate_provider_location(self.config_entry, updated)
                replacement = [updated if item.id == updated.id else item for item in locations]
                validate_monitored_locations(tuple(replacement))
                if not any(item.enabled for item in replacement):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_monitored_location"
            else:
                return self._save_locations(replacement)
        return self.async_show_form(
            step_id="edit_location",
            data_schema=self.add_suggested_values_to_schema(
                _location_schema(),
                {
                    LOCATION_NAME: location.name,
                    LOCATION_LATITUDE: location.latitude,
                    LOCATION_LONGITUDE: location.longitude,
                    LOCATION_RADIUS_KM: location.radius_km,
                    LOCATION_ENABLED: location.enabled,
                },
            ),
            errors=errors,
        )

    async def async_step_toggle_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enable or disable one location while preserving a live center."""
        locations = list(resolve_monitored_locations(self.hass, self.config_entry))
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = _find_location(locations, str(user_input[CONF_LOCATION_ID]))
            replacement = [
                MonitoredLocation(
                    id=item.id,
                    name=item.name,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    radius_km=item.radius_km,
                    enabled=not item.enabled,
                    source=item.source,
                )
                if item.id == selected.id
                else item
                for item in locations
            ]
            if not any(item.enabled for item in replacement):
                errors["base"] = "one_location_required"
            else:
                return self._save_locations(replacement)
        return self._location_selector_form(
            "toggle_location", locations, errors=errors
        )

    async def async_step_delete_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete one location without allowing an empty active list."""
        locations = list(resolve_monitored_locations(self.hass, self.config_entry))
        errors: dict[str, str] = {}
        if user_input is not None:
            selected_id = str(user_input[CONF_LOCATION_ID])
            replacement = [item for item in locations if item.id != selected_id]
            # The selector schema rejects stale/forged IDs before this handler.
            if len(replacement) == len(locations):  # pragma: no cover
                errors["base"] = "invalid_monitored_location"
            elif not any(item.enabled for item in replacement):
                errors["base"] = "one_location_required"
            else:
                return self._save_locations(replacement)
        return self._location_selector_form(
            "delete_location", locations, errors=errors
        )

    def _location_selector_form(
        self,
        step_id: str,
        locations: list[MonitoredLocation],
        *,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": item.id, "label": item.name}
                                for item in locations
                            ]
                        )
                    )
                }
            ),
            errors=errors or {},
        )

    def _save_locations(
        self, locations: list[MonitoredLocation]
    ) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        options[CONF_MONITORED_LOCATIONS] = [
            location.as_dict() for location in locations
        ]
        primary = next(location for location in locations if location.enabled)
        options[CONF_RADIUS_KM] = primary.radius_km
        return self.async_create_entry(data=options)


def _default_options() -> dict[str, Any]:
    return {
        CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
        CONF_FIRE_RISK_RADIUS_KM: DEFAULT_FIRE_RISK_RADIUS_KM,
        CONF_MIN_CONFIDENCE: DEFAULT_MIN_CONFIDENCE,
        CONF_MIN_FRP_MW: DEFAULT_MIN_FRP_MW,
        CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES,
        CONF_DEDUP_RADIUS_KM: DEFAULT_DEDUP_RADIUS_KM,
        CONF_DEDUP_HOURS: DEFAULT_DEDUP_HOURS,
        CONF_FIRE_HISTORY_HOURS: DEFAULT_FIRE_HISTORY_HOURS,
        CONF_RESOLVE_PLACE_NAMES: DEFAULT_RESOLVE_PLACE_NAMES,
        CONF_ENABLE_LAND_SURFACE_TEMPERATURE: (
            DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE
        ),
        CONF_ENABLE_FIRMS: DEFAULT_ENABLE_FIRMS,
    }


def _location_schema() -> vol.Schema:
    """Return the shared manual monitored-location form."""
    return vol.Schema(
        {
            vol.Required(LOCATION_NAME): TextSelector(TextSelectorConfig()),
            vol.Required(LOCATION_LATITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(LOCATION_LONGITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-180, max=180, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(LOCATION_RADIUS_KM): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_RADIUS_KM,
                    max=MAX_RADIUS_KM,
                    step=1,
                    unit_of_measurement="km",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(LOCATION_ENABLED): bool,
        }
    )


def _manual_location_from_input(
    values: dict[str, Any], location_id: str
) -> MonitoredLocation:
    """Build one validated manual location from an options form."""
    location = MonitoredLocation(
        id=location_id,
        name=str(values[LOCATION_NAME]).strip(),
        latitude=float(values[LOCATION_LATITUDE]),
        longitude=float(values[LOCATION_LONGITUDE]),
        radius_km=float(values[LOCATION_RADIUS_KM]),
        enabled=bool(values[LOCATION_ENABLED]),
        source=LOCATION_SOURCE_MANUAL,
    )
    validate_monitored_locations((location,))
    return location


def _location_from_edit_input(
    values: dict[str, Any], existing: MonitoredLocation
) -> MonitoredLocation:
    """Preserve stable identity and source while editing a location."""
    updated = _manual_location_from_input(values, existing.id)
    return MonitoredLocation(
        id=updated.id,
        name=updated.name,
        latitude=updated.latitude,
        longitude=updated.longitude,
        radius_km=updated.radius_km,
        enabled=updated.enabled,
        source=existing.source,
    )


def _find_location(
    locations: list[MonitoredLocation], location_id: str
) -> MonitoredLocation:
    """Resolve a submitted opaque ID without accepting arbitrary records."""
    location = next((item for item in locations if item.id == location_id), None)
    # Every UI caller is protected by a selector containing the current IDs.
    if location is None:  # pragma: no cover
        raise ValueError("Unknown monitored location")
    return location


def _validate_provider_location(
    entry: config_entries.ConfigEntry, location: MonitoredLocation
) -> None:
    """Reject locations unavailable from the configured primary provider."""
    if (
        entry.data.get(
            CONF_ACTIVE_FIRE_PROVIDER, ACTIVE_FIRE_PROVIDER_LSA_SAF
        )
        == ACTIVE_FIRE_PROVIDER_GOES
        and select_goes_satellite(location.latitude, location.longitude) is None
    ):
        raise ValueError("Location is outside NOAA GOES coverage")


def _serialized_monitoring_options(
    center: MonitoringCenter, radius_km: float
) -> dict[str, Any]:
    """Return the version-2 local location-list representation."""
    return {
        CONF_MONITORED_LOCATIONS: [
            monitored_location_from_center(center, radius_km).as_dict()
        ]
    }


def _replace_location_options(
    options: dict[str, Any],
    center: MonitoringCenter,
    *,
    manual_id: str | None = None,
) -> None:
    """Replace temporary form fields with the local location list."""
    options.update(
        {
            CONF_MONITORED_LOCATIONS: [
                monitored_location_from_center(
                    center,
                    float(options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)),
                    manual_id=manual_id,
                ).as_dict()
            ]
        }
    )
    for key in (
        CONF_USE_CUSTOM_MONITORING_CENTER,
        CONF_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE,
        CONF_MONITORING_LONGITUDE,
    ):
        options.pop(key, None)


def _monitoring_form_values(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> dict[str, Any]:
    """Adapt the first enabled stored location to the transition form."""
    locations = resolve_monitored_locations(hass, entry)
    location = next(
        (candidate for candidate in locations if candidate.enabled),
        locations[0] if locations else None,
    )
    if location is None:
        return _home_monitoring_options(hass)
    return {
        CONF_USE_CUSTOM_MONITORING_CENTER: (
            location.source == LOCATION_SOURCE_MANUAL
        ),
        CONF_MONITORING_CENTER_NAME: location.name,
        CONF_MONITORING_LATITUDE: location.latitude,
        CONF_MONITORING_LONGITUDE: location.longitude,
        CONF_RADIUS_KM: location.radius_km,
    }


def _existing_manual_location_id(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> str | None:
    """Preserve a manual location ID while transition options are edited."""
    return next(
        (
            location.id
            for location in resolve_monitored_locations(hass, entry)
            if location.source == LOCATION_SOURCE_MANUAL
        ),
        None,
    )


def _monitoring_center_schema() -> vol.Schema:
    """Return the reusable monitoring-center form schema."""
    return vol.Schema(
        {
            vol.Required(CONF_USE_CUSTOM_MONITORING_CENTER): bool,
            vol.Required(CONF_MONITORING_CENTER_NAME): TextSelector(
                TextSelectorConfig()
            ),
            vol.Required(CONF_MONITORING_LATITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-90,
                    max=90,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_MONITORING_LONGITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-180,
                    max=180,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _home_monitoring_options(hass: HomeAssistant) -> dict[str, Any]:
    """Return form values representing the Home location."""
    return {
        CONF_USE_CUSTOM_MONITORING_CENTER: False,
        CONF_MONITORING_CENTER_NAME: DEFAULT_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE: float(hass.config.latitude),
        CONF_MONITORING_LONGITUDE: float(hass.config.longitude),
    }


def _monitoring_center_from_input(
    hass: HomeAssistant, values: dict[str, Any]
) -> MonitoringCenter:
    """Validate submitted center values, ignoring coordinates when Home is used."""
    custom = bool(values.get(CONF_USE_CUSTOM_MONITORING_CENTER, False))
    if custom:
        name = str(values[CONF_MONITORING_CENTER_NAME]).strip()
        latitude = float(values[CONF_MONITORING_LATITUDE])
        longitude = float(values[CONF_MONITORING_LONGITUDE])
    else:
        name = DEFAULT_MONITORING_CENTER_NAME
        latitude = float(hass.config.latitude)
        longitude = float(hass.config.longitude)
    validate_monitoring_center(latitude, longitude, name)
    return MonitoringCenter(name, latitude, longitude, custom)


def _monitoring_center_from_options(
    hass: HomeAssistant, values: dict[str, Any]
) -> MonitoringCenter:
    """Resolve setup options into a monitoring center."""
    return _monitoring_center_from_input(hass, values)


def _entry_title(center: MonitoringCenter) -> str:
    """Make custom-center entries recognizable without renaming Home entries."""
    return f"TerraLyra · {center.name}" if center.custom else "TerraLyra"


def _firms_validation_bounds(
    latitude: float, longitude: float
) -> tuple[float, float, float, float]:
    """Build a tiny non-wrapping box for MAP_KEY validation."""
    delta = 0.01
    south = max(-90.0, latitude - delta)
    north = min(90.0, latitude + delta)
    west = max(-180.0, longitude - delta)
    east = min(180.0, longitude + delta)
    return west, south, east, north
