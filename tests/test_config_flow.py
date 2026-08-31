"""Tests for the TerraLyra config, reauth, and options flows."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terralyra.api import LsaSafAuthError, LsaSafError
from custom_components.terralyra.const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    CONF_ACTIVE_FIRE_PROVIDER,
    CONF_DEDUP_HOURS,
    CONF_DEDUP_RADIUS_KM,
    CONF_ENABLE_FIRMS,
    CONF_ENABLE_LAND_SURFACE_TEMPERATURE,
    CONF_FIRE_HISTORY_HOURS,
    CONF_FIRE_RISK_RADIUS_KM,
    CONF_FIRMS_MAP_KEY,
    CONF_LOCATION_ID,
    CONF_MANAGE_MONITORED_LOCATIONS,
    CONF_MIN_CONFIDENCE,
    CONF_MIN_FRP_MW,
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_PASSWORD,
    CONF_RADIUS_KM,
    CONF_RESOLVE_PLACE_NAMES,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    CONF_USERNAME,
    DEFAULT_DEDUP_HOURS,
    DEFAULT_DEDUP_RADIUS_KM,
    DEFAULT_ENABLE_FIRMS,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_FIRE_HISTORY_HOURS,
    DEFAULT_FIRE_RISK_RADIUS_KM,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP_MW,
    DEFAULT_MONITORING_CENTER_NAME,
    DEFAULT_RADIUS_KM,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    LOCATION_ENABLED,
    LOCATION_ID,
    LOCATION_LATITUDE,
    LOCATION_LONGITUDE,
    LOCATION_NAME,
    LOCATION_RADIUS_KM,
    LOCATION_SOURCE,
    LOCATION_SOURCE_MANUAL,
    MAX_MONITORED_LOCATIONS,
)
from custom_components.terralyra.products.firms import FirmsError

USERNAME = "testuser"
PASSWORD = "testpass"
NEW_PASSWORD = "newpass"


def _default_options_input() -> dict:
    """Return a complete valid options submission."""
    return {
        CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
        CONF_USE_CUSTOM_MONITORING_CENTER: False,
        CONF_MONITORING_CENTER_NAME: DEFAULT_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE: 47.4979,
        CONF_MONITORING_LONGITUDE: 19.0402,
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


@pytest.fixture
def mock_test_auth() -> AsyncMock:
    """Mock the network authentication probe."""
    with patch(
        "custom_components.terralyra.config_flow.ActiveFireClient.async_test_auth",
        new_callable=AsyncMock,
    ) as mocked:
        yield mocked


async def _start_user_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )


async def _start_lsa_saf_flow(hass):
    result = await _start_user_flow(hass)
    assert result["step_id"] == "monitoring_center"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], _default_monitoring_input(hass)
    )


def _default_monitoring_input(hass, **overrides) -> dict:
    """Return a valid setup submission using Home by default."""
    return {
        CONF_USE_CUSTOM_MONITORING_CENTER: False,
        CONF_MONITORING_CENTER_NAME: DEFAULT_MONITORING_CENTER_NAME,
        CONF_MONITORING_LATITUDE: float(hass.config.latitude),
        CONF_MONITORING_LONGITUDE: float(hass.config.longitude),
    } | overrides


async def test_user_flow_success(hass, mock_test_auth: AsyncMock) -> None:
    """Test successful first-time setup."""
    result = await _start_lsa_saf_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sources"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: f"  {USERNAME}  ",
            CONF_PASSWORD: PASSWORD,
            CONF_FIRMS_MAP_KEY: "",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TerraLyra"
    assert result["data"] == {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
    }
    assert result["options"] == {
        CONF_RADIUS_KM: DEFAULT_RADIUS_KM,
        CONF_MONITORED_LOCATIONS: [
            {
                "id": "home",
                "name": "Home",
                "latitude": float(hass.config.latitude),
                "longitude": float(hass.config.longitude),
                "radius_km": DEFAULT_RADIUS_KM,
                "enabled": True,
                "source": "home_assistant",
            }
        ],
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
    mock_test_auth.assert_awaited_once()


async def test_goes_user_flow_needs_no_credentials(hass) -> None:
    """Test a GOES-covered location needs no credentials or secret."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _default_monitoring_input(
            hass,
            **{
                CONF_USE_CUSTOM_MONITORING_CENTER: True,
                CONF_MONITORING_CENTER_NAME: "California",
                CONF_MONITORING_LATITUDE: 38.5618,
                CONF_MONITORING_LONGITUDE: -121.6263,
            },
        ),
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "", CONF_PASSWORD: "", CONF_FIRMS_MAP_KEY: ""},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    assert CONF_USERNAME not in result["data"]
    assert CONF_PASSWORD not in result["data"]


