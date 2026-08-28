# GOES ABI Fire/Hot Spot technical spike

Status: **research-only, not enabled in Home Assistant**

## Decision

GOES ABI Level 2 Fire/Hot Spot Characterization (FDC/FHS) is technically
suitable as a future provider for users in the Western Hemisphere. It is not a
general replacement or corroborating source for the integration's current
European target region. GOES-East and GOES-West observe the Western Hemisphere;
Hungary and most of Europe must continue to use an appropriate European/global
provider such as EUMETSAT LSA SAF or, in a later phase, NASA FIRMS.

The repository therefore contains only a dependency-free spike. Nothing is
registered as a Home Assistant platform, no new network request is made, and no
runtime dependency or configuration option is added.

## Official product and access path

- Product: NOAA GOES-R ABI Level 2 Fire/Hot Spot Characterization.
- Operational satellites considered by this spike: GOES-18 and GOES-19.
- Public archives: `noaa-goes18` and `noaa-goes19` in AWS Open Data.
- Product prefixes: `ABI-L2-FDCF` (full disk), `ABI-L2-FDCC` (CONUS), and
  `ABI-L2-FDCM` (mesoscale).
- File format: NetCDF4. Relevant variables include the fire mask, fire
  radiative power, fire temperature, fire area, geostationary projection, and
  data-quality metadata.
- Authentication: public archive access is unsigned; production use must still
  apply fixed-host/bucket validation, timeouts, size limits, and bounded reads.

Full-disk ABI imagery is normally available every ten minutes in Mode 6;
regional and mesoscale sectors can update more frequently. The provider must
use the actual file timestamp rather than assuming a fixed schedule.

## Mapping to the common model

| GOES field | `FireDetection` field | Rule |
|---|---|---|
| satellite ID | `satellite` | Preserve `G18` or `G19` |
| scan start/end | `timestamp` | Preserve UTC observation time |
| navigated pixel | `latitude`, `longitude` | Derive from the file projection |
| Power | `frp_mw` | Preserve units and fill values |
| Temp | `fire_temperature_k` | Optional; never invent a value |
| Area | `fire_area_km2` | Convert only from documented units |
| Mask category | `classification`, `quality` | Preserve the original category |
| temporal flag | `temporal_filtered` | Preserve; do not treat as independent proof |
| pixel geometry | `source_resolution_km` | Use actual navigated footprint if available |

The existing provider-neutral model already has every required destination
field. A GOES adapter must return a `ProviderSnapshot` and must not bypass the
common clustering, tracking, situation, diagnostics, or redaction layers.

## Main risks and required controls

1. **Coverage:** validate the actual navigation/coverage mask before fetching
   or presenting the provider. A longitude-only test is only an early gate.
2. **Large files:** list only the newest bounded set of keys; check metadata and
   enforce compressed/downloaded and decoded-array limits.
3. **NetCDF complexity:** do not add a heavy decoder to Home Assistant until a
   package-size, memory, ARM compatibility, and security review passes.
4. **Quality flags:** saturated, cloudy, high/medium/low probability, and
   temporally filtered pixels must remain distinguishable.
5. **Projection:** reject invalid coordinates and fill values. Test limb pixels
   and changing full-disk dimensions.
6. **Duplication:** do not count GOES-18/19 or temporally filtered observations
   as independent incident confirmation without spatial/time correlation.
7. **Freshness:** distinguish no fire, no product, delayed product, and outage.
8. **Network safety:** fixed NOAA endpoints only, HTTPS, TLS verification,
   redirects disabled or revalidated, bounded timeouts, redacted errors.

## Go/no-go gates for a production adapter

- Select and audit a Home Assistant-compatible NetCDF decoding strategy.
- Measure package size, peak memory, parse time, and downloaded bytes on common
  x86-64 and ARM Home Assistant installations.
- Verify current GOES-18/19 product maturity and operational transitions.
- Implement exact coverage checks from product navigation metadata.
- Add recorded, redistributable miniature fixtures for every supported sector
  and important quality category.
- Complete failure, malformed-file, decompression/array-size, SSRF, redirect,
  logging-redaction, and provider-correlation tests.
- Expose GOES only to locations actually covered and only as an explicit,
  optional provider.

## Recommended next implementation

Do not ship GOES in the next public release. Proceed with the independent LSA
SAF Land Surface Temperature module, then prioritize optional NASA FIRMS
correlation for broader active-fire corroboration. Revisit the GOES production
adapter when Western Hemisphere user demand and the NetCDF dependency review
justify it.

## References

- NOAA GOES-R Fire/Hot Spot product overview:
  <https://goes-r.noaa.gov/products/baseline-fire-hot-spot.html>
- NOAA/NCEI ABI L2 Fire/Hot Spot dataset and public archive access:
  <https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC01520>
- NOAA GOES-R ABI instrument and scan cadence:
  <https://www-prod.goesr.woc.noaa.gov/spacesegment/abi.html>
- NOAA STAR Fire and Hot Spot Characterization description:
  <https://www.star.nesdis.noaa.gov/goesr/product_land_fire.php>
