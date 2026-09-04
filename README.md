# TerraLyra for Home Assistant

A HACS-compatible environmental monitoring and early-warning integration for
Home Assistant. TerraLyra automatically assigns every geographically relevant
active-fire source to each monitored location: **EUMETSAT LSA SAF MTG** in its
safe coverage area, **NOAA GOES-18/19** in the Western Hemisphere, and optional
**NASA FIRMS** global observations. Assigned sources are equal peers: none is
labelled primary or secondary, and independent observations can corroborate
the same incident. TerraLyra also includes additional LSA SAF environmental
products.

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

TerraLyra keeps provider access, scientific-product parsing and Home Assistant
entities in separate modules. One installation can therefore combine related
environmental observations without presenting a different HACS repository for
every dataset. Provider names and attribution remain visible; TerraLyra does
not relabel third-party data as its own.

## Product status

| Product | Source / ID | Resolution / cadence | Integration status |
|---|---|---|---|
| MTG Fire Radiative Power Pixel | LSA-509 / MTFRPPIXEL | ~1 km / 10 min | **Implemented** |
| GOES ABI Fire/Hot Spot Characterization | ABI-L2-FDCF | ~2 km / 10 min full disk | **Implemented, coverage-gated** |
| Fire Risk Map v3 Forecast | FRMv3 | Europe / daily, day 0…9 | **Implemented** |
| MTG Land Surface Temperature | LSA-007 / MTLST | ~2 km / 10 min; up to 60 min publication delay | **Implemented, optional** |
| Independent active-fire corroboration | NASA FIRMS NOAA-20/NOAA-21 VIIRS + Terra/Aqua MODIS NRT | ~375 m–1 km / provider-dependent NRT latency | **Implemented, optional** |
| Evapotranspiration | LSA SAF ET family | product-dependent | Roadmap |
| Solar radiation / fluxes | LSA SAF radiation family | product-dependent | Roadmap |
| Vegetation metrics | NDVI/FVC/LAI/FAPAR/GPP | product-dependent | Roadmap |

The integration automatically enables all credential-free sources covering a
location and any configured credentialed source. It also enables the public
**FRMv3 Fire Risk Map** forecast. The MTLST point sensor and NASA FIRMS source
are optional and disabled until explicitly configured.

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

## Active-fire detection

For EUMETSAT installations, the integration reads the compressed CSV
ListProduct from:

`MTG / MTFRPPixel / NATIVE`

For covered Western Hemisphere locations, NOAA GOES uses the public
ABI-L2-FDCF full-disk product without provider credentials. Every assigned
provider passes normalized detections to the same filtering, cross-source
deduplication, clustering, tracking and alert pipeline. On first setup
TerraLyra seeds the current snapshot
without emitting `new_fire` events, so already-existing fires do not cause an
alert flood.

### Entities

- `sensor.*_nearest_active_fire` – distance to the nearest active fire cluster
- `sensor.*_all_active_fire_clusters` – current, cross-source-deduplicated
  incident total from every assigned source
- `sensor.*_nasa_firms_*` – the subset observed by NASA FIRMS; this is a source
  breakdown, not a secondary-source count
- `sensor.*_fire_pixels_in_radius` – raw provider detections after filters
- `sensor.*_latest_fire_product_time` – time of the latest processed provider product
- `sensor.*_fire_product_age` – age of the latest product in minutes
- `sensor.*_active_fire_data_source` – automatic assignment state, with every
  assigned provider, satellite and health state as attributes
- `sensor.*_active_fire_sources` – one entity per enabled monitored location;
  its numeric state is the number of automatically assigned equal sources and
  its attributes list their readable provider names and satellites
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
- `sensor.*_independent_fire_source_confirmation` – whether an incident is
  observed by one source or corroborated by multiple equal sources
- `sensor.*_active_fire_situation` – explainable integration-calculated summary
  of current detected activity (`normal`, `elevated`, `high`, `critical`, or
  `unknown`)
- `event.*_new_active_fire` – Home Assistant Event entity for a newly deduplicated fire
- `event.*_fire_incident_trend_change` – meaningful, cooldown-protected trend changes
- `geo_location.*` – one map marker per recently tracked, deduplicated incident
- `number.*_active_fire_monitoring_radius` – dashboard-adjustable monitoring radius
- `number.*_fire_history_window` – dashboard-adjustable 1–48 hour period for
  retaining inactive incident markers without extending alert deduplication

Entity IDs are generated by Home Assistant and may differ depending on language and naming choices.

### Fire map

