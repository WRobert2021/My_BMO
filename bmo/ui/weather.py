"""Weather-owned Chromium view, secure loopback bridge, and carousel lifecycle."""

from __future__ import annotations

import json
from io import BytesIO
import os
import queue
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol, TypeAlias
from urllib.parse import urlsplit

from PIL import Image

from bmo.features.weather_alerts import WeatherAlert
from bmo.features.weather_config import WeatherLocationConfig
from bmo.features.weather_narration import (
    WeatherCondition,
    condition_for_code,
    narrate_alert,
    narrate_condition,
    narrate_feels_like,
    narrate_high_low,
    narrate_hour,
    narrate_rain,
    narrate_temperature,
    season_for,
)
from bmo.ui.compact_face import (
    CompactFace,
    CompactFaceConfig,
    load_compact_face_config,
    normalize_face_image,
)
from bmo.weather import (
    WEATHER_DESCRIPTIONS,
    HourlyWeather,
    WeatherSnapshot,
    temperature_as_fahrenheit,
)


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480
WEB_ASSET = Path(__file__).with_name("weather_web") / "index.html"
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
_SAFE_ACTIONS = frozenset(
    {"close", "heartbeat", "navigate", "ready", "retry", "speak"}
)
_SPEECH_KEYS = frozenset(
    {"alert", "condition", "feels", "high_low", "rain", "temperature"}
)


class WeatherBrowserUnavailable(RuntimeError):
    """Raised when a supported Chromium executable cannot be started."""


def _parse_local_datetime(value: str | None) -> datetime | None:
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
        timestamp = _parse_local_datetime(hour.time)
        if timestamp is not None and timestamp < local_now:
            continue
        selected.append(hour)
        if len(selected) >= limit:
            break
    return tuple(selected)


def day_period_for(snapshot: WeatherSnapshot, local_now: datetime) -> str:
    """Classify local time into the five scenery periods used by the screen."""
    sunrise = _parse_local_datetime(snapshot.sunrise)
    sunset = _parse_local_datetime(snapshot.sunset)
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


WeatherPageProvider: TypeAlias = Callable[[WeatherLocationConfig], WeatherPageData]
FaceProvider: TypeAlias = Callable[[], Image.Image | None]
AnnouncementCompletion: TypeAlias = Callable[[], None]
Announcer: TypeAlias = Callable[[str, AnnouncementCompletion | None], bool]


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
        WEATHER_DESCRIPTIONS.get(data.snapshot.weather_code, "Mixed weather").title(),
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
        visual in {
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
        return "BMO safety alert. Go with a grown-up and follow official instructions now."
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
        "fog": "The clouds came down to visit. Stay where a grown-up can see you!",
        "drizzle": "A light raincoat could be a cozy sidekick.",
        "rain": "Puddle-jumping weather! Bring your raincoat and boots.",
        "heavy-rain": "Big rain is falling. Raincoat and boots time!",
        "freezing-rain": "Icy rain can make slippery spots. Stay close to a grown-up!",
        "sleet": "Icy drops can make slippery spots. Stay close to a grown-up!",
        "snow": "Bundle up! Coat, hat, gloves, and warm boots.",
        "heavy-snow": "Lots of snow is dancing down. Bundle up and stay with a grown-up!",
        "storm": "Thunder nearby. Let's stay safely inside with a grown-up!",
        "hail": "Hail is falling. Please stay safely inside!",
        "wind": "Hold onto your hat and check with a grown-up before going outside!",
        "hot": "Super-hot alert! Water, shade, sunscreen, and plenty of breaks.",
        "cold": "Brrr! Coat, hat, gloves, and a grown-up are good adventure buddies.",
        "mixed": "The sky has a little bit of everything today!",
    }
    return flavors.get(visual, "Let's look at today's sky!")


def _hour_icon(hour: HourlyWeather) -> str:
    condition = condition_for_code(hour.weather_code)
    if condition is WeatherCondition.CLEAR:
        return "sun" if hour.is_day is not False else "moon"
    if condition in {WeatherCondition.MOSTLY_CLEAR, WeatherCondition.PARTLY_CLOUDY}:
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


