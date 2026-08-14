"""Structured current weather and forecast data from Open-Meteo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from bmo.location import JsonRequest, Location, LocationService, request_json


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


def temperature_as_fahrenheit(value: float, imperial: bool) -> float:
    """Normalize a configured weather temperature to Fahrenheit."""
    return value if imperial else value * 9 / 5 + 32


class WeatherError(RuntimeError):
    """Raised when weather data is unavailable or malformed."""


@dataclass(frozen=True)
class HourlyWeather:
    """One local forecast point used by the weather carousel."""

    time: str
    temperature: float
    apparent_temperature: float
    weather_code: int
    precipitation_probability: float | None = None
    is_day: bool | None = None


@dataclass(frozen=True)
class WeatherSnapshot:
    """Weather values shared by speech formatting and graphical presentation."""

    location: Location
    imperial: bool
    observed_at: str
    temperature: float
    apparent_temperature: float
    weather_code: int
    high: float
    low: float
    precipitation_probability_max: float
    humidity: float | None = None
    wind_speed: float | None = None
    wind_gusts: float | None = None
    visibility_meters: float | None = None
    cloud_cover: float | None = None
    current_precipitation: float | None = None
    precipitation_sum: float | None = None
    is_day: bool | None = None
    sunrise: str | None = None
    sunset: str | None = None
    hourly: tuple[HourlyWeather, ...] = ()

    @property
    def degree_unit(self) -> str:
        return "F" if self.imperial else "C"

    @property
    def wind_unit(self) -> str:
        return "mph" if self.imperial else "km/h"

    @property
    def precipitation_unit(self) -> str:
        return "in" if self.imperial else "mm"


def _required_float(mapping: dict[str, Any], key: str) -> float:
    try:
        return float(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError("weather service returned invalid data") from exc


def _optional_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _daily_value(daily: dict[str, Any], key: str, *, required: bool) -> Any:
    values = daily.get(key)
    if not isinstance(values, list) or not values:
        if required:
            raise WeatherError("weather service returned invalid data")
        return None
    return values[0]


class WeatherService:
    """Fetch typed weather snapshots and speech-friendly reports."""

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
        """Return the historical short spoken report for one place."""
        return self.format_report(self.current_snapshot(place_name))

    def current_snapshot(
        self,
        place_name: str | None = None,
        *,
        location: Location | None = None,
    ) -> WeatherSnapshot:
        """Resolve a place and fetch its structured current forecast."""
        resolved = location or self.location_service.resolve(place_name)
        imperial = self.units.strip().lower() != "metric"
        payload = self._json_request(
            self._forecast_url(resolved, imperial),
            self.timeout,
        )
        return self._parse_snapshot(payload, resolved, imperial)

    def _forecast_url(self, location: Location, imperial: bool) -> str:
        parameters = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "current": (
                "temperature_2m,apparent_temperature,weather_code,"
                "relative_humidity_2m,wind_speed_10m,wind_gusts_10m,"
                "visibility,cloud_cover,is_day,precipitation"
            ),
            "hourly": (
                "temperature_2m,apparent_temperature,weather_code,"
                "precipitation_probability,is_day"
            ),
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,"
                "sunrise,sunset"
            ),
            "forecast_days": 2,
            "timezone": location.timezone,
            "temperature_unit": "fahrenheit" if imperial else "celsius",
            "wind_speed_unit": "mph" if imperial else "kmh",
            "precipitation_unit": "inch" if imperial else "mm",
        }
        return f"{self.FORECAST_URL}?{urlencode(parameters)}"

    @classmethod
    def _parse_snapshot(
        cls,
        payload: Any,
        location: Location,
        imperial: bool,
    ) -> WeatherSnapshot:
        if not isinstance(payload, dict):
            raise WeatherError("weather service returned incomplete data")
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise WeatherError("weather service returned incomplete data")

        try:
            weather_code = int(current["weather_code"])
            high = float(_daily_value(daily, "temperature_2m_max", required=True))
            low = float(_daily_value(daily, "temperature_2m_min", required=True))
            rain_chance = float(
                _daily_value(
                    daily,
                    "precipitation_probability_max",
                    required=True,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherError("weather service returned invalid data") from exc

        observed_at = str(current.get("time") or "")
        return WeatherSnapshot(
            location=location,
            imperial=imperial,
            observed_at=observed_at,
            temperature=_required_float(current, "temperature_2m"),
            apparent_temperature=_required_float(current, "apparent_temperature"),
            weather_code=weather_code,
            high=high,
            low=low,
            precipitation_probability_max=rain_chance,
            humidity=_optional_float(current, "relative_humidity_2m"),
            wind_speed=_optional_float(current, "wind_speed_10m"),
            wind_gusts=_optional_float(current, "wind_gusts_10m"),
            visibility_meters=_optional_float(current, "visibility"),
            cloud_cover=_optional_float(current, "cloud_cover"),
            current_precipitation=_optional_float(current, "precipitation"),
            precipitation_sum=cls._optional_daily_float(daily, "precipitation_sum"),
            is_day=cls._optional_bool(current.get("is_day")),
            sunrise=cls._optional_daily_text(daily, "sunrise"),
            sunset=cls._optional_daily_text(daily, "sunset"),
            hourly=cls._parse_hourly(payload.get("hourly"), observed_at),
        )

    @staticmethod
    def _optional_daily_float(daily: dict[str, Any], key: str) -> float | None:
        value = _daily_value(daily, key, required=False)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_daily_text(daily: dict[str, Any], key: str) -> str | None:
        value = _daily_value(daily, key, required=False)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_bool(value: object) -> bool | None:
        if value in (0, 0.0, False):
            return False
        if value in (1, 1.0, True):
            return True
        return None

    @classmethod
    def _parse_hourly(
        cls,
        raw: object,
        observed_at: str,
    ) -> tuple[HourlyWeather, ...]:
        if not isinstance(raw, dict):
            return ()
        times = raw.get("time")
        temperatures = raw.get("temperature_2m")
        apparent = raw.get("apparent_temperature")
        codes = raw.get("weather_code")
        if not all(isinstance(values, list) for values in (times, temperatures, codes)):
            return ()
        probabilities = raw.get("precipitation_probability")
        day_values = raw.get("is_day")
        hours: list[HourlyWeather] = []
        for index in range(min(len(times), len(temperatures), len(codes))):
            time_value = str(times[index])
            if observed_at and time_value < observed_at:
                continue
            try:
                temperature = float(temperatures[index])
                apparent_temperature = (
                    float(apparent[index])
                    if isinstance(apparent, list) and index < len(apparent)
                    else temperature
                )
                code = int(codes[index])
            except (TypeError, ValueError, IndexError):
                continue
            probability = None
            if isinstance(probabilities, list) and index < len(probabilities):
                try:
                    probability = float(probabilities[index])
                except (TypeError, ValueError):
                    probability = None
            is_day = None
            if isinstance(day_values, list) and index < len(day_values):
                is_day = cls._optional_bool(day_values[index])
            hours.append(
                HourlyWeather(
                    time=time_value,
                    temperature=temperature,
                    apparent_temperature=apparent_temperature,
                    weather_code=code,
                    precipitation_probability=probability,
                    is_day=is_day,
                )
            )
            if len(hours) >= 8:
                break
        return tuple(hours)

    @staticmethod
    def format_report(snapshot: WeatherSnapshot) -> str:
        """Format a typed snapshot for the existing speech response."""
        temperature = round(snapshot.temperature)
        feels_like = round(snapshot.apparent_temperature)
        high = round(snapshot.high)
        low = round(snapshot.low)
        rain_chance = round(snapshot.precipitation_probability_max)
        description = WEATHER_DESCRIPTIONS.get(
            snapshot.weather_code,
            "mixed weather",
        )
        return (
            f"In {snapshot.location.name}, it is {temperature} degrees "
            f"{snapshot.degree_unit} and {description}, and it feels like "
            f"{feels_like}. Today's high is {high}, the low is {low}, "
            f"and the highest hourly rain chance today is {rain_chance} percent."
        )

    @classmethod
    def _format_report(
        cls,
        payload: dict[str, Any],
        location_name: str,
        imperial: bool,
    ) -> str:
        """Retain the old formatter hook for compatibility callers."""
        location = Location(location_name, 0.0, 0.0)
        return cls.format_report(cls._parse_snapshot(payload, location, imperial))
