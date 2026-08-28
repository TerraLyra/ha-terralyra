# Changelog

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