Each recently tracked cluster is exposed as a native Home Assistant `geo_location`
entity. The marker contains its coordinates, distance from the selected
active-fire monitoring center, current and peak FRP, confidence, acquisition
time, pixel count, incident lifecycle, duration,
historical maxima, and FRP/activity/distance trends. Trend states are calculated
from a bounded 90-minute observation window. They remain `unknown` until at
least three observations spanning 20 minutes are available.
Markers keep the same identity while the cluster remains within the configured
same-fire matching radius. Inactive markers remain visible for the independent
**Fire history window** (1–48 hours) and are removed automatically afterward.
Changing this display window does not extend repeat-alert suppression.

Add a **Map** card to a dashboard and select the `terralyra` geolocation source, or
use this YAML configuration:

```yaml
type: map
geo_location_sources:
  - source: terralyra
    label_mode: icon
hours_to_show: 24
```

`label_mode: icon` displays the integration's fire icon instead of a shortened
text label. Clicking a marker shows its exact latitude and longitude together
with the fire attributes. FIRMS-only entity names begin with **NASA FIRMS ·**
so the source is also visible in the entity dialog.

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
- `confirmation_level`
- `providers`
- `satellites`
- `corroborating_detections`
- `place_name`
- `nearest_settlement`
- `location_description`
- `notification_title`
- `notification_message`
- `location_id`
- `location_name`
- `location_radius_km`
- `direction`
- `inside_radius`
- `location_matches`
- `affected_locations`
- `product_time`
- `source_url`

For incidents relevant to multiple configured places, scalar distance and
location fields refer to the nearest place whose monitoring radius contains
the incident. `location_matches` retains the bounded per-location detail, and
`affected_locations` lists the places named in the single new-fire event and
notification. TerraLyra does not emit one duplicate event per place.

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
- `delayed` when the newest valid assigned-source product exceeds its freshness threshold;
- `no_product` when no assigned source has a recent product;
- `outage` when all assigned sources fail to return a safe, valid response;
- `auth_error` when saved credentials require reauthentication.

The status attributes include the provider, satellite, product timestamp and
the time Home Assistant received the product. Failed refreshes retain the last
successful data and persistent fire tracks; they are never converted into a
false zero-fire observation.

Each assigned source is retried independently. TerraLyra honors bounded
`Retry-After` advice and uses exponential backoff for repeated failures, while
healthy equal peers continue normally. Provider health attributes and
privacy-safe diagnostics distinguish authentication, rate-limit, timeout,
service-outage, no-product and invalid-response states, including the next
retry time.

Provider health and geographic coverage are intentionally separate. The
**Monitored-location source coverage** evaluates every enabled location using
conservative pre-download satellite geometry and reports `covered`, `partially
covered`, or `not covered`. TerraLyra also creates one **active-fire sources**
sensor per location. Its state is the assigned source count and its attributes
show the readable provider names, satellites and the equal-peer relationship
without exposing the location coordinates.

Every TerraLyra map marker separately names the provider or providers that
supplied the incident evidence: LSA SAF, NOAA GOES, NASA FIRMS, or multiple
sources. Home Assistant map cards may also combine geolocation entities from
other integrations.

## Installation through HACS

1. In HACS, add `TerraLyra/ha-terralyra` as a **Custom repository** of type
   **Integration**.
2. Install **TerraLyra**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → TerraLyra**.
5. Keep **Home** as the initial monitored location or manage additional named
   locations in the integration options.
6. Optionally enter LSA SAF Data Service credentials to add MTG observations
   where its safe footprint covers a location.
7. TerraLyra automatically adds GOES-18/19 where geographically relevant and
   optional NASA FIRMS observations when a personal MAP_KEY is configured.

A free LSA SAF Data Service account is required only for the MTFRPPixel
provider. GOES downloads the newest validated public NOAA full-disk product and
therefore adds network, storage, decoder and memory cost. TerraLyra rejects
unsafe navigation results, and GOES is assigned only to locations inside its
conservative coverage gate.

## Active fire options

- **Monitoring radius**: 1–500 km. Also exposed as a Number entity so it can be changed from a dashboard.
- **Managed monitored locations**: locally stored names, coordinates and
  radii used for automatic source assignment, distance sensors, alerts and
  fire markers. FRMv3 fire risk and MTLST remain tied to Home.
- **Minimum fire confidence**: 0.0–1.0.
- **Minimum FRP**: filters weak detections by Fire Radiative Power in MW.
- **Check interval**: how often Home Assistant looks for a newer product. The source product itself is nominally 10-minute data.
- **Same-fire matching radius**: nearby detections are considered the same physical fire.
- **Same-fire memory**: how long an already-seen fire suppresses a repeat `new_fire` event.
- **Fire history window**: independently controls how long inactive markers
  remain visible on the map.
