"""Tests for the bounded NASA FIRMS client and provider adapter."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.terralyra.products.firms import FirmsError, parse_firms_csv
from custom_components.terralyra.providers.firms import FirmsActiveFireProvider

HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
    "satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
)


def _csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def test_parse_viirs_csv_preserves_source_semantics() -> None:
    records = parse_firms_csv(
        _csv(
            "46.12345,19.54321,330.44,0.40,0.37,2026-08-28,0631,"
            "N20,VIIRS,n,2.0NRT,295.66,2.24,D"
        ),
        source="VIIRS_NOAA20_NRT",
    )

    assert len(records) == 1
    record = records[0]
    assert record.acquired == datetime(2026, 8, 28, 6, 31, tzinfo=UTC)
    assert record.satellite == "N20"
    assert record.confidence_category == "n"
    assert record.frp_mw == pytest.approx(2.24)


@pytest.mark.parametrize(
    "payload",
    [
        b"not,csv\n1,2\n",
        _csv("nan,19,1,1,1,2026-08-28,0631,N20,VIIRS,n,v,1,2,D"),
        _csv("46,181,1,1,1,2026-08-28,0631,N20,VIIRS,n,v,1,2,D"),
        _csv("46,19,1,1,1,2026-08-28,2561,N20,VIIRS,n,v,1,2,D"),
    ],
)
def test_parse_rejects_malformed_rows(payload: bytes) -> None:
    with pytest.raises(FirmsError):
        parse_firms_csv(payload, source="VIIRS_NOAA20_NRT")


class _Client:
    async def async_area(self, **kwargs):
        assert kwargs["source"] == "VIIRS_NOAA21_NRT"
        return parse_firms_csv(
            _csv(
                "46.12345,19.54321,330.44,0.40,0.37,2026-08-28,1234,"
                "N21,VIIRS,h,2.0NRT,295.66,8.5,D"
            ),
            source=kwargs["source"],
        )


@pytest.mark.asyncio
async def test_provider_normalizes_without_fabricating_probability() -> None:
    snapshot = await FirmsActiveFireProvider(
        _Client(),
        source="VIIRS_NOAA21_NRT",
        west=14,
        south=43,
        east=24,
        north=50,
    ).async_fetch_latest()

    assert snapshot.provider == "nasa_firms"
    assert snapshot.source_url == "https://firms.modaps.eosdis.nasa.gov/"
    assert len(snapshot.detections) == 1
    detection = snapshot.detections[0]
    assert detection.provider == "nasa_firms"
    assert detection.confidence is None
    assert detection.classification == "h"
    assert detection.source_resolution_km == pytest.approx(0.375)
    assert "N21" in (detection.source_detection_id or "")
