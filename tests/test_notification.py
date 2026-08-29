"""Tests for localized fire-notification text."""
from __future__ import annotations

import pytest

from custom_components.terralyra.coordinator import _notification_text


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
