"""Tests for TerraLyra sensor entity-registry maintenance."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

from custom_components.terralyra import sensor
from custom_components.terralyra.coverage import LocationSourcePlan
from custom_components.terralyra.models import ProviderStatus


def test_remove_orphaned_location_source_entities(monkeypatch) -> None:
    """Only obsolete per-location source sensors are removed."""
    registry = SimpleNamespace(async_remove=Mock())
    entries = (
        SimpleNamespace(
            unique_id="entry_location_sources_current",
            entity_id="sensor.current_sources",
        ),
        SimpleNamespace(
            unique_id="entry_location_sources_deleted",
            entity_id="sensor.deleted_sources",
        ),
        SimpleNamespace(
            unique_id="entry_product_age",
            entity_id="sensor.product_age",
        ),
        SimpleNamespace(
            unique_id="entry_location_status_deleted",
            entity_id="sensor.deleted_status",
        ),
        SimpleNamespace(
            unique_id="entry_location_sources_deleted_number",
            entity_id="number.unrelated",
        ),
    )
    monkeypatch.setattr(sensor.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(
        sensor.er,
        "async_entries_for_config_entry",
        lambda registry_arg, entry_id: entries,
    )

    sensor._remove_orphaned_location_source_entities(
        SimpleNamespace(),
        SimpleNamespace(entry_id="entry"),
        (SimpleNamespace(location_id="current"),),
    )

    assert registry.async_remove.call_args_list == [
        call("sensor.deleted_sources"),
        call("sensor.deleted_status"),
    ]


def test_remove_all_location_sources_when_no_location_is_enabled(monkeypatch) -> None:
    """Disabled or deleted locations do not leave stale source sensors behind."""
    registry = SimpleNamespace(async_remove=Mock())
    entries = (
        SimpleNamespace(
            unique_id="entry_location_sources_disabled",
            entity_id="sensor.disabled_sources",
        ),
    )
    monkeypatch.setattr(sensor.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(
        sensor.er,
        "async_entries_for_config_entry",
        lambda registry_arg, entry_id: entries,
    )

    sensor._remove_orphaned_location_source_entities(
        SimpleNamespace(), SimpleNamespace(entry_id="entry"), ()
    )

    registry.async_remove.assert_called_once_with("sensor.disabled_sources")


def test_location_operational_status_reports_equal_peer_health() -> None:
    """A location is partial when one of its equal sources is unavailable."""
    plan = LocationSourcePlan(
        "california", "California", ("goes", "nasa_firms"), ("GOES-18", "VIIRS")
    )
    health = (
        SimpleNamespace(
            provider_id="goes:GOES-18",
            label="NOAA GOES",
            satellite="GOES-18",
            location_ids=("california",),
            status=ProviderStatus.AVAILABLE,
        ),
        SimpleNamespace(
            provider_id="nasa_firms",
            label="NASA FIRMS",
            satellite="VIIRS",
            location_ids=("california",),
            status=ProviderStatus.OUTAGE,
        ),
    )

    status, sources = sensor._location_operational_status(plan, health)

    assert status == "partial"
    assert [source["status"] for source in sources] == ["available", "outage"]


def test_location_operational_status_handles_startup_and_no_coverage() -> None:
    """Startup and missing geographic coverage remain distinguishable."""
    covered = LocationSourcePlan("home", "Home", ("lsa_saf",), ("MTG",))
    uncovered = LocationSourcePlan("remote", "Remote", (), ())

    assert sensor._location_operational_status(covered, ())[0] == "initializing"
    assert sensor._location_operational_status(uncovered, ())[0] == "unavailable"


def test_location_incident_summary_counts_only_matching_incidents() -> None:
    """Per-location incident details do not leak counts from other locations."""
    matching = SimpleNamespace(
        location_matches=(SimpleNamespace(location_id="home", inside_radius=True),),
        confirmation_level=SimpleNamespace(value="multi_source"),
    )
    outside = SimpleNamespace(
        location_matches=(SimpleNamespace(location_id="home", inside_radius=False),),
        confirmation_level=SimpleNamespace(value="single_source"),
    )
    elsewhere = SimpleNamespace(
        location_matches=(SimpleNamespace(location_id="remote", inside_radius=True),),
        confirmation_level=SimpleNamespace(value="multi_source"),
    )

    result = sensor._location_incident_summary(
        "home", SimpleNamespace(tracked_fires=[matching, outside, elsewhere])
    )

    assert result == {"active_incidents": 1, "multi_source_incidents": 1}
