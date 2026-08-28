"""Regression tests for the clean TerraLyra identity."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.terralyra.const import (
    BUS_EVENT_FIRE_RISK_INCREASE,
    BUS_EVENT_FIRE_TREND,
    BUS_EVENT_NEW_FIRE,
    DOMAIN,
    NAME,
)


def test_domain_and_event_names() -> None:
    """The clean-break integration must not reuse the legacy domain."""
    assert DOMAIN == "terralyra"
    assert NAME == "TerraLyra"
    assert BUS_EVENT_NEW_FIRE == "terralyra_new_fire"
    assert BUS_EVENT_FIRE_TREND == "terralyra_fire_trend"
    assert BUS_EVENT_FIRE_RISK_INCREASE == "terralyra_fire_risk_increase"


def test_manifest_identity() -> None:
    """The manifest must point to the new project and domain."""
    manifest_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "terralyra"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["domain"] == DOMAIN
    assert manifest["name"] == NAME
    assert manifest["documentation"] == "https://github.com/TerraLyra/ha-terralyra"
    assert manifest["issue_tracker"] == (
        "https://github.com/TerraLyra/ha-terralyra/issues"
    )
