"""Coverage selection for NOAA GOES ABI active-fire products."""
from __future__ import annotations

from dataclasses import dataclass
import math

# Current operational positions published by NOAA.  A conservative usable
# angle avoids routing near-limb locations to a provider before the product's
# own navigation mask can be checked during decoding.
_SUB_SATELLITE_LONGITUDES = {"G18": -137.2, "G19": -75.2}
MAX_USABLE_CENTRAL_ANGLE_DEGREES = 78.0


@dataclass(frozen=True, slots=True)
class GoesCoverage:
    """Selected operational satellite and geometric viewing angle."""

    satellite: str
    central_angle_degrees: float


def select_goes_satellite(latitude: float, longitude: float) -> GoesCoverage | None:
    """Select the best GOES satellite for a safely visible Home location.

    This is a pre-download gate, not a substitute for checking the NetCDF
    navigation mask.  Locations close to the geometric limb are rejected.
    """
    _validate_coordinate(latitude, longitude)
    candidates = tuple(
        GoesCoverage(satellite, _central_angle(latitude, longitude, sub_lon))
        for satellite, sub_lon in _SUB_SATELLITE_LONGITUDES.items()
    )
    usable = tuple(
        candidate
        for candidate in candidates
        if candidate.central_angle_degrees <= MAX_USABLE_CENTRAL_ANGLE_DEGREES
    )
    return min(usable, key=lambda item: item.central_angle_degrees, default=None)


def _central_angle(latitude: float, longitude: float, sub_lon: float) -> float:
    latitude_radians = math.radians(latitude)
    longitude_delta = math.radians(longitude - sub_lon)
    cosine = math.cos(latitude_radians) * math.cos(longitude_delta)
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("GOES coverage coordinates must be finite")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError("GOES coverage coordinates are out of range")
