"""Validate bundled translations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRANSLATIONS = Path("custom_components/terralyra/translations")
SOURCE_STRINGS = Path("custom_components/terralyra/strings.json")
SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "hu", "it"}
EXPECTED_ENGLISH_IDENTICAL_PATHS = {
    "hu": {
        "title",
        "options.step.init.data.firms_map_key",
        "entity.sensor.active_fire_provider.state.eumetsat_lsa_saf",
        "entity.sensor.active_fire_provider.state.noaa_goes",
    },
    "de": {
        "title",
        "options.step.init.data.firms_map_key",
        "entity.sensor.active_fire_provider.state.eumetsat_lsa_saf",
        "entity.sensor.active_fire_provider.state.noaa_goes",
        "entity.sensor.active_fire_situation.state.normal",
    },
    "fr": {
        "title",
        "options.step.init.data.firms_map_key",
        "entity.sensor.active_fire_provider.state.eumetsat_lsa_saf",
        "entity.sensor.active_fire_provider.state.noaa_goes",
    },
    "es": {
        "title",
        "options.step.init.data.firms_map_key",
        "entity.sensor.active_fire_provider.state.eumetsat_lsa_saf",
        "entity.sensor.active_fire_provider.state.noaa_goes",
        "entity.sensor.active_fire_situation.state.normal",
    },
    "it": {
        "title",
        "config.step.lsa_saf.data.password",
        "config.step.reauth_confirm.data.password",
        "options.step.init.data.firms_map_key",
        "entity.sensor.active_fire_provider.state.eumetsat_lsa_saf",
        "entity.sensor.active_fire_provider.state.noaa_goes",
    },
}


def _leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(value, dict):
        return {prefix}
    return {
        path
        for key, child in value.items()
        for path in _leaf_paths(child, (*prefix, key))
    }


def _leaf_values(
    value: Any, prefix: tuple[str, ...] = ()
) -> dict[tuple[str, ...], Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    return {
        path: leaf
        for key, child in value.items()
        for path, leaf in _leaf_values(child, (*prefix, key)).items()
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

    source = json.loads(SOURCE_STRINGS.read_text(encoding="utf-8"))
    assert _leaf_paths(source) == expected_paths


def test_translation_values_are_non_empty_strings() -> None:
    for path in TRANSLATIONS.glob("*.json"):
        translation = json.loads(path.read_text(encoding="utf-8"))
        for leaf_path in _leaf_paths(translation):
            value: Any = translation
            for key in leaf_path:
                value = value[key]
            assert isinstance(value, str) and value.strip(), (path.name, leaf_path)


def test_localizations_do_not_accidentally_fall_back_to_english() -> None:
    english = _leaf_values(
        json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    )
    for language, allowed in EXPECTED_ENGLISH_IDENTICAL_PATHS.items():
        localized = _leaf_values(
            json.loads(
                (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
            )
        )
        identical = {
            ".".join(path)
            for path, value in localized.items()
            if value == english[path]
        }
        assert identical == allowed
