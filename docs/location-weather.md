# Location and weather

Named weather requests resolve the location spoken by the user at request
time; the weather location does not need to be stored in
`config/settings.json`. The agent does not infer the household's location from
its public IP address.
Place-name lookup uses the public Nominatim service and OpenStreetMap data;
the resulting coordinates are sent to Open-Meteo for current weather. Both
requests use HTTPS and require an internet connection, but neither requires an
API key.

The menu-launched weather view uses the same forecast snapshot as the spoken
response. It opens a dedicated fullscreen Chromium surface containing only
project-owned HTML, CSS, and SVG graphics. Its local communication server binds
to a random `127.0.0.1` port with a per-view token and stops when Weather
closes; it is never exposed on the LAN. The Tk menu and other features do not
use Chromium.

Copy `config/example.weather.json` to the ignored `config/weather.json` to set
the ordered location carousel. Set `"debug": true` while verifying graphics.
A small **D** control then opens selectors for every supported condition,
season, morning/midday/afternoon/sunset/night period, and eight basic moon
phases. The debugger changes only the browser preview; **Live weather** restores
the real forecast immediately. Keep debug disabled for the normal child-facing
screen.

These are external services. A named-place lookup sends the spoken place name
to Nominatim, and every weather lookup sends coordinates to Open-Meteo. Keep a
real home location only in the ignored `config/settings.json`, never in tracked
examples, documentation, or tests. Do not submit exact addresses or other
confidential location data. The public Nominatim endpoint is intended only for
low-volume, user-triggered lookups; do not reuse this feature for bulk,
periodic, or autocomplete geocoding. See the
[Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

Geocoding data is © OpenStreetMap contributors and available under the
[ODbL](https://www.openstreetmap.org/copyright). Weather data is provided by
Open-Meteo under its
[CC BY 4.0 data license](https://open-meteo.com/).

An optional `location` object can be added to the private
`config/settings.json` only if generic requests such as "What's the weather?"
should use a home location. The values below are public example coordinates,
not a project default:

```json
{
  "location": {
    "name": "New York, New York",
    "latitude": 40.7128,
    "longitude": -74.006,
    "timezone": "America/New_York"
  },
  "weather_units": "imperial",
  "online_timeout_seconds": 6
}
```

Coordinates are preferred because home-location requests then skip geocoding.
The coordinates are still sent to Open-Meteo for the weather request. You can
omit latitude, longitude, and timezone and set only `name`; the agent will send
that name to Nominatim when it needs to geocode it. Use
`"weather_units": "metric"` for Celsius and km/h.

Supported examples:

- "Where am I?"
- "What's the weather?"
- "What's the weather in Austin?"
- "Weather for Chicago."

Without a home location, requests naming a city still work and generic home
weather requests return a configuration reminder. City/state phrases such as
"Houston, Texas" are resolved dynamically. Network and malformed response
failures are bounded by the configured timeout and do not stop the main
conversation loop.

Run the unit tests without Pi hardware:

```bash
python -m pytest -q tests/test_location_weather.py
```
