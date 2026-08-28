"""Provider-attributed TerraLyra map entities for active fire clusters."""
from __future__ import annotations

from typing import Any, override

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import ATTR_PRODUCT_TIME, ATTR_SOURCE_URL, DOMAIN
from .coordinator import FireCluster
from .entity import TerraLyraEntity


@callback
def _async_remove_expired_entity(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    entity: TerraLyraFireLocation,
) -> None:
    """Remove an expired marker from both the platform and registry."""
    entity_id = entity.entity_id
    if entity_id is not None and registry.async_get(entity_id) is not None:
        # Removing the registry entry also removes the loaded entity. This
        # prevents expired fire markers from lingering as unavailable entities.
        registry.async_remove(entity_id)
        return

    hass.async_create_task(entity.async_remove(force_remove=True))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraLyraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up and maintain one map entity per active fire cluster."""
    coordinator = entry.runtime_data.coordinator
    entities: dict[str, TerraLyraFireLocation] = {}

    def active_clusters() -> dict[str, FireCluster]:
        data = coordinator.data
        return {
            cluster.track_id: cluster
            for cluster in (data.tracked_fires if data else [])
            if cluster.track_id is not None
        }

    registry = er.async_get(hass)
    active_unique_ids = {
        f"{entry.entry_id}_fire_{track_id}" for track_id in active_clusters()
    }
    prefix = f"{entry.entry_id}_fire_"
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            registry_entry.domain != "geo_location"
            or registry_entry.platform != DOMAIN
            or not registry_entry.unique_id.startswith(prefix)
        ):
            continue
        if registry_entry.unique_id not in active_unique_ids:
            registry.async_remove(registry_entry.entity_id)
        elif registry_entry.device_id is not None:
            registry.async_update_entity(registry_entry.entity_id, device_id=None)

    @callback
    def async_sync_entities() -> None:
        active = active_clusters()

        for track_id in entities.keys() - active.keys():
            entity = entities.pop(track_id)
            _async_remove_expired_entity(hass, registry, entity)

        new_entities: list[TerraLyraFireLocation] = []
        for track_id, cluster in active.items():
            if track_id in entities:
                entities[track_id].set_cluster(cluster)
                continue
            entity = TerraLyraFireLocation(entry, cluster)
            entities[track_id] = entity
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(async_sync_entities))
    async_sync_entities()


class TerraLyraFireLocation(TerraLyraEntity, GeolocationEvent):
    """An active fire cluster shown on Home Assistant maps."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:fire-alert"

    def __init__(self, entry: TerraLyraConfigEntry, cluster: FireCluster) -> None:
        super().__init__(entry)
        self._attr_device_info = None
        if cluster.track_id is None:
            raise ValueError("A map entity requires a tracked fire cluster")
        self._cluster = cluster
        self._attr_unique_id = f"{entry.entry_id}_fire_{cluster.track_id}"
        self._attr_name = _display_name(cluster)

    @callback
    def set_cluster(self, cluster: FireCluster) -> None:
        """Replace this entity's current cluster data."""
        self._cluster = cluster
        self._attr_name = _display_name(cluster)

    @property
    @override
    def distance(self) -> float:
        return self._cluster.distance_km

    @property
    @override
    def latitude(self) -> float:
        return self._cluster.latitude

    @property
    @override
    def longitude(self) -> float:
        return self._cluster.longitude

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs = self._cluster.attrs()
        if data:
            attrs[ATTR_PRODUCT_TIME] = data.product_time.isoformat()
            attrs.setdefault(ATTR_SOURCE_URL, data.source_url)
        return attrs


def _display_name(cluster: FireCluster) -> str:
    """Return a map label that makes supplemental FIRMS markers explicit."""
    track_id = cluster.track_id or "unknown"
    name = cluster.location_description or f"Fire detection {track_id[:6]}"
    if cluster.providers == ("nasa_firms",):
        return f"NASA FIRMS · {name}"
    return name
