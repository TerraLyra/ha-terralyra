"""Tests for actionable Home Assistant repair issues."""

from __future__ import annotations

from unittest.mock import Mock, patch

from homeassistant.helpers import issue_registry as ir

from custom_components.terralyra.coverage import LocationCoverage
from custom_components.terralyra.repairs import (
    OUTAGE_REPAIR_THRESHOLD,
    async_set_fire_risk_outage_issue,
    async_set_authentication_issue,
    async_set_provider_outage_issue,
    async_sync_provider_health_issues,
    async_sync_coverage_issue,
)
from custom_components.terralyra.models import ProviderStatus
from custom_components.terralyra.providers.pool import ProviderHealth


def _entry() -> Mock:
    return Mock(entry_id="entry-1")


@patch("custom_components.terralyra.repairs.ir.async_delete_issue")
@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_authentication_issue_is_actionable_and_clears(
    create_issue: Mock, delete_issue: Mock
) -> None:
    hass = Mock()
    entry = _entry()

    async_set_authentication_issue(hass, entry, active=True)
    assert create_issue.call_args.kwargs["severity"] is ir.IssueSeverity.ERROR
    assert create_issue.call_args.kwargs["translation_key"] == "provider_authentication"

    async_set_authentication_issue(hass, entry, active=False)
    delete_issue.assert_called_once_with(
        hass, "terralyra", "entry-1_provider_authentication"
    )


@patch("custom_components.terralyra.repairs.ir.async_delete_issue")
@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_outage_issue_waits_for_repeated_failures_and_clears_on_success(
    create_issue: Mock, delete_issue: Mock
) -> None:
    hass = Mock()
    entry = _entry()

    async_set_provider_outage_issue(
        hass, entry, consecutive_failures=OUTAGE_REPAIR_THRESHOLD - 1
    )
    create_issue.assert_not_called()
    delete_issue.assert_not_called()

    async_set_provider_outage_issue(
        hass, entry, consecutive_failures=OUTAGE_REPAIR_THRESHOLD
    )
    assert create_issue.call_args.kwargs["translation_placeholders"] == {
        "failures": str(OUTAGE_REPAIR_THRESHOLD)
    }

    async_set_provider_outage_issue(hass, entry, consecutive_failures=0)
    delete_issue.assert_called_once_with(hass, "terralyra", "entry-1_provider_outage")


@patch("custom_components.terralyra.repairs.ir.async_delete_issue")
@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_fire_risk_issue_is_warning_and_clears_after_recovery(
    create_issue: Mock, delete_issue: Mock
) -> None:
    hass = Mock()
    entry = _entry()

    async_set_fire_risk_outage_issue(
        hass, entry, consecutive_failures=OUTAGE_REPAIR_THRESHOLD
    )
    assert create_issue.call_args.kwargs["severity"] is ir.IssueSeverity.WARNING
    assert create_issue.call_args.kwargs["translation_key"] == "fire_risk_outage"
    assert create_issue.call_args.kwargs["translation_placeholders"] == {
        "failures": str(OUTAGE_REPAIR_THRESHOLD),
        "reason": "service issue",
    }

    async_set_fire_risk_outage_issue(hass, entry, consecutive_failures=0)
    delete_issue.assert_called_once_with(hass, "terralyra", "entry-1_fire_risk_outage")


@patch("custom_components.terralyra.repairs.ir.async_delete_issue")
@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_coverage_issue_lists_only_uncovered_locations_and_clears(
    create_issue: Mock, delete_issue: Mock
) -> None:
    hass = Mock()
    entry = _entry()
    covered = LocationCoverage("home", "Home", True, "MTG", None)
    uncovered = LocationCoverage("test", "California test", False, None, "noaa_goes")

    async_sync_coverage_issue(hass, entry, (covered, uncovered))
    assert create_issue.call_args.kwargs["translation_placeholders"] == {
        "locations": "California test"
    }

    async_sync_coverage_issue(hass, entry, (covered,))
    delete_issue.assert_called_once_with(hass, "terralyra", "entry-1_provider_coverage")


@patch("custom_components.terralyra.repairs.ir.async_delete_issue")
@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_provider_health_creates_one_bounded_issue_and_clears(
    create_issue: Mock, delete_issue: Mock
) -> None:
    hass = Mock()
    entry = _entry()
    failed = ProviderHealth(
        "nasa/firms",
        "NASA FIRMS",
        "VIIRS",
        ("home",),
        ProviderStatus.OUTAGE,
        "rate_limit",
        OUTAGE_REPAIR_THRESHOLD,
    )
    healthy = ProviderHealth(
        "mtg",
        "EUMETSAT LSA SAF",
        "MTG",
        ("home",),
        ProviderStatus.AVAILABLE,
    )

    async_sync_provider_health_issues(hass, entry, (failed, healthy))

    assert create_issue.call_args.kwargs["translation_placeholders"] == {
        "service": "NASA FIRMS",
        "failure": "rate_limit",
        "failures": str(OUTAGE_REPAIR_THRESHOLD),
    }
    delete_issue.assert_called_once_with(hass, "terralyra", "entry-1_provider_mtg")


@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_provider_authentication_issue_is_immediate(create_issue: Mock) -> None:
    health = ProviderHealth(
        "mtg",
        "EUMETSAT LSA SAF",
        "MTG",
        ("home",),
        ProviderStatus.AUTH_ERROR,
        "authentication",
        1,
    )

    async_sync_provider_health_issues(Mock(), _entry(), (health,))

    assert create_issue.call_args.kwargs["severity"] is ir.IssueSeverity.ERROR


@patch("custom_components.terralyra.repairs.ir.async_create_issue")
def test_goes_provider_issue_uses_credential_free_guidance(
    create_issue: Mock,
) -> None:
    health = ProviderHealth(
        "noaa_goes:G18",
        "NOAA GOES",
        "G18",
        ("california",),
        ProviderStatus.OUTAGE,
        "invalid_response",
        OUTAGE_REPAIR_THRESHOLD,
    )

    async_sync_provider_health_issues(Mock(), _entry(), (health,))

    assert create_issue.call_args.kwargs["translation_key"] == "upstream_goes_issue"
