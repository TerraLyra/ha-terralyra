"""Tests for FRMv3 response validation and sampling."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
import json

from PIL import Image
import pytest

from custom_components.terralyra.geocoding import MapPlace
from custom_components.terralyra.map_render import COUNTRY_BORDERS, annotate_fire_risk_map
from custom_components.terralyra.fire_risk_coordinator import (
    FIRE_RISK_RETRY_MAX,
    _retry_interval,
    _staggered_interval,
)
from custom_components.terralyra.products.fire_risk import (
    FireRiskClient,
    FireRiskError,
    FireRiskHTTPError,
    _sample_points,
    analyze_risk_map,
    map_bounds,
    parse_feature_info,
)


def _payload(value: str) -> bytes:
    return json.dumps([{"data": {"2026-08-26T12:00:00Z": value}}]).encode()


def _payload_for(value_date: date, value: str) -> bytes:
    return json.dumps([{"data": {f"{value_date.isoformat()}T12:00:00Z": value}}]).encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("low (1)", 1), ("moderate (2)", 2), ("high (3)", 3),
     ("very high (4)", 4), ("extreme (5)", 5), ("nodata", None)],
)
def test_parse_feature_info(value: str, expected: int | None) -> None:
    assert parse_feature_info(_payload(value), date(2026, 8, 26)) == expected


@pytest.mark.parametrize("payload", [b"not json", b"[]", _payload("unknown (9)")])
def test_parse_feature_info_rejects_invalid_data(payload: bytes) -> None:
    with pytest.raises(FireRiskError):
        parse_feature_info(payload, date(2026, 8, 26))


def test_sampling_is_bounded() -> None:
    points = _sample_points(47.5, 19.0, 500)

    assert len(points) == 9
    assert points[0] == (47.5, 19.0)
    assert all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in points)


def test_map_bounds_are_clamped_to_europe() -> None:
    west, south, east, north = map_bounds(47.5, 19.0, 500)

    assert -9.975 <= west < east <= 45.525
    assert 34.475 <= south < north <= 69.975


def test_map_bounds_reject_location_outside_coverage() -> None:
    with pytest.raises(FireRiskError):
        map_bounds(-33.9, 151.2, 25)


@pytest.mark.parametrize("radius", [0, 501, float("nan"), float("inf")])
def test_map_bounds_reject_invalid_radius(radius: float) -> None:
    with pytest.raises(FireRiskError):
        map_bounds(47.5, 19.0, radius)


@pytest.mark.asyncio
async def test_forecast_uses_local_value_as_safe_area_fallback() -> None:
    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            pass

        async def _async_point(self, latitude, longitude, valid_date):
            return 1 if (latitude, longitude) == (47.5, 19.0) else 5

    forecast = await FakeClient().async_forecast(47.5, 19.0, 100)

    assert forecast.days[0].risk == "low"
    assert forecast.latitude == 47.5
    assert forecast.longitude == 19.0
    assert forecast.area_risk == "low"
    assert forecast.area_level == 1
    assert forecast.radius_km == 100


@pytest.mark.asyncio
async def test_local_forecast_remains_unknown_when_home_area_is_nodata() -> None:
    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            pass

        async def _async_point(self, latitude, longitude, valid_date):
            if abs(latitude - 47.5) < 0.2 and abs(longitude - 19.0) < 0.2:
                return None
            return 3

    forecast = await FakeClient().async_forecast(47.5, 19.0, 100)

    assert forecast.days[0].risk == "unknown"
    assert forecast.area_risk == "unknown"


@pytest.mark.asyncio
async def test_forecast_treats_future_date_404_as_missing_not_failure() -> None:
    today = datetime.now(UTC).date()

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            pass

        async def _async_get(self, params, limit):
            valid_date = date.fromisoformat(params["TIME"].replace("T12:00:00Z", ""))
            if valid_date > today:
                raise FireRiskHTTPError("FRMv3 service returned an error", 404)
            return _payload_for(valid_date, "moderate (2)")

    forecast = await FakeClient().async_forecast(47.5, 19.0, 100)

    assert forecast.days[0].level == 2
    assert forecast.days[1].level is None
    assert forecast.days[0].risk == "moderate"
    assert forecast.area_level == 2


@pytest.mark.asyncio
async def test_forecast_fails_when_today_404() -> None:
    today = datetime.now(UTC).date()

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            pass

        async def _async_get(self, params, limit):
            valid_date = date.fromisoformat(params["TIME"].replace("T12:00:00Z", ""))
            if valid_date == today:
                raise FireRiskHTTPError("FRMv3 service returned an error", 404)
            return _payload_for(valid_date, "moderate (2)")

    with pytest.raises(FireRiskError):
        await FakeClient().async_forecast(47.5, 19.0, 100)


def test_map_analysis_finds_maximum_inside_circle() -> None:
    source = BytesIO()
    image = Image.new("RGB", (100, 100), (1, 230, 255))
    image.putpixel((50, 50), (255, 245, 0))
    image.putpixel((0, 0), (255, 3, 0))
    image.save(source, format="PNG")

    level, latitude, longitude = analyze_risk_map(
        source.getvalue(), (14.0, 44.0, 24.0, 51.0), 47.5, 19.0, 100
    )

    assert level == 3
    assert latitude == pytest.approx(47.46, abs=0.1)
    assert longitude == pytest.approx(19.05, abs=0.1)


@pytest.mark.parametrize("radius", [0, 501, float("nan"), float("inf")])
def test_map_analysis_rejects_invalid_radius(radius: float) -> None:
    with pytest.raises(FireRiskError):
        analyze_risk_map(b"not-read", (14.0, 44.0, 24.0, 51.0), 47.5, 19.0, radius)


def test_staggered_interval_is_deterministic_and_bounded() -> None:
    first = _staggered_interval("entry-one")
    second = _staggered_interval("entry-one")

    assert first == second
    assert 11.5 * 3600 <= first.total_seconds() <= 12.5 * 3600


def test_fire_risk_retry_interval_backs_off_and_is_bounded() -> None:
    assert _retry_interval(1) == timedelta(minutes=15)
    assert _retry_interval(2) == timedelta(minutes=30)
    assert _retry_interval(3) == FIRE_RISK_RETRY_MAX
    assert _retry_interval(20) == FIRE_RISK_RETRY_MAX


def test_map_annotation_adds_context_and_keeps_png() -> None:
    source = BytesIO()
    Image.new("RGB", (768, 512), "#10cfe0").save(source, format="PNG")

    result = annotate_fire_risk_map(
        source.getvalue(),
        (14.0, 44.0, 24.0, 51.0),
        47.5,
        19.0,
        date(2026, 8, 26),
        (MapPlace(47.4979, 19.0402, "Budapest"),),
        "hu",
    )

    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(result)) as image:
        assert image.size == (768, 512)
        assert image.getpixel((20, 20)) != (16, 207, 224)


def test_bundled_country_borders_are_bounded() -> None:
    assert 50 < len(COUNTRY_BORDERS) < 500
    assert all(2 <= len(line) <= 500 for line in COUNTRY_BORDERS)
    assert all(
        -180 <= longitude <= 180 and -90 <= latitude <= 90
        for line in COUNTRY_BORDERS
        for longitude, latitude in line
    )


def test_map_annotation_rejects_unexpected_dimensions() -> None:
    source = BytesIO()
    Image.new("RGB", (1025, 1), "white").save(source, format="PNG")

    with pytest.raises(FireRiskError):
        annotate_fire_risk_map(
            source.getvalue(),
            (14.0, 44.0, 24.0, 51.0),
            47.5,
            19.0,
            date(2026, 8, 26),
            (),
            "en",
        )


def test_map_annotation_rejects_invalid_bounds() -> None:
    with pytest.raises(FireRiskError):
        annotate_fire_risk_map(
            b"not-read",
            (24.0, 44.0, 14.0, 51.0),
            47.5,
            19.0,
            date(2026, 8, 26),
            (),
            "en",
        )
