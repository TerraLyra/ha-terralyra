"""Build the compact offline GeoNames database shipped with the integration."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sqlite3
import zipfile


def build(source: Path, destination: Path) -> None:
    """Convert the official cities500 archive to a minimal indexed database."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE places (
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                name TEXT NOT NULL,
                country_code TEXT NOT NULL,
                admin1_code TEXT,
                population INTEGER NOT NULL
            );
            """
        )
        with zipfile.ZipFile(source) as archive:
            with archive.open("cities500.txt") as raw:
                rows = csv.reader(
                    (line.decode("utf-8") for line in raw), delimiter="\t"
                )
                connection.executemany(
                    "INSERT INTO places VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        (
                            float(row[4]),
                            float(row[5]),
                            row[1],
                            row[8],
                            row[10],
                            int(row[14] or 0),
                        )
                        for row in rows
                    ),
                )
        connection.executescript(
            """
            CREATE INDEX places_latitude_idx ON places(latitude);
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata VALUES ('source', 'GeoNames cities500');
            INSERT INTO metadata VALUES ('license', 'CC BY 4.0');
            INSERT INTO metadata VALUES ('url', 'https://www.geonames.org/');
            ANALYZE;
            VACUUM;
            """
        )
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    build(arguments.source, arguments.destination)
