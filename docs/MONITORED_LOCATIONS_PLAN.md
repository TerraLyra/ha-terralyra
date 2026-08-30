# Monitored Locations implementation plan

Status: implementation plan for the existing `ha-terralyra` integration.

This plan applies the TerraLyra PRDs incrementally. It does not authorize a
rewrite, cloud dependency, account requirement, subscription gate, or an
artificial limit on locally monitored locations.

## Current baseline

The current v0.3 implementation supports exactly one active-fire monitoring
center. It may follow Home Assistant Home or use one custom name and coordinate.
That center is used for provider selection, FIRMS bounds, filtering, distances,
notifications, map entities, activity summaries, and persisted track identity.

Working behaviour to preserve during migration:

- LSA SAF and GOES active-fire providers;
- optional NASA FIRMS corroboration;
- initial-snapshot alert suppression;
- incident matching, lifecycle, trends, and event cooldowns;
- offline place-name lookup;
- map entities and localized alert text;
- FRMv3 and land-surface-temperature behaviour;
- privacy-safe diagnostics and security limits.

## Important findings

### Configuration

`config_flow.py` stores a single center in flat options:

- `use_custom_monitoring_center`
- `monitoring_center_name`
- `monitoring_latitude`
- `monitoring_longitude`
- one shared `radius_km`

The options form cannot currently add, edit, enable, disable, or remove a list
of locations.

### Runtime coupling

`__init__.py` resolves one center and builds the primary provider and FIRMS
bounds from it. `coordinator.py` filters every observation against that center
before clustering and incident tracking.

### Incident coupling

`FireCluster` and persisted incident dictionaries contain `distance_km`,
`minimum_distance_km`, and `distance_trend`. These are properties of an
incident-to-location relationship, not properties of the physical incident.

The persistent store records one `monitoring_center` key and discards the old
track history when the center changes. This prevents one incident history from
being reused safely across multiple locations.

### Home Assistant presentation

Sensors and geo-location entities expose one scalar distance. Notifications
refer to one center. Events do not yet contain stable `location_id` and
`location_name` fields. A geo-location entity can retain the nearest relevant
location as its scalar distance while exposing all matches as bounded
attributes.

### Provider geometry

GOES selection currently depends on one coordinate. Multiple locations may
span GOES-East and GOES-West coverage. FIRMS currently receives one bounding
box. Provider requests must eventually be grouped by coverage and overlapping
areas rather than naively repeated once per location.

### Privacy

The current diagnostics redact the flat custom location. A location-list model
must redact every name and coordinate while still exposing a safe location
count and source/enablement summary.

## Target local model

```text
MonitoredLocation
  id: stable local identifier
  name: user-visible name
  latitude: validated coordinate
  longitude: validated coordinate
  radius_km: validated local relevance radius
  enabled: boolean
  source: home_assistant | manual
```

Rules:

- Home is available automatically unless explicitly disabled.
- Manual locations are stored locally in the config entry.
- No TerraLyra account or cloud service is required.
- No artificial local location limit is introduced.
- IDs do not contain names or coordinates.
- Location matching is performed locally wherever provider APIs permit it.

The incident relationship is separate:

```text
IncidentLocationMatch
  incident_id
  location_id
  location_name
  distance_km
  direction
  inside_radius
  distance_trend
```

`HazardIncident` remains independent of all monitored locations.

## Incremental implementation

### Stage 1 — Model and compatibility adapter

Files:

- `custom_components/terralyra/monitoring.py`
- `custom_components/terralyra/const.py`
- `tests/test_monitoring.py`

Changes:

1. Introduce immutable `MonitoredLocation` and validation helpers.
2. Add stable non-coordinate IDs and a serialized list schema.
3. Resolve Home dynamically from Home Assistant configuration.
4. Convert the current single-center options into a one-item compatibility
   list at runtime without changing behaviour.
5. Keep `MonitoringCenter` temporarily as a compatibility alias or adapter.

Acceptance criteria:

- existing v0.3 options resolve to exactly the same center and radius;
- invalid, duplicate, non-finite, or out-of-range locations are rejected;
- serialized data round-trips deterministically;
- no provider or entity behaviour changes yet.

### Stage 2 — Versioned config-entry migration

Files:

- `custom_components/terralyra/__init__.py`
- `custom_components/terralyra/config_flow.py`
- `custom_components/terralyra/const.py`
- translation JSON files
- `tests/test_config_flow.py`

Changes:

1. Increase config-flow version and implement `async_migrate_entry`.
2. Migrate the current Home/custom center and radius to `monitored_locations`.
3. Preserve credentials, provider settings, FIRMS key, thresholds, and all
   unrelated options.
4. Make migration idempotent and safe after interrupted upgrades.
5. Keep legacy option readers for one transition release, then remove them
   before the first public stable release.

