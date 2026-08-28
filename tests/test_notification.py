"""Tests for localized fire-notification text."""
from __future__ import annotations

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
