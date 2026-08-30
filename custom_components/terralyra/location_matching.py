"""Pure incident-to-location matching for local multi-location monitoring."""
from __future__ import annotations

import math
from collections.abc import Mapping

from .clustering import haversine_km
from .models import DistanceTrend, IncidentLocationMatch
from .monitoring import MonitoredLocation

DISTANCE_TREND_TOLERANCE_KM = 1.0
_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def match_incident_to_locations(
    incident_id: str,
    latitude: float,
    longitude: float,
    locations: tuple[MonitoredLocation, ...],
    *,
    previous_distances: Mapping[str, float] | None = None,
) -> tuple[IncidentLocationMatch, ...]:
    """Match one incident to every enabled location, nearest first."""
    if not incident_id.strip():
        raise ValueError("Incident ID must not be empty")
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Incident latitude is out of range")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Incident longitude is out of range")

    previous = previous_distances or {}
    matches = []
    for location in locations:
        if not location.enabled:
            continue
        distance_km = haversine_km(
            location.latitude, location.longitude, latitude, longitude
        )
        matches.append(
            IncidentLocationMatch(
                incident_id=incident_id,
                location_id=location.id,
                location_name=location.name,
                distance_km=distance_km,
                radius_km=location.radius_km,
                direction=_cardinal_direction(
                    location.latitude, location.longitude, latitude, longitude
                ),
                inside_radius=distance_km <= location.radius_km,
                distance_trend=_distance_trend(
                    distance_km, previous.get(location.id)
                ),
            )
        )
    return tuple(
        sorted(matches, key=lambda match: (match.distance_km, match.location_id))
    )


def _distance_trend(current: float, previous: float | None) -> DistanceTrend:
    if previous is None or not math.isfinite(previous):
        return DistanceTrend.UNKNOWN
    change = current - previous
    if change < -DISTANCE_TREND_TOLERANCE_KM:
        return DistanceTrend.APPROACHING
    if change > DISTANCE_TREND_TOLERANCE_KM:
        return DistanceTrend.RECEDING
    return DistanceTrend.STABLE


def _cardinal_direction(
    origin_latitude: float,
    origin_longitude: float,
    target_latitude: float,
    target_longitude: float,
) -> str:
    """Return an eight-point direction from a location toward an incident."""
    if origin_latitude == target_latitude and origin_longitude == target_longitude:
        return "HERE"
    origin_lat = math.radians(origin_latitude)
    target_lat = math.radians(target_latitude)
    delta_lon = math.radians(target_longitude - origin_longitude)
    x = math.sin(delta_lon) * math.cos(target_lat)
    y = math.cos(origin_lat) * math.sin(target_lat) - math.sin(
        origin_lat
    ) * math.cos(target_lat) * math.cos(delta_lon)
    bearing = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
    return _DIRECTIONS[int((bearing + 22.5) // 45.0) % len(_DIRECTIONS)]