async def test_goes_user_flow_rejects_unsafe_coverage(hass) -> None:
    """Test setup explains when no automatic source covers a location."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _default_monitoring_input(
            hass,
            **{
                CONF_USE_CUSTOM_MONITORING_CENTER: True,
                CONF_MONITORING_CENTER_NAME: "Budapest",
                CONF_MONITORING_LATITUDE: 47.4979,
                CONF_MONITORING_LONGITUDE: 19.0402,
            },
        ),
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "", CONF_PASSWORD: "", CONF_FIRMS_MAP_KEY: ""},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sources"
    assert result["errors"] == {"base": "no_source_available"}


async def test_goes_user_flow_accepts_custom_covered_center(hass) -> None:
    """Test GOES coverage is evaluated at the custom center, not Home."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _default_monitoring_input(
            hass,
            **{
                CONF_USE_CUSTOM_MONITORING_CENTER: True,
                CONF_MONITORING_CENTER_NAME: "New York",
                CONF_MONITORING_LATITUDE: 40.7128,
                CONF_MONITORING_LONGITUDE: -74.006,
            },
        ),
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "", CONF_PASSWORD: "", CONF_FIRMS_MAP_KEY: ""},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TerraLyra · New York"
    location = result["options"][CONF_MONITORED_LOCATIONS][0]
    assert location[LOCATION_LATITUDE] == 40.7128
    assert location[LOCATION_SOURCE] == LOCATION_SOURCE_MANUAL


async def test_monitoring_center_rejects_invalid_coordinates(hass) -> None:
    """Test non-finite custom coordinates cannot enter the config entry."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _default_monitoring_input(
            hass,
            **{
                CONF_USE_CUSTOM_MONITORING_CENTER: True,
                CONF_MONITORING_CENTER_NAME: "Invalid",
                CONF_MONITORING_LATITUDE: float("nan"),
            },
        ),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "monitoring_center"
    assert result["errors"] == {"base": "invalid_monitoring_center"}


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (LsaSafAuthError("bad auth"), "invalid_auth"),
        (LsaSafError("offline"), "cannot_connect"),
        (RuntimeError("unexpected"), "cannot_connect"),
    ],
)
async def test_user_flow_errors_recover(
    hass,
    mock_test_auth: AsyncMock,
    side_effect: Exception,
    expected_error: str,
) -> None:
    """Test all setup errors can be corrected without restarting the flow."""
    mock_test_auth.side_effect = [side_effect, None]

    result = await _start_lsa_saf_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: "bad"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sources"
    assert result["errors"] == {"base": expected_error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == PASSWORD


async def test_duplicate_account_aborts(hass, mock_test_auth: AsyncMock) -> None:
    """Test the same LSA SAF account cannot be configured twice."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    existing.add_to_hass(hass)

    result = await _start_lsa_saf_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME.upper(), CONF_PASSWORD: PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _start_reauth_flow(hass, entry: MockConfigEntry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=dict(entry.data),
    )


