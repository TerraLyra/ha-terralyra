"""Bounded discovery of NOAA GOES ABI Fire/Hot Spot products."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import quote
import xml.etree.ElementTree as ET

from aiohttp import ClientError, ClientSession, ClientTimeout

from ..providers.goes_spike import GoesObjectMetadata, parse_fdc_filename

BUCKETS = {"G18": "noaa-goes18", "G19": "noaa-goes19"}
PRODUCT_PREFIX = "ABI-L2-FDCF"
MAX_KEYS = 100
MAX_LIST_BYTES = 512 * 1024
MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_KEY_LENGTH = 512
TIMEOUT = ClientTimeout(total=20, connect=6, sock_read=12)
USER_AGENT = "ha-terralyra (https://github.com/TerraLyra/ha-terralyra)"


class GoesDiscoveryError(Exception):
    """The NOAA product catalogue returned an unsafe or invalid response."""


@dataclass(frozen=True, slots=True)
class GoesObject:
    """One validated public NOAA object ready for a later bounded download."""

    metadata: GoesObjectMetadata
    key: str
    size: int
    public_url: str


class GoesDiscoveryClient:
    """List only the two newest possible full-disk product hours."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_latest(
        self, satellite: str, *, now: datetime | None = None
    ) -> GoesObject | None:
        """Return the newest safely validated catalogue object."""
        current = _as_utc(now or datetime.now(UTC))
        objects: list[GoesObject] = []
        for hour in (current, current - timedelta(hours=1)):
            prefix = catalogue_prefix(satellite, hour)
            payload = await self._async_list(satellite, prefix)
            objects.extend(parse_catalogue(payload, satellite=satellite, prefix=prefix))
        return max(
            objects,
            key=lambda item: item.metadata.observation_end,
            default=None,
        )

    async def _async_list(self, satellite: str, prefix: str) -> bytes:
        bucket = _bucket(satellite)
        url = f"https://{bucket}.s3.amazonaws.com/"
        try:
            async with self._session.get(
                url,
                params={
                    "list-type": "2",
                    "prefix": prefix,
                    "max-keys": str(MAX_KEYS),
                },
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise GoesDiscoveryError("NOAA GOES catalogue returned an error")
                if (
                    response.content_length is not None
                    and response.content_length > MAX_LIST_BYTES
                ):
                    raise GoesDiscoveryError(
                        "NOAA GOES catalogue exceeds the safety limit"
                    )
                data = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_LIST_BYTES:
                        raise GoesDiscoveryError(
                            "NOAA GOES catalogue exceeds the safety limit"
                        )
                return bytes(data)
        except GoesDiscoveryError:
            raise
        except (ClientError, TimeoutError) as err:
            raise GoesDiscoveryError("NOAA GOES catalogue is unavailable") from err


def catalogue_prefix(satellite: str, hour: datetime) -> str:
    """Return a strict full-disk catalogue prefix for one UTC hour."""
    _bucket(satellite)
    value = _as_utc(hour)
    return f"{PRODUCT_PREFIX}/{value:%Y/%j/%H}/"


def parse_catalogue(
    payload: bytes, *, satellite: str, prefix: str
) -> tuple[GoesObject, ...]:
    """Parse a bounded S3 ListObjects response and reject unexpected keys."""
    bucket = _bucket(satellite)
    if len(payload) > MAX_LIST_BYTES:
        raise GoesDiscoveryError("NOAA GOES catalogue exceeds the safety limit")
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise GoesDiscoveryError("NOAA GOES catalogue contains forbidden XML")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as err:
        raise GoesDiscoveryError("NOAA GOES catalogue is not valid XML") from err

    result: list[GoesObject] = []
    for contents in root.findall("{*}Contents"):
        key = (contents.findtext("{*}Key") or "").strip()
        size_text = (contents.findtext("{*}Size") or "").strip()
        if (
            not key.startswith(prefix)
            or len(key) > MAX_KEY_LENGTH
            or key != prefix + PurePosixPath(key).name
        ):
            raise GoesDiscoveryError("NOAA GOES catalogue contains an unexpected key")
        try:
            size = int(size_text)
            metadata = parse_fdc_filename(PurePosixPath(key).name)
        except (TypeError, ValueError) as err:
            raise GoesDiscoveryError("NOAA GOES catalogue metadata is invalid") from err
        if metadata.satellite != satellite or size <= 0 or size > MAX_OBJECT_BYTES:
            raise GoesDiscoveryError("NOAA GOES object exceeds safety constraints")
        result.append(
            GoesObject(
                metadata=metadata,
                key=key,
                size=size,
                public_url=f"https://{bucket}.s3.amazonaws.com/{quote(key, safe='/')}",
            )
        )
        if len(result) > MAX_KEYS:
            raise GoesDiscoveryError("NOAA GOES catalogue contains too many objects")
    return tuple(result)


def _bucket(satellite: str) -> str:
    try:
        return BUCKETS[satellite]
    except KeyError as err:
        raise ValueError("Unsupported GOES satellite") from err


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("GOES catalogue time must include a timezone")
    return value.astimezone(UTC)
