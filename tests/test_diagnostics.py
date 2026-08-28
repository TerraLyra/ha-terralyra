"""Tests for privacy-safe diagnostics."""
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from custom_components.terralyra.const import (
    CONF_FIRMS_MAP_KEY,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from custom_components.terralyra.diagnostics import async_get_config_entry_diagnostics
from custom_components.terralyra.models import ProviderStatus
from custom_components.terralyra.products.fire_risk import FireRiskDay, FireRiskForecast


@pytest.mark.asyncio
async def test_diagnostics_are_bounded_and_redacted(hass) -> None:
    """Diagnostics expose health/counts but no secrets or precise locations."""
    account_value = "test-account"
    credential_value = "-".join(("test", "credential"))
    firms_key_value = "F" * 32
    product_time = datetime(2026, 8, 27, 16, 20, tzinfo=UTC)
    generated_at = datetime(2026, 8, 27, 16, 21, tzinfo=UTC)
    active_data = SimpleNamespace(
        product_time=product_time,
        active_clusters=[object(), object()],
        tracked_fires=[object(), object(), object()],
        raw_pixels_in_radius=4,
        source_url="https://example.invalid/private-product",
    )
    risk_data = FireRiskForecast(
        latitude=46.123456,
        longitude=18.654321,
        generated_at=generated_at,
        days=(FireRiskDay(date(2026, 8, 27), 5),),
        area_level=4,
        area_latitude=46.2,
        area_longitude=18.7,
        radius_km=100,
    )
    entry = SimpleNamespace(
        data={
            CONF_USERNAME: account_value,
            CONF_PASSWORD: credential_value,
            CONF_FIRMS_MAP_KEY: firms_key_value,
        },
        options={"radius_km": 25.0},
        runtime_data=SimpleNamespace(
            coordinator=SimpleNamespace(
                data=active_data,
                last_update_success=True,
                provider_status=ProviderStatus.AVAILABLE,
                provider_name="eumetsat_lsa_saf",
                satellite="mtg",
                provider_product="MTFRPPixel",
                product_timestamp=product_time,
                received_timestamp=generated_at,
            ),
            fire_risk_coordinator=SimpleNamespace(
                data=risk_data, last_update_success=True
            ),
            place_name_resolver=object(),
        ),
    )

    result = await async_get_config_entry_diagnostics(hass, entry)
    serialized = repr(result)

    assert result["active_fire"]["active_cluster_count"] == 2
    assert result["active_fire"]["tracked_fire_count"] == 3
    assert result["active_fire"]["incident_lifecycle_counts"] == {
        "new": 0,
        "continuing": 0,
        "inactive": 0,
    }
    assert result["active_fire"]["provider_status"] == "available"
    assert result["fire_risk"]["near_home_risk"] == "extreme"
    assert result["fire_risk"]["area_risk"] == "very_high"
    assert account_value not in serialized
    assert credential_value not in serialized
    assert firms_key_value not in serialized
    assert "46.123456" not in serialized
    assert "18.654321" not in serialized
    assert "example.invalid" not in serialized


@pytest.mark.asyncio
async def test_diagnostics_handle_coordinators_without_data(hass) -> None:
    """Diagnostics remain downloadable before optional forecast data arrives."""
    credential_value = "-".join(("test", "credential"))
    entry = SimpleNamespace(
        data={CONF_USERNAME: "test-account", CONF_PASSWORD: credential_value},
        options={},
        runtime_data=SimpleNamespace(
            coordinator=SimpleNamespace(
                data=None,
                last_update_success=False,
                provider_status=ProviderStatus.INITIALIZING,
                provider_name=None,
                satellite=None,
                provider_product=None,
                product_timestamp=None,
                received_timestamp=None,
            ),
            fire_risk_coordinator=SimpleNamespace(
                data=None, last_update_success=False
            ),
            place_name_resolver=None,
        ),
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["active_fire"]["product_time"] is None
    assert result["fire_risk"]["near_home_risk"] is None
    assert result["place_names_enabled"] is False
