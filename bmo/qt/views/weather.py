"""QML adapter for the configured weather carousel."""

from __future__ import annotations

import threading
from typing import Any

from bmo.qt.views.base import QtHostedView


class QtWeatherView(QtHostedView):
    kind = "weather"
    title = "Weather"

    def __init__(
        self,
        host: Any,
        *,
        locations: Any,
        default_index: int,
        page_provider: Any,
        announce: Any,
        cancel_announcements: Any,
        announcements_available: bool,
        on_close: Any,
        face_provider: Any = None,
        season_style: Any = None,
        animations: Any = None,
        debug: bool = False,
        announce_warnings: bool = True,
    ) -> None:
        del face_provider, season_style, animations, debug
        self.locations = tuple(locations)
        self.index = min(max(0, int(default_index)), max(0, len(self.locations) - 1))
        self.page_provider = page_provider
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.announcements_available = bool(announcements_available)
        self.announce_warnings = bool(announce_warnings)
        self.page: Any | None = None
        self.loading = True
        self.error = ""
        self._generation = 0
        super().__init__(host, on_close=on_close)
        self._load()

    def payload(self) -> dict[str, object]:
        configured = self.locations[self.index] if self.locations else None
        result: dict[str, object] = {
            "location": getattr(configured, "name", "Weather"),
            "pageLabel": (
                f"{self.index + 1} / {len(self.locations)}"
                if len(self.locations) > 1
                else ""
            ),
            "loading": self.loading,
            "error": self.error,
            "temperature": "--",
            "condition": "",
            "highLow": "",
            "details": [],
            "alerts": [],
            "canAnnounce": self.announcements_available,
        }
        if self.page is None:
            return result
        snapshot = self.page.snapshot
        from bmo.weather import WEATHER_DESCRIPTIONS

        result.update(
            {
                "location": snapshot.location.name,
                "temperature": f"{round(snapshot.temperature):.0f}°{snapshot.degree_unit}",
                "condition": WEATHER_DESCRIPTIONS.get(snapshot.weather_code, "weather unavailable").title(),
                "highLow": (
                    f"High {round(snapshot.high):.0f}°  •  Low {round(snapshot.low):.0f}°"
                ),
                "details": [
                    {"label": "Feels like", "value": f"{round(snapshot.apparent_temperature):.0f}°"},
                    {"label": "Rain", "value": f"{round(snapshot.precipitation_probability_max):.0f}%"},
                    {"label": "Humidity", "value": "--" if snapshot.humidity is None else f"{round(snapshot.humidity):.0f}%"},
                    {"label": "Wind", "value": "--" if snapshot.wind_speed is None else f"{round(snapshot.wind_speed):.0f} {snapshot.wind_unit}"},
                ],
                "alerts": [
                    {"event": alert.event, "headline": alert.headline, "severity": alert.severity}
                    for alert in self.page.alerts
                ],
            }
        )
        return result

    def _load(self) -> None:
        if not self.locations:
            self.loading = False
            self.error = "No weather locations are configured."
            self.refresh()
            return
        self._generation += 1
        generation = self._generation
        self.loading = True
        self.error = ""
        self.page = None
        self.refresh()

        def worker() -> None:
            try:
                page = self.page_provider(self.locations[self.index])
                error = ""
            except Exception as exc:
                page = None
                error = str(exc) or "Weather is unavailable right now."
            if self.closed or generation != self._generation:
                return
            self.page = page
            self.error = error
            self.loading = False
            self.refresh()

        threading.Thread(target=worker, name="qt-weather-load", daemon=True).start()

    def handle_action(self, action: str, value: str) -> None:
        del value
        if action == "weather_next" and self.locations:
            self.index = (self.index + 1) % len(self.locations)
            self._load()
            return
        if action == "weather_previous" and self.locations:
            self.index = (self.index - 1) % len(self.locations)
            self._load()
            return
        if action == "weather_refresh":
            self._load()
            return
        if action == "weather_announce" and self.page is not None:
            snapshot = self.page.snapshot
            from bmo.weather import WeatherService

            self.announce(WeatherService.format_report(snapshot), None)
            return
        super().handle_action(action, "")

    def close(self) -> None:
        self._generation += 1
        self.cancel_announcements()
        super().close()


__all__ = ["QtWeatherView"]
