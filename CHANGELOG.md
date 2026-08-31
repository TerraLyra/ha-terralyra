# Changelog

## 0.6.0

- Replace the configured primary/supplemental active-fire hierarchy with
  automatic source assignment for every enabled monitored location.
- Use all geographically relevant, configured sources as equal peers: MTG in
  its safe coverage area, GOES-18/19 in the Western Hemisphere, and NASA FIRMS
  globally when its key is configured.
- Continue updating from healthy peers during a partial provider outage and
  expose bounded per-source health and assignment details.
- Merge nearby observations from independent satellites into one incident,
  preserving multi-source confirmation without double-counting observed FRP.
- Migrate existing entries without requiring users to reselect a provider and
  add translated, provider-neutral setup, entity and Repair wording.
- Clarify active-fire entity scopes and document Home Assistant map-card
  limitations, attribution and recommended TerraLyra dashboard naming.

## 0.5.2

- Disambiguate simultaneous same-place fire markers without changing their
  stable incident-backed Home Assistant identities.
- Use the nearest actually affected monitored location for map distance,
  scalar location attributes and localized new-fire notifications.
- Include all other affected monitored-location names in one physical
  incident event instead of creating duplicate alerts.
- Query every enabled monitored location when optional NASA FIRMS
  corroboration is active, merging overlapping safe request boxes, keeping
  distant boxes separate and deduplicating repeated observations.

## 0.5.1

- Keep Home Assistant geolocation entity identities tied to stable TerraLyra
  incident IDs so a later fire cannot inherit another incident's history.
- Merge connected same-product detection chains during clustering, reducing
  overlapping map markers caused by source-pixel ordering.
- Remove the internal `firms-` prefix from fallback NASA FIRMS fire names.
- Add regression coverage for stable incident identities, connected clustering
  and user-facing FIRMS fallback names.

## 0.5.0

- Rename the existing active-fire cluster sensor to make clear that it counts
  only detections from the configured primary provider.
- Add a separate NASA FIRMS supplemental-cluster sensor containing only
  detections that are not already represented by a correlated primary-source
  incident.
- Add a combined active-fire cluster sensor that reports the deduplicated
  current total across the primary provider and supplemental NASA FIRMS data.
- Expose explicit count-scope and provider attributes, update all supported
  translations, and document why the primary count can be zero while the map
  still contains supplemental observations.

## 0.4.1

- Fix migration of legacy custom monitoring centers when Home Assistant uses an
  uppercase config-entry identifier by assigning a stable, validated local
  location ID instead of deriving one from the config entry.

## 0.4.0

- Replace the single custom monitoring center with a locally managed list of
  enabled monitored locations, each with its own name, coordinates and active-
  fire radius.
- Match active-fire incidents to every affected monitored location while
  retaining a stable primary-location distance for Home Assistant entities.
- Add translated location-management flows with strict validation and safe
  migration of existing single-center installations.
- Distinguish the configured primary active-fire provider from the provider
  actually observed in the latest product, avoiding misleading source labels.
- Add conservative per-location EUMETSAT LSA SAF and NOAA GOES coverage
  reporting, including an appropriate-provider recommendation when uncovered.
- Add actionable Home Assistant Repairs for rejected provider credentials,
  three consecutive provider failures and uncovered monitored locations.
  Repairs clear automatically when the underlying condition is corrected.
- Extend regression coverage and documentation for multi-location matching,
  provider identity, geographic coverage and repair-notice behavior.

## 0.3.0

- Add a setup and options workflow for choosing Home or one named custom
  active-fire monitoring center with strictly validated coordinates.
- Use the selected center consistently for the primary active-fire provider,
  NASA FIRMS bounds, distance calculations, alerts and map markers while
  keeping FRMv3 fire risk and land-surface temperature tied to Home.
- Allow European Home Assistant installations to create a coverage-gated NOAA
  GOES entry for a safely covered Western Hemisphere test location.
- Show the center name and rounded coordinates as attributes of the active-fire
  data-source sensor and use the name in localized mobile notifications.
- Separate persisted incident tracks and activity history when the center
  changes so detections from two locations cannot be mixed.
- Add English, Hungarian, German, French, Spanish and Italian setup text plus
  regression tests for custom centers, validation, GOES coverage and alerts.

## 0.2.7

- Audit all English, Hungarian, German, French, Spanish and Italian translation
  schemas and guard against accidental English fallback text.
- Reconcile the README with the released GOES primary-provider workflow,
  provider-neutral map behavior, current architecture and remaining roadmap.

## 0.2.6

- Add a translated primary-provider setup step for EUMETSAT LSA SAF and NOAA
  GOES-18/19.
- Allow safely covered Western Hemisphere installations to use GOES without an
  LSA SAF account while retaining the existing credential flow for LSA SAF.
- Explain GOES coverage, account and additional-download implications before
  activation, and reject uncovered Home locations before creating an entry.
- Add a regression test for the exact geolocation attributes consumed by Home
  Assistant's native Map-card source selector.
- Add a strict primary-provider factory that preserves existing LSA SAF entries
  while preparing a coverage-gated GOES runtime path without silent fallback.
- Test LSA SAF compatibility, GOES-East selection, European exclusion, missing
  credentials and unknown-provider rejection at the provider boundary.
- Show the selected active-fire provider, satellite and product in a translated
  Home Assistant sensor, and expose the `terralyra` map-source identifier on
  the active-fire summary even when no marker is currently available.
- Add a network-free end-to-end GOES runtime test covering bounded download,
  temporary-file cleanup, direct NetCDF decoding and provider normalization.
