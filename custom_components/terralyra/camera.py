"""Image entity for the selected FRMv3 forecast map."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import logging

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TerraLyraConfigEntry
from .const import (
    CONF_FIRE_RISK_DAY,
    CONF_FIRE_RISK_RADIUS_KM,
    CONF_RADIUS_KM,
    DEFAULT_FIRE_RISK_DAY,
    DEFAULT_RADIUS_KM,
)
from .entity import TerraLyraFireRiskEntity
from .geocoding import PlaceLookupError
from .map_render import annotate_fire_risk_map
from .products.fire_risk import FireRiskError, map_bounds

_LOGGER = logging.getLogger(__name__)
INTERACTIVE_MAP_URL = "https://adaguc.lsasvcs.ipma.pt/"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraLyraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FireRiskMapCamera(entry)])


class FireRiskMapCamera(TerraLyraFireRiskEntity, Camera):
    """Display one selected day from the official FRMv3 WMS."""

    _attr_translation_key = "fire_risk_map"
    _attr_icon = "mdi:map-clock"

    def __init__(self, entry: TerraLyraConfigEntry) -> None:
        TerraLyraFireRiskEntity.__init__(self, entry)
        Camera.__init__(self)
        self.content_type = "image/png"
        self._attr_unique_id = f"{entry.entry_id}_fire_risk_map"
        self._cached_key: tuple[date, float] | None = None
        self._cached_image: bytes | None = None
        self._cached_at: datetime | None = None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        day = int(self.entry.options.get(CONF_FIRE_RISK_DAY, DEFAULT_FIRE_RISK_DAY))
        valid_date = datetime.now(UTC).date() + timedelta(days=day)
        radius = self._risk_radius
        key = (valid_date, radius)
        if (
            self._cached_key == key
            and self._cached_at is not None
            and datetime.now(UTC) - self._cached_at < timedelta(hours=1)
        ):
            return self._cached_image
        try:
            bbox = map_bounds(
                float(self.hass.config.latitude),
                float(self.hass.config.longitude),
                radius,
            )
            image = await self.entry.runtime_data.fire_risk_client.async_map(
                bbox, valid_date
            )
            places = ()
            if resolver := self.entry.runtime_data.place_name_resolver:
                try:
                    places = await resolver.async_map_places(bbox)
                except PlaceLookupError as err:
                    _LOGGER.debug("Could not add FRMv3 settlement labels: %s", err)
            image = annotate_fire_risk_map(
                image,
                bbox,
                float(self.hass.config.latitude),
                float(self.hass.config.longitude),
                valid_date,
                places,
                self.hass.config.language,
            )
        except FireRiskError as err:
            _LOGGER.debug("Could not retrieve FRMv3 map: %s", err)
            return self._cached_image
        self._cached_key = key
        self._cached_image = image
        self._cached_at = datetime.now(UTC)
        return image

    @property
    def extra_state_attributes(self) -> dict[str, str | int | float]:
        day = int(self.entry.options.get(CONF_FIRE_RISK_DAY, DEFAULT_FIRE_RISK_DAY))
        valid_date = datetime.now(UTC).date() + timedelta(days=day)
        return {
            "forecast_day": day,
            "valid_date": valid_date.isoformat(),
            "map_type": "annotated_static_preview",
            "monitoring_radius_km": float(
                self._risk_radius
            ),
            "interactive_map_url": INTERACTIVE_MAP_URL,
            "attribution": "EUMETSAT / LSA SAF, CC BY 4.0; GeoNames, CC BY 4.0",
        }

    @property
    def _risk_radius(self) -> float:
        """Return the independent FRMv3 map radius with upgrade compatibility."""
        return float(
            self.entry.options.get(
                CONF_FIRE_RISK_RADIUS_KM,
                self.entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
            )
        )
