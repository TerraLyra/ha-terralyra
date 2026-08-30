"""Tests for active-fire monitoring-center resolution."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.terralyra.const import (
    CONF_MONITORED_LOCATIONS,
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_USE_CUSTOM_MONITORING_CENTER,
    LOCATION_ENABLED,
    LOCATION_ID,
    LOCATION_LATITUDE,
    LOCATION_LONGITUDE,
    LOCATION_NAME,
    LOCATION_RADIUS_KM,
    LOCATION_SOURCE,
    LOCATION_SOURCE_MANUAL,
)
from custom_components.terralyra.monitoring import (
    MonitoredLocation,
    monitored_location_from_dict,
    resolve_monitoring_center,
    resolve_monitored_locations,
    validate_monitoring_center,
    validate_monitored_locations,
)


def test_monitoring_center_defaults_to_home() -> None:
    """Existing entries continue to follow the Home location."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    center = resolve_monitoring_center(hass, SimpleNamespace(options={}))

    assert center.name == "Home"
    assert center.latitude == 47.5
    assert center.longitude == 19.04
    assert center.custom is False


def test_monitoring_center_uses_custom_options() -> None:
    """Custom coordinates are resolved independently from Home."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    entry = SimpleNamespace(
        options={
            CONF_USE_CUSTOM_MONITORING_CENTER: True,
            CONF_MONITORING_CENTER_NAME: "New York",
            CONF_MONITORING_LATITUDE: 40.7128,
            CONF_MONITORING_LONGITUDE: -74.006,
        }
    )

    center = resolve_monitoring_center(hass, entry)
    assert center.storage_key == "40.712800:-74.006000"
    assert center.custom is True


def test_legacy_home_center_adapts_to_monitored_location() -> None:
    """The current flat options remain behaviourally compatible."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    entry = SimpleNamespace(options={"radius_km": 42.0})

    locations = resolve_monitored_locations(hass, entry)

    assert locations == (
        MonitoredLocation(
            id="home",
            name="Home",
            latitude=47.5,
            longitude=19.04,
            radius_km=42.0,
            enabled=True,
            source="home_assistant",
        ),
    )


def test_legacy_custom_center_adapts_without_coordinate_id() -> None:
    """Legacy custom coordinates receive a non-sensitive transitional ID."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    entry = SimpleNamespace(
        options={
            CONF_USE_CUSTOM_MONITORING_CENTER: True,
            CONF_MONITORING_CENTER_NAME: "New York",
            CONF_MONITORING_LATITUDE: 40.7128,
            CONF_MONITORING_LONGITUDE: -74.006,
            "radius_km": 75.0,
        }
    )

    location = resolve_monitored_locations(hass, entry)[0]

    assert location.id == "legacy-custom"
    assert location.source == LOCATION_SOURCE_MANUAL
    assert "40.7128" not in location.id
    assert "New York" not in location.id


def test_stored_location_list_round_trips() -> None:
    """The future list representation resolves deterministically."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    values = {
        LOCATION_ID: "farm-1",
        LOCATION_NAME: "Farm",
        LOCATION_LATITUDE: 46.2,
        LOCATION_LONGITUDE: 20.1,
        LOCATION_RADIUS_KM: 30.0,
        LOCATION_ENABLED: False,
        LOCATION_SOURCE: LOCATION_SOURCE_MANUAL,
    }
    entry = SimpleNamespace(options={CONF_MONITORED_LOCATIONS: [values]})

    location = resolve_monitored_locations(hass, entry)[0]

    assert location == monitored_location_from_dict(location.as_dict())
    assert location.enabled is False


def test_duplicate_location_ids_are_rejected() -> None:
    """Stable IDs remain unambiguous for events and persisted matches."""
    location = MonitoredLocation(
        "same", "First", 46.0, 20.0, 25.0, True, LOCATION_SOURCE_MANUAL
    )
    duplicate = MonitoredLocation(
        "same", "Second", 47.0, 21.0, 25.0, True, LOCATION_SOURCE_MANUAL
    )

    with pytest.raises(ValueError, match="Duplicate"):
        validate_monitored_locations((location, duplicate))


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"radius_km": 0.0},
        {"radius_km": float("inf")},
        {"source": "cloud"},
    ],
)
def test_monitored_location_validation_rejects_invalid_records(changes) -> None:
    """Unsafe list records never reach provider planning or matching."""
    values = {
        "id": "valid",
        "name": "Farm",
        "latitude": 46.0,
        "longitude": 20.0,
        "radius_km": 25.0,
        "enabled": True,
        "source": LOCATION_SOURCE_MANUAL,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        monitored_location_from_dict(values)


def test_stored_location_list_rejects_non_mapping_records() -> None:
    """Malformed stored lists fail closed instead of silently dropping items."""
    hass = SimpleNamespace(config=SimpleNamespace(latitude=47.5, longitude=19.04))
    entry = SimpleNamespace(options={CONF_MONITORED_LOCATIONS: ["invalid"]})

    with pytest.raises(ValueError, match="invalid record"):
        resolve_monitored_locations(hass, entry)


@pytest.mark.parametrize(
    ("latitude", "longitude", "name"),
    [(91, 0, "x"), (0, 181, "x"), (float("nan"), 0, "x"), (0, 0, "")],
)
def test_monitoring_center_validation_rejects_invalid_values(
    latitude: float, longitude: float, name: str
) -> None:
    """Invalid values never reach provider requests or persistent state."""
    with pytest.raises(ValueError):
        validate_monitoring_center(latitude, longitude, name)
