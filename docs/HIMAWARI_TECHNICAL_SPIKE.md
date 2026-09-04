# Himawari-9 AHI active-fire technical spike

Status: **conservative coverage foundation implemented; live provider blocked
pending a documented, stable machine-access endpoint**

## Decision

Himawari-9 AHI is a valuable future equal-peer active-fire source for Asia and
Australia. Its filtered FRP-PIXEL detections offer ten-minute observations at
approximately 2 km resolution at the sub-satellite point, normally reaching
NASA FIRMS within about 30 minutes. NASA classifies the geostationary stream as
provisional because false positives and missed detections remain possible.

TerraLyra must not enable the source yet. The documented FIRMS Area API used by
the existing provider exposes MODIS, NOAA-20/21 VIIRS, S-NPP VIIRS and Landsat,
but not the filtered geostationary Himawari layer. The FIRMS map displaying a
layer does not by itself constitute a supported feature-data API contract.

The repository therefore contains only a dependency-free, conservative
coverage selector. It is intentionally not imported by runtime source planning,
does not create entities, and performs no network requests.

## Official product and access findings

- Operational platform: Himawari-9, stationed near 140.7 degrees east.
- Instrument/product: AHI, filtered FRP-PIXEL active-fire detections.
- Geographic description: Asia and Australia; high latitudes and disk-edge
  pixels have increasingly degraded geometry.
- Nominal observation cadence: every 10 minutes.
- Typical FIRMS availability: about 30 minutes after observation.
- FIRMS status: non-NASA, provisional filtered geostationary layer, generally
  available for the most recent ten days.
- Producer: IPMA under the Copernicus Atmosphere Monitoring Service, using
  King's College London algorithms.
- JMA raw imagery: large HSD imagery is not a practical Home Assistant input;
  primary cloud access is aimed at meteorological services, while research
  redistribution is best-effort or commercial.
- Product access: King's College London currently directs prospective users to
  contact the group for near-real-time GOES/Himawari FRP access. Historical
  product documentation also describes an IPMA server, but this is not enough
  to assume anonymous, stable or licensed application access.

## Implemented foundation

`providers/himawari.py`:

- validates finite WGS84 coordinates;
- calculates the geocentric viewing angle from 140.7 degrees east;
- selects Himawari-9 only inside a conservative 70-degree central-angle gate;
- excludes Europe, the Americas and high-latitude/near-limb locations used by
  the regression tests;
- explicitly documents that product navigation and quality masks remain a
  mandatory second gate.

The 70-degree limit is an engineering safety boundary, not a claim about the
satellite's geometric horizon. It can be revised only using real product
navigation, pixel-footprint and validation data.

## Go/no-go gates for a live provider

1. Obtain written confirmation of a stable machine-readable NRT endpoint and
   its authentication, rate-limit and availability contract.
2. Confirm redistribution, attribution and open-source client use terms.
3. Obtain representative redistributable fixtures and the current product user
   manual for Himawari-9 output.
4. Validate filenames, satellite identity, timestamps, content type, compressed
   and decoded size, HDF5 structure, coordinates, fill values and quality flags.
5. Download only the small List Product; never fetch full-disk raw imagery or
   the much larger Quality Product for ordinary Home Assistant operation.
6. Benchmark memory, download size and decode time on Linux x86-64 and ARM64.
7. Keep provisional Himawari evidence visibly labelled and equal to—not above—
   other available satellite evidence.
8. Add isolated provider health, bounded retry, self-clearing Repair,
   diagnostics-redaction, localization and correlation tests.

## Recommended next action

Request NRT List Product access and integration terms from IPMA/KCL. While that
external gate is pending, evaluate MSG-IODC FRP-PIXEL as the next provider: it
has a documented LSA SAF data-service path and can reuse more of TerraLyra's
existing authentication and FRP decoding architecture.

## References

- NASA FIRMS Himawari-9 layer description:
  <https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_GOES_JAXA_Himawari-9.html>
- NASA FIRMS geostationary active-fire overview:
  <https://wiki.earthdata.nasa.gov/spaces/FIRMS/blog/2024/06/25/377718041/Geostationary%2BActive%2BFire%2BDetection%2BData%2Bin%2BFIRMS>
- NASA FIRMS Area API supported sources:
  <https://firms.modaps.eosdis.nasa.gov/api/area/>
- JMA Himawari data distribution overview:
  <https://www.data.jma.go.jp/mscweb/en/general/groundsystem.html>
- JMA Himawari Standard Data samples and file sizes:
  <https://www.data.jma.go.jp/mscweb/en/himawari89/space_segment/sample_hisd.html>
- King's College London FRP product access information:
  <https://wildfire.geog.kcl.ac.uk/products-and-data/>