async def test_reauth_success(hass, mock_test_auth: AsyncMock) -> None:
    """Test successful reauthentication updates credentials and reloads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)

    result = await _start_reauth_flow(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: NEW_PASSWORD},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_USERNAME: USERNAME, CONF_PASSWORD: NEW_PASSWORD}


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (LsaSafAuthError("bad auth"), "invalid_auth"),
        (LsaSafError("offline"), "cannot_connect"),
        (RuntimeError("unexpected"), "cannot_connect"),
    ],
)
async def test_reauth_errors_recover(
    hass,
    mock_test_auth: AsyncMock,
    side_effect: Exception,
    expected_error: str,
) -> None:
    """Test reauth errors keep the flow open and allow recovery."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)
    mock_test_auth.side_effect = [side_effect, None]

    result = await _start_reauth_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: "bad"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected_error}

    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: NEW_PASSWORD},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_reauth_wrong_account_aborts(hass, mock_test_auth: AsyncMock) -> None:
    """Test reauth cannot silently switch to another LSA SAF account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)

    result = await _start_reauth_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "otheruser", CONF_PASSWORD: NEW_PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_USERNAME] == USERNAME
    assert entry.data[CONF_PASSWORD] == PASSWORD


async def test_options_flow_defaults_and_save(hass) -> None:
    """Test options form defaults and saving all user-adjustable values."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    new_options = {
        CONF_RADIUS_KM: 100.0,
        CONF_USE_CUSTOM_MONITORING_CENTER: True,
        CONF_MONITORING_CENTER_NAME: "New York",
        CONF_MONITORING_LATITUDE: 40.7128,
        CONF_MONITORING_LONGITUDE: -74.006,
        CONF_FIRE_RISK_RADIUS_KM: 250.0,
        CONF_MIN_CONFIDENCE: 0.5,
        CONF_MIN_FRP_MW: 10.0,
        CONF_SCAN_INTERVAL_MINUTES: 10.0,
        CONF_DEDUP_RADIUS_KM: 4.0,
        CONF_DEDUP_HOURS: 12.0,
        CONF_FIRE_HISTORY_HOURS: 24.0,
        CONF_RESOLVE_PLACE_NAMES: True,
        CONF_ENABLE_LAND_SURFACE_TEMPERATURE: True,
        CONF_ENABLE_FIRMS: False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], new_options
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RADIUS_KM] == 100.0
    assert CONF_USE_CUSTOM_MONITORING_CENTER not in result["data"]
    location = result["data"][CONF_MONITORED_LOCATIONS][0]
    assert location["name"] == "New York"
    assert location["latitude"] == 40.7128
    assert location["radius_km"] == 100.0
    assert location["source"] == LOCATION_SOURCE_MANUAL


async def test_options_flow_uses_existing_values(hass) -> None:
    """Test options flow presents existing values rather than resetting defaults."""
    existing_options = {
        CONF_RADIUS_KM: 75.0,
        CONF_USE_CUSTOM_MONITORING_CENTER: True,
        CONF_MONITORING_CENTER_NAME: "Madrid",
        CONF_MONITORING_LATITUDE: 40.4168,
        CONF_MONITORING_LONGITUDE: -3.7038,
        CONF_FIRE_RISK_RADIUS_KM: 150.0,
        CONF_MIN_CONFIDENCE: 0.75,
        CONF_MIN_FRP_MW: 20.0,
        CONF_SCAN_INTERVAL_MINUTES: 7.0,
        CONF_DEDUP_RADIUS_KM: 2.5,
        CONF_DEDUP_HOURS: 8.0,
        CONF_FIRE_HISTORY_HOURS: 18.0,
        CONF_RESOLVE_PLACE_NAMES: True,
        CONF_ENABLE_LAND_SURFACE_TEMPERATURE: False,
        CONF_ENABLE_FIRMS: False,
        "geocoding_url": "https://geo.example.org/reverse",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options=existing_options,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    schema = result["data_schema"]
    suggested = {
        marker.schema: (
            marker.description.get("suggested_value")
            if marker.description is not None
            else None
        )
        for marker in schema.schema
    }
    for key, value in existing_options.items():
        if key == "geocoding_url":
            continue
        assert suggested[key] == value
    assert "geocoding_url" not in suggested


async def test_options_flow_preserves_stored_manual_location_id(hass) -> None:
    """Editing transition options does not change the stable location ID."""
    options = {
        **{
            key: value
            for key, value in _default_options_input().items()
            if key
            not in {
                CONF_USE_CUSTOM_MONITORING_CENTER,
                CONF_MONITORING_CENTER_NAME,
                CONF_MONITORING_LATITUDE,
                CONF_MONITORING_LONGITUDE,
            }
        },
        CONF_MONITORED_LOCATIONS: [
            {
                "id": "manual-stable",
                "name": "Farm",
                "latitude": 46.0,
                "longitude": 20.0,
                "radius_km": 25.0,
                "enabled": True,
                "source": LOCATION_SOURCE_MANUAL,
            }
        ],
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options=options,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    submission = {
        **_default_options_input(),
        CONF_USE_CUSTOM_MONITORING_CENTER: True,
        CONF_MONITORING_CENTER_NAME: "Renamed farm",
        CONF_MONITORING_LATITUDE: 46.1,
        CONF_MONITORING_LONGITUDE: 20.1,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], submission
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    location = result["data"][CONF_MONITORED_LOCATIONS][0]
    assert location["id"] == "manual-stable"
    assert location["name"] == "Renamed farm"


async def test_options_flow_empty_location_list_falls_back_to_home(hass) -> None:
    """A damaged empty development list remains recoverable in the UI."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: []},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    suggested = {
        marker.schema: marker.description.get("suggested_value")
        for marker in result["data_schema"].schema
        if marker.description is not None
    }

    assert suggested[CONF_USE_CUSTOM_MONITORING_CENTER] is False
    assert suggested[CONF_MONITORING_LATITUDE] == float(hass.config.latitude)


async def test_options_reject_invalid_custom_monitoring_center(hass) -> None:
    """Test invalid custom-center values keep the options form open."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_USE_CUSTOM_MONITORING_CENTER: True,
        CONF_MONITORING_CENTER_NAME: " ",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_monitoring_center"}


async def test_options_reject_uncovered_goes_center(hass) -> None:
    """Test locations outside GOES coverage remain editable for peer sources."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ACTIVE_FIRE_PROVIDER_GOES,
        data={CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_USE_CUSTOM_MONITORING_CENTER: True,
        CONF_MONITORING_CENTER_NAME: "Budapest",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_enable_firms_validates_and_stores_secret(hass) -> None:
    """Test a newly supplied MAP_KEY is validated and stored outside options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_ENABLE_FIRMS: True,
        CONF_FIRMS_MAP_KEY: "A" * 32,
    }

    with patch(
        "custom_components.terralyra.config_flow.FirmsClient.async_area",
        new_callable=AsyncMock,
        return_value=(),
    ) as validate:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENABLE_FIRMS] is True
    assert CONF_FIRMS_MAP_KEY not in result["data"]
    assert entry.data[CONF_FIRMS_MAP_KEY] == "A" * 32
    validate.assert_awaited_once()


