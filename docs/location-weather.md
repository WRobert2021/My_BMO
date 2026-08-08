# Location and weather

Named weather requests resolve the location spoken by the user at request
time; the weather location does not need to be stored in `config.json`. The
agent does not infer the household's location from its public IP address.
Current weather and place-name lookup use Open-Meteo over HTTPS and require an
internet connection, but no API key.
Weather data is provided by Open-Meteo under its CC BY 4.0 data license.

An optional `location` object can be added only if generic requests such as
"What's the weather?" should use a home location:

```json
{
  "location": {
    "name": "Dallas, Texas",
    "latitude": 32.7767,
    "longitude": -96.797,
    "timezone": "America/Chicago"
  },
  "weather_units": "imperial",
  "online_timeout_seconds": 6
}
```

Coordinates are preferred because home-location requests then skip geocoding.
You can omit latitude, longitude, and timezone and set only `name`; the agent
will geocode that name when needed. Use `"weather_units": "metric"` for Celsius
and km/h.

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
python -m unittest tests.test_location_weather
```
