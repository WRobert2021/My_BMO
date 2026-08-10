"""Deterministic, child-friendly weather descriptions and presentation rules."""

from __future__ import annotations

from enum import Enum

from bmo.features.weather_alerts import WeatherAlert
from bmo.weather import HourlyWeather, WEATHER_DESCRIPTIONS, WeatherSnapshot


class WeatherCondition(str, Enum):
    CLEAR = "clear"
    MOSTLY_CLEAR = "mostly_clear"
    PARTLY_CLOUDY = "partly_cloudy"
    CLOUDY = "cloudy"
    OVERCAST = "overcast"
    FOG = "fog"
    DRIZZLE = "drizzle"
    RAIN = "rain"
    HEAVY_RAIN = "heavy_rain"
    FREEZING_RAIN = "freezing_rain"
    SLEET = "sleet"
    SNOW = "snow"
    HEAVY_SNOW = "heavy_snow"
    THUNDERSTORM = "thunderstorm"
    HAIL = "hail"
    MIXED = "mixed"


class WeatherSeason(str, Enum):
    OFF = "off"
    NEUTRAL = "neutral"
    SPRING = "spring"
    SUMMER = "summer"
    FALL = "fall"
    WINTER = "winter"


def condition_for_code(code: int) -> WeatherCondition:
    """Map WMO weather codes to the smaller animation vocabulary."""
    if code == 0:
        return WeatherCondition.CLEAR
    if code == 1:
        return WeatherCondition.MOSTLY_CLEAR
    if code == 2:
        return WeatherCondition.PARTLY_CLOUDY
    if code == 3:
        return WeatherCondition.OVERCAST
    if code in {45, 48}:
        return WeatherCondition.FOG
    if code in {51, 53, 55}:
        return WeatherCondition.DRIZZLE
    if code in {56, 57}:
        return WeatherCondition.SLEET
    if code in {66, 67}:
        return WeatherCondition.FREEZING_RAIN
    if code in {61, 63, 80, 81}:
        return WeatherCondition.RAIN
    if code in {65, 82}:
        return WeatherCondition.HEAVY_RAIN
    if code in {71, 73, 77, 85}:
        return WeatherCondition.SNOW
    if code in {75, 86}:
        return WeatherCondition.HEAVY_SNOW
    if code == 95:
        return WeatherCondition.THUNDERSTORM
    if code in {96, 99}:
        return WeatherCondition.HAIL
    return WeatherCondition.MIXED


def season_for(
    latitude: float,
    month: int,
    style: str = "auto",
) -> WeatherSeason:
    """Return a simple hemisphere-aware decorative season."""
    if style == "off":
        return WeatherSeason.OFF
    if abs(latitude) < 23.5:
        return WeatherSeason.NEUTRAL
    if month not in range(1, 13):
        return WeatherSeason.NEUTRAL

    northern = {
        12: WeatherSeason.WINTER,
        1: WeatherSeason.WINTER,
        2: WeatherSeason.WINTER,
        3: WeatherSeason.SPRING,
        4: WeatherSeason.SPRING,
        5: WeatherSeason.SPRING,
        6: WeatherSeason.SUMMER,
        7: WeatherSeason.SUMMER,
        8: WeatherSeason.SUMMER,
        9: WeatherSeason.FALL,
        10: WeatherSeason.FALL,
        11: WeatherSeason.FALL,
    }[month]
    if latitude >= 0:
        return northern
    return {
        WeatherSeason.WINTER: WeatherSeason.SUMMER,
        WeatherSeason.SPRING: WeatherSeason.FALL,
        WeatherSeason.SUMMER: WeatherSeason.WINTER,
        WeatherSeason.FALL: WeatherSeason.SPRING,
    }[northern]


def _fahrenheit(value: float, imperial: bool) -> float:
    return value if imperial else value * 9 / 5 + 32


def _degrees(value: float, snapshot: WeatherSnapshot) -> str:
    return f"{round(value)} degrees {snapshot.degree_unit}"


def narrate_temperature(snapshot: WeatherSnapshot) -> str:
    temperature = _fahrenheit(snapshot.temperature, snapshot.imperial)
    spoken = _degrees(snapshot.temperature, snapshot)
    if temperature <= 32:
        advice = "Brrr! Bundle up with a coat, hat, and gloves, and watch for ice."
    elif temperature < 50:
        advice = "That is warm-coat weather."
    elif temperature < 65:
        advice = "A light jacket could be a cozy sidekick."
    elif temperature < 80:
        advice = "That sounds like comfortable adventure weather."
    elif temperature < 90:
        advice = "Wear something cool and bring water."
    elif temperature < 100:
        advice = "It is hot, so bring water and take breaks in the shade."
    else:
        advice = "That is very hot. Stay cool and check for an official heat alert."
    return f"Beep boop! It is {spoken}. {advice}"


def narrate_feels_like(snapshot: WeatherSnapshot) -> str:
    actual = round(snapshot.temperature)
    feels = round(snapshot.apparent_temperature)
    difference = snapshot.apparent_temperature - snapshot.temperature
    if not snapshot.imperial:
        difference *= 9 / 5
    sentence = (
        f"It is {actual} degrees {snapshot.degree_unit}, but your body may feel "
        f"about {feels}."
    )
    if difference >= 5 and snapshot.humidity is not None and snapshot.humidity >= 65:
        return f"{sentence} The air is extra sticky today!"
    if difference <= -5 and snapshot.wind_speed is not None and snapshot.wind_speed >= 15:
        return f"{sentence} The wind is making it feel cooler!"
    if abs(difference) < 3:
        return f"{sentence} That is pretty close to the real temperature."
    return sentence


