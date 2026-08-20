"""Toolkit-neutral weather presentation state shared by every GUI adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from bmo.features.weather_alerts import WeatherAlert
from bmo.features.weather_narration import (
    WeatherCondition,
    condition_for_code,
    season_for,
)
from bmo.weather import (
    WEATHER_DESCRIPTIONS,
    HourlyWeather,
    WeatherSnapshot,
    temperature_as_fahrenheit,
)


MOON_PHASES = (
    "new",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
)
_REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14)
_SYNODIC_MONTH_DAYS = 29.530588853


@dataclass(frozen=True)
class WeatherPageData:
    """One successfully loaded location page."""

    snapshot: WeatherSnapshot
    alerts: tuple[WeatherAlert, ...] = ()


class WeatherCarousel:
    """Wrap ordered weather locations independently from rendering."""

    def __init__(self, count: int, selected_index: int = 0) -> None:
        if count < 1:
            raise ValueError("A weather carousel needs at least one location.")
        if not 0 <= selected_index < count:
            raise ValueError("Weather carousel index is out of range.")
        self.count = count
        self.selected_index = selected_index

    def swipe_left(self) -> int:
        self.selected_index = (self.selected_index + 1) % self.count
        return self.selected_index

    def swipe_right(self) -> int:
        self.selected_index = (self.selected_index - 1) % self.count
        return self.selected_index


def parse_local_datetime(value: str | None) -> datetime | None:
    """Parse an Open-Meteo local ISO timestamp without inventing a timezone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def moon_phase_for(moment: datetime) -> str:
    """Return one of eight child-readable moon phases for a moment."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    age_days = (
        (moment - _REFERENCE_NEW_MOON).total_seconds() / 86400
    ) % _SYNODIC_MONTH_DAYS
    phase_index = int(age_days / _SYNODIC_MONTH_DAYS * 8 + 0.5) % 8
    return MOON_PHASES[phase_index]


def select_upcoming_hours(
    snapshot: WeatherSnapshot,
    local_now: datetime,
    *,
    limit: int = 4,
) -> tuple[HourlyWeather, ...]:
    """Select the next local forecast points, dropping time slots already past."""
    if limit < 1:
        return ()
    selected: list[HourlyWeather] = []
    for hour in snapshot.hourly:
        timestamp = parse_local_datetime(hour.time)
        if timestamp is not None and timestamp < local_now:
            continue
        selected.append(hour)
        if len(selected) >= limit:
            break
    return tuple(selected)


def day_period_for(snapshot: WeatherSnapshot, local_now: datetime) -> str:
    """Classify local time into the five scenery periods used by the screen."""
    sunrise = parse_local_datetime(snapshot.sunrise)
    sunset = parse_local_datetime(snapshot.sunset)
    if sunrise is not None and local_now < sunrise:
        return "night"
    if sunset is not None:
        if local_now >= sunset + timedelta(minutes=35):
            return "night"
        if local_now >= sunset - timedelta(minutes=75):
            return "sunset"
    if snapshot.is_day is False:
        return "night"
    if local_now.hour < 10:
        return "morning"
    if local_now.hour < 14:
        return "midday"
    return "afternoon"


def _visual_condition(data: WeatherPageData) -> str:
    """Layer measured modifiers over the WMO condition without inventing alerts."""
    snapshot = data.snapshot
    if data.alerts:
        alert = data.alerts[0]
        if (
            "warning" in alert.event.casefold()
            or alert.severity.casefold() in {"extreme", "severe"}
        ):
            return "severe"
    condition = condition_for_code(snapshot.weather_code)
    primary = {
        WeatherCondition.CLEAR: "sunny",
        WeatherCondition.MOSTLY_CLEAR: "mostly-clear",
        WeatherCondition.PARTLY_CLOUDY: "partly",
        WeatherCondition.CLOUDY: "cloudy",
        WeatherCondition.OVERCAST: "overcast",
        WeatherCondition.FOG: "fog",
        WeatherCondition.DRIZZLE: "drizzle",
        WeatherCondition.RAIN: "rain",
        WeatherCondition.HEAVY_RAIN: "heavy-rain",
        WeatherCondition.FREEZING_RAIN: "freezing-rain",
        WeatherCondition.SLEET: "sleet",
        WeatherCondition.SNOW: "snow",
        WeatherCondition.HEAVY_SNOW: "heavy-snow",
        WeatherCondition.THUNDERSTORM: "storm",
        WeatherCondition.HAIL: "hail",
        WeatherCondition.MIXED: "mixed",
    }[condition]
    if condition not in {
        WeatherCondition.CLEAR,
        WeatherCondition.MOSTLY_CLEAR,
        WeatherCondition.PARTLY_CLOUDY,
        WeatherCondition.CLOUDY,
        WeatherCondition.OVERCAST,
        WeatherCondition.MIXED,
    }:
        return primary
    if snapshot.wind_gusts is not None:
        gust_mph = (
            snapshot.wind_gusts
            if snapshot.imperial
            else snapshot.wind_gusts / 1.609344
        )
        if gust_mph >= 35:
            return "wind"
    temperature_f = temperature_as_fahrenheit(
        snapshot.temperature,
        snapshot.imperial,
    )
    feels_f = temperature_as_fahrenheit(
        snapshot.apparent_temperature,
        snapshot.imperial,
    )
    if max(temperature_f, feels_f) >= 100:
        return "hot"
    if min(temperature_f, feels_f) <= 25:
        return "cold"
    return primary


def _condition_title(data: WeatherPageData, period: str, visual: str) -> str:
    if visual == "severe":
        return "Safety alert"
    if visual == "wind":
        return "Very windy"
    if visual == "hot":
        return "Very hot"
    if visual == "cold":
        return "Very cold"
    if period == "night" and visual in {"sunny", "mostly-clear"}:
        return "Clear night"
    titles = {
        "sunny": "Sunny",
        "mostly-clear": "Mostly clear",
        "partly": "Partly cloudy",
        "cloudy": "Cloudy",
        "overcast": "Overcast",
        "fog": "Foggy",
        "drizzle": "Drizzly",
        "rain": "Rainy",
        "heavy-rain": "Heavy rain",
        "freezing-rain": "Freezing rain",
        "sleet": "Sleet & ice",
        "snow": "Snowy",
        "heavy-snow": "Heavy snow",
        "storm": "Stormy",
        "hail": "Hail",
        "mixed": "Mixed weather",
    }
    return titles.get(
        visual,
        WEATHER_DESCRIPTIONS.get(
            data.snapshot.weather_code,
            "Mixed weather",
        ).title(),
    )


def _condition_modifier(
    data: WeatherPageData,
    period: str,
    visual: str,
    local_now: datetime,
) -> str:
    snapshot = data.snapshot
    if visual == "severe":
        return "Official warning active"
    if period == "night" and visual in {
        "sunny",
        "mostly-clear",
        "partly",
        "hot",
    }:
        return f"{moon_phase_for(local_now).replace('_', ' ')} moon"
    if visual == "wind" and snapshot.wind_gusts is not None:
        return f"Gusts near {round(snapshot.wind_gusts)} {snapshot.wind_unit}"
    if visual == "hot":
        return "Heat-safety day"
    if visual == "cold":
        return "Freezing outside"
    labels = {
        "sunny": "Warm sunshine",
        "mostly-clear": "A few cloud friends",
        "partly": "Sun-and-cloud team-up",
        "cloudy": "A soft cloud blanket",
        "overcast": "Cloud blanket overhead",
        "fog": "Low visibility",
        "drizzle": "Tiny tiptoe raindrops",
        "rain": "Puddle weather",
        "heavy-rain": "Big raindrops",
        "freezing-rain": "Slippery-ground alert",
        "sleet": "Slippery-ground alert",
        "snow": "Dancing snowflakes",
        "heavy-snow": "Lots of snowflakes",
        "storm": "Thunder nearby",
        "hail": "Icy pebbles falling",
        "mixed": "A little bit of everything",
    }
    if (
        visual
        in {
            "sunny",
            "mostly-clear",
            "partly",
            "cloudy",
            "overcast",
            "mixed",
        }
        and snapshot.humidity is not None
        and snapshot.humidity >= 80
    ):
        return "Extra-sticky air"
    return labels.get(visual, "Today's sky")


def _condition_flavor(data: WeatherPageData, period: str, visual: str) -> str:
    if visual == "severe":
        return (
            "BMO safety alert. Go with a grown-up and follow official "
            "instructions now."
        )
    if period == "night" and visual in {"sunny", "mostly-clear"}:
        return "The moon is smiling! Cozy night-sky time."
    if period == "night" and visual == "partly":
        return "The moon and clouds are playing peekaboo!"
    if period == "night" and visual == "hot":
        return "It is a warm night. Keep water nearby!"
    flavors = {
        "sunny": "The sun is smiling! Grab water and sunscreen.",
        "mostly-clear": "The sun has a few fluffy cloud friends!",
        "partly": "The sun and clouds are sharing the sky!",
        "cloudy": "The clouds are having a parade!",
        "overcast": "A soft cloud blanket is covering the sky!",
        "fog": (
            "The clouds came down to visit. Stay where a grown-up can see you!"
        ),
        "drizzle": "A light raincoat could be a cozy sidekick.",
        "rain": "Puddle-jumping weather! Bring your raincoat and boots.",
        "heavy-rain": "Big rain is falling. Raincoat and boots time!",
        "freezing-rain": (
            "Icy rain can make slippery spots. Stay close to a grown-up!"
        ),
        "sleet": "Icy drops can make slippery spots. Stay close to a grown-up!",
        "snow": "Bundle up! Coat, hat, gloves, and warm boots.",
        "heavy-snow": (
            "Lots of snow is dancing down. Bundle up and stay with a grown-up!"
        ),
        "storm": "Thunder nearby. Let's stay safely inside with a grown-up!",
        "hail": "Hail is falling. Please stay safely inside!",
        "wind": (
            "Hold onto your hat and check with a grown-up before going outside!"
        ),
        "hot": (
            "Super-hot alert! Water, shade, sunscreen, and plenty of breaks."
        ),
        "cold": (
            "Brrr! Coat, hat, gloves, and a grown-up are good adventure buddies."
        ),
        "mixed": "The sky has a little bit of everything today!",
    }
    return flavors.get(visual, "Let's look at today's sky!")


def _hour_icon(hour: HourlyWeather) -> str:
    condition = condition_for_code(hour.weather_code)
    if condition is WeatherCondition.CLEAR:
        return "sun" if hour.is_day is not False else "moon"
    if condition in {
        WeatherCondition.MOSTLY_CLEAR,
        WeatherCondition.PARTLY_CLOUDY,
    }:
        return "partly" if hour.is_day is not False else "moon-cloud"
    return {
        WeatherCondition.CLOUDY: "cloud",
        WeatherCondition.OVERCAST: "cloud",
        WeatherCondition.FOG: "fog",
        WeatherCondition.DRIZZLE: "drizzle",
        WeatherCondition.RAIN: "rain",
        WeatherCondition.HEAVY_RAIN: "rain",
        WeatherCondition.FREEZING_RAIN: "sleet",
        WeatherCondition.SLEET: "sleet",
        WeatherCondition.SNOW: "snow",
        WeatherCondition.HEAVY_SNOW: "snow",
        WeatherCondition.THUNDERSTORM: "storm",
        WeatherCondition.HAIL: "hail",
        WeatherCondition.MIXED: "cloud",
    }[condition]


def _format_hour(value: str) -> str:
    raw = value.split("T")[-1]
    try:
        hour = int(raw.split(":", 1)[0])
    except ValueError:
        return raw[:5]
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def weather_view_state(
    data: WeatherPageData,
    local_now: datetime,
    *,
    season_style: str,
    animations: bool,
    debug: bool,
    speech_available: bool,
    page_index: int,
    page_count: int,
    subtitle: str = "",
    speaking_key: str | None = None,
) -> dict[str, Any]:
    """Serialize immutable weather data into the shared scene contract."""
    snapshot = data.snapshot
    period = day_period_for(snapshot, local_now)
    visual = _visual_condition(data)
    season = season_for(
        snapshot.location.latitude,
        local_now.month,
        season_style,
    ).value
    hours = select_upcoming_hours(snapshot, local_now)
    serialized_hours = [
        {
            "key": f"hour:{index}",
            "time": _format_hour(hour.time),
            "temperature": round(hour.temperature),
            "icon": _hour_icon(hour),
        }
        for index, hour in enumerate(hours)
    ]
    alert = data.alerts[0] if data.alerts else None
    flavor = _condition_flavor(data, period, visual)
    return {
        "status": "ready",
        "location": snapshot.location.name,
        "condition": visual,
        "condition_name": _condition_title(data, period, visual),
        "modifier": _condition_modifier(data, period, visual, local_now),
        "speech": subtitle or flavor,
        "temperature": round(snapshot.temperature),
        "feels": round(snapshot.apparent_temperature),
        "high": round(snapshot.high),
        "low": round(snapshot.low),
        "rain": round(snapshot.precipitation_probability_max),
        "time": period,
        "season": season,
        "phase": moon_phase_for(local_now).replace("_", "-"),
        "hours": serialized_hours,
        "page_index": page_index,
        "page_count": page_count,
        "alert": alert.event if alert is not None else None,
        "animations": animations,
        "debug": debug,
        "speech_available": speech_available,
        "speaking_key": speaking_key,
    }


__all__ = [
    "MOON_PHASES",
    "WeatherCarousel",
    "WeatherPageData",
    "day_period_for",
    "moon_phase_for",
    "parse_local_datetime",
    "select_upcoming_hours",
    "weather_view_state",
]
