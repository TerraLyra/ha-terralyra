# TerraLyra for Home Assistant

A HACS-compatible environmental monitoring and early-warning integration for
Home Assistant. TerraLyra currently combines **EUMETSAT LSA SAF** products and
an optional NASA FIRMS corroboration source, with a provider-neutral foundation
for additional environmental data sources.

Repository: `https://github.com/TerraLyra/ha-terralyra`

> TerraLyra is an independent project. It is not an official EUMETSAT, LSA SAF,
> NASA, or FIRMS integration.

> **Clean-break release:** TerraLyra uses the new `terralyra` Home Assistant
> domain and does not migrate settings or entity IDs from the earlier
> `lsa_saf` development integration. Remove the old integration before enabling
> TerraLyra to avoid duplicate polling and alerts, then configure TerraLyra as
> a new integration. Existing dashboards and automations must be updated to the
> new entity IDs and `terralyra_*` event names.

## Why one integration?

LSA SAF exposes several related satellite products through the same ecosystem. This repository uses one authentication/configuration layer and keeps each scientific product in a separate Python module. That makes it possible to add new products without creating a separate HACS repository for every dataset.

## Product status

| Product | LSA SAF ID | Resolution / cadence | Integration status |
|---|---|---|---|
| MTG Fire Radiative Power Pixel | LSA-509 / MTFRPPIXEL | ~1 km / 10 min | **Implemented** |
| Fire Risk Map v3 Forecast | FRMv3 | Europe / daily, day 0…9 | **Implemented** |
| MTG Land Surface Temperature | LSA-007 / MTLST | ~2 km / 10 min; up to 60 min publication delay | **Implemented, optional** |
| Evapotranspiration | LSA SAF ET family | product-dependent | Roadmap |
| Solar radiation / fluxes | LSA SAF radiation family | product-dependent | Roadmap |
| Vegetation metrics | NDVI/FVC/LAI/FAPAR/GPP | product-dependent | Roadmap |

The integration enables **MTG Active Fire Detection** and the public **FRMv3
Fire Risk Map** forecast. The MTLST point sensor is optional and disabled by
default.

## MTG Land Surface Temperature

MTLST reports the radiative temperature of the land surface, not the shaded air
temperature reported by a weather station. When explicitly enabled in the
integration options, Home Assistant sends the configured Home latitude and
longitude to the official `adaguc.lsasvcs.ipma.pt` LSA SAF WMS approximately
every 15 minutes. The option is disabled by default; while disabled, no MTLST
request is made and no MTLST entity is created.

The sensor exposes the latest temperature in the user's preferred temperature
unit. Attributes preserve the observation time, sampled coordinates, product
quality label, uncertainty in kelvin, product ID, source, and CC BY 4.0
attribution. A clear-sky satellite observation can be unavailable because of
cloud, coverage, or publication delay; such a result remains unavailable rather
than being replaced with an invented value.

## MTG Active Fire Detection

The integration reads the compressed CSV ListProduct from:

`MTG / MTFRPPixel / NATIVE`

It checks for the newest deterministic 10-minute product filename, parses the fire pixels, filters them around Home Assistant's configured **Home** location, groups adjacent pixels into fire clusters, and remembers recently observed clusters so the same fire does not create a new alert every product cycle. On first setup it seeds the current snapshot without emitting `new_fire` events, so already-existing fires do not cause an alert flood.

### Entities

- `sensor.*_nearest_active_fire` – distance to the nearest active fire cluster
- `sensor.*_active_fire_clusters` – number of active clusters in the configured radius
- `sensor.*_fire_pixels_in_radius` – raw MTG fire pixels after filters
- `sensor.*_latest_fire_product_time` – time of the latest processed LSA SAF product
- `sensor.*_fire_product_age` – age of the latest product in minutes
- `sensor.*_active_fire_data_status` – provider health and freshness, including
  delayed, no-product and outage states
- `sensor.*_fire_detections_in_the_last_hour` – detections during the last hour,
  with 3-hour and 6-hour counters as bounded attributes
