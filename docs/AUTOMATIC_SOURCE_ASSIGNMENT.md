# Automatic active-fire source assignment

TerraLyra assigns sources independently for every enabled monitored location.
There is no primary, secondary or fallback rank.

| Location coverage | Automatically assigned source |
|---|---|
| Safe MTG viewing area | EUMETSAT LSA SAF MTG, when credentials are configured |
| GOES-18 or GOES-19 viewing area | NOAA GOES ABI FDCF |
| Any location | NASA FIRMS, when a MAP_KEY is configured |

All successful sources enter the same normalized incident pipeline. A failed
source does not stop healthy peers. Nearby observations from different
satellites are merged into one incident and reported as multi-source evidence;
their radiative power is not added together as if it were separate fire
energy.

The assignment and current health of each source are visible in the
active-fire data-source and independent-source-confirmation entity attributes.
An uncovered location creates an actionable Home Assistant Repair instead of
silently selecting an unsuitable source.

## Home Assistant map notes

TerraLyra publishes native `geo_location` entities so the standard Home
Assistant map card can display incidents. The card controls its own base-map
provider, attribution and marker rendering. Consequently:

- a CARTO `API KEY REQUIRED` watermark comes from the selected Home Assistant
  base-map tiles, not from TerraLyra or its satellite providers;
- the standard card may render geolocation markers as initials rather than the
  entity's fire icon;
- the map source selector correctly shows `terralyra`, because all upstream
  satellite observations are normalized and deduplicated by this integration.

For a clear dashboard title use **TerraLyra active fires** rather than the
legacy **LSA SAF active fires**. Provider names, satellites, confirmation level
and attribution remain available on each marker's attributes.
