"""Shared pytest fixtures for the TerraLyra custom integration."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading integrations from custom_components for every test."""
    yield
