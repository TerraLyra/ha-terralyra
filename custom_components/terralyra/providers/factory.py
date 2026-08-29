"""Construct the selected primary active-fire provider."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientSession

from ..const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
)
from ..products.fire import ActiveFireClient
from .base import ActiveFireProvider
from .goes_active import GoesActiveFireProvider
from .mtg import MtgActiveFireProvider


def build_primary_provider(
    session: ClientSession,
    run_in_executor: Callable[..., Awaitable[Any]],
    *,
    provider_name: str,
    latitude: float,
    longitude: float,
    username: str | None = None,
    password: str | None = None,
) -> ActiveFireProvider:
    """Build one validated primary provider without silent fallback."""
    if provider_name == ACTIVE_FIRE_PROVIDER_LSA_SAF:
        if not username or not password:
            raise ValueError("LSA SAF credentials are required")
        return MtgActiveFireProvider(ActiveFireClient(session, username, password))
    if provider_name == ACTIVE_FIRE_PROVIDER_GOES:
        return GoesActiveFireProvider(
            session,
            run_in_executor,
            latitude=latitude,
            longitude=longitude,
        )
    raise ValueError("Unsupported active-fire provider")
