"""Provider-neutral spatial helpers for active-fire detections."""
from __future__ import annotations

import math

from .models import FireCluster, FireDetection

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def cluster_detections(
    detections: list[tuple[FireDetection, float]],
    home_latitude: float,
    home_longitude: float,
    cluster_radius_km: float,
) -> list[FireCluster]:
    """Group connected nearby detections from the same provider product.

    A connected-component pass avoids splitting one continuous group merely
    because its outermost pixels are farther apart than the configured radius.
    Every pixel must still be connected to another pixel in the same group by
    a hop no longer than ``cluster_radius_km``.
    """
    groups: list[list[FireDetection]] = []
    ordered = sorted(
        detections,
        key=lambda item: item[0].frp_mw or 0.0,
        reverse=True,
    )
    for detection, _distance in ordered:
        connected = [
            group
            for group in groups
            if any(
                haversine_km(
                    detection.latitude,
                    detection.longitude,
                    member.latitude,
                    member.longitude,
                )
                <= cluster_radius_km
                for member in group
            )
        ]
        if not connected:
            groups.append([detection])
        else:
            target = connected[0]
            target.append(detection)
            # The new detection can bridge groups that were previously
            # separate. Merge those groups now so one incident cannot produce
            # overlapping map markers solely because of input ordering.
            for other in connected[1:]:
                target.extend(other)
                groups.remove(other)

    clusters: list[FireCluster] = []
    for group in groups:
        total_frp = sum(item.frp_mw or 0.0 for item in group)
        if total_frp > 0:
            latitude = sum(
                item.latitude * (item.frp_mw or 0.0) for item in group
            ) / total_frp
            longitude = sum(
                item.longitude * (item.frp_mw or 0.0) for item in group
            ) / total_frp
        else:
            latitude = sum(item.latitude for item in group) / len(group)
            longitude = sum(item.longitude for item in group) / len(group)
        clusters.append(
            FireCluster(
                latitude=latitude,
                longitude=longitude,
                distance_km=haversine_km(
                    home_latitude, home_longitude, latitude, longitude
                ),
                confidence=max(item.confidence or 0.0 for item in group),
                frp_mw=total_frp,
                acquired=max(item.timestamp for item in group),
                pixel_count=len(group),
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.distance_km)