def narrate_high_low(snapshot: WeatherSnapshot) -> str:
    high = round(snapshot.high)
    low = round(snapshot.low)
    unit = snapshot.degree_unit
    high_f = _fahrenheit(snapshot.high, snapshot.imperial)
    low_f = _fahrenheit(snapshot.low, snapshot.imperial)
    if high_f >= 90 and low_f >= 70:
        ending = "It will stay warm, even later today."
    elif high_f - low_f >= 20:
        ending = "The temperature changes a lot, so a layer could help later."
    elif low_f <= 40:
        ending = "Keep something warm nearby for the cooler part of the day."
    else:
        ending = "The temperature should stay fairly steady."
    return f"Today's high is {high} and the low is {low} degrees {unit}. {ending}"


def narrate_rain(snapshot: WeatherSnapshot) -> str:
    chance = round(snapshot.precipitation_probability_max)
    condition = condition_for_code(snapshot.weather_code)
    prefix = f"The biggest hourly precipitation chance today is {chance} percent."
    if condition in {WeatherCondition.THUNDERSTORM, WeatherCondition.HAIL}:
        return f"{prefix} Thunder may be nearby, so check with a grown-up before going outside."
    if condition is WeatherCondition.FREEZING_RAIN:
        return f"{prefix} Freezing rain can make the ground slippery, so be extra careful."
    if condition is WeatherCondition.SLEET:
        return f"{prefix} Icy drizzle can make slippery spots, so warm boots could help."
    if condition in {WeatherCondition.SNOW, WeatherCondition.HEAVY_SNOW}:
        return f"{prefix} Snow gear and warm boots could be helpful."
    if chance < 20:
        advice = "It will probably stay dry."
    elif chance < 40:
        advice = "A little rain might visit."
    elif chance < 60:
        advice = "An umbrella could be a good sidekick."
    elif chance < 80:
        advice = "Rain looks likely, so a raincoat could help."
    else:
        advice = "Rain is very likely. Boots and a raincoat are a good idea."
    return f"{prefix} {advice}"


def narrate_condition(snapshot: WeatherSnapshot) -> str:
    description = WEATHER_DESCRIPTIONS.get(snapshot.weather_code, "mixed weather")
    condition = condition_for_code(snapshot.weather_code)
    flavor = {
        WeatherCondition.CLEAR: "The sun is smiling!",
        WeatherCondition.MOSTLY_CLEAR: "The sun and clouds are playing peekaboo!",
        WeatherCondition.PARTLY_CLOUDY: "The clouds and sun are sharing the sky!",
        WeatherCondition.CLOUDY: "The clouds are having a parade!",
        WeatherCondition.OVERCAST: "A big cloud blanket is covering the sky!",
        WeatherCondition.FOG: "The clouds have come down for a ground-level visit!",
        WeatherCondition.DRIZZLE: "Tiny raindrops are tiptoeing outside!",
        WeatherCondition.RAIN: "Puddle-jumping weather has arrived!",
        WeatherCondition.HEAVY_RAIN: "The clouds are pouring a very big drink!",
        WeatherCondition.FREEZING_RAIN: "The rain may freeze, so watch for slippery spots.",
        WeatherCondition.SLEET: "Tiny icy drops are visiting, so watch for slippery spots.",
        WeatherCondition.SNOW: "Snowflakes are dancing through the air!",
        WeatherCondition.HEAVY_SNOW: "A whole crowd of snowflakes is visiting!",
        WeatherCondition.THUNDERSTORM: "Thunder is nearby, so it is safer to stay inside.",
        WeatherCondition.HAIL: "Hail and thunder may be nearby, so please stay inside.",
        WeatherCondition.MIXED: "The sky has a little bit of everything today!",
    }[condition]
    return f"It is {description} in {snapshot.location.name}. {flavor}"


def narrate_hour(hour: HourlyWeather, *, imperial: bool) -> str:
    unit = "F" if imperial else "C"
    raw_time = hour.time.split("T")[-1]
    time_label = raw_time
    try:
        clock_hour = int(raw_time.split(":", 1)[0])
        suffix = "AM" if clock_hour < 12 else "PM"
        time_label = f"{clock_hour % 12 or 12} {suffix}"
    except ValueError:
        pass
    description = WEATHER_DESCRIPTIONS.get(hour.weather_code, "mixed weather")
    chance = ""
    if hour.precipitation_probability is not None:
        chance = (
            f" The precipitation chance is "
            f"{round(hour.precipitation_probability)} percent."
        )
    return (
        f"At {time_label}, it should be {round(hour.temperature)} degrees {unit} "
        f"and {description}.{chance}"
    )


def narrate_alert(alert: WeatherAlert) -> str:
    """Speak an official alert without adding playful safety claims."""
    opening = f"BMO safety alert. {alert.headline}."
    if alert.instruction:
        first_instruction = alert.instruction.splitlines()[0].strip()
        if first_instruction:
            return f"{opening} {first_instruction}"
    return opening
