"""Tests for primary active-fire provider construction."""
from __future__ import annotations

import pytest

from custom_components.terralyra.const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
)
from custom_components.terralyra.providers.factory import build_primary_provider
from custom_components.terralyra.providers.goes_active import GoesActiveFireProvider
from custom_components.terralyra.providers.mtg import MtgActiveFireProvider


async def _executor(function, *args):
    return function(*args)


def test_factory_preserves_existing_lsa_saf_provider() -> None:
    provider = build_primary_provider(
        object(),
        _executor,
        provider_name=ACTIVE_FIRE_PROVIDER_LSA_SAF,
        latitude=47.49,
        longitude=19.04,
        username="user",
        password="password",
    )

    assert isinstance(provider, MtgActiveFireProvider)


def test_factory_builds_goes_only_inside_safe_coverage() -> None:
    provider = build_primary_provider(
        object(),
        _executor,
        provider_name=ACTIVE_FIRE_PROVIDER_GOES,
        latitude=40.71,
        longitude=-74.01,
    )

    assert isinstance(provider, GoesActiveFireProvider)
    assert provider.coverage.satellite == "G19"

    with pytest.raises(ValueError, match="outside safe GOES coverage"):
        build_primary_provider(
            object(),
            _executor,
            provider_name=ACTIVE_FIRE_PROVIDER_GOES,
            latitude=47.49,
            longitude=19.04,
        )


def test_factory_never_silently_falls_back() -> None:
    with pytest.raises(ValueError, match="credentials are required"):
        build_primary_provider(
            object(),
            _executor,
            provider_name=ACTIVE_FIRE_PROVIDER_LSA_SAF,
            latitude=47.49,
            longitude=19.04,
        )

    with pytest.raises(ValueError, match="Unsupported"):
        build_primary_provider(
            object(),
            _executor,
            provider_name="unexpected",
            latitude=47.49,
            longitude=19.04,
        )
