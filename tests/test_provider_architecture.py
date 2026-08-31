"""Regression tests for the provider-neutral active-fire pipeline."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.terralyra.api import LsaSafAuthError, LsaSafError
from custom_components.terralyra.clustering import cluster_detections
from custom_components.terralyra.const import CONF_ACTIVE_FIRE_PROVIDER
from custom_components.terralyra.models import (
    FireDetection,
    ProviderSnapshot,
    ProviderStatus,
)
from custom_components.terralyra.monitoring import MonitoredLocation, MonitoringCenter
from custom_components.terralyra.products.fire import (
    FirePixel,
    LsaSafNoDataError,
    Product,
)
from custom_components.terralyra.providers.base import (
    ProviderAuthenticationError,
    ProviderNoDataError,
    ProviderUnavailableError,
)
from custom_components.terralyra.providers.mtg import (
    PRODUCT,
    PROVIDER,
    SATELLITE,
    MtgActiveFireProvider,
)
from custom_components.terralyra.sensor import (
    ActiveFireCountSensor,
    ActiveFireProviderSensor,
    CombinedFireCountSensor,
    ProviderCoverageSensor,
    ProviderStatusSensor,
    SupplementalFireCountSensor,
)


def _detection(**changes) -> FireDetection:
    values = {
        "provider": PROVIDER,
        "satellite": SATELLITE,
        "product": PRODUCT,
        "timestamp": datetime(2026, 8, 27, 16, 20, tzinfo=UTC),
        "latitude": 46.25,
        "longitude": 20.14,
        "frp_mw": 10.0,
        "confidence": 0.8,
    }
    values.update(changes)
    return FireDetection(**values)


def test_provider_snapshot_is_immutable() -> None:
    """Provider results are stable values passed into common processing."""
    snapshot = ProviderSnapshot(
        provider=PROVIDER,
        satellite=SATELLITE,
        product=PRODUCT,
        product_timestamp=datetime(2026, 8, 27, 16, 20, tzinfo=UTC),
        received_timestamp=datetime(2026, 8, 27, 16, 22, tzinfo=UTC),
        status=ProviderStatus.AVAILABLE,
        source_url="https://example.invalid/product",
        filename="product.csv.gz",
        detections=(_detection(),),
    )

    with pytest.raises(AttributeError):
        snapshot.status = ProviderStatus.OUTAGE  # type: ignore[misc]


def test_independent_sources_with_small_location_offset_form_one_incident() -> None:
    acquired = datetime(2026, 8, 27, 16, 20, tzinfo=UTC)
    clusters = cluster_detections(
        [
            (
                _detection(
                    provider="EUMETSAT LSA SAF",
                    satellite="MTG",
                    timestamp=acquired,
                    latitude=46.250,
                    longitude=20.140,
                    frp_mw=10.0,
                ),
                0.0,
            ),
            (
                _detection(
                    provider="NASA FIRMS",
                    satellite="NOAA-20 VIIRS",
                    timestamp=acquired,
                    latitude=46.275,
                    longitude=20.140,
                    frp_mw=11.0,
                ),
                0.0,
            ),
        ],
        46.25,
        20.14,
        cluster_radius_km=1.0,
    )

    assert len(clusters) == 1
    assert clusters[0].confirmation_level.value == "multi_source"
    assert clusters[0].providers == ("EUMETSAT LSA SAF", "NASA FIRMS")
    assert clusters[0].frp_mw == 11.0


def test_same_source_keeps_configured_clustering_radius() -> None:
    clusters = cluster_detections(
        [
            (_detection(latitude=46.250, longitude=20.140), 0.0),
            (_detection(latitude=46.275, longitude=20.140), 0.0),
        ],
        46.25,
        20.14,
        cluster_radius_km=1.0,
    )

    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_mtg_adapter_preserves_product_values() -> None:
    """The MTG adapter maps every existing parser value without loss."""
    product_time = datetime.now(UTC)
    acquired = product_time + timedelta(seconds=30)
    pixel = FirePixel(
        latitude=46.25,
        longitude=20.14,
        confidence=0.91,
        frp_mw=12.4,
        acquired=acquired,
        pixel_size_km2=1.2,
        frp_uncertainty_mw=2.1,
        abs_line=100,
        abs_samp=200,
    )
    client = AsyncMock()
    client.async_fetch_latest.return_value = Product(
        filename="product.csv.gz",
        url="https://example.invalid/product",
        product_time=product_time,
        pixels=[pixel],
    )

    snapshot = await MtgActiveFireProvider(client).async_fetch_latest()
    detection = snapshot.detections[0]

    assert snapshot.provider == PROVIDER
    assert snapshot.status is ProviderStatus.AVAILABLE
    assert snapshot.product_timestamp == product_time
    assert detection.timestamp == acquired
    assert detection.latitude == pixel.latitude
    assert detection.longitude == pixel.longitude
    assert detection.frp_mw == pixel.frp_mw
    assert detection.frp_uncertainty_mw == pixel.frp_uncertainty_mw
    assert detection.confidence == pixel.confidence
    assert detection.fire_area_km2 == pixel.pixel_size_km2
    assert detection.source_detection_id.endswith(":100:200")


@pytest.mark.asyncio
async def test_mtg_adapter_marks_old_products_as_delayed() -> None:
    """A valid but old product is distinct from a current product or outage."""
    client = AsyncMock()
    client.async_fetch_latest.return_value = Product(
        filename="old.csv.gz",
        url="https://example.invalid/old",
        product_time=datetime.now(UTC) - timedelta(hours=2),
        pixels=[],
    )

    snapshot = await MtgActiveFireProvider(client).async_fetch_latest()

    assert snapshot.status is ProviderStatus.DELAYED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_error", "provider_error"),
    [
        (LsaSafAuthError("auth"), ProviderAuthenticationError),
        (LsaSafNoDataError("missing"), ProviderNoDataError),
        (LsaSafError("outage"), ProviderUnavailableError),
    ],
)
async def test_mtg_adapter_normalizes_provider_errors(
    source_error: Exception, provider_error: type[Exception]
) -> None:
    """The common coordinator does not depend on MTG-specific exceptions."""
    client = AsyncMock()
    client.async_fetch_latest.side_effect = source_error

    with pytest.raises(provider_error):
        await MtgActiveFireProvider(client).async_fetch_latest()


def test_common_clustering_preserves_mtg_aggregation() -> None:
    """Common clustering retains weighted centroid and peak confidence logic."""
    first = _detection(frp_mw=10.0, confidence=0.8)
    second = _detection(
        latitude=46.251,
        longitude=20.141,
        frp_mw=30.0,
        confidence=0.95,
    )

    clusters = cluster_detections(
        [(first, 10.0), (second, 10.1)],
        home_latitude=46.2,
        home_longitude=20.1,
        cluster_radius_km=1.0,
    )

    assert len(clusters) == 1
    assert clusters[0].pixel_count == 2
    assert clusters[0].frp_mw == 40.0
    assert clusters[0].confidence == 0.95
    assert clusters[0].latitude == pytest.approx(46.25075)
    assert clusters[0].longitude == pytest.approx(20.14075)


def test_clustering_merges_connected_pixels_independent_of_seed_distance() -> None:
    """A bridging pixel keeps one continuous fire group as one cluster."""
    detections = [
        (
            _detection(provider="nasa_firms", latitude=46.000, longitude=20.000),
            0.0,
        ),
        (
            _detection(
                provider="nasa_firms", latitude=46.009, longitude=20.000
            ),
            1.0,
        ),
        (
            _detection(
                provider="nasa_firms", latitude=46.018, longitude=20.000
            ),
            2.0,
        ),
    ]

    clusters = cluster_detections(
        detections,
        home_latitude=46.0,
        home_longitude=20.0,
        cluster_radius_km=1.1,
    )

    assert len(clusters) == 1
    assert clusters[0].pixel_count == 3


def test_common_model_accepts_provider_specific_missing_values() -> None:
    """Providers are not forced to invent confidence, FRP, or quality values."""
    detection = _detection(
        frp_mw=None,
        confidence=None,
        quality=None,
        classification=None,
    )

    assert detection.frp_mw is None
    assert detection.confidence is None


def test_provider_status_sensor_remains_available_during_outage() -> None:
    """Automations can distinguish an outage from a valid zero-fire result."""
    product_time = datetime(2026, 8, 27, 16, 20, tzinfo=UTC)
    received_time = datetime(2026, 8, 27, 16, 22, tzinfo=UTC)
    entity = object.__new__(ProviderStatusSensor)
    entity.coordinator = SimpleNamespace(
        provider_status=ProviderStatus.OUTAGE,
        provider_name=PROVIDER,
        satellite=SATELLITE,
        provider_product=PRODUCT,
        product_timestamp=product_time,
        received_timestamp=received_time,
    )

    assert entity.available is True
    assert entity.native_value == "outage"
    assert entity.extra_state_attributes == {
        "provider": PROVIDER,
        "satellite": SATELLITE,
        "product": PRODUCT,
        "product_timestamp": product_time.isoformat(),
        "received_timestamp": received_time.isoformat(),
    }


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("eumetsat_lsa_saf", "eumetsat_lsa_saf"),
        ("noaa_goes", "noaa_goes"),
        (None, "eumetsat_lsa_saf"),
        ("unexpected", "unknown"),
    ],
)
def test_active_fire_provider_sensor_has_stable_translated_states(
    provider: str | None, expected: str
) -> None:
    entity = object.__new__(ActiveFireProviderSensor)
    entity.entry = SimpleNamespace(
        data={CONF_ACTIVE_FIRE_PROVIDER: provider}
        if provider is not None
        else {}
    )
    entity.coordinator = SimpleNamespace(
        provider_name="nasa_firms",
        corroboration_provider_name="nasa_firms",
        satellite="G19",
        provider_product="ABI-L2-FDCF",
        monitoring_center=MonitoringCenter("New York", 40.7128, -74.006, True),
    )

    assert entity.native_value == expected
    assert entity.extra_state_attributes == {
        "observed_provider": "nasa_firms",
        "corroborating_provider": "nasa_firms",
        "satellite": "G19",
        "product": "ABI-L2-FDCF",
        "monitoring_center": "New York",
        "monitoring_latitude": 40.7128,
        "monitoring_longitude": -74.006,
        "custom_monitoring_center": True,
    }


def test_provider_coverage_sensor_separates_health_and_geography() -> None:
    entity = object.__new__(ProviderCoverageSensor)
    entity.entry = SimpleNamespace(
        data={CONF_ACTIVE_FIRE_PROVIDER: "eumetsat_lsa_saf"}
    )
    entity.coordinator = SimpleNamespace(
        provider_status=ProviderStatus.AVAILABLE,
        monitored_locations=(
            MonitoredLocation(
                id="home",
                name="Budapest",
                latitude=47.4979,
                longitude=19.0402,
                radius_km=25,
                enabled=True,
                source="manual",
            ),
            MonitoredLocation(
                id="test",
                name="California test",
                latitude=38.5618,
                longitude=-121.6263,
                radius_km=100,
                enabled=True,
                source="manual",
            ),
        ),
    )

    assert entity.native_value == "partial"
    attrs = entity.extra_state_attributes
    assert attrs["provider_status"] == "available"
    assert attrs["covered_locations"] == 1
    assert attrs["uncovered_locations"] == 1
    assert attrs["locations"][1]["recommended_provider"] == "noaa_goes"


@pytest.mark.parametrize("data", [None, SimpleNamespace(active_clusters=[], tracked_fires=[])])
def test_active_fire_summary_identifies_terralyra_map_source(data: object) -> None:
    """Map-card support information stays explicit even with no detections."""
    entity = object.__new__(ActiveFireCountSensor)
    entity.entry = SimpleNamespace(data={})
    entity.coordinator = SimpleNamespace(data=data)

    assert entity.extra_state_attributes["map_source"] == "terralyra"
    assert entity.extra_state_attributes["map_markers"] == 0


def test_source_specific_and_combined_counts_do_not_double_count() -> None:
    """The combined count adds only unmatched supplemental FIRMS clusters."""
    data = SimpleNamespace(
        active_clusters=[object(), object()],
        supplemental_clusters=[object(), object(), object()],
        tracked_fires=[],
    )
    primary = object.__new__(ActiveFireCountSensor)
    primary.entry = SimpleNamespace(data={CONF_ACTIVE_FIRE_PROVIDER: "noaa_goes"})
    primary.coordinator = SimpleNamespace(data=data)
    supplemental = object.__new__(SupplementalFireCountSensor)
    supplemental.coordinator = SimpleNamespace(data=data)
    combined = object.__new__(CombinedFireCountSensor)
    combined.coordinator = SimpleNamespace(data=data)

    assert primary.native_value == 2
    assert supplemental.native_value == 3
    assert combined.native_value == 5
    assert primary.extra_state_attributes["count_scope"] == (
        "configured_primary_provider_only"
    )
    assert supplemental.extra_state_attributes["deduplicated_against_primary"] is True
    assert combined.extra_state_attributes == {
        "primary_clusters": 2,
        "nasa_firms_supplemental_clusters": 3,
        "count_scope": "deduplicated_current_clusters_all_sources",
    }
