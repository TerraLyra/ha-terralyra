"""Tests for private offline GeoNames lookup."""
from __future__ import annotations

import math
from pathlib import Path
import sqlite3

import pytest

from custom_components.terralyra.geocoding import (
    GEONAMES_ATTRIBUTION,
    PlaceLookupError,
    PlaceNameResolver,
    _haversine_km,
    _location_description,
    _query_candidates,
)


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE places (
            latitude REAL NOT NULL, longitude REAL NOT NULL, name TEXT NOT NULL,
            country_code TEXT NOT NULL, admin1_code TEXT, population INTEGER NOT NULL
        );
        CREATE INDEX places_latitude_idx ON places(latitude);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata VALUES ('source', 'GeoNames cities500');
        INSERT INTO places VALUES (46.2530, 20.1414, 'Szeged', 'HU', '06', 160000);
        INSERT INTO places VALUES (47.4979, 19.0402, 'Budapest', 'HU', '05', 1700000);
        """
    )
    connection.close()


async def test_resolves_nearest_settlement_without_network(hass, tmp_path: Path) -> None:
    database = tmp_path / "places.sqlite3"
    _database(database)
    resolver = PlaceNameResolver(hass, database)
    await resolver.async_setup()

    place = await resolver.async_resolve(46.27, 20.15)

    assert place.place_name is None
    assert place.nearest_settlement == "Szeged"
    assert place.location_description == "Szeged közelében észlelt tűz"
    assert place.attribution == GEONAMES_ATTRIBUTION


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0), (math.nan, 0.0)],
)
async def test_rejects_invalid_coordinates(hass, tmp_path: Path, latitude, longitude) -> None:
    database = tmp_path / "places.sqlite3"
    _database(database)
    resolver = PlaceNameResolver(hass, database)

    with pytest.raises(PlaceLookupError):
        await resolver.async_resolve(latitude, longitude)


async def test_rejects_missing_or_untrusted_database(hass, tmp_path: Path) -> None:
    resolver = PlaceNameResolver(hass, tmp_path / "missing.sqlite3")

    with pytest.raises(PlaceLookupError):
        await resolver.async_setup()


async def test_map_places_are_population_ranked_and_bounded(hass, tmp_path: Path) -> None:
    database = tmp_path / "places.sqlite3"
    _database(database)
    resolver = PlaceNameResolver(hass, database)

    places = await resolver.async_map_places((18.0, 46.0, 21.0, 48.0), limit=2)

    assert [place.name for place in places] == ["Budapest", "Szeged"]


async def test_map_places_reject_invalid_bounds(hass, tmp_path: Path) -> None:
    resolver = PlaceNameResolver(hass, tmp_path / "unused.sqlite3")

    with pytest.raises(PlaceLookupError):
        await resolver.async_map_places((20.0, 46.0, 19.0, 48.0))


def test_bounding_box_handles_date_line() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE places (latitude REAL, longitude REAL, name TEXT, country_code TEXT)"
    )
    connection.executemany(
        "INSERT INTO places VALUES (?, ?, ?, ?)",
        [(0.0, 179.95, "East", "FJ"), (0.0, -179.95, "West", "FJ")],
    )

    names = {row[2] for row in _query_candidates(connection, 0.0, 179.99, 25.0)}

    assert names == {"East", "West"}


def test_haversine_distance_is_stable() -> None:
    assert _haversine_km(47.4979, 19.0402, 47.4979, 19.0402) == 0.0
    assert _haversine_km(47.4979, 19.0402, 46.2530, 20.1414) == pytest.approx(
        162.3, abs=1.0
    )


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("de", "Brand in der Nähe von Erdut erkannt"),
        ("en", "Fire detected near Erdut"),
        ("es", "Incendio detectado cerca de Erdut"),
        ("fr", "Incendie détecté près de Erdut"),
        ("hu-HU", "Erdut közelében észlelt tűz"),
        ("it", "Incendio rilevato vicino a Erdut"),
    ],
)
def test_location_description_is_localized(language: str, expected: str) -> None:
    assert _location_description(language, "Erdut") == expected


def test_location_description_falls_back_to_english() -> None:
    assert _location_description("nl", "Erdut") == "Fire detected near Erdut"
