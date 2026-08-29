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
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
)
from .monitoring import MonitoringCenter, validate_monitoring_center
from .products.fire import ActiveFireClient
from .products.firms import FirmsAuthenticationError, FirmsClient, FirmsError
from .providers.goes import select_goes_satellite

FIRMS_VALIDATION_SOURCE = "VIIRS_NOAA20_NRT"


class TerraLyraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a TerraLyra config flow."""

    VERSION = 1

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
                        options=_default_options() | self._monitoring_options,
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
                    options=_default_options() | self._monitoring_options,
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

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options = dict(user_input)
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
                return self.async_create_entry(data=options)

        current = _default_options() | dict(self.config_entry.options)
        current.setdefault(CONF_MONITORING_LATITUDE, float(self.hass.config.latitude))
        current.setdefault(CONF_MONITORING_LONGITUDE, float(self.hass.config.longitude))
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


def _default_options() -> dict[str, Any]:
    return {
        CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
        CONF_USE_CUSTOM_MONITORING_CENTER: DEFAULT_USE_CUSTOM_MONITORING_CENTER,
        CONF_MONITORING_CENTER_NAME: DEFAULT_MONITORING_CENTER_NAME,
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