def weather_web_state(
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
    """Serialize immutable weather data into the local page's narrow contract."""
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


class _WeatherHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class WeatherWebBridge:
    """Serve one static page and a tokenized JSON bridge on loopback only."""

    MAX_ACTION_BYTES = 4096

    def __init__(
        self,
        actions: queue.Queue[dict[str, Any]],
        *,
        asset_path: Path = WEB_ASSET,
        compact_face_config: CompactFaceConfig | None = None,
    ) -> None:
        self.actions = actions
        self.token = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(24)
        self.asset_path = asset_path
        self.compact_face_config = compact_face_config or load_compact_face_config()
        self.compact_face_payload = {
            "layout": self.compact_face_config.web_layout(),
            "frame_url": "face/current",
        }
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {"status": "loading", "debug": False}
        self._face_lock = threading.Lock()
        self._face_content: bytes | None = None
        self._closed = False
        self._started = False
        self._server = _WeatherHTTPServer(("127.0.0.1", 0), self._handler())
        port = int(self._server.server_address[1])
        self.origin = f"http://127.0.0.1:{port}"
        self.url = f"{self.origin}/{self.token}/"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="weather-web-bridge",
            daemon=True,
        )

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
                path = urlsplit(self.path).path
                if path == f"/{bridge.token}/":
                    try:
                        content = bridge.asset_path.read_text(encoding="utf-8")
                    except OSError:
                        self._send_json(
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                            {"error": "weather display asset unavailable"},
                        )
                        return
                    content = content.replace(
                        "<script>",
                        f'<script nonce="{bridge.nonce}">',
                    )
                    content = content.replace(
                        "__COMPACT_FACE_JSON__",
                        json.dumps(bridge.compact_face_payload, separators=(",", ":")),
                    )
                    self._send(
                        HTTPStatus.OK,
                        content.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )
                    return
                if path == f"/{bridge.token}/face/current":
                    face_content = bridge.face_content()
                    if face_content is None:
                        self._send_json(
                            HTTPStatus.NOT_FOUND,
                            {"error": "face unavailable"},
                        )
                        return
                    self._send(
                        HTTPStatus.OK,
                        face_content,
                        "image/png",
                    )
                    return
                if path == f"/{bridge.token}/state":
                    with bridge._state_lock:
                        state = dict(bridge._state)
                    self._send_json(HTTPStatus.OK, state)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                if urlsplit(self.path).path != f"/{bridge.token}/action":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                if self.headers.get("Origin") != bridge.origin:
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": "bad origin"})
                    return
                if self.headers.get_content_type() != "application/json":
                    self._send_json(
                        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                        {"error": "JSON required"},
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if not 0 < length <= bridge.MAX_ACTION_BYTES:
                    self._send_json(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {"error": "invalid action size"},
                    )
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    action = bridge._validated_action(payload)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid action"},
                    )
                    return
                bridge.actions.put(action)
                self._send_json(HTTPStatus.ACCEPTED, {"ok": True})

            def _send_json(
                self,
                status: HTTPStatus,
                payload: Mapping[str, Any],
            ) -> None:
                self._send(
                    status,
                    json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    "application/json; charset=utf-8",
                )

            def _send(
                self,
                status: HTTPStatus,
                body: bytes,
                content_type: str,
                *,
                cache_control: str = "no-store",
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache_control)
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    f"script-src 'nonce-{bridge.nonce}'; "
                    "style-src 'unsafe-inline'; img-src 'self' data:; "
                    "connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'",
                )
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        return Handler

    def set_face(self, face: object | None) -> None:
        """Publish the host-selected frame as one normalized browser raster."""
        content: bytes | None = None
        if isinstance(face, Image.Image):
            try:
                output = BytesIO()
                normalize_face_image(face, self.compact_face_config).save(
                    output,
                    format="PNG",
                )
                content = output.getvalue()
            except (OSError, ValueError):
                content = None
        with self._face_lock:
            self._face_content = content

    def face_content(self) -> bytes | None:
        """Return the latest immutable frame snapshot for an HTTP response."""
        with self._face_lock:
            return self._face_content

    @staticmethod
    def _validated_action(payload: object) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("action must be an object")
        name = payload.get("name")
        if not isinstance(name, str) or name not in _SAFE_ACTIONS:
            raise ValueError("unknown action")
        action: dict[str, Any] = {"name": name}
        if name == "navigate":
            direction = payload.get("direction")
            if type(direction) is not int or direction not in {-1, 1}:
                raise ValueError("bad navigation direction")
            action["direction"] = direction
        elif name == "speak":
            key = payload.get("key")
            if not isinstance(key, str) or not (
                key in _SPEECH_KEYS
                or (
                    key.startswith("hour:")
                    and key.removeprefix("hour:").isdigit()
                )
            ):
                raise ValueError("bad speech key")
            action["key"] = key
        return action

    def set_state(self, state: Mapping[str, Any]) -> None:
        with self._state_lock:
            self._state = dict(state)

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)


