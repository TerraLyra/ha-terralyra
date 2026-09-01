"""Tests for TerraLyra sensor entity-registry maintenance."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.terralyra import sensor


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

    registry.async_remove.assert_called_once_with("sensor.deleted_sources")


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
