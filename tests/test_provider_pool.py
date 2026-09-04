"""Tests for automatic equal-peer active-fire source pooling."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.terralyra.models import (
    FireDetection,
    ProviderSnapshot,
    ProviderStatus,
)
from custom_components.terralyra.providers.base import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from custom_components.terralyra.providers.pool import (
    MultiProviderPool,
    ProviderBinding,
)

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


def _snapshot(provider: str, satellite: str) -> ProviderSnapshot:
    detection = FireDetection(
        provider=provider,
        satellite=satellite,
        product="test",
        timestamp=NOW,
        latitude=46.0,
        longitude=20.0,
        frp_mw=10.0,
        confidence=0.8,
        source_detection_id=provider,
    )
    return ProviderSnapshot(
        provider=provider,
        satellite=satellite,
        product="test",
        product_timestamp=NOW,
        received_timestamp=NOW,
        status=ProviderStatus.AVAILABLE,
        source_url="https://example.invalid",
        filename="test",
        detections=(detection,),
    )


def _binding(provider_id: str, satellite: str, result: object) -> ProviderBinding:
    provider = AsyncMock()
    if isinstance(result, Exception):
        provider.async_fetch_latest.side_effect = result
    else:
        provider.async_fetch_latest.return_value = result
    return ProviderBinding(provider_id, provider_id, satellite, ("home",), provider)


@pytest.mark.asyncio
async def test_pool_merges_equal_sources() -> None:
    pool = MultiProviderPool(
        (
            _binding("mtg", "MTG", _snapshot("LSA SAF", "MTG")),
            _binding("firms", "VIIRS", _snapshot("NASA FIRMS", "VIIRS")),
        )
    )

    result = await pool.async_fetch_latest()

    assert len(result.detections) == 2
    assert {item.provider for item in result.detections} == {"LSA SAF", "NASA FIRMS"}
    assert all(item.status is ProviderStatus.AVAILABLE for item in pool.health)
    assert all(item.product_timestamp == NOW for item in pool.health)
    assert all(item.received_timestamp == NOW for item in pool.health)


@pytest.mark.asyncio
async def test_one_failed_source_does_not_block_healthy_peer() -> None:
    pool = MultiProviderPool(
        (
            _binding("mtg", "MTG", ProviderUnavailableError()),
            _binding("firms", "VIIRS", _snapshot("NASA FIRMS", "VIIRS")),
        )
    )

    result = await pool.async_fetch_latest()

    assert len(result.detections) == 1
    assert [item.status for item in pool.health] == [
        ProviderStatus.OUTAGE,
        ProviderStatus.AVAILABLE,
    ]


@pytest.mark.asyncio
async def test_pool_reports_when_every_source_rejects_authentication() -> None:
    pool = MultiProviderPool(
        (
            _binding("mtg", "MTG", ProviderAuthenticationError()),
            _binding("firms", "VIIRS", ProviderAuthenticationError()),
        )
    )

    with pytest.raises(ProviderAuthenticationError):
        await pool.async_fetch_latest()


@pytest.mark.asyncio
async def test_failed_peer_is_deferred_while_healthy_peer_continues() -> None:
    current = [NOW]
    failed = _binding("mtg", "MTG", ProviderUnavailableError())
    healthy = _binding("firms", "VIIRS", _snapshot("NASA FIRMS", "VIIRS"))
    pool = MultiProviderPool((failed, healthy), now=lambda: current[0])

    await pool.async_fetch_latest()
    await pool.async_fetch_latest()

    assert failed.provider.async_fetch_latest.await_count == 1
    assert healthy.provider.async_fetch_latest.await_count == 2
    assert pool.health[0].consecutive_failures == 1
    assert pool.health[0].failure_type == "service_outage"
    assert pool.health[0].retry_at == NOW + timedelta(minutes=5)
    assert pool.health[0].received_timestamp is None


@pytest.mark.asyncio
async def test_provider_retry_after_is_honored_and_clears_after_recovery() -> None:
    current = [NOW]
    binding = _binding(
        "firms",
        "VIIRS",
        ProviderRateLimitError(retry_after=timedelta(minutes=17)),
    )
    pool = MultiProviderPool((binding,), now=lambda: current[0])

    with pytest.raises(ProviderUnavailableError) as first_error:
        await pool.async_fetch_latest()
    assert first_error.value.retry_after == timedelta(minutes=17)
    assert pool.health[0].failure_type == "rate_limit"

    binding.provider.async_fetch_latest.side_effect = None
    binding.provider.async_fetch_latest.return_value = _snapshot("NASA FIRMS", "VIIRS")
    current[0] += timedelta(minutes=18)
    await pool.async_fetch_latest()

    assert pool.health[0].consecutive_failures == 0
    assert pool.health[0].failure_type is None
    assert pool.health[0].retry_at is None
