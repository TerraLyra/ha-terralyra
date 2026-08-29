# GOES FDCF decoder benchmark

Date: **2026-08-29**  
Host: Apple ARM64, Python 3.12 for runtime measurements; Python 3.14 wheel
availability checked separately against PyPI.

## Decision

**Conditional go with direct `h5py`.** Do not use `netCDF4`, `h5netcdf`, or
`xarray` in the Home Assistant runtime path.

The next implementation may add an explicit, coverage-gated GOES option using
`h5py`, provided that:

- it remains disabled by default;
- the user is told about the additional download, storage and memory cost;
- only the newest validated FDCF object is downloaded;
- the existing 64 MiB object limit and fixed NOAA hosts remain enforced;
- decoding runs outside the Home Assistant event loop;
- the mask is scanned in bounded row stripes and detail arrays are read only at
  selected fire pixels;
- exact navigation, quality-category and fill-value tests use redistributable
  miniature fixtures before public activation.

## Samples

Fresh full-disk `ABI-L2-FDCF` objects were discovered through the public NOAA
GOES buckets and downloaded over HTTPS:

| Satellite | Downloaded bytes | Grid | Fire-mask pixels |
|---|---:|---:|---:|
| GOES-18 | 1,177,467 | 5424 × 5424 | 8 |
| GOES-19 | 1,759,869 | 5424 × 5424 | 120 |

The files were retained only in the local benchmark workspace and are not
committed to the integration repository.

## Method

Each decoder ran in a separate clean ARM64 virtual environment. The benchmark:

1. scanned `Mask` in 24-row stripes;
2. selected documented fire and temporally filtered fire categories;
3. read `Power`, `Temp`, `Area`, and `DQF` only for selected pixels;
4. applied `_FillValue`, `valid_range`, `scale_factor`, and `add_offset`
   consistently in benchmark code;
5. converted sample fixed-grid coordinates with the file's own geostationary
   projection metadata;
6. measured wall time and process peak resident memory.

All three decoders returned identical fire-pixel counts, valid-value counts,
FRP sums, projection metadata and sample coordinates for both satellites.

## Results

| Decoder | Installed clean environment | Typical GOES-18 / GOES-19 time | Peak RSS | Assessment |
|---|---:|---:|---:|---|
| direct `h5py` 3.16.0 | ~58 MiB | 0.26–0.35 s / 0.53–0.56 s | ~52 MiB | **Selected** |
| `h5netcdf` 1.8.1 + `h5py` | ~59 MiB | 0.39–0.60 s / 0.80–0.95 s | ~44–45 MiB | Extra abstraction without a needed benefit |
| `netCDF4` 1.7.4 | ~106 MiB | 0.30–0.97 s / 0.34–0.38 s | ~106–133 MiB | Rejected for size and memory |

One initial `netCDF4` run also took approximately 6.7 seconds, reinforcing the
preference for the simpler direct reader even though later warm runs were fast.

The clean `h5py` environment consisted mainly of approximately 34 MiB NumPy
and 11 MiB `h5py` package directories. If a compatible NumPy is already present
in Home Assistant, the incremental installed cost is therefore around 11 MiB;
otherwise the combined dependency cost is roughly 45 MiB. Current ARM64 wheel
downloads are substantially smaller than their installed directories.

## Data-shape findings

- The full 5424 × 5424 arrays must never be decoded together.
- FDCF uses compressed row-oriented chunks; bounded stripe scanning stays near
  44–52 MiB peak RSS in the tested direct paths.
- `Power`, `Temp`, and `Area` are not available for every fire-mask category.
  Missing values must remain missing rather than being fabricated.
- Temporally filtered mask values must stay distinguishable and must not count
  as independent corroboration by themselves.
- The projection longitude was −137° for GOES-18 and −75° for GOES-19.
- Independently decoded sample coordinates were identical across all three
  engines and fell inside the expected Western Hemisphere coverage.

## Compatibility evidence

- NOAA's public-data registry identifies GOES-18 as the operational West source
  and GOES-19 as the operational East source and provides unauthenticated public
  buckets: <https://registry.opendata.aws/noaa-goes/>
- NOAA documents the ABI Fire/Hot Spot Characterization product at approximately
  2 km resolution: <https://goes-r.noaa.gov/products/baseline-fire-hot-spot.html>
- `h5py` 3.16.0 declares Python 3.14 support and publishes ARM64 manylinux and
  musllinux wheels: <https://pypi.org/project/h5py/>
- `netCDF4` 1.7.4 also supports Python 3.14, but its tested installed and runtime
  footprint was materially larger: <https://pypi.org/project/netCDF4/>

## Remaining gate

Before enabling GOES for users, create a production decoder and miniature
fixtures covering:

- all accepted and rejected fire-mask categories;
- temporally filtered flags;
- valid and fill values for FRP, temperature and area;
- limb and off-disk navigation;
- malformed dimensions, chunks, attributes and projection metadata;
- bounded download cleanup and cancellation;
- correlation between GOES-18/19 and other providers without double counting.
