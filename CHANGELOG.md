# Changelog

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
