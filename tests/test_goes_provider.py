"""Tests for the normalized NOAA GOES active-fire provider."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.terralyra.models import ProviderSnapshot, ProviderStatus
from custom_components.terralyra.products.goes import GoesDiscoveryError
from custom_components.terralyra.providers.base import (
    ProviderInvalidResponseError,
    ProviderNoDataError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from custom_components.terralyra.providers.goes_active import GoesActiveFireProvider
from custom_components.terralyra.providers.goes_spike import parse_fdc_filename

NOW = datetime(2026, 8, 29, 12, 15, tzinfo=UTC)
FILENAME = (
    "OR_ABI-L2-FDCF-M6_G19_s20262411200200_"
    "e20262411209508_c20262411210123.nc"
)


async def _executor(function, *args):
    return function(*args)


def _provider() -> GoesActiveFireProvider:
    return GoesActiveFireProvider(
        object(),
        _executor,
        latitude=40.71,
        longitude=-74.01,
        now=lambda: NOW,
    )


def _item(age: timedelta = timedelta(minutes=5)):
    metadata = parse_fdc_filename(FILENAME)
    metadata = metadata.__class__(
        satellite=metadata.satellite,
        sector=metadata.sector,
        scan_mode=metadata.scan_mode,
        observation_start=NOW - age - timedelta(minutes=9),
        observation_end=NOW - age,
        created_at=NOW - age + timedelta(minutes=1),
        filename=metadata.filename,
    )
    return type(
        "Object",
        (),
        {
            "metadata": metadata,
            "filename": metadata.filename,
            "public_url": f"https://noaa-goes19.s3.amazonaws.com/{metadata.filename}",
        },
    )()


def _snapshot(item, *, provider: str = "noaa_goes") -> ProviderSnapshot:
    return ProviderSnapshot(
        provider=provider,
        satellite="G19",
        product="ABI-L2-FDCF",
        product_timestamp=item.metadata.observation_end,
        received_timestamp=NOW,
        status=ProviderStatus.AVAILABLE,
        source_url=item.public_url,
        filename=item.metadata.filename,
        detections=(),
    )


@pytest.mark.asyncio
async def test_provider_selects_goes_east_and_returns_available_snapshot() -> None:
    provider = _provider()
    item = _item()
    provider._discovery.async_latest = AsyncMock(return_value=item)
    provider._products.async_fetch = AsyncMock(return_value=_snapshot(item))

    snapshot = await provider.async_fetch_latest()

    assert provider.coverage.satellite == "G19"
    assert snapshot.status is ProviderStatus.AVAILABLE
    provider._discovery.async_latest.assert_awaited_once_with("G19", now=NOW)


@pytest.mark.asyncio
async def test_provider_marks_an_older_valid_product_delayed() -> None:
    provider = _provider()
    item = _item(timedelta(minutes=45))
    provider._discovery.async_latest = AsyncMock(return_value=item)
    provider._products.async_fetch = AsyncMock(return_value=_snapshot(item))

    snapshot = await provider.async_fetch_latest()

    assert snapshot.status is ProviderStatus.DELAYED


@pytest.mark.asyncio
async def test_provider_distinguishes_no_product_and_outage() -> None:
    provider = _provider()
    provider._discovery.async_latest = AsyncMock(return_value=None)
    with pytest.raises(ProviderNoDataError):
        await provider.async_fetch_latest()

    provider._discovery.async_latest = AsyncMock(
        side_effect=GoesDiscoveryError("unsafe details")
    )
    with pytest.raises(ProviderUnavailableError, match="temporarily unavailable"):
        await provider.async_fetch_latest()


@pytest.mark.asyncio
async def test_provider_rejects_stale_or_mismatched_snapshot() -> None:
    provider = _provider()
    stale = _item(timedelta(hours=3))
    provider._discovery.async_latest = AsyncMock(return_value=stale)
    with pytest.raises(ProviderNoDataError, match="No current"):
        await provider.async_fetch_latest()

    item = _item()
    provider._discovery.async_latest = AsyncMock(return_value=item)
    provider._products.async_fetch = AsyncMock(
        return_value=_snapshot(item, provider="unexpected")
    )
    with pytest.raises(ProviderUnavailableError, match="identity mismatch"):
        await provider.async_fetch_latest()


def test_provider_rejects_locations_outside_goes_coverage() -> None:
    with pytest.raises(ValueError, match="outside safe GOES coverage"):
        GoesActiveFireProvider(
            object(),
            _executor,
            latitude=47.49,
            longitude=19.04,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_type", "provider_error"),
    [
        ("rate_limit", ProviderRateLimitError),
        ("timeout", ProviderTimeoutError),
        ("invalid_response", ProviderInvalidResponseError),
        ("service_outage", ProviderUnavailableError),
    ],
)
async def test_goes_provider_preserves_normalized_failure_type(
    failure_type: str, provider_error: type[Exception]
) -> None:
    provider = _provider()
    provider._discovery.async_latest = AsyncMock(
        side_effect=GoesDiscoveryError("safe", failure_type=failure_type)
    )

    with pytest.raises(provider_error) as caught:
        await provider.async_fetch_latest()

    assert caught.value.failure_type == failure_type
