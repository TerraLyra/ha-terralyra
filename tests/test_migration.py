"""Tests for versioned TerraLyra config-entry migration."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.terralyra import async_migrate_entry
from custom_components.terralyra.const import (
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    LEGACY_CUSTOM_LOCATION_ID,
    LOCATION_ID,
    LOCATION_RADIUS_KM,
    LOCATION_SOURCE,
    LOCATION_SOURCE_HOME_ASSISTANT,
    LOCATION_SOURCE_MANUAL,
)


def _hass() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(latitude=47.5, longitude=19.04),
        config_entries=SimpleNamespace(async_update_entry=Mock()),
    )


@pytest.mark.asyncio
async def test_v1_home_entry_migrates_without_changing_radius() -> None:
    """A legacy Home center becomes one dynamic Home location."""
    hass = _hass()
    entry = SimpleNamespace(
        entry_id="home-entry", version=1, options={CONF_RADIUS_KM: 42.0}
    )

    assert await async_migrate_entry(hass, entry) is True

    call = hass.config_entries.async_update_entry.call_args
    options = call.kwargs["options"]
    assert call.kwargs["version"] == 3
    assert options[CONF_RADIUS_KM] == 42.0
    location = options[CONF_MONITORED_LOCATIONS][0]
    assert location[LOCATION_ID] == "home"
    assert location[LOCATION_RADIUS_KM] == 42.0
    assert location[LOCATION_SOURCE] == LOCATION_SOURCE_HOME_ASSISTANT


@pytest.mark.asyncio
async def test_v1_custom_entry_migrates_to_opaque_manual_id() -> None:
    """A private legacy center migrates without embedding private data in its ID."""
    hass = _hass()
    entry = SimpleNamespace(
        # Recent Home Assistant versions may use uppercase ULID entry IDs.
        # Migration must not copy that implementation detail into a location ID.
        entry_id="01K4ABCDEF1234567890XYZABC",
        version=1,
        options={
            CONF_RADIUS_KM: 75.0,
            CONF_USE_CUSTOM_MONITORING_CENTER: True,
            CONF_MONITORING_CENTER_NAME: "Private farm",
            CONF_MONITORING_LATITUDE: 46.123456,
            CONF_MONITORING_LONGITUDE: 20.654321,
        },
    )

    assert await async_migrate_entry(hass, entry) is True

    options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    location = options[CONF_MONITORED_LOCATIONS][0]
    assert location[LOCATION_ID] == LEGACY_CUSTOM_LOCATION_ID
    assert "Private" not in location[LOCATION_ID]
    assert "46.123456" not in location[LOCATION_ID]
    assert location[LOCATION_SOURCE] == LOCATION_SOURCE_MANUAL
    assert CONF_USE_CUSTOM_MONITORING_CENTER not in options
    assert CONF_MONITORING_LATITUDE not in options


@pytest.mark.asyncio
async def test_v2_entry_removes_legacy_provider_selection() -> None:
    """A v2 entry switches to automatic source assignment."""
    hass = _hass()
    entry = SimpleNamespace(
        entry_id="current-entry",
        version=2,
        data={"active_fire_provider": "eumetsat_lsa_saf", "username": "user"},
        options={CONF_MONITORED_LOCATIONS: []},
    )

    assert await async_migrate_entry(hass, entry) is True
    call = hass.config_entries.async_update_entry.call_args
    assert call.kwargs["version"] == 3
    assert "active_fire_provider" not in call.kwargs["data"]
    assert call.kwargs["data"]["username"] == "user"


@pytest.mark.asyncio
async def test_current_entry_migration_is_idempotent() -> None:
    hass = _hass()
    entry = SimpleNamespace(entry_id="current-entry", version=3, options={})

    assert await async_migrate_entry(hass, entry) is True
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_future_entry_version_is_rejected() -> None:
    """Newer unknown schemas fail closed instead of being downgraded."""
    hass = _hass()
    entry = SimpleNamespace(entry_id="future-entry", version=4, options={})

    assert await async_migrate_entry(hass, entry) is False
    hass.config_entries.async_update_entry.assert_not_called()
