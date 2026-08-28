"""Validate bundled translations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRANSLATIONS = Path("custom_components/terralyra/translations")
SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "hu", "it"}


def _leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(value, dict):
        return {prefix}
    return {
        path
        for key, child in value.items()
        for path in _leaf_paths(child, (*prefix, key))
    }


def test_all_supported_translations_match_english_schema() -> None:
    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    expected_paths = _leaf_paths(english)

    assert {path.stem for path in TRANSLATIONS.glob("*.json")} == SUPPORTED_LANGUAGES
    for language in SUPPORTED_LANGUAGES - {"en"}:
        translation = json.loads(
            (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
        )
        assert _leaf_paths(translation) == expected_paths


def test_translation_values_are_non_empty_strings() -> None:
    for path in TRANSLATIONS.glob("*.json"):
        translation = json.loads(path.read_text(encoding="utf-8"))
        for leaf_path in _leaf_paths(translation):
            value: Any = translation
            for key in leaf_path:
                value = value[key]
            assert isinstance(value, str) and value.strip(), (path.name, leaf_path)
