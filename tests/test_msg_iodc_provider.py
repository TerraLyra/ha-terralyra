"""Tests for live MSG-IODC provider normalization and assignment."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.terralyra.clustering import cluster_detections
from custom_components.terralyra.const import LOCATION_SOURCE_MANUAL
from custom_components.terralyra.models import FireDetection
from custom_components.terralyra.monitoring import MonitoredLocation
from custom_components.terralyra.products.msg_iodc import (
    MsgIodcAuthenticationError,
    MsgIodcPixel,
    MsgIodcProduct,
    MsgIodcSchemaError,
)
from custom_components.terralyra.providers.base import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
)
from custom_components.terralyra.providers.factory import build_provider_pool
from custom_components.terralyra.providers.msg_iodc import (
    PRODUCT,
    PROVIDER,
    SATELLITE,
    SOURCE_FAMILY,
    MsgIodcActiveFireProvider,
)


async def _executor(function, *args):
    return function(*args)


def _location(
    location_id: str, latitude: float, longitude: float
) -> MonitoredLocation:
    return MonitoredLocation(
        id=location_id,
        name=location_id,
        latitude=latitude,
        longitude=longitude,
        radius_km=50,
        enabled=True,
        source=LOCATION_SOURCE_MANUAL,
    )


@pytest.mark.asyncio
async def test_provider_normalizes_decoded_iodc_pixels() -> None:
    product_time = datetime.now(UTC).replace(second=0, microsecond=0)
    product = MsgIodcProduct(
        filename="safe-product",
        url="https://example.invalid/safe-product",
        product_time=product_time,
        pixels=(
            MsgIodcPixel(
                latitude=0.35,
                longitude=32.58,
                confidence=0.9,
                frp_mw=42.5,
                acquired=product_time,
                pixel_size_km2=9.6,
                frp_uncertainty_mw=2.4,
                abs_line=123,
                abs_pixel=456,
            ),
        ),
    )
    provider = MsgIodcActiveFireProvider(
        object(),
        _executor,
        username="account",
        password="credential",  # pragma: allowlist secret
    )

    with (
        patch(
            "custom_components.terralyra.providers.msg_iodc."
            "async_fetch_latest_list_product",
            new=AsyncMock(return_value=("safe-product", b"payload")),
        ),
        patch(
            "custom_components.terralyra.providers.msg_iodc.decode_list_product",
            return_value=product,
        ),
    ):
        snapshot = await provider.async_fetch_latest()

    detection = snapshot.detections[0]
    assert snapshot.provider == PROVIDER
    assert snapshot.satellite == SATELLITE
    assert snapshot.product == PRODUCT
    assert detection.source_family == SOURCE_FAMILY
    assert detection.frp_mw == 42.5
    assert detection.confidence == 0.9
    assert detection.source_detection_id.endswith(":123:456")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_error", "provider_error"),
    [
        (MsgIodcAuthenticationError("auth"), ProviderAuthenticationError),
        (MsgIodcSchemaError("schema"), ProviderInvalidResponseError),
    ],
)
async def test_provider_normalizes_iodc_errors(
    source_error: Exception, provider_error: type[Exception]
) -> None:
    provider = MsgIodcActiveFireProvider(
        object(),
        _executor,
        username="account",
        password="credential",  # pragma: allowlist secret
    )
    with (
        patch(
            "custom_components.terralyra.providers.msg_iodc."
            "async_fetch_latest_list_product",
            new=AsyncMock(side_effect=source_error),
        ),
        pytest.raises(provider_error),
    ):
        await provider.async_fetch_latest()


def test_pool_assigns_one_iodc_download_to_all_covered_locations() -> None:
    pool, plans = build_provider_pool(
        object(),
        _executor,
        locations=(
            _location("kampala", 0.35, 32.58),
            _location("delhi", 28.61, 77.21),
            _location("california", 38.56, -121.63),
        ),
        username="account",
        password="credential",  # pragma: allowlist secret
        firms_enabled=False,
        firms_map_key=None,
    )

    binding = next(item for item in pool.bindings if item.provider_id == PROVIDER)
    assert binding.location_ids == ("kampala", "delhi")
    assert sum(PROVIDER in plan.providers for plan in plans) == 2


def test_mtg_and_iodc_are_not_independent_confirmation() -> None:
    acquired = datetime(2026, 9, 4, 18, 15, tzinfo=UTC)
    common = {
        "product": "FRPPixel",
        "timestamp": acquired,
        "frp_mw": 20.0,
        "confidence": 0.9,
        "source_family": SOURCE_FAMILY,
    }
    clusters = cluster_detections(
        [
            (
                FireDetection(
                    provider="eumetsat_lsa_saf",
                    satellite="MTG",
                    latitude=0.35,
                    longitude=32.58,
                    **common,
                ),
                0.0,
            ),
            (
                FireDetection(
                    provider=PROVIDER,
                    satellite=SATELLITE,
                    latitude=0.351,
                    longitude=32.581,
                    **common,
                ),
                0.0,
            ),
        ],
        0.35,
        32.58,
        cluster_radius_km=1.0,
    )

    assert len(clusters) == 1
    assert clusters[0].confirmation_level.value == "single_source"
