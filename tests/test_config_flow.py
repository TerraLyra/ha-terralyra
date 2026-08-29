"""Tests for the TerraLyra config, reauth, and options flows."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terralyra.api import LsaSafAuthError, LsaSafError
from custom_components.terralyra.const import (
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
    CONF_PASSWORD,
    CONF_RADIUS_KM,
    CONF_RESOLVE_PLACE_NAMES,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_USERNAME,
    DEFAULT_DEDUP_HOURS,
    DEFAULT_DEDUP_RADIUS_KM,
    DEFAULT_ENABLE_FIRMS,
    DEFAULT_ENABLE_LAND_SURFACE_TEMPERATURE,
    DEFAULT_FIRE_RISK_RADIUS_KM,
    DEFAULT_FIRE_HISTORY_HOURS,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP_MW,
    DEFAULT_RADIUS_KM,
    DEFAULT_RESOLVE_PLACE_NAMES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from custom_components.terralyra.products.firms import FirmsError

USERNAME = "testuser"
PASSWORD = "testpass"
NEW_PASSWORD = "newpass"


def _default_options_input() -> dict:
    """Return a complete valid options submission."""
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
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_LSA_SAF},
    )


async def test_user_flow_success(hass, mock_test_auth: AsyncMock) -> None:
    """Test successful first-time setup."""
    result = await _start_lsa_saf_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lsa_saf"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: f"  {USERNAME}  ", CONF_PASSWORD: PASSWORD},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TerraLyra"
    assert result["data"] == {
        CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_LSA_SAF,
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
    }
    assert result["options"] == {
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
    mock_test_auth.assert_awaited_once()


async def test_goes_user_flow_needs_no_credentials(hass) -> None:
    """Test covered locations can select GOES without creating a secret."""
    with patch(
        "custom_components.terralyra.config_flow.select_goes_satellite",
        return_value=object(),
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES
    }
    assert CONF_USERNAME not in result["data"]
    assert CONF_PASSWORD not in result["data"]


async def test_goes_user_flow_rejects_unsafe_coverage(hass) -> None:
    """Test GOES cannot be enabled outside its conservative coverage gate."""
    with patch(
        "custom_components.terralyra.config_flow.select_goes_satellite",
        return_value=None,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ACTIVE_FIRE_PROVIDER: ACTIVE_FIRE_PROVIDER_GOES},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "goes_not_available"}


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
    assert result["step_id"] == "lsa_saf"
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
        unique_id=USERNAME,
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
    assert result["data"] == new_options


async def test_options_flow_uses_existing_values(hass) -> None:
    """Test options flow presents existing values rather than resetting defaults."""
    existing_options = {
        CONF_RADIUS_KM: 75.0,
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
