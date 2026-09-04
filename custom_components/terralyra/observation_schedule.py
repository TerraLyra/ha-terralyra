"""Conservative active-fire refresh and observation estimates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from .models import ProviderStatus

GEOSTATIONARY_REFRESH = timedelta(minutes=10)
FIRMS_REFRESH = timedelta(minutes=15)
VIIRS_WINDOW_HALF_WIDTH = timedelta(minutes=45)
_VIIRS_LOCAL_SOLAR_TIMES = (
    time(1, 30),
    time(2, 20),
    time(13, 30),
    time(14, 20),
)
_USABLE_STATUSES = {ProviderStatus.AVAILABLE, ProviderStatus.DELAYED}


@dataclass(frozen=True, slots=True)
class SourceUpdateEstimate:
    """One bounded, explicitly qualified provider timing estimate."""

    provider: str
    name: str
    satellite: str
    status: str
    expected_at: datetime | None
    estimate_type: str
    cadence_minutes: int | None = None
    observation_window_start: datetime | None = None
    observation_window_end: datetime | None = None

    def attrs(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "name": self.name,
            "satellite": self.satellite,
            "status": self.status,
            "expected_at": (
                self.expected_at.isoformat() if self.expected_at else None
            ),
            "estimate_type": self.estimate_type,
            "cadence_minutes": self.cadence_minutes,
            "observation_window_start": (
                self.observation_window_start.isoformat()
                if self.observation_window_start
                else None
            ),
            "observation_window_end": (
                self.observation_window_end.isoformat()
                if self.observation_window_end
                else None
            ),
        }


def location_update_estimates(
    plan: Any,
    location: Any,
    health: tuple[Any, ...],
    *,
    now: datetime | None = None,
) -> tuple[SourceUpdateEstimate, ...]:
    """Estimate the next useful update for every equal source at one location."""
    current = _as_utc(now or datetime.now(UTC))
    estimates: list[SourceUpdateEstimate] = []
    for provider, satellite in zip(plan.providers, plan.satellites, strict=True):
        item = _matching_health(provider, satellite, plan.location_id, health)
        status = item.status if item is not None else ProviderStatus.INITIALIZING
        received_at = getattr(item, "received_timestamp", None)
        if provider in {"eumetsat_lsa_saf", "noaa_goes"}:
            expected = _next_refresh(received_at, current, GEOSTATIONARY_REFRESH)
            estimates.append(
                SourceUpdateEstimate(
                    provider,
                    getattr(item, "label", None) or provider,
                    satellite,
                    status.value,
                    expected,
                    "product_refresh_cadence",
                    10,
                )
            )
            continue

        if provider == "nasa_firms":
            expected = _next_refresh(received_at, current, FIRMS_REFRESH)
            overpass = next_viirs_overpass_window(
                float(location.longitude), now=current
            )
            estimates.append(
                SourceUpdateEstimate(
                    provider,
                    getattr(item, "label", None) or provider,
                    satellite,
                    status.value,
                    expected,
                    "api_refresh_with_nominal_overpass_window",
                    15,
                    overpass[0],
                    overpass[1],
                )
            )
    return tuple(estimates)


def next_usable_update(
    estimates: tuple[SourceUpdateEstimate, ...],
) -> SourceUpdateEstimate | None:
    """Return the earliest update from a currently usable equal source."""
    candidates = [
        item
        for item in estimates
        if item.expected_at is not None
        and ProviderStatus(item.status) in _USABLE_STATUSES
    ]
    return min(candidates, key=lambda item: item.expected_at, default=None)


def next_viirs_overpass_window(
    longitude: float, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return a deliberately broad nominal NOAA-20/21 local-solar window."""
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Longitude is out of range")
    current = _as_utc(now or datetime.now(UTC))
    solar_offset = timedelta(minutes=longitude * 4.0)
    candidates: list[datetime] = []
    for day_offset in range(-1, 3):
        day = (current + timedelta(days=day_offset)).date()
        for local_time in _VIIRS_LOCAL_SOLAR_TIMES:
            nominal_local = datetime.combine(day, local_time, UTC)
            candidate = nominal_local - solar_offset
            if candidate + VIIRS_WINDOW_HALF_WIDTH > current:
                candidates.append(candidate)
    midpoint = min(candidates)
    return midpoint - VIIRS_WINDOW_HALF_WIDTH, midpoint + VIIRS_WINDOW_HALF_WIDTH


def _next_refresh(
    received_at: datetime | None,
    now: datetime,
    cadence: timedelta,
) -> datetime | None:
    if received_at is None:
        return None
    candidate = _as_utc(received_at) + cadence
    if candidate > now:
        return candidate
    elapsed = now - candidate
    steps = int(elapsed // cadence) + 1
    return candidate + cadence * steps


def _matching_health(
    provider: str,
    satellite: str,
    location_id: str,
    health: tuple[Any, ...],
) -> Any | None:
    return next(
        (
            item
            for item in health
            if location_id in item.location_ids
            and (
                item.provider_id == provider
                or item.provider_id.startswith(f"{provider}:")
            )
            and item.satellite == satellite
        ),
        None,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Observation schedule timestamps must be timezone-aware")
    return value.astimezone(UTC)
