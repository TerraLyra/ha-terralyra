"""Provider-neutral coordinator for active-fire detections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .activity import ActivitySummary, summarize_activity, update_activity_history
from .clustering import cluster_detections, haversine_km
from .correlation import CorrelatedDetection, correlate_detections
from .const import (
    ATTR_NOTIFICATION_MESSAGE,
    ATTR_NOTIFICATION_TITLE,
    ATTR_PRODUCT_TIME,
    ATTR_SOURCE_URL,
    BUS_EVENT_FIRE_TREND,
    BUS_EVENT_NEW_FIRE,
    CONF_DEDUP_HOURS,
    CONF_FIRE_HISTORY_HOURS,
    CONF_DEDUP_RADIUS_KM,
    CONF_MIN_CONFIDENCE,
    CONF_MIN_FRP_MW,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DEDUP_HOURS,
    DEFAULT_FIRE_HISTORY_HOURS,
    DEFAULT_DEDUP_RADIUS_KM,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP_MW,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .geocoding import (
    GEONAMES_ATTRIBUTION,
    PlaceInfo,
    PlaceLookupError,
    PlaceNameResolver,
)
from .models import (
    ConfirmationLevel,
    DistanceTrend,
    FireCluster,
    FireDetection,
    FireLifecycle,
    MetricTrend,
    ProviderStatus,
)
from .providers.base import (
    ActiveFireProvider,
    ProviderAuthenticationError,
    ProviderNoDataError,
    ProviderUnavailableError,
)
from .situation import SituationAssessment, assess_situation
from .tracking import update_incidents

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


@dataclass(slots=True)
class CoordinatorData:
    """Data published to Home Assistant entities."""

    product_time: datetime
    source_url: str
    filename: str
    active_clusters: list[FireCluster]
    tracked_fires: list[FireCluster]
    new_fires: list[dict[str, Any]]
    trend_events: list[dict[str, Any]]
    raw_pixels_in_radius: int
    activity: ActivitySummary
    situation: SituationAssessment
    confirmation_level: ConfirmationLevel = ConfirmationLevel.DISABLED
    corroborating_detections: int = 0


class TerraLyraCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Fetch, filter, cluster, and deduplicate active-fire detections."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: ActiveFireProvider,
        place_resolver: PlaceNameResolver | None = None,
        *,
        corroboration_provider: ActiveFireProvider | None = None,
    ) -> None:
        self.entry = entry
        self.provider = provider
        self.corroboration_provider = corroboration_provider
        self.provider_status = ProviderStatus.INITIALIZING
        self.provider_name: str | None = None
        self.satellite: str | None = None
        self.provider_product: str | None = None
        self.product_timestamp: datetime | None = None
        self.received_timestamp: datetime | None = None
        self.corroboration_status = (
            ProviderStatus.INITIALIZING
            if corroboration_provider is not None
            else None
        )
        self.corroboration_provider_name: str | None = None
        self.corroboration_satellite: str | None = None
        self.corroboration_product_timestamp: datetime | None = None
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.tracks")
        self._tracks: list[dict[str, Any]] = []
        self._activity_history: list[dict[str, Any]] = []
        self._store_loaded = False
        self._initialized = False
        self._place_resolver = place_resolver
        self._pending_place_ids: set[str] = set()
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=int(entry.options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES))
            ),
        )

    async def _async_setup(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("tracks"), list):
            self._tracks = stored["tracks"]
            if isinstance(stored.get("activity_history"), list):
                self._activity_history = stored["activity_history"]
            self._initialized = bool(stored.get("initialized", True))
            for track in self._tracks:
                if track.get("place_attribution") != GEONAMES_ATTRIBUTION:
                    for key in (
                        "place_name",
                        "nearest_settlement",
                        "location_description",
                        "place_attribution",
                    ):
                        track.pop(key, None)
        self._store_loaded = True

    async def _async_update_data(self) -> CoordinatorData:
        try:
            snapshot = await self.provider.async_fetch_latest()
        except ProviderAuthenticationError as err:
            self._set_provider_failure_status(ProviderStatus.AUTH_ERROR)
            raise ConfigEntryAuthFailed from err
        except ProviderNoDataError as err:
            self._set_provider_failure_status(ProviderStatus.NO_PRODUCT)
            raise UpdateFailed(str(err)) from err
        except ProviderUnavailableError as err:
            self._set_provider_failure_status(ProviderStatus.OUTAGE)
            raise UpdateFailed(str(err)) from err

        self.provider_status = snapshot.status
        self.provider_name = snapshot.provider
        self.satellite = snapshot.satellite
        self.provider_product = snapshot.product
        self.product_timestamp = snapshot.product_timestamp
        self.received_timestamp = snapshot.received_timestamp

        corroboration_snapshot = None
        if self.corroboration_provider is not None:
            try:
                corroboration_snapshot = (
                    await self.corroboration_provider.async_fetch_latest()
                )
            except ProviderAuthenticationError:
                self.corroboration_status = ProviderStatus.AUTH_ERROR
            except ProviderNoDataError:
                self.corroboration_status = ProviderStatus.NO_PRODUCT
            except ProviderUnavailableError:
                self.corroboration_status = ProviderStatus.OUTAGE
            except Exception as err:  # noqa: BLE001
                # An optional secondary source must never stop primary
                # LSA SAF monitoring or expose its credential-bearing request.
                self.corroboration_status = ProviderStatus.OUTAGE
                _LOGGER.warning(
                    "NASA FIRMS corroboration failed safely: %s",
                    type(err).__name__,
                )
            else:
                self.corroboration_status = corroboration_snapshot.status
                self.corroboration_provider_name = corroboration_snapshot.provider
                self.corroboration_satellite = corroboration_snapshot.satellite
                self.corroboration_product_timestamp = (
                    corroboration_snapshot.product_timestamp
                )

        radius_km = float(self.entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        min_conf = float(self.entry.options.get(CONF_MIN_CONFIDENCE, DEFAULT_MIN_CONFIDENCE))
        min_frp = float(self.entry.options.get(CONF_MIN_FRP_MW, DEFAULT_MIN_FRP_MW))
        dedup_radius = float(self.entry.options.get(CONF_DEDUP_RADIUS_KM, DEFAULT_DEDUP_RADIUS_KM))
        dedup_hours = int(self.entry.options.get(CONF_DEDUP_HOURS, DEFAULT_DEDUP_HOURS))
        history_hours = int(
            self.entry.options.get(
                CONF_FIRE_HISTORY_HOURS, DEFAULT_FIRE_HISTORY_HOURS
            )
        )
        home_lat = float(self.hass.config.latitude)
        home_lon = float(self.hass.config.longitude)

        filtered: list[tuple[FireDetection, float]] = []
        for detection in snapshot.detections:
            confidence = detection.confidence or 0.0
            frp_mw = detection.frp_mw or 0.0
            if confidence < min_conf or frp_mw < min_frp:
                continue
            distance = haversine_km(
                home_lat, home_lon, detection.latitude, detection.longitude
            )
            if distance <= radius_km:
                filtered.append((detection, distance))

        clusters = cluster_detections(
            filtered,
            home_lat,
            home_lon,
            max(0.5, dedup_radius * 0.66),
        )
        correlated: tuple[CorrelatedDetection, ...] = ()
        if corroboration_snapshot is not None:
            secondary = tuple(
                detection
                for detection in corroboration_snapshot.detections
                if haversine_km(
                    home_lat,
                    home_lon,
                    detection.latitude,
                    detection.longitude,
                )
                <= radius_km
            )
            correlated = correlate_detections(
                tuple(detection for detection, _distance in filtered), secondary
            )
        confirmation_level, corroborating_count = _annotate_corroboration(
            clusters,
            correlated,
            provider_enabled=self.corroboration_provider is not None,
            provider_available=corroboration_snapshot is not None,
            cluster_radius_km=max(0.5, dedup_radius * 0.66),
        )
        new_fires: list[dict[str, Any]] = []
        trend_events: list[dict[str, Any]] = []
        first_snapshot = not self._initialized
        tracking = update_incidents(
            self._tracks,
            clusters,
            # Lifecycle age follows observation time, not wall-clock polling
            # time. A delayed but valid product must not expire and recreate
            # the same incident as a false new-fire alert.
            now=snapshot.product_timestamp,
            matching_radius_km=dedup_radius,
            memory_hours=dedup_hours,
            history_hours=history_hours,
        )
        self._tracks = tracking.incidents
        changed = tracking.changed
        for track, cluster in tracking.new_incidents:
            if not first_snapshot:
                await self._async_resolve_new_fire_place(track, cluster)
            attrs = cluster.attrs() | {
                ATTR_SOURCE_URL: snapshot.source_url,
                ATTR_PRODUCT_TIME: snapshot.product_timestamp.isoformat(),
            }
            if not first_snapshot:
                title, message = _notification_text(
                    self.hass.config.language,
                    cluster.nearest_settlement,
                    cluster.distance_km,
                    cluster.confidence,
                )
                attrs[ATTR_NOTIFICATION_TITLE] = title
                attrs[ATTR_NOTIFICATION_MESSAGE] = message
                new_fires.append(attrs)
                self.hass.bus.async_fire(BUS_EVENT_NEW_FIRE, attrs)

        for event_type, _track, cluster in tracking.trend_events:
            attrs = cluster.attrs() | {
                "event_type": event_type,
                ATTR_SOURCE_URL: snapshot.source_url,
                ATTR_PRODUCT_TIME: snapshot.product_timestamp.isoformat(),
            }
            trend_events.append(attrs)
            self.hass.bus.async_fire(BUS_EVENT_FIRE_TREND, attrs)

        if first_snapshot:
            self._initialized = True
            changed = True

        self._activity_history = update_activity_history(
            self._activity_history,
            timestamp=snapshot.product_timestamp,
            detections=len(filtered),
            total_frp_mw=sum(cluster.frp_mw for cluster in clusters),
            new_incidents=0 if first_snapshot else len(tracking.new_incidents),
        )
        activity = summarize_activity(
            self._activity_history, now=snapshot.product_timestamp
        )
        situation = assess_situation(
            clusters,
            provider_status=snapshot.status,
            product_time=snapshot.product_timestamp,
            now=snapshot.received_timestamp,
        )
        changed = True

        if changed and self._store_loaded:
            await self._async_save_state()

        if self._place_resolver is not None:
            for track in self._tracks:
                self._schedule_place_lookup(track)

        return CoordinatorData(
            product_time=snapshot.product_timestamp,
            source_url=snapshot.source_url,
            filename=snapshot.filename,
            active_clusters=clusters,
            tracked_fires=_tracked_fire_clusters(
                self._tracks,
                home_lat,
                home_lon,
                visible_since=(
                    snapshot.product_timestamp - timedelta(hours=history_hours)
                ),
            ),
            new_fires=new_fires,
            trend_events=trend_events,
            raw_pixels_in_radius=len(filtered),
            activity=activity,
            situation=situation,
            confirmation_level=confirmation_level,
            corroborating_detections=corroborating_count,
        )

    def _set_provider_failure_status(self, status: ProviderStatus) -> None:
        """Notify the health sensor when consecutive failures change type."""
        if self.provider_status is status:
            return
        self.provider_status = status
        self.async_update_listeners()

    async def _async_resolve_new_fire_place(
        self, track: dict[str, Any], cluster: FireCluster
    ) -> None:
        """Resolve a new fire before publishing its notification event."""
        if self._place_resolver is None:
            return
        try:
            place = await self._place_resolver.async_resolve(
                cluster.latitude, cluster.longitude
            )
        except PlaceLookupError as err:
            _LOGGER.debug("Could not resolve a new fire place name: %s", err)
            return
        _apply_place(track, cluster, place)

    def _schedule_place_lookup(self, track: dict[str, Any]) -> None:
        """Schedule one cached background lookup for an unresolved track."""
        track_id = str(track.get("track_id", ""))
        if (
            not track_id
            or track_id in self._pending_place_ids
            or track.get("location_description")
        ):
            return
        try:
            latitude = float(track["latitude"])
            longitude = float(track["longitude"])
        except (KeyError, TypeError, ValueError):
            return
        self._pending_place_ids.add(track_id)
        self.entry.async_create_background_task(
            self.hass,
            self._async_resolve_place(track_id, latitude, longitude),
            f"{DOMAIN} offline place lookup {track_id}",
        )

    async def _async_resolve_place(
        self, track_id: str, latitude: float, longitude: float
    ) -> None:
        """Resolve and persist a human-readable location for one fire."""
        try:
            if self._place_resolver is None:
                return
            place = await self._place_resolver.async_resolve(latitude, longitude)
            track = next(
                (item for item in self._tracks if item.get("track_id") == track_id),
                None,
            )
            if track is None:
                return
            _apply_place(track, None, place)
            await self._async_save_state()
            if self.data:
                for cluster in self.data.tracked_fires:
                    if cluster.track_id == track_id:
                        cluster.place_name = place.place_name
                        cluster.nearest_settlement = place.nearest_settlement
                        cluster.location_description = place.location_description
                        cluster.place_attribution = place.attribution
                        self.async_set_updated_data(self.data)
                        break
        except PlaceLookupError as err:
            _LOGGER.debug("Could not resolve place name for fire %s: %s", track_id, err)
        finally:
            self._pending_place_ids.discard(track_id)

    async def _async_save_state(self) -> None:
        """Persist incidents and bounded activity aggregates together."""
        await self._store.async_save(
            {
                "initialized": self._initialized,
                "tracks": self._tracks,
                "activity_history": self._activity_history,
            }
        )


def _apply_place(
    track: dict[str, Any], cluster: FireCluster | None, place: PlaceInfo
) -> None:
    """Apply one resolved place consistently to persisted and live data."""
    track["place_name"] = place.place_name
    track["nearest_settlement"] = place.nearest_settlement
    track["location_description"] = place.location_description
    track["place_attribution"] = place.attribution
    if cluster is not None:
        cluster.place_name = place.place_name
        cluster.nearest_settlement = place.nearest_settlement
        cluster.location_description = place.location_description
        cluster.place_attribution = place.attribution


def _annotate_corroboration(
    clusters: list[FireCluster],
    correlated: tuple[CorrelatedDetection, ...],
    *,
    provider_enabled: bool,
    provider_available: bool,
    cluster_radius_km: float,
) -> tuple[ConfirmationLevel, int]:
    """Attach bounded, explainable independent-source matches to clusters."""
    if not provider_enabled:
        return ConfirmationLevel.DISABLED, 0
    if not clusters:
        return (
            ConfirmationLevel.NO_ACTIVE_FIRE
            if provider_available
            else ConfirmationLevel.NOT_AVAILABLE,
            0,
        )
    total_matches = 0
    for cluster in clusters:
        matches = [
            match
            for item in correlated
            if haversine_km(
                cluster.latitude,
                cluster.longitude,
                item.primary.latitude,
                item.primary.longitude,
            )
            <= cluster_radius_km
            for match in item.matches
        ]
        unique_matches = {
            match.detection.source_detection_id
            or (
                f"{match.detection.provider}:{match.detection.satellite}:"
                f"{match.detection.timestamp.isoformat()}:"
                f"{match.detection.latitude:.5f}:{match.detection.longitude:.5f}"
            )
            for match in matches
        }
        cluster.corroborating_detections = len(unique_matches)
        total_matches += len(unique_matches)
        if unique_matches:
            cluster.confirmation_level = ConfirmationLevel.MULTI_SOURCE
            cluster.providers = ("eumetsat_lsa_saf", "nasa_firms")
        elif not provider_available:
            cluster.confirmation_level = ConfirmationLevel.NOT_AVAILABLE
        else:
            cluster.confirmation_level = ConfirmationLevel.SINGLE_SOURCE
    if total_matches:
        return ConfirmationLevel.MULTI_SOURCE, total_matches
    if not provider_available:
        return ConfirmationLevel.NOT_AVAILABLE, 0
    return ConfirmationLevel.SINGLE_SOURCE, 0


def _notification_text(
    language: str | None,
    settlement: str | None,
    distance_km: float,
    confidence: float,
) -> tuple[str, str]:
    """Build a concise localized mobile-notification title and message."""
    confidence_percent = round(confidence * 100)
    if (language or "").lower().startswith("hu"):
        distance = f"{distance_km:.1f}".replace(".", ",")
        location = f" {settlement} közelében" if settlement else ""
        return (
            "🔥 Tűzészlelés riasztás",
            f"Tűz észlelve{location}, {distance} km-re az otthonodtól. "
            f"Megbízhatóság: {confidence_percent}%.",
        )
    location = f" near {settlement}" if settlement else ""
    return (
        "🔥 Fire detection alert",
        f"Fire detected{location}, {distance_km:.1f} km from Home. "
        f"Confidence: {confidence_percent}%.",
    )


def _tracked_fire_clusters(
    tracks: list[dict[str, Any]],
    home_lat: float,
    home_lon: float,
    *,
    visible_since: datetime | None = None,
) -> list[FireCluster]:
    """Convert persisted recent tracks into map-ready fire clusters."""
    result: list[FireCluster] = []
    for track in tracks:
        try:
            latitude = float(track["latitude"])
            longitude = float(track["longitude"])
            acquired = _parse_dt(track.get("last_seen"))
            if visible_since is not None and acquired < visible_since:
                continue
            track_id = str(track["track_id"])
            confidence = float(track["confidence"])
            frp_mw = float(track["frp_mw"])
            pixel_count = int(track["pixel_count"])
            peak_frp_mw = float(track["peak_frp_mw"])
            lifecycle = FireLifecycle(str(track.get("lifecycle", "continuing")))
            first_seen = _parse_dt(track.get("first_seen"))
            last_seen = _parse_dt(track.get("last_seen"))
            minimum_distance_km = float(
                track.get(
                    "minimum_distance_km",
                    haversine_km(home_lat, home_lon, latitude, longitude),
                )
            )
            maximum_frp_mw = float(track.get("maximum_frp_mw", peak_frp_mw))
            maximum_pixel_count = int(track.get("maximum_pixel_count", pixel_count))
            detections_total = int(track.get("detections_total", pixel_count))
            maximum_confidence = float(track.get("maximum_confidence", confidence))
            frp_trend = MetricTrend(str(track.get("frp_trend", "unknown")))
            activity_trend = MetricTrend(
                str(track.get("activity_trend", "unknown"))
            )
            distance_trend = DistanceTrend(
                str(track.get("distance_trend", "unknown"))
            )
            trend_samples = int(track.get("trend_sample_count", 0))
            trend_window_minutes = float(track.get("trend_window_minutes", 0))
            confirmation_level = ConfirmationLevel(
                str(
                    track.get(
                        "confirmation_level",
                        ConfirmationLevel.SINGLE_SOURCE.value,
                    )
                )
            )
            providers = tuple(
                str(provider)
                for provider in track.get("providers", ["eumetsat_lsa_saf"])
            )
            corroborating_detections = int(
                track.get("corroborating_detections", 0)
            )
        except (KeyError, TypeError, ValueError):
            # Tracks written before v0.1.5 do not contain enough map metadata.
            continue
        result.append(
            FireCluster(
                latitude=latitude,
                longitude=longitude,
                distance_km=haversine_km(home_lat, home_lon, latitude, longitude),
                confidence=confidence,
                frp_mw=frp_mw,
                acquired=acquired,
                pixel_count=pixel_count,
                track_id=track_id,
                peak_frp_mw=peak_frp_mw,
                place_name=_optional_text(track.get("place_name")),
                nearest_settlement=_optional_text(track.get("nearest_settlement")),
                location_description=_optional_text(track.get("location_description")),
                place_attribution=_optional_text(track.get("place_attribution")),
                lifecycle=lifecycle,
                first_seen=first_seen,
                last_seen=last_seen,
                minimum_distance_km=minimum_distance_km,
                maximum_frp_mw=maximum_frp_mw,
                maximum_pixel_count=maximum_pixel_count,
                detections_total=detections_total,
                maximum_confidence=maximum_confidence,
                frp_trend=frp_trend,
                activity_trend=activity_trend,
                distance_trend=distance_trend,
                trend_samples=trend_samples,
                trend_window_minutes=trend_window_minutes,
                confirmation_level=confirmation_level,
                providers=providers,
                corroborating_detections=corroborating_detections,
            )
        )
    return sorted(result, key=lambda cluster: cluster.distance_km)


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_dt(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=UTC)
