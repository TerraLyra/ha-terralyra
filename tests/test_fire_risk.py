"""Tests for FRMv3 response validation and sampling."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from unittest.mock import Mock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from PIL import Image

from custom_components.terralyra.fire_risk_coordinator import (
    FIRE_RISK_RETRY_MAX,
    FireRiskCoordinator,
    _retry_interval,
    _staggered_interval,
)
from custom_components.terralyra.geocoding import MapPlace
from custom_components.terralyra.map_render import (
    COUNTRY_BORDERS,
    annotate_fire_risk_map,
)
from custom_components.terralyra.products.fire_risk import (
    FireRiskAuthenticationError,
    FireRiskClient,
    FireRiskDay,
    FireRiskError,
    FireRiskForecast,
    FireRiskHTTPError,
    FireRiskRateLimitError,
    FireRiskServiceUnavailableError,
    FireRiskTemporaryServiceError,
    _parse_retry_after,
    _safe_error_detail,
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


@pytest.mark.asyncio
async def test_async_get_includes_http_error_body() -> None:
    class DummyBody:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def iter_chunked(self, _chunk_size: int):
            yield self._payload

    class DummyResponse:
        def __init__(self, status: int, text: str) -> None:
            self.status = status
            self.content = DummyBody(text.encode())
            self.content_length = len(text)
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
            return None

    class DummySession:
        def __init__(self, response: DummyResponse) -> None:
            self._response = response

        def get(self, *_args, **_kwargs) -> DummyResponse:
            return self._response

    client = FireRiskClient(DummySession(DummyResponse(503, "maintenance mode")))
    with pytest.raises(FireRiskHTTPError) as err:
        await client._async_get({"x": "y"}, 10)

    message = str(err.value)
    assert "503" in message
    assert "maintenance mode" in message


def test_error_detail_is_bounded_and_single_line() -> None:
    detail = _safe_error_detail(b"  maintenance\n\tmode  " + b"x" * 2048)

    assert detail is not None
    assert detail.startswith("maintenance mode ")
    assert "\n" not in detail
    assert len(detail) == 1024


@pytest.mark.asyncio
async def test_async_get_distinguishes_rate_limit() -> None:
    class DummyBody:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def iter_chunked(self, _chunk_size: int):
            yield self._payload

    class DummyResponse:
        def __init__(self, status: int, text: str) -> None:
            self.status = status
            self.content = DummyBody(text.encode())
            self.content_length = len(text)
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
            return None

    class DummySession:
        def __init__(self, response: DummyResponse) -> None:
            self._response = response

        def get(self, *_args, **_kwargs) -> DummyResponse:
            return self._response

    client = FireRiskClient(DummySession(DummyResponse(429, "too many requests")))

    with pytest.raises(FireRiskRateLimitError):
        await client._async_get({"x": "y"}, 10)


@pytest.mark.asyncio
async def test_async_get_uses_retry_after_for_temporary_service_errors() -> None:
    class DummyBody:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def iter_chunked(self, _chunk_size: int):
            yield self._payload

    class DummyResponse:
        def __init__(self, status: int, text: str) -> None:
            self.status = status
            self.content = DummyBody(text.encode())
            self.content_length = len(text)
            self.headers = {"Retry-After": "45"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
            return None

    class DummySession:
        def __init__(self, response: DummyResponse) -> None:
            self._response = response

        def get(self, *_args, **_kwargs) -> DummyResponse:
            return self._response

    client = FireRiskClient(DummySession(DummyResponse(500, "error")))

    with pytest.raises(FireRiskTemporaryServiceError) as err:
        await client._async_get({"x": "y"}, 10)

    assert isinstance(err.value, FireRiskTemporaryServiceError)
    assert err.value.retry_after == timedelta(seconds=45)


def test_parse_retry_after_none_and_empty() -> None:
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None


def test_parse_retry_after_numeric_delay() -> None:
    assert _parse_retry_after("60") == timedelta(seconds=60)
    assert _parse_retry_after("0") == timedelta(seconds=0)
    assert _parse_retry_after(" -10") is None
    assert _parse_retry_after("9" * 1000) is None


def test_parse_retry_after_http_date_delay() -> None:
    retry_at = datetime.now(UTC) + timedelta(minutes=2)
    header = retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = _parse_retry_after(header)

    assert parsed is not None
    assert timedelta(minutes=1) < parsed <= timedelta(minutes=3)


@pytest.mark.asyncio
async def test_async_get_maps_network_errors_to_service_unavailable() -> None:
    class DummySession:
        def get(self, *_args, **_kwargs):
            raise TimeoutError("timed out")

    client = FireRiskClient(DummySession())

    with pytest.raises(FireRiskServiceUnavailableError):
        await client._async_get({"x": "y"}, 10)


@pytest.mark.asyncio
async def test_async_map_returns_last_cached_map_on_temporary_fetch_error() -> None:
    source = BytesIO()
    Image.new("RGB", (768, 512), "#10cfe0").save(source, format="PNG")
    cached_map = source.getvalue()
    bbox = (14.0, 44.0, 24.0, 51.0)

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            super().__init__(session=Mock())
            self.calls = 0

        async def _async_get(self, params, limit):
            self.calls += 1
            if self.calls == 1:
                return cached_map
            raise FireRiskTemporaryServiceError("FRMv3 temporary outage", 500)

    client = FakeClient()
    today = datetime.now(UTC).date()

    first = await client.async_map(bbox, today)
    client._map_cache_time = datetime.now(UTC) - timedelta(hours=2)
    second = await client.async_map(bbox, today)

    assert first == cached_map
    assert second == cached_map
    assert client.calls == 2


@pytest.mark.asyncio
async def test_async_map_does_not_fallback_for_authentication_error() -> None:
    bbox = (14.0, 44.0, 24.0, 51.0)

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            super().__init__(session=Mock())
            self.calls = 0

        async def _async_get(self, params, limit):
            self.calls += 1
            if self.calls == 1:
                source = BytesIO()
                Image.new("RGB", (768, 512), "#10cfe0").save(source, format="PNG")
                return source.getvalue()
            raise FireRiskAuthenticationError("FRMv3 authentication error", 403)

    client = FakeClient()
    today = datetime.now(UTC).date()

    await client.async_map(bbox, today)
    client._map_cache_time = datetime.now(UTC) - timedelta(hours=2)

    with pytest.raises(FireRiskAuthenticationError):
        await client.async_map(bbox, today)


@pytest.mark.asyncio
async def test_async_map_does_not_reuse_cache_for_another_date() -> None:
    source = BytesIO()
    Image.new("RGB", (768, 512), "#10cfe0").save(source, format="PNG")
    cached_map = source.getvalue()
    bbox = (14.0, 44.0, 24.0, 51.0)

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            super().__init__(session=Mock())
            self.calls = 0

        async def _async_get(self, params, limit):
            self.calls += 1
            if self.calls == 1:
                return cached_map
            raise FireRiskTemporaryServiceError("FRMv3 temporary outage", 500)

    client = FakeClient()
    today = datetime.now(UTC).date()

    await client.async_map(bbox, today)

    with pytest.raises(FireRiskTemporaryServiceError):
        await client.async_map(bbox, today + timedelta(days=1))


@pytest.mark.asyncio
async def test_async_map_does_not_reuse_expired_stale_cache() -> None:
    source = BytesIO()
    Image.new("RGB", (768, 512), "#10cfe0").save(source, format="PNG")
    cached_map = source.getvalue()
    bbox = (14.0, 44.0, 24.0, 51.0)

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            super().__init__(session=Mock())
            self.calls = 0

        async def _async_get(self, params, limit):
            self.calls += 1
            if self.calls == 1:
                return cached_map
            raise FireRiskTemporaryServiceError("FRMv3 temporary outage", 500)

    client = FakeClient()
    today = datetime.now(UTC).date()

    await client.async_map(bbox, today)
    client._map_cache_time = datetime.now(UTC) - timedelta(hours=25)

    with pytest.raises(FireRiskTemporaryServiceError):
        await client.async_map(bbox, today)


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


def test_fire_risk_retry_interval_uses_retry_after_hint() -> None:
    assert _retry_interval(
        4, error=FireRiskRateLimitError("x", 429, timedelta(minutes=45))
    ) == timedelta(minutes=45)
    assert _retry_interval(
        4, error=FireRiskRateLimitError("x", 429, timedelta(minutes=2))
    ) == timedelta(minutes=15)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "map_error",
    [
        FireRiskError("map temporarily unavailable"),
        FireRiskError("map image analysis failed"),
    ],
)
async def test_fire_risk_coordinator_keeps_forecast_when_map_layer_fails(
    hass, map_error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = (
        FireRiskDay(date(2026, 8, 26), 2),
        FireRiskDay(date(2026, 8, 27), None),
    )
    forecast = FireRiskForecast(
        latitude=47.5,
        longitude=19.0,
        generated_at=datetime.now(UTC),
        days=days,
        area_level=2,
        area_latitude=47.5,
        area_longitude=19.0,
        radius_km=100,
    )

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            pass

        async def async_forecast(self, latitude, longitude, radius):
            return forecast

        async def async_map(self, bbox, valid_date):
            raise map_error

    calls = Mock()
    hass.config.latitude = 47.5
    hass.config.longitude = 19.0
    entry = Mock(entry_id="entry-1", options={"fire_risk_radius_km": 100})
    coordinator = FireRiskCoordinator(hass, entry, FakeClient())

    monkeypatch.setattr(
        "custom_components.terralyra.fire_risk_coordinator.async_set_fire_risk_outage_issue",
        lambda *args, **kwargs: calls(*args, **kwargs),
    )
    result = await coordinator._async_update_data()

    assert result == forecast
    calls.assert_called_once_with(
        hass,
        entry,
        consecutive_failures=0,
        reason=None,
    )


@pytest.mark.asyncio
async def test_fire_risk_coordinator_retries_with_backoff_on_forecast_failure_then_recovers(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = (
        FireRiskDay(date(2026, 8, 26), 2),
    )
    forecast = FireRiskForecast(
        latitude=47.5,
        longitude=19.0,
        generated_at=datetime.now(UTC),
        days=days,
        area_level=2,
        area_latitude=47.5,
        area_longitude=19.0,
        radius_km=100,
    )

    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            self.calls = 0
            self.map_calls = 0

        async def async_forecast(self, latitude, longitude, radius):
            self.calls += 1
            if self.calls == 1:
                raise FireRiskError("temporary outage")
            return forecast

        async def async_map(self, bbox, valid_date):
            self.map_calls += 1
            return b"map"

    calls = Mock()
    hass.config.latitude = 47.5
    hass.config.longitude = 19.0
    entry = Mock(entry_id="entry-1", options={"fire_risk_radius_km": 100})
    client = FakeClient()
    coordinator = FireRiskCoordinator(hass, entry, client)

    monkeypatch.setattr(
        "custom_components.terralyra.fire_risk_coordinator.async_set_fire_risk_outage_issue",
        lambda *args, **kwargs: calls(*args, **kwargs),
    )
    monkeypatch.setattr(
        "custom_components.terralyra.fire_risk_coordinator.analyze_risk_map",
        lambda *args: (2, 47.5, 19.0),
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert client.map_calls == 0
    assert coordinator.update_interval == timedelta(minutes=15)
    assert calls.call_args.kwargs == {
        "consecutive_failures": 1,
        "reason": "temporary outage",
    }

    result = await coordinator._async_update_data()

    assert result == forecast
    assert client.map_calls == 1
    assert calls.call_args.kwargs == {"consecutive_failures": 0, "reason": None}
    assert coordinator.update_interval == _staggered_interval("entry-1")


@pytest.mark.asyncio
async def test_fire_risk_coordinator_uses_server_retry_after_when_available(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeClient(FireRiskClient):
        def __init__(self) -> None:
            self.calls = 0

        async def async_forecast(self, latitude, longitude, radius):
            raise FireRiskRateLimitError(
                "too many requests", 429, timedelta(minutes=40)
            )

        async def async_map(self, bbox, valid_date):
            raise AssertionError("map should not run")

    calls = Mock()
    hass.config.latitude = 47.5
    hass.config.longitude = 19.0
    entry = Mock(entry_id="entry-1", options={"fire_risk_radius_km": 100})
    coordinator = FireRiskCoordinator(hass, entry, FakeClient())

    monkeypatch.setattr(
        "custom_components.terralyra.fire_risk_coordinator.async_set_fire_risk_outage_issue",
        lambda *args, **kwargs: calls(*args, **kwargs),
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.update_interval == timedelta(minutes=40)
    assert calls.call_args.kwargs == {
        "consecutive_failures": 1,
        "reason": "too many requests",
    }


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
