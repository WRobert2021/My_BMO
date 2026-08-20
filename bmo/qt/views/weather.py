"""QML adapter for the animated, child-friendly weather carousel."""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import QTimer

from bmo.features.weather_narration import (
    narrate_alert,
    narrate_condition,
    narrate_feels_like,
    narrate_high_low,
    narrate_hour,
    narrate_rain,
    narrate_temperature,
)
from bmo.features.weather_view import (
    WeatherPageData,
    parse_local_datetime,
    select_upcoming_hours,
    weather_view_state,
)
from bmo.qt.views.base import QtHostedView
from bmo.weather import HourlyWeather, WeatherSnapshot


_DEBUG_CONDITION_SPEECH = {
    "sunny": "The sun is smiling! Grab water and sunscreen.",
    "mostly-clear": "The sun has a few fluffy cloud friends!",
    "partly": "The sun and clouds are sharing the sky!",
    "cloudy": "The clouds are having a parade!",
    "overcast": "A soft cloud blanket is covering the sky!",
    "fog": "The clouds came down to visit. Stay where a grown-up can see you!",
    "drizzle": "A light raincoat could be a cozy sidekick.",
    "rain": "Puddle-jumping weather! Bring your raincoat and boots.",
    "heavy-rain": "Big rain is falling. Raincoat and boots time!",
    "freezing-rain": "Icy rain can make slippery spots. Stay close to a grown-up!",
    "storm": "Thunder nearby. Let's stay safely inside with a grown-up!",
    "snow": "Bundle up! Coat, hat, gloves, and warm boots.",
    "heavy-snow": "Lots of snow is dancing down. Bundle up and stay with a grown-up!",
    "sleet": "Icy drops can make slippery spots. Stay close to a grown-up!",
    "hail": "Hail is falling. Please stay safely inside!",
    "wind": "Hold onto your hat and check with a grown-up before going outside!",
    "hot": "Super-hot alert! Water, shade, sunscreen, and plenty of breaks.",
    "cold": "Brrr! Coat, hat, gloves, and warm boots.",
    "mixed": "The sky has a little bit of everything today!",
    "severe": "BMO safety alert. Go with a grown-up and follow official instructions now.",
}