- **Fire-risk forecast radius**: controls FRMv3 regional maximum sampling and
  the static map extent; it does not change active-fire alerts.
- **Resolve nearby place names**: uses the bundled offline GeoNames database.
- **Land-surface temperature**: creates the optional MTLST point sensor and
  sends Home coordinates to the official LSA SAF WMS while enabled.
- **NASA FIRMS corroboration**: enables independent VIIRS and MODIS comparison and
  requires the user's own FIRMS MAP_KEY.

## Optional NASA FIRMS source

NASA FIRMS is disabled by default. To enable it, create a personal FIRMS
MAP_KEY, open **Settings → Devices & services → TerraLyra → Configure**, enable
NASA FIRMS observations and enter the key. TerraLyra validates the key before
saving the option.

When enabled, TerraLyra requests only the bounded areas around all enabled
monitored locations from the NOAA-20 and NOAA-21 VIIRS plus Terra and Aqua
MODIS near-real-time feeds.
Overlapping safe boxes are merged; geographically distant boxes remain
separate, with at most ten planned areas. Results are deduplicated across
areas. Requests are cached for at least 15 minutes, use a maximum one-day query
window, and are isolated from their equal peers: a FIRMS outage cannot stop
healthy MTG or GOES updates.

Detections within 5 km and 6 hours are treated as independent corroboration.
Independent satellites remain separate evidence even when NASA FIRMS delivers
them through the same API. Their duplicate observations are clustered without
adding the same fire energy twice, and contributing satellite names are kept
on the incident attributes.
FIRMS-only detections can appear as **NASA FIRMS · …** map markers. Nearby
observations from independent providers are correlated into one incident, with
the contributing providers preserved as evidence. The source-specific and
all-source count sensors remain available so users can understand the scope of
each value without implying a provider hierarchy.

Enabling the option sends each required monitoring-area bounding box and the
user's MAP_KEY to the official NASA FIRMS service. Exact place names are not
sent. The key is stored in the Home Assistant config entry, redacted from
diagnostics and never logged.

## Expected active-fire updates

Every enabled monitored location has a **Next expected active-fire update**
timestamp sensor. It selects the earliest currently usable equal source and
keeps the complete source-by-source estimate in its attributes:

- MTG and GOES use the official 10-minute product cadence, anchored to the
  latest successfully received product.
- NASA FIRMS uses TerraLyra's bounded 15-minute API refresh interval. Its
  attributes also include a broad longitude-adjusted NOAA-20/21 VIIRS and
  Terra/Aqua MODIS nominal overpass window.

These values are estimates, not service guarantees. Publication latency,
clouds, scan-mode changes, maintenance and upstream outages can delay usable
data. The polar-orbit window intentionally avoids false minute-level precision; an
exact orbital pass predictor would require current orbital elements from an
additional external service.

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
the Home Assistant system language in English, Hungarian, German, Spanish,
French and Italian. Unsupported languages fall back to English. If place-name
lookup is disabled or unavailable, the message safely falls back to distance
from the named active-fire monitoring center.

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
cached for one hour. The most recent valid, size-bounded PNG can be reused for
the exact same date and bounds for up to 24 hours during a temporary outage,
including after a Home Assistant restart. Authentication failures are never
hidden by this fallback. Data is EUMETSAT / LSA SAF, CC BY 4.0; settlement
labels are GeoNames, CC BY 4.0.

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
├── geo_location.py        # recent active-fire map markers
├── number.py
├── select.py              # FRMv3 forecast day 0–9
├── providers/
│   ├── base.py            # typed provider interface
│   ├── firms.py           # VIIRS and MODIS corroboration adapter
│   ├── goes.py            # conservative GOES-18/19 coverage selection
│   ├── goes_active.py     # GOES discovery/download/decoder provider adapter
│   ├── goes_spike.py      # dependency-free GOES filename/timing validation
│   └── mtg.py             # MTFRPPixel → FireDetection adapter
└── products/
    ├── fire.py            # MTFRPPixel parser + client (implemented)
    ├── fire_risk.py       # bounded FRMv3 WMS client and parser
    ├── firms.py           # bounded NASA FIRMS Area API client/parser
    ├── goes.py            # bounded NOAA GOES catalogue discovery
    ├── goes_decoder.py    # bounded stripe-based ABI-L2-FDCF decoder
    └── lst.py             # optional MTLST WMS client/parser
