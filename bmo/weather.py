"""Current weather and today's forecast from Open-Meteo."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from bmo.location import JsonRequest, LocationService, request_json


WEATHER_DESCRIPTIONS = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with frost",
    51: "light drizzle",
    53: "drizzling",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "raining",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snowing",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with light hail",
    99: "thunderstorms with heavy hail",
}


class WeatherError(RuntimeError):
    """Raised when weather data is unavailable or malformed."""


class WeatherService:
    """Return short, speech-friendly weather reports."""

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(
        self,
        location_service: LocationService,
        timeout: float = 6.0,
        units: str = "imperial",
        json_request: JsonRequest = request_json,
    ) -> None:
        self.location_service = location_service
        self.timeout = timeout
        self.units = units
        self._json_request = json_request

    def current_report(self, place_name: str | None = None) -> str:
        location = self.location_service.resolve(place_name)
        imperial = self.units.lower() != "metric"
        parameters = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "current": (
                "temperature_2m,apparent_temperature,weather_code,"
                "relative_humidity_2m,wind_speed_10m"
            ),
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "forecast_days": 1,
            "timezone": location.timezone,
            "temperature_unit": "fahrenheit" if imperial else "celsius",
            "wind_speed_unit": "mph" if imperial else "kmh",
            "precipitation_unit": "inch" if imperial else "mm",
        }
        payload = self._json_request(
            f"{self.FORECAST_URL}?{urlencode(parameters)}",
            self.timeout,
        )
        return self._format_report(payload, location.name, imperial)

    @staticmethod
    def _format_report(
        payload: dict[str, Any],
        location_name: str,
        imperial: bool,
    ) -> str:
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise WeatherError("weather service returned incomplete data")

        try:
            temperature = round(float(current["temperature_2m"]))
            feels_like = round(float(current["apparent_temperature"]))
            code = int(current["weather_code"])
            high = round(float(daily["temperature_2m_max"][0]))
            low = round(float(daily["temperature_2m_min"][0]))
            rain_chance = round(float(daily["precipitation_probability_max"][0]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WeatherError("weather service returned invalid data") from exc

        degree_unit = "F" if imperial else "C"
        description = WEATHER_DESCRIPTIONS.get(code, "mixed weather")
        return (
            f"In {location_name}, it is {temperature} degrees {degree_unit} "
            f"and {description}, and it feels like {feels_like}. "
            f"Today's high is {high}, the low is {low}, "
            f"and the rain chance is {rain_chance} percent."
        )
