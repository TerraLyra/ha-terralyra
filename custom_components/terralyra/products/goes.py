"""Bounded discovery of NOAA GOES ABI Fire/Hot Spot products."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
import os
from pathlib import Path
from pathlib import PurePosixPath
import tempfile
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout
from defusedxml import ElementTree as ET

from ..providers.goes_spike import GoesObjectMetadata, parse_fdc_filename
from .http import parse_retry_after

BUCKETS = {"G18": "noaa-goes18", "G19": "noaa-goes19"}
PRODUCT_PREFIX = "ABI-L2-FDCF"
MAX_KEYS = 100
MAX_LIST_BYTES = 512 * 1024
MAX_OBJECT_BYTES = 64 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_KEY_LENGTH = 512
TIMEOUT = ClientTimeout(total=20, connect=6, sock_read=12)
DOWNLOAD_TIMEOUT = ClientTimeout(total=60, connect=6, sock_read=30)
USER_AGENT = "ha-terralyra (https://github.com/TerraLyra/ha-terralyra)"


class GoesDiscoveryError(Exception):
    """The NOAA product catalogue returned an unsafe or invalid response."""

    def __init__(
        self,
        message: str,
        *,
        failure_type: str = "invalid_response",
        retry_after: timedelta | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.retry_after = retry_after


class GoesProductError(Exception):
    """A GOES product could not be downloaded and decoded safely."""

    def __init__(
        self,
        message: str,
        *,
        failure_type: str = "invalid_response",
        retry_after: timedelta | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.retry_after = retry_after


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
                timeout=DOWNLOAD_TIMEOUT,
            ) as response:
                retry_after = parse_retry_after(
                    getattr(response, "headers", {}).get("Retry-After")
                )
                if response.status == 429:
                    raise GoesDiscoveryError(
                        "NOAA GOES catalogue rate limited the request",
                        failure_type="rate_limit",
                        retry_after=retry_after,
                    )
                if 500 <= response.status <= 599:
                    raise GoesDiscoveryError(
                        f"NOAA GOES catalogue is temporarily unavailable ({response.status})",
                        failure_type="service_outage",
                        retry_after=retry_after,
                    )
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
        except TimeoutError as err:
            raise GoesDiscoveryError(
                "NOAA GOES catalogue request timed out", failure_type="timeout"
            ) from err
        except ClientError as err:
            raise GoesDiscoveryError(
                "NOAA GOES catalogue is unavailable",
                failure_type="service_outage",
            ) from err


class GoesProductClient:
    """Download one validated object and decode it outside the event loop.

    ``run_in_executor`` is normally ``hass.async_add_executor_job``. Keeping it
    injectable makes the download boundary testable without starting Home
    Assistant or importing the native decoder during ordinary discovery.
    """

    def __init__(
        self,
        session: ClientSession,
        run_in_executor: Callable[..., Awaitable[Any]],
        *,
        decoder: Callable[..., Any] | None = None,
        temp_directory: str | None = None,
    ) -> None:
        self._session = session
        self._run_in_executor = run_in_executor
        self._decoder = decoder
        self._temp_directory = temp_directory

    async def async_fetch(self, item: GoesObject) -> Any:
        """Download, verify, decode and always remove one temporary object."""
        _validate_download_object(item)
        path = await self._run_in_executor(
            _create_temp_file, self._temp_directory
        )
        try:
            await self._async_download(item, path)
            decoder = self._decoder
            if decoder is None:
                from .goes_decoder import decode_goes_fdc

                decoder = decode_goes_fdc
            return await self._run_in_executor(
                partial(
                    decoder,
                    path,
                    item.metadata,
                    source_url=item.public_url,
                )
            )
        except GoesProductError:
            raise
        except asyncio.CancelledError:
            raise
        except TimeoutError as err:
            raise GoesProductError(
                "NOAA GOES product request timed out", failure_type="timeout"
            ) from err
        except ClientError as err:
            raise GoesProductError(
                "NOAA GOES product is unavailable", failure_type="service_outage"
            ) from err
        except Exception as err:
            # Decoder details can contain native-library internals and local
            # paths. Expose only a stable, non-sensitive provider error here.
            raise GoesProductError("NOAA GOES product is invalid") from err
        finally:
            await _async_cleanup(self._run_in_executor, path)

    async def _async_download(self, item: GoesObject, path: Path) -> None:
        try:
            async with self._session.get(
                item.public_url,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
                timeout=TIMEOUT,
            ) as response:
                retry_after = parse_retry_after(
                    getattr(response, "headers", {}).get("Retry-After")
                )
                if response.status == 429:
                    raise GoesProductError(
                        "NOAA GOES product rate limited the request",
                        failure_type="rate_limit",
                        retry_after=retry_after,
                    )
                if 500 <= response.status <= 599:
                    raise GoesProductError(
                        f"NOAA GOES product is temporarily unavailable ({response.status})",
                        failure_type="service_outage",
                        retry_after=retry_after,
                    )
                if response.status != 200:
                    raise GoesProductError("NOAA GOES product returned an error")
                if (
                    response.content_length is not None
                    and response.content_length != item.size
                ):
                    raise GoesProductError("NOAA GOES product size changed")
                downloaded = 0
                async for chunk in response.content.iter_chunked(
                    DOWNLOAD_CHUNK_BYTES
                ):
                    downloaded += len(chunk)
                    if downloaded > item.size or downloaded > MAX_OBJECT_BYTES:
                        raise GoesProductError(
                            "NOAA GOES product exceeds the safety limit"
                        )
                    await self._run_in_executor(_append_file, path, bytes(chunk))
                if downloaded != item.size:
                    raise GoesProductError("NOAA GOES product is incomplete")
        except GoesProductError:
            raise
        except TimeoutError as err:
            raise GoesProductError(
                "NOAA GOES product request timed out", failure_type="timeout"
            ) from err
        except ClientError as err:
            raise GoesProductError(
                "NOAA GOES product is unavailable", failure_type="service_outage"
            ) from err


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


def _validate_download_object(item: GoesObject) -> None:
    """Revalidate an object before its URL reaches the HTTP client."""
    bucket = _bucket(item.metadata.satellite)
    expected_key = (
        catalogue_prefix(item.metadata.satellite, item.metadata.observation_start)
        + item.metadata.filename
    )
    if (
        item.size <= 0
        or item.size > MAX_OBJECT_BYTES
        or item.key != expected_key
        or item.public_url
        != f"https://{bucket}.s3.amazonaws.com/{quote(item.key, safe='/')}"
    ):
        raise GoesProductError("NOAA GOES download object is invalid")


def _create_temp_file(directory: str | None) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix="terralyra-goes-", suffix=".nc", dir=directory
    )
    os.close(descriptor)
    return Path(name)


def _append_file(path: Path, chunk: bytes) -> None:
    with path.open("ab") as output:
        output.write(chunk)


def _unlink_file(path: Path) -> None:
    path.unlink(missing_ok=True)


async def _async_cleanup(
    run_in_executor: Callable[..., Awaitable[Any]], path: Path
) -> None:
    """Finish cleanup even when the caller is being cancelled."""
    cleanup = asyncio.create_task(run_in_executor(_unlink_file, path))
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        await cleanup
        raise