async def test_options_enable_firms_reuses_saved_secret(hass) -> None:
    """Test leaving the masked field blank retains and validates the saved key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_FIRMS_MAP_KEY: "B" * 32,
        },
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_ENABLE_FIRMS: True,
        CONF_FIRMS_MAP_KEY: "",
    }

    with patch(
        "custom_components.terralyra.config_flow.FirmsClient.async_area",
        new_callable=AsyncMock,
        return_value=(),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_FIRMS_MAP_KEY] == "B" * 32


async def test_options_firms_requires_a_key(hass) -> None:
    """Test FIRMS cannot be enabled without a personal MAP_KEY."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_ENABLE_FIRMS: True,
        CONF_FIRMS_MAP_KEY: "",
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_FIRMS_MAP_KEY: "firms_key_required"}


@pytest.mark.parametrize(
    ("map_key", "side_effect", "expected_errors"),
    [
        ("short", None, {CONF_FIRMS_MAP_KEY: "invalid_firms_key"}),
        ("C" * 32, FirmsError("offline"), {"base": "firms_cannot_connect"}),
        ("D" * 32, RuntimeError("unexpected"), {"base": "firms_cannot_connect"}),
    ],
)
async def test_options_firms_validation_errors_recover(
    hass,
    map_key: str,
    side_effect: Exception | None,
    expected_errors: dict[str, str],
) -> None:
    """Test invalid credentials and connectivity failures keep the form open."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        **_default_options_input(),
        CONF_ENABLE_FIRMS: True,
        CONF_FIRMS_MAP_KEY: map_key,
    }

    with patch(
        "custom_components.terralyra.config_flow.FirmsClient.async_area",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == expected_errors


def _stored_location(
    location_id: str = "home", *, enabled: bool = True
) -> dict[str, object]:
    return {
        LOCATION_ID: location_id,
        LOCATION_NAME: "Home" if location_id == "home" else "Cabin",
        LOCATION_LATITUDE: 47.4979,
        LOCATION_LONGITUDE: 19.0402,
        LOCATION_RADIUS_KM: 25.0,
        LOCATION_ENABLED: enabled,
        LOCATION_SOURCE: (
            "home_assistant" if location_id == "home" else LOCATION_SOURCE_MANUAL
        ),
    }


async def _start_location_management(hass, entry: MockConfigEntry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **_default_options_input(),
            CONF_MANAGE_MONITORED_LOCATIONS: True,
        },
    )


async def test_options_add_monitored_location(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_location"}
    )
    assert result["step_id"] == "add_location"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            LOCATION_NAME: "Cabin",
            LOCATION_LATITUDE: 46.5,
            LOCATION_LONGITUDE: 18.5,
            LOCATION_RADIUS_KM: 40.0,
            LOCATION_ENABLED: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    locations = result["data"][CONF_MONITORED_LOCATIONS]
    assert len(locations) == 2
    assert locations[1][LOCATION_NAME] == "Cabin"
    assert locations[1][LOCATION_ID].startswith("manual-")


async def test_options_edit_monitored_location(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "home"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            LOCATION_NAME: "My home",
            LOCATION_LATITUDE: 47.5,
            LOCATION_LONGITUDE: 19.1,
            LOCATION_RADIUS_KM: 30.0,
            LOCATION_ENABLED: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    location = result["data"][CONF_MONITORED_LOCATIONS][0]
    assert location[LOCATION_ID] == "home"
    assert location[LOCATION_NAME] == "My home"


async def test_options_cannot_disable_or_delete_last_location(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "toggle_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "home"}
    )
    assert result["errors"] == {"base": "one_location_required"}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**_default_options_input(), CONF_MANAGE_MONITORED_LOCATIONS: True},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "home"}
    )
    assert result["errors"] == {"base": "one_location_required"}


async def test_options_toggle_and_delete_with_two_locations(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={
            CONF_MONITORED_LOCATIONS: [
                _stored_location(),
                _stored_location("cabin"),
            ]
        },
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "toggle_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "cabin"}
    )
    assert result["data"][CONF_MONITORED_LOCATIONS][1][LOCATION_ENABLED] is False

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={
            CONF_MONITORED_LOCATIONS: [
                _stored_location(),
                _stored_location("cabin"),
            ]
        },
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "cabin"}
    )
    assert len(result["data"][CONF_MONITORED_LOCATIONS]) == 1


async def test_options_add_location_reports_limit_and_allows_peer_coverage(hass) -> None:
    """Adding reports the local limit and permits automatic peer assignment."""
    locations = [
        {
            **_stored_location(f"location-{index}"),
            LOCATION_NAME: f"Location {index}",
        }
        for index in range(MAX_MONITORED_LOCATIONS)
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
        options={CONF_MONITORED_LOCATIONS: locations},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_location"}
    )
    location_input = {
        LOCATION_NAME: "Remote site",
        LOCATION_LATITUDE: 47.0,
        LOCATION_LONGITUDE: 19.0,
        LOCATION_RADIUS_KM: 25.0,
        LOCATION_ENABLED: True,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], location_input
    )
    assert result["errors"] == {"base": "too_many_locations"}

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], location_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["data"][CONF_MONITORED_LOCATIONS]) == 2


async def test_options_edit_cannot_disable_last_location(hass) -> None:
    """Editing cannot leave the installation without an enabled location."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LOCATION_ID: "home"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            LOCATION_NAME: "Home",
            LOCATION_LATITUDE: 47.4979,
            LOCATION_LONGITUDE: 19.0402,
            LOCATION_RADIUS_KM: 25.0,
            LOCATION_ENABLED: False,
        },
    )
    assert result["errors"] == {"base": "invalid_monitored_location"}


@pytest.mark.parametrize("step_id", ["toggle_location", "delete_location"])
async def test_options_reject_unknown_location_id(hass, step_id: str) -> None:
    """Forged or stale opaque location IDs never mutate stored options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        options={CONF_MONITORED_LOCATIONS: [_stored_location()]},
    )
    entry.add_to_hass(hass)
    result = await _start_location_management(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )
    with pytest.raises(InvalidData, match="Schema validation failed"):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_LOCATION_ID: "unknown"}
        )
