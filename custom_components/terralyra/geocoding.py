"""Offline nearest-settlement lookup using the bundled GeoNames database."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3

from homeassistant.core import HomeAssistant

GEONAMES_ATTRIBUTION = "GeoNames, CC BY 4.0"
DATABASE_PATH = Path(__file__).with_name("data") / "geonames_cities500.sqlite3"
SEARCH_RADII_KM = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 20020.0)
EARTH_RADIUS_KM = 6371.0088


class PlaceLookupError(Exception):
    """The bundled place database could not resolve a coordinate."""


@dataclass(frozen=True, slots=True)
class PlaceInfo:
    """Nearest settlement information for a fire coordinate."""

    place_name: str | None
    nearest_settlement: str | None
    location_description: str
    attribution: str = GEONAMES_ATTRIBUTION


@dataclass(frozen=True, slots=True)
class MapPlace:
    """One prominent settlement label for a forecast map."""

    latitude: float
    longitude: float
    name: str


class PlaceNameResolver:
    """Resolve coordinates locally without external network requests."""

    def __init__(self, hass: HomeAssistant, database_path: Path = DATABASE_PATH) -> None:
        self._hass = hass
        self._database_path = database_path
        self._lock = asyncio.Lock()

    async def async_setup(self) -> None:
        """Verify that the bundled database can be opened and has metadata."""
        valid = await self._hass.async_add_executor_job(self._validate_database)
        if not valid:
            raise PlaceLookupError("The bundled GeoNames database is invalid")

    async def async_resolve(self, latitude: float, longitude: float) -> PlaceInfo:
        """Return the closest settlement without sending coordinates off-device."""
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise PlaceLookupError("Latitude is outside the valid range")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise PlaceLookupError("Longitude is outside the valid range")
        async with self._lock:
            result = await self._hass.async_add_executor_job(
                self._resolve_sync, latitude, longitude
            )
        if result is None:
            raise PlaceLookupError("No settlement was found")
        name, _country_code, _distance_km = result
        return PlaceInfo(
            place_name=None,
            nearest_settlement=name,
            location_description=f"{name} közelében észlelt tűz",
        )

    async def async_map_places(
        self, bbox: tuple[float, float, float, float], limit: int = 12
    ) -> tuple[MapPlace, ...]:
        """Return a small population-ranked label set inside European bounds."""
        west, south, east, north = bbox
        if not (
            all(math.isfinite(value) for value in bbox)
            and -180 <= west < east <= 180
            and -90 <= south < north <= 90
            and 1 <= limit <= 20
        ):
            raise PlaceLookupError("Invalid map label bounds")
        async with self._lock:
            return await self._hass.async_add_executor_job(
                self._map_places_sync, bbox, limit
            )

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self._database_path.as_posix()}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True)

    def _validate_database(self) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'source'"
                ).fetchone()
            return row == ("GeoNames cities500",)
        except sqlite3.Error:
            return False

    def _resolve_sync(
        self, latitude: float, longitude: float
    ) -> tuple[str, str, float] | None:
        try:
            with self._connect() as connection:
                for radius_km in SEARCH_RADII_KM:
                    candidates = _query_candidates(
                        connection, latitude, longitude, radius_km
                    )
                    distances = [
                                (
                                    name,
                                    country,
                                    _haversine_km(latitude, longitude, lat, lon),
                                )
                        for lat, lon, name, country in candidates
                    ]
                    within_radius = [item for item in distances if item[2] <= radius_km]
                    if within_radius:
                        return min(within_radius, key=lambda item: item[2])
        except sqlite3.Error as err:
            raise PlaceLookupError("The bundled GeoNames database is unavailable") from err
        return None

    def _map_places_sync(
        self, bbox: tuple[float, float, float, float], limit: int
    ) -> tuple[MapPlace, ...]:
        west, south, east, north = bbox
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT latitude, longitude, name FROM places "
                    "WHERE latitude BETWEEN ? AND ? "
                    "AND longitude BETWEEN ? AND ? "
                    "ORDER BY population DESC LIMIT ?",
                    (south, north, west, east, limit),
                ).fetchall()
        except sqlite3.Error as err:
            raise PlaceLookupError("The bundled GeoNames database is unavailable") from err
        return tuple(MapPlace(float(lat), float(lon), str(name)) for lat, lon, name in rows)


def _query_candidates(
    connection: sqlite3.Connection,
    latitude: float,
    longitude: float,
    radius_km: float,
) -> list[tuple[float, float, str, str]]:
    """Read settlements from a conservative bounding box around a coordinate."""
    latitude_delta = min(180.0, radius_km / 110.574)
    cosine = max(0.01, abs(math.cos(math.radians(latitude))))
    longitude_delta = min(180.0, radius_km / (111.320 * cosine))
    south = max(-90.0, latitude - latitude_delta)
    north = min(90.0, latitude + latitude_delta)
    west = longitude - longitude_delta
    east = longitude + longitude_delta
    base = (
        "SELECT latitude, longitude, name, country_code FROM places "
        "WHERE latitude BETWEEN ? AND ? AND "
    )
    if west < -180.0:
        query = base + "(longitude >= ? OR longitude <= ?)"
        params = (south, north, west + 360.0, east)
    elif east > 180.0:
        query = base + "(longitude >= ? OR longitude <= ?)"
        params = (south, north, west, east - 360.0)
    else:
        query = base + "longitude BETWEEN ? AND ?"
        params = (south, north, west, east)
    return list(connection.execute(query, params))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    d_lat = lat2_rad - lat1_rad
    d_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    value = min(1.0, max(0.0, value))
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