Acceptance criteria:

- existing installations upgrade without recreation;
- clean installations create Home by default;
- no credentials or incident state are lost;
- rollback behaviour is documented for the development release.

### Stage 3 — Location-independent incident engine

Files:

- `custom_components/terralyra/models.py`
- `custom_components/terralyra/tracking.py`
- `custom_components/terralyra/trends.py`
- `custom_components/terralyra/coordinator.py`
- tracking, trend, and coordinator tests

Changes:

1. Remove location-relative distance aggregates from incident identity and
   physical incident history.
2. Keep provider observations, position, first/last seen, intensity,
   confidence, lifecycle, and evidence on the incident.
3. Calculate `IncidentLocationMatch` after incident creation/update for every
   enabled location.
4. Calculate approaching/receding independently per incident/location pair.
5. Ensure one incident can be relevant to multiple locations without creating
   multiple physical incidents or repeated new-fire events.

Acceptance criteria:

- one fire near two locations remains one incident;
- two nearby real fires remain separate;
- location changes do not erase physical incident history;
- startup never announces all visible incidents as new;
- distance trends do not leak between locations.

### Stage 4 — Persistent store migration

Files:

- `custom_components/terralyra/coordinator.py`, or a new focused storage module
- persistence tests

Target store sections:

```text
schema_version
initialized_providers
incidents
location_match_history
activity_history
```

Changes:

1. Replace the single `monitoring_center` guard with a schema version.
2. Migrate existing tracks without treating them as newly detected.
3. Bound and expire location-match history independently.
4. Preserve atomic Home Assistant `Store` writes.

### Stage 5 — Local location management UI

Files:

- `custom_components/terralyra/config_flow.py`
- `strings.json` and all translations
- `tests/test_config_flow.py`

Changes:

1. Add list, add, edit, enable/disable, and remove steps.
2. Show Home distinctly from manual locations.
3. Validate provider coverage per location and explain partial/unsupported
   coverage without implying global availability.
4. Keep advanced global provider thresholds separate from per-location radius.

The flow should use ordinary Home Assistant forms and remain usable on mobile.

### Stage 6 — Entities, events, maps, and notifications

Files:

- `custom_components/terralyra/sensor.py`
- `custom_components/terralyra/event.py`
- `custom_components/terralyra/geo_location.py`
- `custom_components/terralyra/coordinator.py`
- translations and notification tests

Changes:

1. Add `location_id`, `location_name`, `distance_km`, `direction`, and
   `inside_radius` to relevant events.
2. Emit one physical `wildfire_detected` transition with a bounded list of
   relevant locations, not one duplicate event per location.
3. Keep the nearest relevant location as the scalar map distance and expose
   all relevant matches as attributes.
4. Keep the primary entity set small; avoid location × provider entity
   multiplication.
5. Localize natural notification text for each relevant location.

### Stage 7 — Provider request planning

Files:

- `custom_components/terralyra/providers/factory.py`
- `custom_components/terralyra/providers/goes*.py`
- `custom_components/terralyra/providers/firms.py`
- `custom_components/terralyra/coordinator.py`

Changes:

1. Group locations by provider coverage.
2. Merge overlapping FIRMS request areas when safe and split distant areas.
3. Fetch once and match locally when a provider product already covers all
   configured locations.
4. Report per-location coverage as supported, partial, unsupported, or
   temporarily unavailable.
5. Never translate provider failure into “no hazards”.

This stage must be driven by measured provider behaviour and documented API
limits, not assumptions.

### Stage 8 — Documentation and public-contract cleanup

Files:

- `README.md`
- `ARCHITECTURE.md`
- `ROADMAP.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- release notes

Changes:

1. Document local-first operation and location privacy.
2. State which external providers receive coordinates.
3. Document detection, corroboration, official confirmation, forecast, and
   unknown as distinct concepts.
4. Mark low-level provider entities diagnostic or disabled by default where
   appropriate.
5. Complete contributor and HACS-default readiness material.

## Explicitly deferred

The monitored-location work must not also introduce:

- TerraLyra accounts, billing, subscriptions, or feature locks;
- TerraLyra Cloud runtime dependencies;
- FIRMS-only new-fire alerts;
- news or AI-based incident creation;
- a premature shared Python framework;
- immediate repository splitting or IGNIS renaming;
- environmental-product extraction in the same migration.

## Recommended release sequence

- v0.3.x: compatibility fixes for the existing single-center release.
- v0.4.0: `MonitoredLocation` model, migration, and multiple local locations.
- v0.4.x: UI, map, notification, and provider-coverage refinements.
- v0.5.0: normalized provider observations and provider-independent incident
  preparation.

No version should be released until tests cover clean install, config-entry
migration, restart persistence, multi-location matching, duplicate suppression,
provider outage semantics, and diagnostic redaction.
