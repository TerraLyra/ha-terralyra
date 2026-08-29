"""Tests for the production-safe GOES discovery foundation."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.terralyra.products.goes import (
    GoesDiscoveryClient,
    GoesDiscoveryError,
    MAX_LIST_BYTES,
    catalogue_prefix,
    parse_catalogue,
)
from custom_components.terralyra.providers.goes import select_goes_satellite


def _catalogue(key: str, size: int = 8_000_000) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Contents><Key>{key}</Key><Size>{size}</Size></Contents>"
        "</ListBucketResult>"
    ).encode()


@pytest.mark.parametrize(
    ("latitude", "longitude", "satellite"),
    [
        (40.71, -74.01, "G19"),
        (34.05, -118.24, "G18"),
        (-33.45, -70.67, "G19"),
    ],
)
def test_selects_best_operational_satellite(
    latitude: float, longitude: float, satellite: str
) -> None:
    coverage = select_goes_satellite(latitude, longitude)
    assert coverage is not None
    assert coverage.satellite == satellite
    assert coverage.central_angle_degrees < 78


def test_coverage_gate_excludes_europe_and_invalid_coordinates() -> None:
    assert select_goes_satellite(47.4979, 19.0402) is None
    with pytest.raises(ValueError):
        select_goes_satellite(float("nan"), 0)
    with pytest.raises(ValueError):
        select_goes_satellite(0, 181)


def test_catalogue_prefix_is_utc_and_bounded() -> None:
    assert catalogue_prefix(
        "G19", datetime(2026, 8, 29, 1, 15, tzinfo=UTC)
    ) == "ABI-L2-FDCF/2026/241/01/"
    with pytest.raises(ValueError):
        catalogue_prefix("G16", datetime.now(UTC))
    with pytest.raises(ValueError):
        catalogue_prefix("G19", datetime(2026, 8, 29, 1, 15))


def test_parse_catalogue_returns_strict_public_object() -> None:
    prefix = "ABI-L2-FDCF/2026/241/01/"
    filename = (
        "OR_ABI-L2-FDCF-M6_G19_s20262410100200_"
        "e20262410109508_c20262410110123.nc"
    )
    (item,) = parse_catalogue(
        _catalogue(prefix + filename), satellite="G19", prefix=prefix
    )
    assert item.size == 8_000_000
    assert item.metadata.satellite == "G19"
    assert item.public_url.startswith("https://noaa-goes19.s3.amazonaws.com/")


@pytest.mark.parametrize(
    "payload",
    [
        b"not xml",
        b"<!DOCTYPE x [<!ENTITY y 'z'>]><x>&y;</x>",
        _catalogue("ABI-L2-FDCF/2026/241/02/other.nc"),
        _catalogue(
            "ABI-L2-FDCF/2026/241/01/"
            "OR_ABI-L2-FDCF-M6_G18_s20262410100200_"
            "e20262410109508_c20262410110123.nc"
        ),
        _catalogue(
            "ABI-L2-FDCF/2026/241/01/"
            "OR_ABI-L2-FDCF-M6_G19_s20262410100200_"
            "e20262410109508_c20262410110123.nc",
            size=100_000_000,
        ),
    ],
)
def test_catalogue_rejects_malformed_or_unsafe_objects(payload: bytes) -> None:
    with pytest.raises(GoesDiscoveryError):
        parse_catalogue(
            payload,
            satellite="G19",
            prefix="ABI-L2-FDCF/2026/241/01/",
        )


class _Content:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, _size: int):
        yield self._payload


class _Response:
    def __init__(
        self, payload: bytes, *, status: int = 200, content_length: int | None = None
    ) -> None:
        self.status = status
        self.content_length = len(payload) if content_length is None else content_length
        self.content = _Content(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_discovery_checks_two_hours_and_selects_newest() -> None:
    first_prefix = "ABI-L2-FDCF/2026/241/01/"
    previous_prefix = "ABI-L2-FDCF/2026/241/00/"
    newest = (
        "OR_ABI-L2-FDCF-M6_G19_s20262410100200_"
        "e20262410109508_c20262410110123.nc"
    )
    older = (
        "OR_ABI-L2-FDCF-M6_G19_s20262410050200_"
        "e20262410059508_c20262410100123.nc"
    )
    session = _Session(
        [
            _Response(_catalogue(first_prefix + newest)),
            _Response(_catalogue(previous_prefix + older)),
        ]
    )

    item = await GoesDiscoveryClient(session).async_latest(
        "G19", now=datetime(2026, 8, 29, 1, 15, tzinfo=UTC)
    )

    assert item is not None
    assert item.metadata.filename == newest
    assert len(session.calls) == 2
    for url, kwargs in session.calls:
        assert url == "https://noaa-goes19.s3.amazonaws.com/"
        assert kwargs["allow_redirects"] is False
        assert kwargs["params"]["max-keys"] == "100"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _Response(b"", status=301),
        _Response(b"", content_length=MAX_LIST_BYTES + 1),
    ],
)
async def test_discovery_rejects_redirect_or_oversized_response(
    response: _Response,
) -> None:
    session = _Session([response])
    with pytest.raises(GoesDiscoveryError):
        await GoesDiscoveryClient(session).async_latest(
            "G19", now=datetime(2026, 8, 29, 1, 15, tzinfo=UTC)
        )
