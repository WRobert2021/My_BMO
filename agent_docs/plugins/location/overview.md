---
id: plugin.location
type: plugin
plugin_type: feature
entrypoint: bmo.features.get_location
status: stable
tests: [tests/test_location_weather.py, tests/test_weather_feature.py]
---

# Plugin: Location

## Purpose

Answer “where am I?” from explicitly configured home data. Location does not
infer the household from public IP and is independently disableable from
Weather.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/tool behavior | `bmo/features/get_location.py` |
| validated locations and geocoding | `bmo/location.py` |
| timeout parsing | `bmo/network.py` (shared) |
| configuration | optional private `location` object in shared settings |
| persistence/UI/workers | none |

`register(registry, settings)` builds `GetLocationTool`. Generic location
requests resolve the configured home through `resolve_home_location`; a named
place path is consumed by Weather rather than this tool. `geocode_location`
uses low-volume user-triggered Nominatim HTTPS lookup and validates returned
finite coordinates. No API key is required.

## Configuration and privacy

The private settings object may contain name, latitude, longitude, and
timezone. Coordinates avoid a geocoding lookup but are still sensitive and
must not enter tracked docs/tests. Use public invented examples only. Provider
lookups send a place name to Nominatim. Network failures are bounded by
`online_timeout_seconds` and become user-facing expected errors.

## Failure boundary and tests

Missing home configuration affects only generic home requests. Invalid config
or provider data fails locally; no worker or client persists after execution.
Primary: `tests/test_location_weather.py`. Shared Weather integration:
`tests/test_weather_feature.py`.

## Shared interfaces

Consumes shared text/tool and bounded network-timeout contracts. `bmo.location`
is neutral support also consumed by Weather; Location exposes no plugin-owned
cross-plugin API.

For continuation/status, read `progress.md`.
