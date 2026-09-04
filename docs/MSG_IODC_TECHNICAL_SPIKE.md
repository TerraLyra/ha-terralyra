# MSG-IODC FRP-PIXEL technical spike

Status: **schema validated against a current product; bounded decoder and live
coverage-gated provider implemented in TerraLyra 0.13.0**

## Decision

MSG-IODC is a strong candidate for TerraLyra's next active-fire source. LSA SAF
publishes the demonstration FRP-PIXEL product through its existing Data Service
under `MSG-IODC/FRP-PIXEL`. It uses Meteosat-9 SEVIRI observations from 45.5
degrees east, has approximately 3 km nadir resolution and a 15-minute cadence.
The existing TerraLyra LSA SAF account and HTTP security boundary can therefore
be reused.

The source was kept runtime-disabled until a representative List Product was
inspected and its validated schema was turned into a tiny synthetic test fixture.
Directory listings alone were not used as a parser contract. The development-only
`tools/probe_msg_iodc.py` utility retrieves one recent product using credentials
from process environment variables, keeps it only in memory, reads metadata but
not science-array values, and emits bounded JSON suitable for schema review.
The response-only `terralyra.probe_msg_iodc` Home Assistant action applies the
same limits using the credentials already stored in the selected TerraLyra
configuration entry. It returns the sanitized schema to the caller without
persisting either the product or the result.

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
The production decoder also validates product identity and quality, and rejects
pixels with invalid coordinates or acquisition times.

The provider-neutral detection model now also supports `source_family`. This
prevents overlapping MTG and MSG-IODC observations derived by the same LSA SAF
FRP family from being incorrectly described as two independent confirmations.
They may be equal observing feeds without being statistically independent.

## Completed activation slice

1. Inspected one current representative product through the response-only
   compatibility action and reviewed its sanitized metadata.
2. Created a tiny synthetic HDF5 fixture containing only the required schema.
3. Implemented a bounded decoder that reads only List Products and rejects
   redirects, oversized files, unknown filenames, missing datasets and unsafe
   coordinates or timestamps.
4. Added deterministic 15-minute filename probing with bounded lookback and
   provider-specific health/retry state.
5. Grouped downloads by satellite coverage and match detections locally to all
   relevant monitored locations.
6. Exposed Meteosat-9 IODC as an equal feed, while using `source_family` to keep
   independent-confirmation claims scientifically accurate.
7. Added privacy-safe diagnostics and provider-specific health/backoff. The
   existing translated generic source-health Repair path is reused.

## Official references

- LSA SAF fire products and data access:
  <https://lsa-saf.eumetsat.int/en/data/products/fire-products/>
- LSA SAF MSG-IODC FRP-PIXEL Data Service:
  <https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG-IODC/FRP-PIXEL/>
- EUMETSAT MSG Indian Ocean Data Coverage service:
  <https://user.eumetsat.int/data/satellites/meteosat-second-generation/indian-ocean-data-coverage>