```

The domain is intentionally the generic `terralyra`, not `terralyra_mtg_fire`, so future products can be added to the same installed integration.

### Migrating an existing map card

Dashboard geolocation-source selections belong to the user's dashboard and
cannot be rewritten by an integration update. If a map card was created for the
older development integration, edit that card, remove the legacy `lsa_saf`
value from **Geolocation sources**, and select `terralyra`. Single-source
markers name their observing provider and corroborated incidents retain all
contributors. Home Assistant only lists sources that currently have a loaded
`geo_location` entity. If no recent fire marker exists, leave the source filter
empty temporarily or enter `terralyra` in the card's YAML as shown above.

## Roadmap

### Next

- obtain a documented near-real-time Himawari-9 FRP-PIXEL List Product endpoint
  and access terms; a conservative, runtime-disabled coverage foundation and
  the remaining go/no-go gates are recorded in
  [`docs/HIMAWARI_TECHNICAL_SPIKE.md`](docs/HIMAWARI_TECHNICAL_SPIKE.md)
- validate one current MSG-IODC FRP-PIXEL List Product with the bounded,
  metadata-only schema probe, then implement the decoder and provider adapter;
  its documented LSA SAF path, conservative runtime-disabled coverage selector,
  evidence-family safeguard, safe probe and remaining activation gates are
  recorded in
  [`docs/MSG_IODC_TECHNICAL_SPIKE.md`](docs/MSG_IODC_TECHNICAL_SPIKE.md)
- collect operational GOES-18/19 experience from covered installations while
  retaining the conservative pre-download coverage gate and product navigation
  checks; technical and resource details are in
  [`docs/GOES_TECHNICAL_SPIKE.md`](docs/GOES_TECHNICAL_SPIKE.md) and
  [`docs/GOES_DECODER_BENCHMARK.md`](docs/GOES_DECODER_BENCHMARK.md)
- continue localization and usability review on real Home Assistant dashboards;
  every enabled location now has a translated operational-status entity with
  equal-source health, timestamps and local incident-confirmation counts
- submit TerraLyra artwork to the upstream Home Assistant brands repository

### Multi-source detection and incident verification

- NASA FIRMS can be enabled as an optional equal active-fire source with the
  user's personal MAP_KEY; it remains disabled by default
- bounded NOAA-20/21 VIIRS and Terra/Aqua MODIS Area API requests are cached for at least
  15 minutes and failures never stop healthy peer-source monitoring
- nearby independent-provider detections are correlated within explicit
  5 km and 6 hour gates, with source attribution retained on each incident
- FIRMS-only detections appear as source-labelled map markers with locally resolved
  nearest-settlement names; current and persisted cross-provider matches are
  reconciled instead of being displayed as duplicates
- the independent fire-source confirmation sensor distinguishes disabled,
  unavailable, single-source, and multi-source results
- expose a provider-neutral confirmation level instead of treating either
  satellite source as authoritative on its own
- distinguish detections seen by multiple satellites from single-source,
  low-intensity, stale, or otherwise uncertain thermal anomalies through a
  bounded, explainable evidence-strength sensor
- displayed fire-history window is configurable independently of same-fire
  alert suppression so provider observations can be compared consistently
- preserve source attribution, observation time, resolution, confidence, and
  FRP for every contributing detection

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

## Home Assistant Repairs

TerraLyra creates one actionable Home Assistant repair notice for each upstream
provider whose credentials are rejected or which fails at least three
consecutive attempts, and also when no configured source geographically covers
one or more enabled monitored locations. A successful update or corrected
configuration removes the corresponding notice automatically. A short
transient failure does not create a repair notice, and healthy peer sources
continue independently.

## Important limitations

Satellite fire detection is **not an emergency warning service**. Cloud, viewing geometry, product latency, spatial resolution and algorithmic false positives/negatives can delay or prevent detection. Do not use this integration as the sole life-safety or property-protection warning system.

MTFRPPixel is currently an LSA SAF demonstration product, so its availability or format may change.

NASA FIRMS VIIRS and MODIS near-real-time data has its own latency, coverage, confidence and
false-positive limitations. Multi-source agreement strengthens the available
satellite evidence but does not prove that an emergency is occurring.

## Data attribution

LSA SAF products are provided by the **EUMETSAT Satellite Application Facility on Land Surface Analysis (LSA SAF)**. Follow the LSA SAF/EUMETSAT acknowledgement and licensing requirements when redistributing derived data or screenshots.

NASA FIRMS active-fire observations are provided by
[NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/). Users are responsible for
complying with the provider's current terms and attribution requirements when
redistributing data or derived material.

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
