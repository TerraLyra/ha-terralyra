"""Conservative geographic coverage assessment for active-fire providers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .const import (
    ACTIVE_FIRE_PROVIDER_GOES,
    ACTIVE_FIRE_PROVIDER_LSA_SAF,
)
from .monitoring import MonitoredLocation
from .providers.goes import select_goes_satellite

MTG_SUB_SATELLITE_LONGITUDE = 0.0
MAX_SAFE_MTG_CENTRAL_ANGLE_DEGREES = 78.0
NASA_FIRMS_PROVIDER = "nasa_firms"
NASA_FIRMS_SATELLITES = "NOAA-20/NOAA-21 VIIRS + Terra/Aqua MODIS"

SOURCE_DISPLAY_NAMES = {
    ACTIVE_FIRE_PROVIDER_LSA_SAF: "EUMETSAT LSA SAF",
    ACTIVE_FIRE_PROVIDER_GOES: "NOAA GOES",
    NASA_FIRMS_PROVIDER: "NASA FIRMS",
}


@dataclass(frozen=True, slots=True)
class LocationCoverage:
    """Coverage result for one enabled monitored location."""

    location_id: str
    location_name: str
    covered: bool
    satellite: str | None
    recommended_provider: str | None

    def attrs(self) -> dict[str, str | bool | None]:
        """Return bounded Home Assistant attributes without coordinates."""
        return {
            "location_id": self.location_id,
            "location_name": self.location_name,
            "covered": self.covered,
            "satellite": self.satellite,
            "recommended_provider": self.recommended_provider,
        }


@dataclass(frozen=True, slots=True)
class LocationSourcePlan:
    """Equal active-fire sources available to one monitored location."""

    location_id: str
    location_name: str
    providers: tuple[str, ...]
    satellites: tuple[str, ...]

    @property
    def covered(self) -> bool:
        return bool(self.providers)

    def attrs(self) -> dict[str, object]:
        assignments = [
            {
                "provider": provider,
                "name": SOURCE_DISPLAY_NAMES.get(provider, provider),
                "satellite": satellite,
            }
            for provider, satellite in zip(self.providers, self.satellites, strict=True)
        ]
        return {
            "location_id": self.location_id,
            "location_name": self.location_name,
            "covered": self.covered,
            "providers": list(self.providers),
            "source_names": [item["name"] for item in assignments],
            "satellites": list(self.satellites),
            "assignments": assignments,
            "source_count": len(assignments),
            "relationship": "equal_peers",
        }


def plan_location_sources(
    location: MonitoredLocation,
    *,
    lsa_saf_available: bool,
    firms_available: bool,
) -> LocationSourcePlan:
    """Assign every configured source that safely covers a location."""
    providers: list[str] = []
    satellites: list[str] = []
    if (
        lsa_saf_available
        and _central_angle(
            location.latitude,
            location.longitude,
            MTG_SUB_SATELLITE_LONGITUDE,
        )
        <= MAX_SAFE_MTG_CENTRAL_ANGLE_DEGREES
    ):
        providers.append(ACTIVE_FIRE_PROVIDER_LSA_SAF)
        satellites.append("MTG")
    goes = select_goes_satellite(location.latitude, location.longitude)
    if goes is not None:
        providers.append(ACTIVE_FIRE_PROVIDER_GOES)
        satellites.append(goes.satellite)
    if firms_available:
        providers.append(NASA_FIRMS_PROVIDER)
        satellites.append(NASA_FIRMS_SATELLITES)
    return LocationSourcePlan(
        location.id,
        location.name,
        tuple(providers),
        tuple(satellites),
    )


def summarize_source_plans(results: tuple[LocationSourcePlan, ...]) -> str:
    """Summarize automatic source availability across enabled locations."""
    if not results:
        return "unknown"
    covered = sum(result.covered for result in results)
    if covered == len(results):
        return "covered"
    if covered:
        return "partial"
    return "not_covered"


def assess_location_coverage(
    provider: str, location: MonitoredLocation
) -> LocationCoverage:
    """Assess conservative pre-download coverage for one provider/location."""
    satellite: str | None = None
    if provider == ACTIVE_FIRE_PROVIDER_GOES:
        goes = select_goes_satellite(location.latitude, location.longitude)
        covered = goes is not None
        satellite = goes.satellite if goes else None
    elif provider == ACTIVE_FIRE_PROVIDER_LSA_SAF:
        covered = (
            _central_angle(
                location.latitude,
                location.longitude,
                MTG_SUB_SATELLITE_LONGITUDE,
            )
            <= MAX_SAFE_MTG_CENTRAL_ANGLE_DEGREES
        )
        satellite = "MTG" if covered else None
    else:
        covered = False

    return LocationCoverage(
        location_id=location.id,
        location_name=location.name,
        covered=covered,
        satellite=satellite,
        recommended_provider=(
            None
            if covered
            else _recommended_provider(location.latitude, location.longitude)
        ),
    )


def summarize_coverage(results: tuple[LocationCoverage, ...]) -> str:
    """Summarize all enabled locations as one translated sensor state."""
    if not results:
        return "unknown"
    covered = sum(result.covered for result in results)
    if covered == len(results):
        return "covered"
    if covered:
        return "partial"
    return "not_covered"


def _recommended_provider(latitude: float, longitude: float) -> str:
    """Return one legacy recommendation for compatibility diagnostics."""
    if select_goes_satellite(latitude, longitude) is not None:
        return ACTIVE_FIRE_PROVIDER_GOES
    if (
        _central_angle(latitude, longitude, MTG_SUB_SATELLITE_LONGITUDE)
        <= MAX_SAFE_MTG_CENTRAL_ANGLE_DEGREES
    ):
        return ACTIVE_FIRE_PROVIDER_LSA_SAF
    return NASA_FIRMS_PROVIDER


def _central_angle(latitude: float, longitude: float, sub_lon: float) -> float:
    """Return the geocentric angle from a geostationary sub-satellite point."""
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("Coverage coordinates must be finite")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coverage coordinates are out of range")
    latitude_radians = math.radians(latitude)
    longitude_delta = math.radians(longitude - sub_lon)
    cosine = math.cos(latitude_radians) * math.cos(longitude_delta)
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))