- Add conservative spherical coverage selection for the operational GOES-18
  and GOES-19 satellites while rejecting Europe and near-limb locations.
- Add a fixed-host, redirect-free and size-limited NOAA catalogue discovery
  client that inspects only the current and previous UTC product hour.
- Strictly validate GOES catalogue XML, object paths, filenames, satellite
  identity, timestamps and advertised NetCDF object size before download, using
  a pinned attack-resistant XML parser.
- Add tests for satellite selection, European exclusion, UTC prefixes and
  malformed, oversized or cross-satellite catalogue objects.
- Document the completed production foundation and retain NetCDF downloading
  behind a separate package-size, memory and ARM compatibility gate.
- Record a real GOES-18/19 ARM64 decoder benchmark and select direct `h5py`
  conditionally; keep the native dependency and user option out until the
  bounded production decoder and miniature fixtures pass the remaining gate.
- Add the bounded direct-`h5py` FDCF decoder with stripe-based mask scanning,
  strict dimensions/chunks/units/projection validation, optional-value
  preservation and synthetic miniature fixtures. The decoder remains
  disconnected from normal integration operation pending provider activation.
- Add redirect-free, advertised-size-verified streaming downloads with
  executor-backed file writes and cancellation-safe temporary-file cleanup.
- Add a dedicated Python 3.14 GOES compatibility workflow on Linux x86-64 and
  ARM64 GitHub-hosted runners.
- Add a provider-neutral GOES active-fire adapter with conservative coverage
  selection, explicit freshness states and strict decoded-product identity
  checks. It remains unregistered until multi-provider coordination is ready.

## 0.2.5

- Localize generated fire-place descriptions and mobile notification text in
  English, Hungarian, German, Spanish, French, and Italian, with an English
  fallback for other Home Assistant languages.

- Audit and update the README against the current integration behavior,
  entities, options, privacy boundaries and provider attribution.
- Verify the native Map-card geolocation-source YAML and document why
  `terralyra` may be absent while no recent fire marker exists.
- Add complete NASA FIRMS setup, behavior, failure-isolation, privacy and
  supplemental-marker guidance.
- Correct obsolete MTLST roadmap and architecture descriptions, remove a
  duplicated installation step and decouple map history wording from alert
  memory.
- Remove a stale development version from the NASA FIRMS HTTP User-Agent.

## 0.2.4

- Reconcile persisted NASA FIRMS-only tracks with primary LSA SAF incidents
  across refresh cycles, preventing historical cross-provider duplicates.
- Prefix supplemental map entity names with `NASA FIRMS` so their source is
  immediately visible on Home Assistant maps and entity dialogs.
- Document migration of manually configured geolocation cards from the legacy
  `lsa_saf` source to `terralyra`.

## 0.2.3

- Show NASA FIRMS-only VIIRS detections as supplemental Home Assistant map
  markers when FIRMS corroboration is enabled.
- Suppress duplicate FIRMS markers when the same detection already corroborates
  an LSA SAF incident.
- Resolve the nearest settlement locally for supplemental FIRMS incidents and
  retain explicit NASA FIRMS source attribution.
- Use a separate identifier namespace for FIRMS incidents to prevent entity
  identity collisions with primary LSA SAF incidents.
- Keep FIRMS-only markers out of primary LSA SAF alerts and situation scoring.

## 0.2.2

- Add a separate, dashboard-adjustable 1–48 hour fire-history window for map
  markers.
- Keep inactive incidents visible for the selected history period without
  extending same-fire alert suppression.
- Preserve the previous six-hour behavior by default for existing users.

## 0.2.1

- Add a translated, explainable evidence-strength sensor for the nearest active
  fire detection, with `limited`, `moderate`, and `strong` states.
- Explain the assessment with bounded factors and cautions covering independent
  satellite corroboration, freshness, FRP, primary confidence, and pixel count.
- Explicitly label the assessment as integration-calculated and not an official
  emergency confirmation.

## 0.2.0

- Activate optional NASA FIRMS corroboration with the user's personal MAP_KEY.
- Query bounded NOAA-20 and NOAA-21 VIIRS feeds no more than once every 15
  minutes and keep FIRMS failures isolated from primary LSA SAF monitoring.
- Correlate independent detections within explicit 5 km and 6 hour gates.
- Expose translated source-confirmation states and per-incident provider,
  confirmation, and corroborating-detection attributes.

## 0.1.1

- Replace the fire-specific branding with TerraLyra's provider-neutral globe
  and observation-eye identity.
- Include a scalable SVG source and transparent 256 px and 512 px icons.

## 0.1.0

- Launch TerraLyra as a clean, provider-neutral Home Assistant integration
  under the new `terralyra` domain and `TerraLyra/ha-terralyra` repository.
- Include EUMETSAT LSA SAF active-fire monitoring, persistent incident tracking,
  trend and situation indicators, offline place-name lookup, and map entities.
- Include the FRMv3 ten-day fire-risk forecast, calendar, sensors, and bounded
  forecast-map camera with offline country borders.
- Include optional, default-off MTLST land-surface temperature monitoring with
  clear location-disclosure text.
- Include optional, default-off NASA FIRMS configuration and secure provider
  foundation for future multi-source corroboration.
- Preserve bounded downloads, strict URL and host validation, TLS verification,
  decompression and image limits, credential redaction, and privacy-safe
  diagnostics.
- Provide English, Hungarian, German, French, Spanish, and Italian interface
  translations.

TerraLyra does not automatically migrate the earlier `lsa_saf` development
integration. Remove the old integration before installing TerraLyra, then
recreate dashboards and automations with the new entity and event names.
