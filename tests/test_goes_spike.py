"""Tests for the dependency-free GOES technical spike."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.terralyra.providers.goes_spike import (
    expected_bucket,
    is_primary_candidate_for,
    parse_fdc_filename,
)


def test_parse_goes_full_disk_filename() -> None:
    """Stable NOAA identity and timestamps can be normalized without NetCDF."""
    filename = (
        "OR_ABI-L2-FDCF-M6_G19_s20262401200200_"
        "e20262401209508_c20262401210123.nc"
    )

    metadata = parse_fdc_filename(filename)

    assert metadata.satellite == "G19"
    assert metadata.sector == "F"
    assert metadata.scan_mode == 6
    assert metadata.observation_start == datetime(
        2026, 8, 28, 12, 0, 20, tzinfo=UTC
    )
    assert metadata.observation_end.microsecond == 800_000
    assert metadata.created_at > metadata.observation_end


@pytest.mark.parametrize(
    "filename",
    [
        "../../secret.nc",
        "OR_ABI-L2-FDCF-M6_G16_s20262401200200_e20262401209508_c20262401210123.nc",
        "OR_ABI-L2-FDCF-M6_G19_s20262401209508_e20262401200200_c20262401210123.nc",
        "OR_ABI-L2-FDCF-M6_G19_s20262401200200_e20262401209508_c20262401200000.nc",
        "OR_ABI-L2-FDCF-M6_G19_snotatime_e20262401209508_c20262401210123.nc",
    ],
)
def test_reject_unsupported_or_inconsistent_filename(filename: str) -> None:
    """Unexpected objects never reach a future parser or downloader."""
    with pytest.raises(ValueError):
        parse_fdc_filename(filename)


def test_fixed_public_bucket_allowlist() -> None:
    assert expected_bucket("G18") == "noaa-goes18"
    assert expected_bucket("G19") == "noaa-goes19"
    with pytest.raises(ValueError):
        expected_bucket("G20")


def test_coarse_coverage_gate_excludes_europe() -> None:
    """The spike cannot accidentally advertise GOES as a European provider."""
    assert is_primary_candidate_for(-100.0) is True
    assert is_primary_candidate_for(-25.0) is True
    assert is_primary_candidate_for(19.04) is False
    with pytest.raises(ValueError):
        is_primary_candidate_for(181.0)
