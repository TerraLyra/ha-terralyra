"""Parser tests using a synthetic MTFRPPixel CSV payload."""
from datetime import UTC
import gzip

import pytest

from custom_components.terralyra.api import LsaSafError, validate_service_url
from custom_components.terralyra.clustering import haversine_km
from custom_components.terralyra.products.fire import (
    MAX_COMPRESSED_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    parse_product,
)

FILENAME = "LSA-509_MTG_MTFRPPIXEL-ListProduct_MTG-FD_202608211000.csv.gz"


def test_parse_product() -> None:
    csv_text = (
        "LATITUDE,LONGITUDE,FIRE_CONFIDENCE,FRP,ACQTIME,PIXEL_SIZE,FRP_UNCERTAINTY,ABS_LINE,ABS_SAMP\n"
        "46.30,20.18,0.91,12.4,20260821101030,1.2,2.1,100,200\n"
    )
    product = parse_product(FILENAME, "https://example.invalid/file", gzip.compress(csv_text.encode()))
    assert product.product_time.tzinfo == UTC
    assert len(product.pixels) == 1
    assert product.pixels[0].confidence == 0.91
    assert product.pixels[0].frp_mw == 12.4


def test_haversine() -> None:
    assert haversine_km(46.22, 20.19, 46.22, 20.19) == 0
    assert 10 < haversine_km(46.22, 20.19, 46.32, 20.19) < 12


@pytest.mark.parametrize(
    "url",
    [
        "http://datalsasaf.lsasvcs.ipma.pt/file",
        "https://evil.invalid/file",
        "https://datalsasaf.lsasvcs.ipma.pt.evil.invalid/file",
        "https://user:pass@datalsasaf.lsasvcs.ipma.pt/file",
        "https://datalsasaf.lsasvcs.ipma.pt:8443/file",
    ],
)
def test_service_url_rejects_credential_leak_destinations(url: str) -> None:
    with pytest.raises(LsaSafError, match="untrusted"):
        validate_service_url(url)


def test_service_url_accepts_official_https_host() -> None:
    validate_service_url("https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/file.csv.gz")


def test_rejects_oversized_compressed_payload() -> None:
    with pytest.raises(LsaSafError, match="Compressed"):
        parse_product(FILENAME, "https://example.invalid/file", b"x" * (MAX_COMPRESSED_BYTES + 1))


def test_rejects_gzip_bomb() -> None:
    payload = gzip.compress(b"x" * (MAX_UNCOMPRESSED_BYTES + 1))
    with pytest.raises(LsaSafError, match="Decompressed"):
        parse_product(FILENAME, "https://example.invalid/file", payload)


def test_rejects_malformed_gzip() -> None:
    with pytest.raises(LsaSafError, match="decompress"):
        parse_product(FILENAME, "https://example.invalid/file", b"not gzip")


def test_invalid_numeric_rows_are_discarded() -> None:
    rows = (
        "LATITUDE,LONGITUDE,FIRE_CONFIDENCE,FRP,ACQTIME\n"
        "91,20,0.5,1,20260821101030\n"
        "45,181,0.5,1,20260821101030\n"
        "45,20,nan,1,20260821101030\n"
        "45,20,0.5,inf,20260821101030\n"
        "45,20,1.1,1,20260821101030\n"
        "45,20,0.5,-1,20260821101030\n"
    )
    product = parse_product(FILENAME, "https://example.invalid/file", gzip.compress(rows.encode()))
    assert product.pixels == []


def test_rejects_extra_csv_columns() -> None:
    csv_text = "LATITUDE,LONGITUDE,FIRE_CONFIDENCE,FRP,ACQTIME\n1,2,.5,3,20260821101030,extra\n"
    product = parse_product(FILENAME, "https://example.invalid/file", gzip.compress(csv_text.encode()))
    assert product.pixels == []


def test_rejects_duplicate_columns() -> None:
    csv_text = "LATITUDE,LATITUDE,LONGITUDE,FIRE_CONFIDENCE,FRP,ACQTIME\n1,1,2,.5,3,20260821101030\n"
    with pytest.raises(LsaSafError, match="columns"):
        parse_product(FILENAME, "https://example.invalid/file", gzip.compress(csv_text.encode()))


def test_discards_implausible_acquisition_time() -> None:
    csv_text = "LATITUDE,LONGITUDE,FIRE_CONFIDENCE,FRP,ACQTIME\n1,2,.5,3,19990101000000\n"
    product = parse_product(FILENAME, "https://example.invalid/file", gzip.compress(csv_text.encode()))
    assert product.pixels == []