class QtWeatherView(QtHostedView):
    """Own weather data, narration, refresh, and QML scene state."""

    kind = "weather"
    title = "Weather"
    REFRESH_SECONDS = 15 * 60
    TICK_MS = 1000

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
        season_style: Any = "auto",
        animations: Any = True,
        debug: bool = False,
        announce_warnings: bool = True,
    ) -> None:
        # The shared QML shell already owns the canonical animated BMO face.
        del face_provider
        self.locations = tuple(locations)
        self.index = min(
            max(0, int(default_index)),
            max(0, len(self.locations) - 1),
        )
        self.page_provider = page_provider
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.announcements_available = bool(announcements_available)
        self.season_style = str(season_style or "auto")
        self.animations = bool(animations)
        self.debug = bool(debug)
        self.announce_warnings = bool(announce_warnings)
        self.speaking_key: str | None = None
        self.subtitle = ""
        self._cache: dict[str, WeatherPageData] = {}
        self._errors: dict[str, str] = {}
        self._inflight: set[str] = set()
        self._tokens: dict[str, int] = {}
        self._loaded_at: dict[str, float] = {}
        self._hour_targets: dict[str, HourlyWeather] = {}
        self._announced_alerts: set[str] = set()
        super().__init__(host, on_close=on_close)
        self._timer = QTimer(host)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._load_current()

    @property
    def current_location(self) -> Any | None:
        if not self.locations:
            return None
        return self.locations[self.index]

    @property
    def current_data(self) -> WeatherPageData | None:
        location = self.current_location
        if location is None:
            return None
        return self._cache.get(str(location.id))

    def _base_payload(self) -> dict[str, object]:
        location = self.current_location
        location_id = str(location.id) if location is not None else ""
        if location is None:
            status = "empty"
            message = "Add a location to config/weather.json."
        elif location_id in self._errors and location_id not in self._cache:
            status = "error"
            message = self._errors[location_id]
        else:
            status = "loading"
            message = "BMO is checking the sky..."
        return {
            "status": status,
            "location": getattr(location, "name", "Weather"),
            "message": message,
            "page_index": self.index if self.locations else 0,
            "page_count": len(self.locations),
            "debug": self.debug,
            "animations": self.animations,
            "speech_available": self.announcements_available,
            "speaking_key": self.speaking_key,
        }

    def payload(self) -> dict[str, object]:
        data = self.current_data
        if data is None:
            return self._base_payload()
        local_now = self._local_now(data.snapshot)
        hours = select_upcoming_hours(data.snapshot, local_now)
        self._hour_targets = {
            f"hour:{index}": hour for index, hour in enumerate(hours)
        }
        return weather_view_state(
            data,
            local_now,
            season_style=self.season_style,
            animations=self.animations,
            debug=self.debug,
            speech_available=self.announcements_available,
            page_index=self.index,
            page_count=len(self.locations),
            subtitle=self.subtitle,
            speaking_key=self.speaking_key,
        )

    def _load_current(self, *, force: bool = False) -> None:
        location = self.current_location
        if location is None:
            self.refresh()
            return
        location_id = str(location.id)
        if location_id in self._cache and not force:
            self.refresh()
            return
        if location_id in self._inflight:
            return
        self._inflight.add(location_id)
        token = self._tokens.get(location_id, 0) + 1
        self._tokens[location_id] = token
        self._errors.pop(location_id, None)
        self.refresh()

        def worker() -> None:
            try:
                page = self.page_provider(location)
                if not isinstance(page, WeatherPageData):
                    raise TypeError("weather page provider returned invalid data")
            except Exception as exc:
                page = None
                error = self._safe_error(exc)
            else:
                error = ""
            if self.closed or self._tokens.get(location_id) != token:
                return
            self._inflight.discard(location_id)
            self._loaded_at[location_id] = time.monotonic()
            if page is not None:
                self._cache[location_id] = page
                self._errors.pop(location_id, None)
                if self.speaking_key is None:
                    self.subtitle = ""
            else:
                self._errors[location_id] = error
            self.refresh()
            if page is not None and self.current_location is location:
                self._announce_current_warning()

        threading.Thread(
            target=worker,
            name=f"qt-weather-{location_id}",
            daemon=True,
        ).start()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        print(
            f"[WEATHER] Menu page unavailable: {type(exc).__name__}",
            flush=True,
        )
        return "BMO could not reach the weather service. Swipe or tap to retry."

    def _local_now(self, snapshot: WeatherSnapshot) -> datetime:
        observed = parse_local_datetime(snapshot.observed_at)
        if observed is None:
            return datetime.now()
        location = self.current_location
        if location is None:
            return observed
        loaded_at = self._loaded_at.get(str(location.id))
        if loaded_at is None:
            return observed
        elapsed = max(0.0, time.monotonic() - loaded_at)
        return observed + timedelta(seconds=elapsed)

    def _tick(self) -> None:
        if self.closed:
            return
        location = self.current_location
        if location is not None:
            location_id = str(location.id)
            loaded_at = self._loaded_at.get(location_id)
            if (
                loaded_at is not None
                and time.monotonic() - loaded_at >= self.REFRESH_SECONDS
            ):
                self._load_current(force=True)
        # Time labels, day scenery, and moon state change without reopening.
        self.refresh()

    def _location_changed(self) -> None:
        self.cancel_announcements()
        self.speaking_key = None
        self.subtitle = ""
        self._hour_targets.clear()
        self.refresh()
        self._load_current()
        self._announce_current_warning()

    def _announce_current_warning(self) -> None:
        location = self.current_location
        data = self.current_data
        if (
            not self.announce_warnings
            or not self.announcements_available
            or location is None
            or data is None
            or not data.alerts
            or str(location.id) in self._announced_alerts
        ):
            return
        alert = data.alerts[0]
        if (
            "warning" not in alert.event.casefold()
            and alert.severity.casefold() not in {"extreme", "severe"}
        ):
            return
        self._announced_alerts.add(str(location.id))
        self._speak("alert")

    def _speak(self, key: str) -> None:
        data = self.current_data
        if data is None or not self.announcements_available:
            return
        snapshot = data.snapshot
        if key == "temperature":
            text = narrate_temperature(snapshot)
        elif key == "feels":
            text = narrate_feels_like(snapshot)
        elif key == "high_low":
            text = narrate_high_low(snapshot)
        elif key == "rain":
            text = narrate_rain(snapshot)
        elif key == "condition":
            text = narrate_condition(snapshot)
        elif key == "alert" and data.alerts:
            text = narrate_alert(data.alerts[0])
        elif key in self._hour_targets:
            text = narrate_hour(
                self._hour_targets[key],
                imperial=snapshot.imperial,
            )
        else:
            return
        self._announce_text(key, text)

    def _announce_text(self, key: str, text: str) -> None:
        self.speaking_key = key
        self.subtitle = text
        self.refresh()

        def completed() -> None:
            self._speech_completed(key)

        if not self.announce(text, completed):
            self.speaking_key = None
            self.refresh()

    @staticmethod
    def _debug_number(
        payload: dict[str, object],
        name: str,
        *,
        minimum: float = -200,
        maximum: float = 200,
    ) -> int | None:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            return None
        return round(number)

    def _speak_debug(self, value: str) -> None:
        if (
            not self.debug
            or not self.announcements_available
            or len(value) > 2048
        ):
            return
        try:
            payload = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        key = payload.get("key")
        condition = payload.get("condition")
        if (
            not isinstance(key, str)
            or not isinstance(condition, str)
            or condition not in _DEBUG_CONDITION_SPEECH
        ):
            return

        temperature = self._debug_number(payload, "temperature")
        feels = self._debug_number(payload, "feels")
        high = self._debug_number(payload, "high")
        low = self._debug_number(payload, "low")
        rain = self._debug_number(payload, "rain", minimum=0, maximum=100)
        if key == "condition":
            text = _DEBUG_CONDITION_SPEECH[condition]
        elif key == "temperature" and temperature is not None:
            text = f"Beep boop! This weather preview is {temperature} degrees."
        elif key == "feels" and feels is not None:
            text = f"In this preview, it feels like {feels} degrees outside."
        elif key == "high_low" and high is not None and low is not None:
            text = f"This preview has a high of {high} and a low of {low} degrees."
        elif key == "rain" and rain is not None:
            text = f"This preview's rain chance is {rain} percent."
        elif key == "alert" and condition == "severe":
            text = _DEBUG_CONDITION_SPEECH["severe"]
        elif key.startswith("hour:"):
            try:
                hour_index = int(key.partition(":")[2])
            except ValueError:
                return
            if hour_index not in range(4):
                return
            hour = payload.get("hour")
            if not isinstance(hour, dict):
                return
            hour_temperature = self._debug_number(hour, "temperature")
            if hour_temperature is None:
                return
            labels = ("12 P M", "2 P M", "4 P M", "8 P M")
            text = (
                f"At {labels[hour_index]}, this preview shows "
                f"{hour_temperature} degrees."
            )
        else:
            return
        self._announce_text(key, text)

    def _speech_completed(self, key: str) -> None:
        if self.closed or self.speaking_key != key:
            return
        self.speaking_key = None
        self.refresh()

    def handle_action(self, action: str, value: str) -> None:
        if action == "weather_next" and self.locations:
            self.index = (self.index + 1) % len(self.locations)
            self._location_changed()
            return
        if action == "weather_previous" and self.locations:
            self.index = (self.index - 1) % len(self.locations)
            self._location_changed()
            return
        if action in {"weather_refresh", "weather_retry"}:
            location = self.current_location
            if location is not None:
                self._errors.pop(str(location.id), None)
            self._load_current(force=True)
            return
        if action in {"weather_speak", "weather_announce"}:
            self._speak(value or "condition")
            return
        if action == "weather_debug_speak":
            self._speak_debug(value)
            return
        super().handle_action(action, value)

    def close(self) -> None:
        if self.closed:
            return
        self._tokens = {
            location_id: token + 1
            for location_id, token in self._tokens.items()
        }
        self._timer.stop()
        self._timer.deleteLater()
        self.cancel_announcements()
        super().close()


__all__ = ["QtWeatherView"]