- `sensor.*_fire_activity_frp_change_over_one_hour` – aggregate clustered FRP
  change over one hour, with the 3-hour change as a bounded attribute
- `sensor.*_new_fire_incidents_in_the_last_24_hours` – new tracked incidents in
  the rolling 24-hour window
- `sensor.*_nearest_fire_evidence_strength` – explainable strength of the
  satellite evidence for the nearest incident; never an official confirmation
- `sensor.*_active_fire_situation` – explainable integration-calculated summary
  of current detected activity (`normal`, `elevated`, `high`, `critical`, or
  `unknown`)
- `event.*_new_active_fire` – Home Assistant Event entity for a newly deduplicated fire
- `event.*_fire_incident_trend_change` – meaningful, cooldown-protected trend changes
- `geo_location.*` – one live map marker per active fire cluster
- `number.*_active_fire_monitoring_radius` – dashboard-adjustable monitoring radius

Entity IDs are generated by Home Assistant and may differ depending on language and naming choices.

### Fire map

Each recently tracked cluster is exposed as a native Home Assistant `geo_location`
entity. The marker contains its coordinates, distance from Home, current and peak
FRP, confidence, acquisition time, pixel count, incident lifecycle, duration,
historical maxima, and FRP/activity/distance trends. Trend states are calculated
from a bounded 90-minute observation window. They remain `unknown` until at
least three observations spanning 20 minutes are available.
Markers keep the same identity while the cluster remains within the configured
same-fire matching radius. They remain visible for the configured same-fire
memory period and are removed automatically when that period expires.

Add a **Map** card to a dashboard and select the `terralyra` geolocation source, or
use this YAML configuration:

```yaml
type: map
geo_location_sources:
  - source: terralyra
    label_mode: icon
hours_to_show: 24
```

`label_mode: icon` displays the integration's fire icon instead of the `LSF`
letter label. Clicking a marker shows the exact latitude and longitude together
with all fire attributes.

The integration resolves the nearest settlement locally from its bundled
GeoNames `cities500` database. It sends no fire or Home coordinates to an
external geocoding service, has no lookup quota, and remains available without
internet access. Lookup runs outside Home Assistant's event loop and the
database is opened read-only. Place data is provided by GeoNames under CC BY
4.0. The feature is enabled by default and can be disabled in the integration
options.

### Home Assistant bus event

Every newly detected/deduplicated nearby fire also fires:

```text
terralyra_new_fire
```

Event data includes:

- `distance_km`
- `latitude`
- `longitude`
- `frp_mw`
- `peak_frp_mw`
- `confidence`
- `acquired`
- `pixel_count`
- `track_id`
- `incident_id`
- `lifecycle`
- `first_seen`
- `last_seen`
- `duration_minutes`
- `minimum_distance_km`
- `maximum_frp_mw`
- `maximum_pixel_count`
- `detections_total`
- `maximum_confidence`
- `frp_trend`
- `activity_trend`
- `distance_trend`
- `product_time`
- `source_url`

Meaningful incident trend transitions also fire:

```text
terralyra_fire_trend
```

Its `event_type` is one of `fire_intensity_increasing`,
`fire_activity_increasing`, `fire_activity_decreasing`, or `fire_approaching`.
The integration only emits a transition after the trend engine's minimum sample
and duration rules are satisfied. A persisted 60-minute per-incident,
per-event-type cooldown prevents notification floods, including across restarts.

### Activity history

The integration persists only a compact rolling 24-hour history, capped at 180
product observations. It derives small Recorder-friendly sensor states from
this history; raw observation arrays are never exposed as entity attributes.
"Detections" means filtered provider fire detections contributing to processed
products, while "new incidents" means newly created deduplicated incident IDs.
FRP change is the difference between the first and last total clustered FRP in
the selected window and remains unavailable until at least two samples exist.

### Active Fire Situation

Active Fire Situation is deliberately separate from the FRMv3 **Fire Risk**
forecast. Fire Risk describes environmental conditions that favour fire;
Active Fire Situation summarizes current satellite-detected activity. It is an
integration-calculated situation indicator, not an official emergency or
fire-danger classification.

