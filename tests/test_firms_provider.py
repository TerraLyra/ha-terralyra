"""Tests for the bounded NASA FIRMS client and provider adapter."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.terralyra.products.firms import FirmsError, parse_firms_csv
from custom_components.terralyra.providers.firms import (
    FirmsActiveFireProvider,
    FirmsMultiAreaProvider,
    FirmsMultiSatelliteProvider,
    merge_monitoring_bounds,
    monitoring_bounds,
)
from custom_components.terralyra.providers.base import ProviderUnavailableError

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


class _MultiClient:
    def __init__(self) -> None:
        self.calls = 0

    async def async_area(self, **kwargs):
        self.calls += 1
        source = kwargs["source"]
        satellite = "N20" if source == "VIIRS_NOAA20_NRT" else "N21"
        minute = "1234" if satellite == "N20" else "1235"
        return parse_firms_csv(
            _csv(
                f"46.12345,19.54321,330.44,0.40,0.37,2026-08-28,{minute},"
                f"{satellite},VIIRS,h,2.0NRT,295.66,8.5,D"
            ),
            source=source,
        )


@pytest.mark.asyncio
async def test_multi_satellite_provider_combines_noaa20_and_noaa21() -> None:
    client = _MultiClient()
    provider = FirmsMultiSatelliteProvider(
        client, west=14, south=43, east=24, north=50
    )
    snapshot = await provider.async_fetch_latest()
    cached = await provider.async_fetch_latest()

    assert snapshot.provider == "nasa_firms"
    assert snapshot.satellite == "NOAA-20/NOAA-21 VIIRS"
    assert len(snapshot.detections) == 2
    assert {item.satellite for item in snapshot.detections} == {"N20", "N21"}
    assert cached is snapshot
    assert client.calls == 2


def test_monitoring_bounds_are_bounded_and_contain_home() -> None:
    west, south, east, north = monitoring_bounds(47.5, 19.0, 500)

    assert west < 19.0 < east
    assert south < 47.5 < north
    assert east - west <= 20
    assert north - south <= 20


def test_overlapping_monitoring_bounds_are_merged() -> None:
    first = monitoring_bounds(47.5, 19.0, 50)
    second = monitoring_bounds(47.6, 19.1, 50)

    planned = merge_monitoring_bounds((first, second))

    assert len(planned) == 1
    assert planned[0] == (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def test_distant_monitoring_bounds_remain_separate() -> None:
    europe = monitoring_bounds(47.5, 19.0, 50)
    america = monitoring_bounds(38.5, -121.6, 50)

    assert merge_monitoring_bounds((europe, america)) == (america, europe)


def test_monitoring_bound_plan_rejects_unbounded_input() -> None:
    with pytest.raises(ValueError):
        merge_monitoring_bounds(tuple((index, 0, index + 0.5, 1) for index in range(11)))
    with pytest.raises(ValueError):
        merge_monitoring_bounds(((0, 0, 21, 1),))


@pytest.mark.asyncio
async def test_multi_area_provider_deduplicates_overlapping_results() -> None:
    class DuplicateClient:
        async def async_area(self, **kwargs):
            return parse_firms_csv(
                _csv(
                    "46.12345,19.54321,330.44,0.40,0.37,2026-08-28,1234,"
                    "N20,VIIRS,h,2.0NRT,295.66,8.5,D"
                ),
                source=kwargs["source"],
            )

    provider = FirmsMultiAreaProvider(
        DuplicateClient(),
        (
            monitoring_bounds(47.5, 19.0, 10),
            monitoring_bounds(40.0, -74.0, 10),
        ),
    )

    snapshot = await provider.async_fetch_latest()

    assert len(snapshot.detections) == 2
    assert snapshot.filename == "firms-viirs-2-areas.csv"


@pytest.mark.asyncio
async def test_multi_area_provider_survives_partial_area_failure() -> None:
    class _AreaClient:
        async def async_area(self, **kwargs):
            if kwargs["west"] > 0:
                satellite = "N20" if kwargs["source"] == "VIIRS_NOAA20_NRT" else "N21"
                return parse_firms_csv(
                    _csv(
                        f"46.12345,19.54321,330.44,0.40,0.37,2026-08-28,1234,"
                        f"{satellite},VIIRS,h,2.0NRT,295.66,8.5,D"
                    ),
                    source=kwargs["source"],
                )
            raise FirmsError("service unavailable for this area")

    provider = FirmsMultiAreaProvider(
        _AreaClient(),
        (
            monitoring_bounds(47.5, 19.0, 10),
            monitoring_bounds(40.0, -74.0, 10),
        ),
    )

    snapshot = await provider.async_fetch_latest()

    assert len(snapshot.detections) == 2
    assert snapshot.filename == "firms-viirs-2-areas.csv"


@pytest.mark.asyncio
async def test_multi_area_provider_all_areas_fail_with_unavailable_error() -> None:
    class _FailingClient:
        async def async_area(self, **kwargs):
            raise FirmsError("service unavailable")

    provider = FirmsMultiAreaProvider(
        _FailingClient(),
        (
            monitoring_bounds(47.5, 19.0, 10),
            monitoring_bounds(40.0, -74.0, 10),
        ),
    )

    with pytest.raises(ProviderUnavailableError):
        await provider.async_fetch_latest()


@pytest.mark.parametrize("radius", [0, -1, 501, float("nan")])
def test_monitoring_bounds_reject_unsafe_radius(radius: float) -> None:
    with pytest.raises(ValueError):
        monitoring_bounds(47.5, 19.0, radius)
