"""Ensure every platform declared by the integration can be imported."""
from __future__ import annotations

import importlib

import pytest

from custom_components.terralyra.const import DOMAIN, PLATFORMS


@pytest.mark.parametrize("platform", PLATFORMS)
def test_platform_import(platform: str) -> None:
    """Catch removed or renamed Home Assistant platform base classes."""
    importlib.import_module(f"custom_components.{DOMAIN}.{platform}")
