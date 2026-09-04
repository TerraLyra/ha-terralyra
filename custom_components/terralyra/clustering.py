"""Provider-neutral spatial helpers for active-fire detections."""
from __future__ import annotations

import math

from .models import ConfirmationLevel, FireCluster, FireDetection

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
    """Group connected nearby detections into provider-neutral incidents.

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
                <= _connection_radius_km(
                    detection,
                    member,
                    cluster_radius_km,
                )
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
        source_frp: dict[tuple[str, str], float] = {}
        source_counts: dict[tuple[str, str], int] = {}
        for item in group:
            source = _independent_source_key(item)
            source_frp[source] = source_frp.get(source, 0.0) + (
                item.frp_mw or 0.0
            )
            source_counts[source] = source_counts.get(source, 0) + 1
        # Independent satellites can observe the same energy. Use the largest
        # source total instead of adding equal observations twice.
        total_frp = max(source_frp.values(), default=0.0)
        if total_frp > 0:
            weights = [max(item.frp_mw or 0.0, 0.000001) for item in group]
            weight_total = sum(weights)
            latitude = (
                sum(
                    item.latitude * weight
                    for item, weight in zip(group, weights, strict=True)
                )
                / weight_total
            )
            longitude = (
                sum(
                    item.longitude * weight
                    for item, weight in zip(group, weights, strict=True)
                )
                / weight_total
            )
        else:
            latitude = sum(item.latitude for item in group) / len(group)
            longitude = sum(item.longitude for item in group) / len(group)
        providers = tuple(sorted({item.provider for item in group}))
        satellites = tuple(sorted({item.satellite for item in group}))
        independent_sources = len(source_counts)
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
                providers=providers,
                satellites=satellites,
                confirmation_level=(
                    ConfirmationLevel.MULTI_SOURCE
                    if independent_sources > 1
                    else ConfirmationLevel.SINGLE_SOURCE
                ),
                corroborating_detections=(
                    len(group) - max(source_counts.values())
                    if source_counts
                    else 0
                ),
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.distance_km)


def _connection_radius_km(
    left: FireDetection,
    right: FireDetection,
    configured_radius_km: float,
) -> float:
    """Allow realistic geolocation offsets only between independent sources."""
    if left.provider != right.provider or left.satellite != right.satellite:
        return max(configured_radius_km, 5.0)
    return configured_radius_km


def _independent_source_key(detection: FireDetection) -> tuple[str, str]:
    """Group feeds from one algorithm family without merging FIRMS satellites."""
    if detection.source_family is not None:
        return detection.source_family, ""
    return detection.provider, detection.satellite
