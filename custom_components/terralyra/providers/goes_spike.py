"""Network-free GOES ABI Fire/Hot Spot technical-spike helpers.

This module is deliberately not wired into Home Assistant.  It records and
tests the stable parts of a possible future GOES provider without introducing
NetCDF, S3, or HTTP dependencies into the production integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re

PROVIDER = "noaa_goes"
PRODUCT = "ABI-L2-FDC"
SUPPORTED_SATELLITES = frozenset({"G18", "G19"})
SUPPORTED_SECTORS = frozenset({"F", "C", "M1", "M2"})
PUBLIC_BUCKETS = {
    "G18": "noaa-goes18",
    "G19": "noaa-goes19",
}

# NOAA filenames use sYYYYJJJHHMMSSd, where JJJ is day of year and d is a
# tenth of a second.  Only the stable identity fields are parsed here.
_FILENAME_RE = re.compile(
    r"^OR_ABI-L2-FDC(?P<sector>F|C|M1|M2)-M(?P<mode>\d)_"
    r"(?P<satellite>G(?:18|19))_s(?P<start>\d{14})_"
    r"e(?P<end>\d{14})_c(?P<created>\d{14})\.nc$"
)


@dataclass(frozen=True, slots=True)
class GoesObjectMetadata:
    """Validated identity and timing fields from one NOAA FDC object."""

    satellite: str
    sector: str
    scan_mode: int
    observation_start: datetime
    observation_end: datetime
    created_at: datetime
    filename: str


def _parse_goes_time(value: str) -> datetime:
    """Parse NOAA's UTC year/day-of-year timestamp with a tenth of a second."""
    base = datetime.strptime(value[:13], "%Y%j%H%M%S").replace(tzinfo=UTC)
    return base.replace(microsecond=int(value[13]) * 100_000)


def parse_fdc_filename(filename: str) -> GoesObjectMetadata:
    """Parse a strict NOAA ABI L2 FDC filename.

    Strict parsing prevents arbitrary object names from entering a future
    download pipeline and provides deterministic product identity.
    """
    match = _FILENAME_RE.fullmatch(filename)
    if match is None:
        raise ValueError("Not a supported GOES ABI L2 FDC filename")

    start = _parse_goes_time(match["start"])
    end = _parse_goes_time(match["end"])
    created = _parse_goes_time(match["created"])
    if end < start or created < end:
        raise ValueError("GOES product timestamps are not monotonic")

    return GoesObjectMetadata(
        satellite=match["satellite"],
        sector=match["sector"],
        scan_mode=int(match["mode"]),
        observation_start=start,
        observation_end=end,
        created_at=created,
        filename=filename,
    )


def expected_bucket(satellite: str) -> str:
    """Return the fixed public NOAA bucket for a supported satellite."""
    try:
        return PUBLIC_BUCKETS[satellite]
    except KeyError as err:
        raise ValueError("Unsupported GOES satellite") from err


def is_primary_candidate_for(longitude: float) -> bool:
    """Return whether GOES is a sensible primary-provider candidate.

    This is intentionally conservative. GOES ABI observes the Western
    Hemisphere; Europe and the LSA SAF target region must not be routed to it.
    A later production adapter must replace this coarse gate with the actual
    product navigation/coverage mask before downloading data.
    """
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Longitude is outside the valid range")
    return longitude <= -25.0
