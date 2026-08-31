"""Tests for localized fire-notification text."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.terralyra.coordinator import (
    _notification_location_context,
    _notification_text,
)
from custom_components.terralyra.location_matching import match_incident_to_locations
from custom_components.terralyra.models import FireCluster
from custom_components.terralyra.monitoring import MonitoredLocation


def test_hungarian_notification_prefers_settlement() -> None:
    title, message = _notification_text("hu", "Erdut", 117.68, 0.83)

    assert title == "🔥 Tűzészlelés riasztás"
    assert message == (
        "Tűz észlelve Erdut közelében, 117,7 km-re az otthonodtól. "
        "Megbízhatóság: 83%."
    )


def test_english_notification_prefers_settlement() -> None:
    title, message = _notification_text("en", "Erdut", 117.68, 0.83)

    assert title == "🔥 Fire detection alert"
    assert message == (
        "Fire detected near Erdut, 117.7 km from Home. Confidence: 83%."
    )


def test_notification_falls_back_without_settlement() -> None:
    _, message = _notification_text("hu-HU", None, 12.34, 0.55)

    assert message == (
        "Tűz észlelve, 12,3 km-re az otthonodtól. Megbízhatóság: 55%."
    )


@pytest.mark.parametrize(
    ("language", "expected_title", "message_fragment"),
    [
        ("de", "🔥 Branddetektionswarnung", "in der Nähe von Erdut"),
        ("es", "🔥 Alerta de detección de incendio", "cerca de Erdut"),
        ("fr", "🔥 Alerte de détection d’incendie", "près de Erdut"),
        ("it", "🔥 Avviso di rilevamento incendio", "vicino a Erdut"),
    ],
)
def test_notification_supports_all_translated_languages(
    language: str, expected_title: str, message_fragment: str
) -> None:
    title, message = _notification_text(language, "Erdut", 117.68, 0.83)

    assert title == expected_title
    assert message_fragment in message
    assert "117,7" in message


def test_unsupported_notification_language_falls_back_to_english() -> None:
    assert _notification_text("nl", "Erdut", 10, 0.8) == _notification_text(
        "en", "Erdut", 10, 0.8
    )


def test_notification_names_custom_monitoring_center() -> None:
    """Custom centers replace Home wording without exposing coordinates."""
    title, message = _notification_text(
        "en", "Albany", 24.68, 0.91, monitoring_center="New York"
    )

    assert title == "🔥 Fire detection alert"
    assert message == (
        "Fire detected near Albany, 24.7 km from New York. "
        "Confidence: 91%."
    )


def test_notification_uses_nearest_affected_location_and_lists_others() -> None:
    locations = (
        MonitoredLocation(
            id="home",
            name="Home",
            latitude=47.0,
            longitude=19.0,
            radius_km=100,
            enabled=True,
            source="manual",
        ),
        MonitoredLocation(
            id="cabin",
            name="Cabin",
            latitude=47.0,
            longitude=19.2,
            radius_km=100,
            enabled=True,
            source="manual",
        ),
    )
    matches = match_incident_to_locations(
        "incident-1", 47.0, 19.19, locations
    )
    cluster = FireCluster(
        latitude=47.0,
        longitude=19.19,
        distance_km=14.4,
        confidence=0.91,
        frp_mw=12.0,
        acquired=datetime(2026, 8, 31, tzinfo=UTC),
        pixel_count=1,
        track_id="incident-1",
        location_matches=matches,
    )

    center, distance, affected = _notification_location_context(cluster, "Home")
    title, message = _notification_text(
        "en", "Village", distance, cluster.confidence, center, affected
    )

    assert center == "Cabin"
    assert distance == pytest.approx(matches[0].distance_km)
    assert affected == ("Cabin", "Home")
    assert title == "🔥 Fire detection alert"
    assert "km from Cabin" in message
    assert message.endswith("Also within the monitoring radius of: Home.")


def test_notification_location_context_falls_back_without_matches() -> None:
    cluster = FireCluster(
        latitude=47.0,
        longitude=19.0,
        distance_km=12.34,
        confidence=0.8,
        frp_mw=5.0,
        acquired=datetime(2026, 8, 31, tzinfo=UTC),
        pixel_count=1,
        track_id="incident-2",
    )

    assert _notification_location_context(cluster, "Home") == (
        "Home",
        12.34,
        (),
    )
