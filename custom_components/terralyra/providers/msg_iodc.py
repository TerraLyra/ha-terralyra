"""Coverage selection for MSG Indian Ocean Data Coverage fire products."""

from __future__ import annotations

from dataclasses import dataclass
import math

# Meteosat-9 currently provides the MSG IODC service from 45.5 degrees east.
# The 70-degree limit is deliberately stricter than the geometric horizon.
# A future live adapter must also validate the product navigation/quality mask.
MSG_IODC_SUB_SATELLITE_LONGITUDE = 45.5
MAX_USABLE_CENTRAL_ANGLE_DEGREES = 70.0


@dataclass(frozen=True, slots=True)
class MsgIodcCoverage:
    """Selected IODC satellite and its geometric viewing angle."""

    satellite: str
    central_angle_degrees: float


def select_msg_iodc_satellite(
    latitude: float, longitude: float
) -> MsgIodcCoverage | None:
    """Return Meteosat-9 when a location is conservatively visible.

    This is a pre-download gate only. Product navigation and quality flags
    remain authoritative once a bounded HDF5 decoder is implemented.
    """
    _validate_coordinate(latitude, longitude)
    central_angle = _central_angle(latitude, longitude)
    if central_angle > MAX_USABLE_CENTRAL_ANGLE_DEGREES:
        return None
    return MsgIodcCoverage("Meteosat-9 IODC", central_angle)


def _central_angle(latitude: float, longitude: float) -> float:
    latitude_radians = math.radians(latitude)
    longitude_delta = math.radians(
        longitude - MSG_IODC_SUB_SATELLITE_LONGITUDE
    )
    cosine = math.cos(latitude_radians) * math.cos(longitude_delta)
    return math.degrees(math.acos(min(1.0, max(-1.0, cosine))))


def _validate_coordinate(latitude: float, longitude: float) -> None:
    if not all(math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("MSG-IODC coverage coordinates must be finite")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError("MSG-IODC coverage coordinates are out of range")
