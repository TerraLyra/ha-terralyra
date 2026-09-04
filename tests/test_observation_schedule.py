"""Tests for qualified provider update and VIIRS overpass estimates."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.terralyra.coverage import LocationSourcePlan
from custom_components.terralyra.models import ProviderStatus
from custom_components.terralyra.observation_schedule import (
    location_update_estimates,
    next_usable_update,
    next_viirs_overpass_window,
)

NOW = datetime(2026, 9, 4, 10, 2, tzinfo=UTC)


def _health(
    provider_id: str,
    satellite: str,
    *,
    status: ProviderStatus = ProviderStatus.AVAILABLE,
    received: datetime | None = NOW,
) -> SimpleNamespace:
    return SimpleNamespace(
        provider_id=provider_id,
        label=provider_id,
        satellite=satellite,
        location_ids=("home",),
        status=status,
        received_timestamp=received,
    )


def test_geostationary_update_uses_last_received_product_cadence() -> None:
    plan = LocationSourcePlan("home", "Home", ("noaa_goes",), ("G19",))
    estimates = location_update_estimates(
        plan,
        SimpleNamespace(longitude=-75.0),
        (_health("noaa_goes:G19", "G19"),),
        now=NOW + timedelta(minutes=2),
    )

    assert estimates[0].expected_at == NOW + timedelta(minutes=10)
    assert estimates[0].estimate_type == "product_refresh_cadence"
    assert next_usable_update(estimates) == estimates[0]


def test_refresh_estimate_advances_past_missed_intervals() -> None:
    plan = LocationSourcePlan(
        "home", "Home", ("eumetsat_lsa_saf",), ("MTG",)
    )
    estimates = location_update_estimates(
        plan,
        SimpleNamespace(longitude=20.0),
        (_health("eumetsat_lsa_saf", "MTG"),),
        now=NOW + timedelta(minutes=25),
    )

    assert estimates[0].expected_at == NOW + timedelta(minutes=30)


def test_unavailable_source_is_not_selected_as_next_update() -> None:
    plan = LocationSourcePlan(
        "home",
        "Home",
        ("noaa_goes", "nasa_firms"),
        ("G19", "NOAA-20/NOAA-21 VIIRS"),
    )
    estimates = location_update_estimates(
        plan,
        SimpleNamespace(longitude=-75.0),
        (
            _health("noaa_goes:G19", "G19", status=ProviderStatus.OUTAGE),
            _health("nasa_firms", "NOAA-20/NOAA-21 VIIRS"),
        ),
        now=NOW + timedelta(minutes=2),
    )

    assert estimates[1].estimate_type == "api_refresh_with_nominal_overpass_window"
    assert next_usable_update(estimates) == estimates[1]


def test_viirs_window_is_broad_and_longitude_adjusted() -> None:
    start, end = next_viirs_overpass_window(30.0, now=datetime(2026, 9, 4, 0, tzinfo=UTC))

    assert start == datetime(2026, 9, 3, 22, 45, tzinfo=UTC)
    assert end == datetime(2026, 9, 4, 0, 15, tzinfo=UTC)
    assert end - start == timedelta(minutes=90)


def test_viirs_window_rejects_invalid_longitude() -> None:
    with pytest.raises(ValueError, match="out of range"):
        next_viirs_overpass_window(181.0, now=NOW)
