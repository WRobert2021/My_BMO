"""Toolkit-neutral weather page records shared by feature presentations."""

from __future__ import annotations

from dataclasses import dataclass

from bmo.features.weather_alerts import WeatherAlert
from bmo.weather import WeatherSnapshot


@dataclass(frozen=True)
class WeatherPageData:
    """One successfully loaded location page."""

    snapshot: WeatherSnapshot
    alerts: tuple[WeatherAlert, ...] = ()


__all__ = ["WeatherPageData"]
