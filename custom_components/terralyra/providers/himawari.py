"""Coverage selection for Himawari AHI active-fire products."""

from __future__ import annotations

from dataclasses import dataclass
import math

# Himawari-9 is stationed near 140.7 degrees east. The deliberately stricter
# limit than the geometric limb keeps strongly distorted edge pixels out of the
# future provider before its product-level navigation mask is checked.
HIMAWARI_9_SUB_SATELLITE_LONGITUDE = 140.7
MAX_USABLE_CENTRAL_ANGLE_DEGREES = 70.0


@dataclass(frozen=True, slots=True)
class HimawariCoverage:
    """Selected operational satellite and geometric viewing angle."""

    satellite: str
    central_angle_degrees: float


def select_himawari_satellite(
    latitude: float, longitude: float
) -> HimawariCoverage | None:
    """Return Himawari-9 when a location is conservatively visible.

    This is only a pre-download gate. A future production adapter must also
    validate the actual product navigation/quality mask before using pixels.
    """
    _validate_coordinate(latitude, longitude)
    central_angle = _central_angle(latitude, longitude)
    if central_angle > MAX_USABLE_CENTRAL_ANGLE_DEGREES:
        return None
    return HimawariCoverage("Himawari-9", central_angle)


def _central_angle(latitude: float, longitude: float) -> float:
    latitude_radians = math.radians(latitude)
    longitude_delta = math.radians(
        longitude - HIMAWARI_9_SUB_SATELLITE_LONGITUDE
    )
    cosine = math.cos(latitude_radians) * math.cos(longitude_delta)
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("Himawari coverage coordinates must be finite")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError("Himawari coverage coordinates are out of range")