The score is deterministic and uses only bounded inputs:

- nearest detection: 5/4/3/2/1 points within 10/25/50/100/250 km;
- active incidents: 1 point for at least 2, 2 points for at least 5;
- highest current FRP: 1 point from 30 MW, 2 points from 100 MW;
- detected activity approaching Home: 2 points;
- increasing FRP and increasing detection activity: 1 point each.

With fresh provider data, no current detections is `normal`. Any current
detection is at least `elevated`; `high` requires a detection within 100 km and
at least 5 points, while `critical` requires a detection within 25 km and at
least 7 points. If the provider is delayed/unavailable or the product is older
than 60 minutes, the state is `unknown` rather than a potentially misleading
`normal`.

### Data freshness and provider health

An empty active-fire cluster count means that a current satellite product was
successfully processed and contained no matching detections. It is deliberately
different from a provider failure. The **Active-fire data status** sensor reports:

- `available` for a current valid product;
- `delayed` when the newest valid MTG product is more than 60 minutes old;
- `no_product` when no recent MTFRPPixel product can be found;
- `outage` when the provider cannot return a safe, valid response;
- `auth_error` when saved credentials require reauthentication.

The status attributes include the provider, satellite, product timestamp and
the time Home Assistant received the product. Failed refreshes retain the last
successful data and persistent fire tracks; they are never converted into a
false zero-fire observation.

## Installation through HACS

1. In HACS, add `TerraLyra/ha-terralyra` as a custom repository.
2. In HACS, add it as a **Custom repository** of type **Integration**.
3. Install **TerraLyra**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → TerraLyra**.
6. Enter your LSA SAF Data Service username and password.

A free LSA SAF Data Service account is required for the MTFRPPixel archive.

## Active fire options

- **Monitoring radius**: 1–500 km. Also exposed as a Number entity so it can be changed from a dashboard.
- **Minimum fire confidence**: 0.0–1.0.
- **Minimum FRP**: filters weak detections by Fire Radiative Power in MW.
- **Check interval**: how often Home Assistant looks for a newer product. The source product itself is nominally 10-minute data.
- **Same-fire matching radius**: nearby detections are considered the same physical fire.
- **Same-fire memory**: how long an already-seen fire suppresses a repeat `new_fire` event.

## Example iPhone notification automation

```yaml
alias: TerraLyra - new fire notification
triggers:
  - trigger: event
    event_type: terralyra_new_fire
actions:
  - action: notify.mobile_app_iphone_13_pro
    data:
      title: "{{ trigger.event.data.notification_title }}"
      message: "{{ trigger.event.data.notification_message }}"
mode: queued
```

The integration resolves the nearest settlement before publishing a new-fire
event. `notification_title` and `notification_message` are concise and follow
the Home Assistant system language: Hungarian installations use **Tűzészlelés
riasztás**, while other languages currently fall back to English. If place-name
lookup is disabled or unavailable, the message safely falls back to distance
from Home.

## FRMv3 fire-risk forecast

The integration also reads the public demonstration **FRMv3 Fire Risk Map v3**
service for Europe. It creates:

- a **Fire risk near Home** sensor for today, with all ten daily forecasts in
  its `forecast` attribute;
- a separate **Highest fire risk in monitoring area** sensor;
- a localized **Fire risk forecast day** selector (Today, Tomorrow, …);
- an independent **Fire-risk forecast radius** control;
- a **Fire risk forecast map** camera showing the selected day;
- a **Latest fire-risk forecast update** status sensor;
- a localized **10-day fire-risk forecast** calendar entity;
- a **Fire risk increase** event when the monitoring-area maximum rises to high
  or worse.

FRMv3 has five levels: low, moderate, high, very high and extreme. Because an
exact Home coordinate can be an urban or otherwise non-burnable `nodata` pixel,
the local sensor uses the nearest valid sample within 10 km. The area sensor
separately scans the bounded FRMv3 raster inside the configured circular
monitoring radius and reports its highest risk pixel. Image analysis happens
locally and does not create additional point requests. This is a regional
planning indicator, not a property-level prediction.

