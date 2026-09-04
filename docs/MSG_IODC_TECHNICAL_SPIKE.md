# MSG-IODC FRP-PIXEL technical spike

Status: **documented access path, conservative coverage foundation and bounded
schema probe implemented; live ingestion awaits a validated synthetic fixture
and decoder**

## Decision

MSG-IODC is a strong candidate for TerraLyra's next active-fire source. LSA SAF
publishes the demonstration FRP-PIXEL product through its existing Data Service
under `MSG-IODC/FRP-PIXEL`. It uses Meteosat-9 SEVIRI observations from 45.5
degrees east, has approximately 3 km nadir resolution and a 15-minute cadence.
The existing TerraLyra LSA SAF account and HTTP security boundary can therefore
be reused.

The source remains runtime-disabled until a representative List Product is
inspected and its validated schema is turned into a tiny synthetic test fixture.
Directory listings alone are not a safe parser contract. The development-only
`tools/probe_msg_iodc.py` utility retrieves one recent product using credentials
from process environment variables, keeps it only in memory, reads metadata but
not science-array values, and emits bounded JSON suitable for schema review.

## Verified access characteristics

- Product: MSG-IODC FRP-PIXEL, demonstration status.
- Platform: Meteosat-9 / SEVIRI at 45.5 degrees east.
- Published coverage description: Europe, Africa and the Middle East.
- Nominal spatial resolution: 3 km at the sub-satellite point.
- Nominal temporal resolution: 15 minutes.
- Data Service path: `PRODUCTS/MSG-IODC/FRP-PIXEL/HDF5/YYYY/MM/DD/`.
- List Product filename pattern:
  `HDF5_LSASAF_MSG-IODC_FRP-PIXEL-ListProduct_IODC-Disk_YYYYMMDDHHMM`.
- Typical indexed List Product size is small (roughly 90–300 KB), but the
  decoder must enforce independent compressed/downloaded and decoded limits.
- LSA SAF products are published under CC BY 4.0 with the requested
  attribution.
- The IODC service has no in-flight backup satellite, so longer outages are a
  documented operational possibility and must not stop peer providers.

## Implemented foundation

`providers/msg_iodc.py` validates WGS84 coordinates and selects Meteosat-9 only
inside a conservative 70-degree central-angle gate around 45.5 degrees east.
This pre-download check is intentionally narrower than the geometric horizon.
The eventual decoder must still reject pixels outside the actual navigation and
quality masks.

The provider-neutral detection model now also supports `source_family`. This
prevents overlapping MTG and MSG-IODC observations derived by the same LSA SAF
FRP family from being incorrectly described as two independent confirmations.
They may be equal observing feeds without being statistically independent.

## Required next implementation slice

1. Run the bounded schema probe for one current, representative List Product
   using the user's existing LSA SAF account; do not commit its output until the
   metadata has been reviewed for safe redistribution.
2. Create a tiny synthetic HDF5 fixture containing only the required schema.
3. Implement a bounded decoder that reads only List Products and rejects
   redirects, oversized files, unknown filenames, missing datasets and unsafe
   coordinates or timestamps.
4. Add deterministic 15-minute filename probing with bounded lookback and
   provider-specific health/retry state.
5. Group downloads by satellite coverage and match detections locally to all
   relevant monitored locations.
6. Expose Meteosat-9 IODC as an equal feed, while using `source_family` to keep
   independent-confirmation claims scientifically accurate.
7. Add translations, diagnostics redaction, self-clearing Repairs and Linux
   x86-64/ARM64 decoder tests before runtime activation.

## Official references

- LSA SAF fire products and data access:
  <https://lsa-saf.eumetsat.int/en/data/products/fire-products/>
- LSA SAF MSG-IODC FRP-PIXEL Data Service:
  <https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG-IODC/FRP-PIXEL/>
- EUMETSAT MSG Indian Ocean Data Coverage service:
  <https://user.eumetsat.int/data/satellites/meteosat-second-generation/indian-ocean-data-coverage>
