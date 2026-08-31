"""Construct geographically relevant active-fire providers."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientSession

from ..const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
)
from ..coverage import plan_location_sources
from ..monitoring import MonitoredLocation
from ..products.fire import ActiveFireClient
from ..products.firms import FirmsClient
from .base import ActiveFireProvider
from .firms import FirmsMultiAreaProvider, monitoring_bounds
from .goes_active import GoesActiveFireProvider
from .mtg import MtgActiveFireProvider
from .pool import MultiProviderPool, ProviderBinding


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


def build_provider_pool(
    session: ClientSession,
    run_in_executor: Callable[..., Awaitable[Any]],
    *,
    locations: tuple[MonitoredLocation, ...],
    username: str | None,
    password: str | None,
    firms_enabled: bool,
    firms_map_key: str | None,
) -> tuple[MultiProviderPool, tuple[Any, ...]]:
    """Build every geographically relevant provider as an equal peer."""
    enabled_locations = tuple(location for location in locations if location.enabled)
    lsa_available = bool(username and password)
    firms_available = bool(firms_enabled and firms_map_key)
    plans = tuple(
        plan_location_sources(
            location,
            lsa_saf_available=lsa_available,
            firms_available=firms_available,
        )
        for location in enabled_locations
    )
    bindings: list[ProviderBinding] = []

    mtg_location_ids = tuple(
        plan.location_id
        for plan in plans
        if ACTIVE_FIRE_PROVIDER_LSA_SAF in plan.providers
    )
    if mtg_location_ids:
        bindings.append(
            ProviderBinding(
                ACTIVE_FIRE_PROVIDER_LSA_SAF,
                "EUMETSAT LSA SAF",
                "MTG",
                mtg_location_ids,
                MtgActiveFireProvider(
                    ActiveFireClient(session, str(username), str(password))
                ),
            )
        )

    goes_groups: dict[str, list[MonitoredLocation]] = {}
    for location, plan in zip(enabled_locations, plans, strict=True):
        for provider, satellite in zip(plan.providers, plan.satellites, strict=True):
            if provider == ACTIVE_FIRE_PROVIDER_GOES:
                goes_groups.setdefault(satellite, []).append(location)
    for satellite, covered_locations in sorted(goes_groups.items()):
        representative = covered_locations[0]
        bindings.append(
            ProviderBinding(
                f"{ACTIVE_FIRE_PROVIDER_GOES}:{satellite}",
                "NOAA GOES",
                satellite,
                tuple(location.id for location in covered_locations),
                GoesActiveFireProvider(
                    session,
                    run_in_executor,
                    latitude=representative.latitude,
                    longitude=representative.longitude,
                ),
            )
        )

    if firms_available:
        bounds = tuple(
            monitoring_bounds(
                location.latitude,
                location.longitude,
                location.radius_km,
            )
            for location in enabled_locations
        )
        bindings.append(
            ProviderBinding(
                "nasa_firms",
                "NASA FIRMS",
                "NOAA-20/NOAA-21 VIIRS",
                tuple(location.id for location in enabled_locations),
                FirmsMultiAreaProvider(
                    FirmsClient(session, str(firms_map_key)),
                    bounds,
                ),
            )
        )
    return MultiProviderPool(tuple(bindings)), plans
