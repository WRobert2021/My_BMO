---
id: plugin.weather
type: plugin
plugin_type: feature
entrypoint: bmo.features.get_weather
status: stable
tests: [tests/test_weather_feature.py, tests/test_location_weather.py]
---

# Plugin: Weather

## Purpose

Provide named/home spoken forecasts and a menu carousel rendered directly in
production QML, using Nominatim/OpenStreetMap for optional geocoding and
Open-Meteo for forecasts. Optional US alerts use NWS.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/provider/view lifecycle | `bmo/features/get_weather.py` |
| private config | `weather_config.py` |
| alert provider | `weather_alerts.py` |
| narration and neutral scene data | `weather_narration.py`, `weather_view.py` |
| neutral providers | `bmo/location.py`, `bmo/weather.py`, `bmo/network.py` |
| production adapter/QML | `bmo/qt/views/weather.py`, Weather QML files |
| legacy UI | `bmo/ui/weather.py`, `bmo/ui/weather_web/` |
| persistent state | none; view-lifetime cache |

Named requests geocode at request time; generic requests use explicit private
home configuration. No IP geolocation is permitted. `WeatherSnapshot` is the
neutral contract for speech and UI. The Qt adapter owns bounded daemon fetch
workers, per-location cache/tokens, refresh timer, deterministic tap narration,
debug previews, and stale/closed-view guards. Production starts no browser or
loopback server; only the explicit Tk fallback owns Chromium/bridge lifecycle.

## Configuration and failure

`config/example.weather.json` documents units, ordered locations, default,
scene flags, debug, and optional alerts. Private exact locations must not enter
tracked content. Provider calls use bounded timeouts. Alert failure never
invalidates a valid forecast; late workers cannot update a closed/newer view.
Closing stops timers, invalidates workers, and cancels scoped speech. Metadata
loading creates no provider, cache, worker, or UI.

## Tests and interfaces

Primary: `tests/test_weather_feature.py`, `tests/test_location_weather.py`;
shared Qt: `tests/test_qt_shell.py`. Consumes scoped announcements and neutral
location/network services. Exposes no plugin-owned cross-plugin API.

For continuation/status, read `progress.md`.
