"""Base entity helpers."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TerraLyraConfigEntry
from .const import DOMAIN, MANUFACTURER, NAME
from .coordinator import TerraLyraCoordinator
from .fire_risk_coordinator import FireRiskCoordinator
from .lst_coordinator import LandSurfaceTemperatureCoordinator


class TerraLyraEntity(CoordinatorEntity[TerraLyraCoordinator]):
    """Base entity for TerraLyra."""

    _attr_has_entity_name = True

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self.entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Environmental monitoring and early warning",
            configuration_url="https://github.com/TerraLyra/ha-terralyra",
        )


class TerraLyraFireRiskEntity(CoordinatorEntity[FireRiskCoordinator]):
    """Base entity for the daily FRMv3 product."""

    _attr_has_entity_name = True

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry.runtime_data.fire_risk_coordinator)
        self.entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Environmental monitoring and early warning",
            configuration_url="https://github.com/TerraLyra/ha-terralyra",
        )


class TerraLyraLandSurfaceTemperatureEntity(
    CoordinatorEntity[LandSurfaceTemperatureCoordinator]
):
    """Base entity for the optional MTLST product."""

    _attr_has_entity_name = True

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        super().__init__(entry.runtime_data.lst_coordinator)
        self.entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Environmental monitoring and early warning",
            configuration_url="https://github.com/TerraLyra/ha-terralyra",
        )
