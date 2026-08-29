"""Tests for active-fire monitoring-center resolution."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.terralyra.const import (
    CONF_MONITORING_CENTER_NAME,
    CONF_MONITORING_LATITUDE,
    CONF_MONITORING_LONGITUDE,
    CONF_USE_CUSTOM_MONITORING_CENTER,
)
from custom_components.terralyra.monitoring import (
    resolve_monitoring_center,
    validate_monitoring_center,
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