class BrowserSession(Protocol):
    def poll(self) -> int | None: ...

    def close(self) -> None: ...


def find_chromium() -> Path:
    """Find the platform browser without touching a user's normal profile."""
    for command in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved)
    for candidate in (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise WeatherBrowserUnavailable(
        "Chromium is required for the weather display."
    )


class ChromiumSession:
    """Own one kiosk browser process group and its isolated temporary profile."""

    def __init__(
        self,
        url: str,
        *,
        executable: Path | None = None,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        browser = executable or find_chromium()
        self._profile = tempfile.TemporaryDirectory(prefix="bmo-weather-")
        command = [
            str(browser),
            f"--app={url}",
            "--kiosk",
            f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
            "--window-position=0,0",
            f"--user-data-dir={self._profile.name}",
            "--no-first-run",
            "--no-default-browser-check",
            # The weather profile is temporary and never handles credentials.
            # Avoid desktop keyring prompts that would cover the kiosk UI.
            "--password-store=basic",
            "--use-mock-keychain",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-extensions",
            "--disable-features=MediaRouter,Translate",
            "--disable-sync",
            "--metrics-recording-only",
        ]
        try:
            self._process = popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._profile.cleanup()
            raise WeatherBrowserUnavailable(
                "Chromium could not start the weather display."
            ) from exc
        self._closed = False

    def poll(self) -> int | None:
        return self._process.poll()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        running = self._process.poll() is None
        try:
            os.killpg(self._process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if running:
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self._process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        self._profile.cleanup()


BrowserLauncher: TypeAlias = Callable[[str], BrowserSession]
BridgeFactory: TypeAlias = Callable[
    [queue.Queue[dict[str, Any]]], WeatherWebBridge
]


class WeatherApp:
    """Own the asynchronous forecast carousel and its local web presentation."""

    POLL_MS = 150
    REFRESH_SECONDS = 15 * 60
    RENDERER_STARTUP_TIMEOUT_SECONDS = 10.0
    RENDERER_HEARTBEAT_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        root: tk.Misc,
        *,
        locations: Sequence[WeatherLocationConfig],
        default_index: int,
        page_provider: WeatherPageProvider,
        face_provider: FaceProvider,
        announce: Announcer,
        cancel_announcements: Callable[[], None],
        announcements_available: bool,
        season_style: str = "auto",
        animations: bool = True,
        debug: bool = False,
        announce_warnings: bool = False,
        on_close: Callable[[], None],
        browser_launcher: BrowserLauncher = ChromiumSession,
        bridge_factory: BridgeFactory = WeatherWebBridge,
    ) -> None:
        self.root = root
        self.face_provider = face_provider
        self.locations = tuple(locations)
        self.page_provider = page_provider
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.announcements_available = bool(announcements_available)
        self.season_style = season_style
        self.animations = bool(animations)
        self.debug = bool(debug)
        self.announce_warnings = bool(announce_warnings)
        self.on_close = on_close
        self.closed = False
        self.speaking_key: str | None = None
        self.subtitle = ""
        self.carousel = (
            WeatherCarousel(len(self.locations), default_index)
            if self.locations
            else None
        )
        self._cache: dict[str, WeatherPageData] = {}
        self._errors: dict[str, str] = {}
        self._inflight: set[str] = set()
        self._tokens: dict[str, int] = {}
        self._loaded_at: dict[str, float] = {}
        self._results: queue.Queue[
            tuple[str, int, WeatherPageData | None, str | None]
        ] = queue.Queue()
        self._actions: queue.Queue[dict[str, Any]] = queue.Queue()
        self._hour_targets: dict[str, HourlyWeather] = {}
        self._announced_alerts: set[str] = set()
        self._after_ids: set[str] = set()
        self._renderer_started_at = time.monotonic()
        self._renderer_last_seen: float | None = None
        self._compact_face_suspended = False
        self._bridge = bridge_factory(self._actions)
        self._sync_face()
        self._bridge.set_state(self._loading_state())
        try:
            self._bridge.start()
            self._browser = browser_launcher(self._bridge.url)
            CompactFace.suspend_for_external_surface(root)
            self._compact_face_suspended = True
        except Exception:
            self._bridge.close()
            raise
        self._schedule(self.POLL_MS, self._poll)
        self._load_current()

    @property
    def current_location(self) -> WeatherLocationConfig | None:
        if self.carousel is None:
            return None
        return self.locations[self.carousel.selected_index]

    @property
    def current_data(self) -> WeatherPageData | None:
        location = self.current_location
        return self._cache.get(location.id) if location is not None else None

    def _schedule(self, delay: int, callback: Callable[[], None]) -> None:
        if self.closed:
            return
        after_id = ""

        def run() -> None:
            self._after_ids.discard(after_id)
            callback()

        after_id = self.root.after(delay, run)
        self._after_ids.add(after_id)

    def _load_current(self, *, force: bool = False) -> None:
        location = self.current_location
        if location is None:
            self._publish_state()
            return
        if location.id in self._cache and not force:
            self._publish_state()
            return
        if location.id in self._inflight:
            return
        self._inflight.add(location.id)
        token = self._tokens.get(location.id, 0) + 1
        self._tokens[location.id] = token
        self._publish_state()

        def worker() -> None:
            try:
                data = self.page_provider(location)
                if not isinstance(data, WeatherPageData):
                    raise TypeError("weather page provider returned invalid data")
            except Exception as exc:
                self._results.put(
                    (location.id, token, None, self._safe_error(exc))
                )
            else:
                self._results.put((location.id, token, data, None))

        threading.Thread(
            target=worker,
            name=f"weather-page-{location.id}",
            daemon=True,
        ).start()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        print(
            f"[WEATHER] Menu page unavailable: {type(exc).__name__}",
            flush=True,
        )
        return "BMO could not reach the weather service. Swipe or try again later."

    def _poll(self) -> None:
        if self.closed:
            return
        self._sync_face()
        if self._browser.poll() is not None:
            self.close()
            return
        if not self._handle_actions():
            return
        if not self._renderer_is_healthy():
            self.close()
            return
        changed = False
        while True:
            try:
                location_id, token, data, error = self._results.get_nowait()
            except queue.Empty:
                break
            if self._tokens.get(location_id) != token:
                continue
            self._inflight.discard(location_id)
            self._loaded_at[location_id] = time.monotonic()
            if data is not None:
                self._cache[location_id] = data
                self._errors.pop(location_id, None)
            elif error is not None:
                self._errors[location_id] = error
            if self.current_location and self.current_location.id == location_id:
                if data is not None and self.speaking_key is None:
                    self.subtitle = ""
                changed = True
        if changed:
            self._announce_current_warning()
        self._refresh_if_stale()
        self._publish_state()
        self._schedule(self.POLL_MS, self._poll)

    def _sync_face(self) -> None:
        """Forward the host runtime's current frame without owning animation state."""
        try:
            face = self.face_provider()
            self._bridge.set_face(face)
        except Exception:
            try:
                self._bridge.set_face(None)
            except Exception:
                pass

    def _handle_actions(self) -> bool:
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                return True
            name = action["name"]
            if name in {"ready", "heartbeat"}:
                self._renderer_last_seen = time.monotonic()
                continue
            if name == "close":
                self.close()
                return False
            if name == "navigate" and self.carousel is not None:
                if action["direction"] == 1:
                    self.carousel.swipe_left()
                else:
                    self.carousel.swipe_right()
                self._location_changed()
            elif name == "retry":
                location = self.current_location
                if location is not None:
                    self._errors.pop(location.id, None)
                    self._load_current(force=True)
            elif name == "speak":
                self._speak(str(action["key"]))

    def _renderer_is_healthy(self) -> bool:
        """Fail closed when a kiosk page never starts or stops responding."""
        now = time.monotonic()
        if self._renderer_last_seen is None:
            healthy = (
                now - self._renderer_started_at
                < self.RENDERER_STARTUP_TIMEOUT_SECONDS
            )
        else:
            healthy = (
                now - self._renderer_last_seen
                < self.RENDERER_HEARTBEAT_TIMEOUT_SECONDS
            )
        if not healthy:
            print(
                "[WEATHER] Browser renderer stopped responding; closing display.",
                flush=True,
            )
        return healthy

    def _refresh_if_stale(self) -> None:
        location = self.current_location
        if location is None or location.id not in self._cache:
            return
        loaded_at = self._loaded_at.get(location.id)
        if loaded_at is None:
            return
        if time.monotonic() - loaded_at >= self.REFRESH_SECONDS:
            self._load_current(force=True)

    def _local_now(self, snapshot: WeatherSnapshot) -> datetime:
        observed = _parse_local_datetime(snapshot.observed_at)
        if observed is None:
            return datetime.now()
        location = self.current_location
        if location is None:
            return observed
        loaded_at = self._loaded_at.get(location.id)
        if loaded_at is None:
            return observed
        elapsed = max(0.0, time.monotonic() - loaded_at)
        return observed + timedelta(seconds=elapsed)

    def _loading_state(self) -> dict[str, Any]:
        location = self.current_location
        return {
            "status": "loading" if location is not None else "empty",
            "location": location.name if location is not None else "Weather",
            "message": (
                "BMO is checking the sky..."
                if location is not None
                else "Add a location to config/weather.json."
            ),
            "page_index": self.carousel.selected_index if self.carousel else 0,
            "page_count": self.carousel.count if self.carousel else 0,
            "debug": self.debug,
            "animations": self.animations,
        }

    def _publish_state(self) -> None:
        if self.closed:
            return
        location = self.current_location
        data = self.current_data
        if location is None:
            self._bridge.set_state(self._loading_state())
            return
        if data is None:
            state = self._loading_state()
            error = self._errors.get(location.id)
            if error:
                state.update(status="error", message=error)
            self._bridge.set_state(state)
            return
        local_now = self._local_now(data.snapshot)
        hours = select_upcoming_hours(data.snapshot, local_now)
        self._hour_targets = {
            f"hour:{index}": hour for index, hour in enumerate(hours)
        }
        self._bridge.set_state(
            weather_web_state(
                data,
                local_now,
                season_style=self.season_style,
                animations=self.animations,
                debug=self.debug,
                speech_available=self.announcements_available,
                page_index=self.carousel.selected_index,
                page_count=self.carousel.count,
                subtitle=self.subtitle,
                speaking_key=self.speaking_key,
            )
        )

    def _location_changed(self) -> None:
        self.cancel_announcements()
        self.speaking_key = None
        self.subtitle = ""
        self._publish_state()
        self._announce_current_warning()
        self._load_current()

    def _announce_current_warning(self) -> None:
        location = self.current_location
        data = self.current_data
        if (
            not self.announce_warnings
            or not self.announcements_available
            or location is None
            or data is None
            or not data.alerts
            or location.id in self._announced_alerts
        ):
            return
        alert = data.alerts[0]
        if (
            "warning" not in alert.event.casefold()
            and alert.severity.casefold() not in {"extreme", "severe"}
        ):
            return
        self._announced_alerts.add(location.id)
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
        self.speaking_key = key
        self.subtitle = text
        self._publish_state()

        def completed() -> None:
            try:
                self.root.after(0, lambda: self._speech_completed(key))
            except tk.TclError:
                pass

        if not self.announce(text, completed):
            self.speaking_key = None
            self._publish_state()

    def _speech_completed(self, key: str) -> None:
        if self.closed or self.speaking_key != key:
            return
        self.speaking_key = None
        self._publish_state()

    def close(self) -> None:
        """Release browser, loopback server, callbacks, and scoped speech."""
        if self.closed:
            return
        self.closed = True
        self.cancel_announcements()
        for after_id in tuple(self._after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self._after_ids.clear()
        try:
            self._browser.close()
        except Exception as exc:
            print(
                f"[WEATHER] Browser cleanup failed: {type(exc).__name__}",
                flush=True,
            )
        try:
            self._bridge.close()
        except Exception as exc:
            print(
                f"[WEATHER] Local bridge cleanup failed: {type(exc).__name__}",
                flush=True,
            )
        if getattr(self, "_compact_face_suspended", False):
            CompactFace.resume_after_external_surface(self.root)
            self._compact_face_suspended = False
        self.on_close()