The static Home Assistant map is annotated with its validity date, the Home
position, prominent offline GeoNames settlements, country borders and a
localized color legend. Country boundaries use a compact bundled extract from
Natural Earth at 1:110m scale and require no additional network request.

For the full outlook without YAML templates, add Home Assistant's standard
**Calendar** card to a dashboard and select the TerraLyra **10-day fire-risk
forecast** calendar. Each all-day entry shows that day's localized risk level.
For free pan, zoom, time navigation and layer opacity controls, open the
[official LSA SAF ADAGUC viewer](https://adaguc.lsasvcs.ipma.pt/) and choose
**MSG – FRMv3 – Fire Risk** under Add layers. This uses the product owner's
viewer directly and needs no API key.

Home Assistant's **Visit website** link under **Settings → Devices & services →
TerraLyra → TerraLyra** opens the TerraLyra project and support page. To put a
one-tap shortcut to the official interactive LSA SAF viewer on a dashboard, add
this Button card:

```yaml
type: button
name: Interactive fire-risk map
icon: mdi:map-search
tap_action:
  action: url
  url_path: https://adaguc.lsasvcs.ipma.pt/
```

Example dashboard card:

```yaml
type: picture-entity
entity: camera.terralyra_fire_risk_forecast_map
camera_view: auto
show_name: true
show_state: false
```

Add `select.terralyra_fire_risk_forecast_day` beside the image to choose a named
forecast day. Forecast data refreshes every 12 hours; generated map images are
cached for one hour. Data is EUMETSAT / LSA SAF, CC BY 4.0; settlement labels
are GeoNames, CC BY 4.0.

To remain friendly to the public service at larger adoption levels, the raw map
download is shared by the regional analysis and camera preview. Each Home
Assistant installation also receives a stable, randomized offset within a
one-hour window around the twelve-hour forecast refresh interval, preventing
large groups of installations from keeping the same scheduled polling time.

For a compact ten-day outlook, add a Markdown card and replace the entity ID if
Home Assistant generated a different one:

```yaml
type: markdown
title: 10-day fire-risk outlook
content: >-
  {% set forecast = state_attr('sensor.terralyra_fire_risk_near_home', 'forecast') or [] %}
  {% set labels = {'low':'🟦 Low','moderate':'🟩 Moderate','high':'🟨 High','very_high':'🟧 Very high','extreme':'🟥 Extreme','unknown':'⬜ Unknown'} %}
  {% for day in forecast %}
  **{{ as_timestamp(day.date) | timestamp_custom('%a, %d %b') }}** — {{ labels.get(day.risk, day.risk) }}<br>
  {% endfor %}
```

The active-fire radius and fire-risk radius are deliberately independent. The
first controls detections and alerts; the second controls the static FRMv3 map
extent and regional maximum-risk sampling.

## Architecture

```text
custom_components/terralyra/
├── __init__.py
├── api.py                 # shared Data Service authentication/client base
├── models.py              # provider-neutral detections and clusters
├── clustering.py          # common distance and spatial clustering
├── situation.py           # explainable current Active Fire Situation scoring
├── config_flow.py
├── const.py
├── coordinator.py         # common active-fire processing pipeline
├── diagnostics.py         # privacy-safe troubleshooting summary
├── fire_risk_coordinator.py
├── camera.py              # selected FRMv3 forecast map
├── entity.py
├── sensor.py
├── event.py
├── geo_location.py       # live active-fire map markers
├── number.py
├── select.py              # FRMv3 forecast day 0–9
├── providers/
│   ├── base.py            # typed provider interface
│   └── mtg.py             # MTFRPPixel → FireDetection adapter
└── products/
    ├── fire.py            # MTFRPPixel parser + client (implemented)
    ├── fire_risk.py       # bounded FRMv3 WMS client and parser
    └── lst.py             # MTLST product metadata / future module
```

The domain is intentionally the generic `terralyra`, not `terralyra_mtg_fire`, so future products can be added to the same installed integration.

## Roadmap

### Next

- GOES technical spike completed without production dependencies; see
  [`docs/GOES_TECHNICAL_SPIKE.md`](docs/GOES_TECHNICAL_SPIKE.md). The result is
  intentionally not enabled for Europe because GOES observes the Western
  Hemisphere
- stabilize the planned LSA SAF Land Surface Temperature product as an
  independent, explicit opt-in module. Enabling it sends the configured Home
  coordinates to the official LSA SAF WMS about every 15 minutes

### Multi-source detection and incident verification

- NASA FIRMS can be enabled as an optional secondary active-fire provider with
  the user's personal MAP_KEY; it remains disabled by default
- bounded NOAA-20 and NOAA-21 VIIRS Area API requests are cached for at least
  15 minutes and failures never stop primary LSA SAF monitoring
- nearby LSA SAF and FIRMS detections are correlated within explicit 5 km and
  6 hour gates, with source attribution retained on each incident
- the independent fire-source confirmation sensor distinguishes disabled,
  unavailable, single-source, and multi-source results
- expose a provider-neutral confirmation level instead of treating either
  satellite source as authoritative on its own
- distinguish detections seen by multiple satellites from single-source,
  low-intensity, stale, or otherwise uncertain thermal anomalies through a
  bounded, explainable evidence-strength sensor
- make the displayed fire-history window configurable so providers with
  different retention periods can be compared consistently
- preserve source attribution, observation time, resolution, confidence, and
  FRP for every contributing detection
- add GOES-18/19 as an optional location-aware provider for covered Western
  Hemisphere users after the NetCDF/resource gates in the technical spike pass

### News and official-report enrichment

- research a candidate catalogue of local, national, and cross-border fire
  information sources, including fire-service and civil-protection feeds,
  emergency alerts, public incident APIs, RSS/Atom feeds, and reputable news
  outlets
- assess each source for geographic coverage, update frequency, structured-data
  availability, authentication and rate limits, licensing and redistribution
  terms, reliability, language, and long-term operational suitability
- ingest only explicitly enabled sources through isolated provider adapters;
  do not scrape sites whose terms or technical controls prohibit it
- match reports to satellite detections using time, coordinates, settlement
  names, distance, and incident keywords while retaining the original source
  link and publication time
- show corroborating reports as context and calculate an explainable incident
  confidence; never present an automatically matched article as definitive
  emergency confirmation
- add deduplication, caching, request limits, safe URL validation, content-size
  limits, redacted logging, and tests before enabling network news enrichment

### Later

- evapotranspiration useful for irrigation logic
- surface solar radiation
- selected vegetation metrics where satellite resolution is meaningful

## Important limitations

Satellite fire detection is **not an emergency warning service**. Cloud, viewing geometry, product latency, spatial resolution and algorithmic false positives/negatives can delay or prevent detection. Do not use this integration as the sole life-safety or property-protection warning system.

MTFRPPixel is currently an LSA SAF demonstration product, so its availability or format may change.

## Data attribution

LSA SAF products are provided by the **EUMETSAT Satellite Application Facility on Land Surface Analysis (LSA SAF)**. Follow the LSA SAF/EUMETSAT acknowledgement and licensing requirements when redistributing derived data or screenshots.

Offline settlement names are derived from [GeoNames](https://www.geonames.org/)
`cities500`, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Country boundaries are derived from [Natural Earth](https://www.naturalearthdata.com/)
1:110m Admin 0 boundary lines, provided in the public domain.

## License

Integration source code: MIT License.

## Validation and release readiness

The repository includes automated GitHub Actions for:

- Python 3.14 syntax compilation and JSON validation
- Home Assistant Hassfest validation
- HACS repository validation
- CodeQL static analysis
- Bandit Python security analysis
- pip-audit dependency vulnerability checks
- repository secret-pattern scanning and weekly Dependabot updates

The repository bundles local normal- and high-DPI brand icons for Home Assistant
2026.3 and newer. The HACS `brands` check remains ignored until the same artwork
is accepted into the separate upstream `home-assistant/brands` repository. Each
stable integration version is published as a GitHub release for predictable
HACS installation and rollback.
