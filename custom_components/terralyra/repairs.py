"""Actionable Home Assistant repair issues for TerraLyra."""

from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coverage import LocationCoverage, LocationSourcePlan
from .providers.pool import ProviderHealth

OUTAGE_REPAIR_THRESHOLD = 3


def _issue_id(entry: ConfigEntry, kind: str) -> str:
    """Return an issue id scoped to one config entry."""
    return f"{entry.entry_id}_{kind}"


def _provider_issue_id(entry: ConfigEntry, provider_id: str) -> str:
    """Return a safe issue id scoped to one configured provider."""
    safe_id = re.sub(r"[^a-z0-9_-]", "_", provider_id.lower())[:80]
    return _issue_id(entry, f"provider_{safe_id}")


def async_sync_provider_health_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    health: tuple[ProviderHealth, ...],
) -> None:
    """Create at most one self-clearing Repair for each unhealthy peer."""
    for item in health:
        issue_id = _provider_issue_id(entry, item.provider_id)
        authentication_failure = item.failure_type == "authentication"
        if not authentication_failure and (
            item.failure_type is None
            or item.consecutive_failures < OUTAGE_REPAIR_THRESHOLD
        ):
            if item.failure_type is None:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
            continue

        is_goes = item.provider_id.startswith("noaa_goes")
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=(
                ir.IssueSeverity.ERROR
                if authentication_failure
                else ir.IssueSeverity.WARNING
            ),
            translation_key=(
                "upstream_goes_issue" if is_goes else "upstream_provider_issue"
            ),
            translation_placeholders={
                "service": item.label,
                "failure": item.failure_type or "unknown",
                "failures": str(item.consecutive_failures),
            },
        )


def async_set_authentication_issue(
    hass: HomeAssistant, entry: ConfigEntry, *, active: bool
) -> None:
    """Create or clear the active-fire source authentication issue."""
    issue_id = _issue_id(entry, "provider_authentication")
    if not active:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="provider_authentication",
    )


def async_set_provider_outage_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    consecutive_failures: int,
) -> None:
    """Create an issue only after repeated provider failures, or clear it."""
    issue_id = _issue_id(entry, "provider_outage")
    if consecutive_failures < OUTAGE_REPAIR_THRESHOLD:
        if consecutive_failures == 0:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="provider_outage",
        translation_placeholders={"failures": str(consecutive_failures)},
    )


def async_set_fire_risk_outage_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    consecutive_failures: int,
    reason: str | None = None,
) -> None:
    """Create a self-clearing issue after repeated FRMv3 failures."""
    issue_id = _issue_id(entry, "fire_risk_outage")
    if consecutive_failures < OUTAGE_REPAIR_THRESHOLD:
        if consecutive_failures == 0:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="fire_risk_outage",
        translation_placeholders={
            "failures": str(consecutive_failures),
            "reason": reason or "service issue",
        },
    )


def async_sync_coverage_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    results: tuple[LocationCoverage | LocationSourcePlan, ...],
) -> None:
    """Synchronize the actionable geographic-coverage issue."""
    uncovered = [result.location_name for result in results if not result.covered]
    issue_id = _issue_id(entry, "provider_coverage")
    if not uncovered:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    names = ", ".join(uncovered[:3])
    if len(uncovered) > 3:
        names = f"{names} (+{len(uncovered) - 3})"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="provider_coverage",
        translation_placeholders={"locations": names},
    )
