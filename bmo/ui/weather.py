"""Child-friendly animated weather carousel for BMO's touch display."""

from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from PIL import Image, ImageTk

from bmo.features.weather_alerts import WeatherAlert
from bmo.features.weather_config import WeatherLocationConfig
from bmo.features.weather_narration import (
    WeatherCondition,
    WeatherSeason,
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
from bmo.ui.gestures import GestureKind, HorizontalSwipeRecognizer
from bmo.weather import WEATHER_DESCRIPTIONS, WeatherSnapshot


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480


@dataclass(frozen=True)
class WeatherPageData:
    """One successfully loaded location page."""

    snapshot: WeatherSnapshot
    alerts: tuple[WeatherAlert, ...] = ()


class WeatherCarousel:
    """Wrap ordered weather locations independently from Tk rendering."""

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


class WeatherApp:
    """Show animated conditions and tappable BMO weather explanations."""

    NAVY = "#102a5e"
    WHITE = "#ffffff"
    BLUE = "#1578d3"
    PALE_BLUE = "#dff5ff"
    MUTED = "#58708c"
    CARD = "#ffffff"
    ALERT = "#b32834"
    FACE_BOUNDS = (704, 6, 790, 53)
    CONDITION_BOUNDS = (16, 66, 348, 258)
    TEMPERATURE_BOUNDS = (360, 66, 688, 166)
    FEELS_BOUNDS = (18, 278, 252, 365)
    HIGH_LOW_BOUNDS = (282, 278, 516, 365)
    RAIN_BOUNDS = (546, 278, 780, 365)
    ALERT_BOUNDS = (16, 239, 784, 272)
    POLL_MS = 80
    ANIMATION_MS = 220

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
        announce_warnings: bool = False,
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.locations = tuple(locations)
        self.page_provider = page_provider
        self.face_provider = face_provider
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.announcements_available = bool(announcements_available)
        self.season_style = season_style
        self.animations = bool(animations)
        self.announce_warnings = bool(announce_warnings)
        self.on_close = on_close
        self.closed = False
        self.phase = 0
        self.speaking_key: str | None = None
        self.subtitle = "Tap a weather card and BMO will tell you more!"
        self.gesture = HorizontalSwipeRecognizer()
        self.carousel = (
            WeatherCarousel(len(self.locations), default_index)
            if self.locations
            else None
        )
        self._cache: dict[str, WeatherPageData] = {}
        self._errors: dict[str, str] = {}
        self._inflight: set[str] = set()
        self._tokens: dict[str, int] = {}
        self._results: queue.Queue[
            tuple[str, int, WeatherPageData | None, str | None]
        ] = queue.Queue()
        self._hit_targets: list[tuple[tuple[int, int, int, int], str]] = []
        self._hour_targets: dict[str, int] = {}
        self._announced_alerts: set[str] = set()
        self._after_ids: set[str] = set()
        self._face_image: ImageTk.PhotoImage | None = None

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=self.PALE_BLUE,
            highlightthickness=0,
        )
        self.canvas.place(x=0, y=0, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        self.canvas.bind("<ButtonPress-1>", self._handle_press)
        self.canvas.bind("<ButtonRelease-1>", self._handle_release)
        self._draw()
        self._schedule(self.POLL_MS, self._poll_results)
        if self.animations:
            self._schedule(self.ANIMATION_MS, self._animate)
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

    def _load_current(self) -> None:
        location = self.current_location
        if location is None or location.id in self._cache:
            return
        if location.id in self._inflight:
            return
        self._inflight.add(location.id)
        token = self._tokens.get(location.id, 0) + 1
        self._tokens[location.id] = token

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

    def _poll_results(self) -> None:
        if self.closed:
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
            if data is not None:
                self._cache[location_id] = data
                self._errors.pop(location_id, None)
            elif error is not None:
                self._errors[location_id] = error
            if self.current_location and self.current_location.id == location_id:
                changed = True
        if changed:
            self._draw()
            self._announce_current_warning()
        self._schedule(self.POLL_MS, self._poll_results)

    def _announce_current_warning(self) -> None:
        """Optionally announce each newly shown official warning once."""
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
        if "warning" not in alert.event.casefold() and alert.severity.casefold() not in {
            "extreme",
            "severe",
        }:
            return
        self._announced_alerts.add(location.id)
        self._speak("alert")

    def _animate(self) -> None:
        if self.closed:
            return
        self.phase = (self.phase + 1) % 24
        self._draw()
        self._schedule(self.ANIMATION_MS, self._animate)

    def _draw(self) -> None:
        if self.closed:
            return
        self.canvas.delete("all")
        self._hit_targets.clear()
        self._hour_targets.clear()
        data = self.current_data
        snapshot = data.snapshot if data is not None else None
        background = self._background(snapshot)
        self.canvas.configure(bg=background)
        self.canvas.create_rectangle(0, 0, 800, 58, fill=self.NAVY, outline="")
        self._draw_header()
        if self.current_location is None:
            self._draw_empty()
            return
        if data is None:
            self._draw_loading(self._errors.get(self.current_location.id))
            return
        self._draw_season(snapshot)
        self._draw_condition_scene(snapshot)
        self._draw_current(snapshot)
        if data.alerts:
            self._draw_alert(data.alerts[0])
        self._draw_cards(snapshot)
        self._draw_hourly(snapshot)
        self._draw_subtitle()

    def _background(self, snapshot: WeatherSnapshot | None) -> str:
        if snapshot is None:
            return self.PALE_BLUE
        if snapshot.is_day is False:
            return "#263a70"
        season = self._season(snapshot)
        return {
            WeatherSeason.SPRING: "#e9f9e1",
            WeatherSeason.SUMMER: "#fff4bd",
            WeatherSeason.FALL: "#ffe0b5",
            WeatherSeason.WINTER: "#e6f2f7",
        }.get(season, self.PALE_BLUE)

    def _draw_header(self) -> None:
        location = self.current_location
        label = location.label.upper() if location is not None else "WEATHER"
        self.canvas.create_text(
            24, 28, anchor="w", text="WEATHER", fill=self.WHITE,
            font=("Arial Rounded MT Bold", 22, "bold"),
        )
        self.canvas.create_text(
            181, 28, anchor="w", text=label, fill="#bde7ff",
            font=("Arial Rounded MT Bold", 14, "bold"),
        )
        if self.carousel is not None and self.carousel.count > 1:
            self.canvas.create_text(
                390, 28, text="‹  SWIPE LOCATIONS  ›", fill="#bde7ff",
                font=("Arial", 10, "bold"),
            )
            if self.carousel.count <= 8:
                for index in range(self.carousel.count):
                    x = 560 + index * 14
                    fill = (
                        self.WHITE
                        if index == self.carousel.selected_index
                        else "#587daa"
                    )
                    self.canvas.create_oval(
                        x, 25, x + 7, 32, fill=fill, outline=""
                    )
            else:
                self.canvas.create_text(
                    610,
                    28,
                    text=(
                        f"{self.carousel.selected_index + 1} / "
                        f"{self.carousel.count}"
                    ),
                    fill=self.WHITE,
                    font=("Arial", 10, "bold"),
                )
        self._draw_face()

    def _draw_face(self) -> None:
        left, top, right, bottom = self.FACE_BOUNDS
        glow = "#ffe36e" if self.speaking_key else self.WHITE
        self.canvas.create_rectangle(
            left, top, right, bottom, fill="#65c6a6", outline=glow, width=3,
        )
        try:
            face = self.face_provider()
            if face is not None:
                resized = face.convert("RGB").resize((78, 39), Image.Resampling.LANCZOS)
                self._face_image = ImageTk.PhotoImage(resized)
                self.canvas.create_image(747, 29, image=self._face_image)
                return
        except (tk.TclError, ValueError, AttributeError):
            pass
        self.canvas.create_oval(722, 17, 731, 26, fill=self.NAVY, outline="")
        self.canvas.create_oval(763, 17, 772, 26, fill=self.NAVY, outline="")
        mouth_y = 38 + (self.phase % 2 if self.speaking_key else 0)
        self.canvas.create_arc(
            738, mouth_y - 8, 757, mouth_y + 4,
            start=190, extent=160, style=tk.ARC, outline=self.NAVY, width=2,
        )

    def _draw_empty(self) -> None:
        self.canvas.create_text(
            400, 205, text="WHERE SHOULD BMO CHECK?", fill=self.NAVY,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.canvas.create_text(
            400, 255,
            text="Add a location to config/weather.json.", fill=self.MUTED,
            font=("Arial", 14, "bold"),
        )

    def _draw_loading(self, error: str | None) -> None:
        if error:
            self.canvas.create_text(
                400, 220, width=650, text=error, fill=self.NAVY,
                font=("Arial Rounded MT Bold", 18, "bold"),
            )
            self.canvas.create_text(
                400, 275, text="Tap here to try again", fill=self.BLUE,
                font=("Arial", 13, "bold"),
            )
            self._hit_targets.append(((120, 160, 680, 315), "retry"))
            return
        bounce = int(8 * math.sin(self.phase / 3)) if self.animations else 0
        self.canvas.create_text(
            400, 210 + bounce, text="☁", fill=self.WHITE,
            font=("Arial", 70, "bold"),
        )
        self.canvas.create_text(
            400, 300, text="BMO IS CHECKING THE SKY...", fill=self.NAVY,
            font=("Arial Rounded MT Bold", 18, "bold"),
        )

    def _season(self, snapshot: WeatherSnapshot) -> WeatherSeason:
        month = datetime.now().month
        if len(snapshot.observed_at) >= 7:
            try:
                month = int(snapshot.observed_at[5:7])
            except ValueError:
                pass
        return season_for(
            snapshot.location.latitude,
            month,
            self.season_style,
        )

    def _draw_season(self, snapshot: WeatherSnapshot) -> None:
        season = self._season(snapshot)
        if snapshot.is_day is False:
            for x, y in ((48, 84), (142, 105), (245, 78), (327, 111)):
                self.canvas.create_text(x, y, text="✦", fill="#fff6a8", font=("Arial", 13))
            self.canvas.create_oval(275, 81, 321, 127, fill="#fff4ad", outline="")
            self.canvas.create_oval(291, 72, 330, 113, fill=self._background(snapshot), outline="")
        if season is WeatherSeason.SPRING:
            for x, color in ((38, "#ff82a9"), (110, "#a473db"), (300, "#ffb43b")):
                self.canvas.create_text(x, 249, text="✿", fill=color, font=("Arial", 19, "bold"))
        elif season is WeatherSeason.SUMMER:
            self.canvas.create_line(20, 254, 344, 254, fill="#58a940", width=7)
        elif season is WeatherSeason.FALL:
            drift = self.phase * 3 % 50 if self.animations else 0
            for x, y, color in ((35, 90, "#e5682e"), (105, 235, "#d99924"), (270, 210, "#b94b2c")):
                self.canvas.create_oval(x + drift, y, x + 13 + drift, y + 8, fill=color, outline="")
        elif season is WeatherSeason.WINTER:
            self.canvas.create_line(22, 257, 45, 205, 64, 257, fill="#725c57", width=4, smooth=True)

    def _draw_condition_scene(self, snapshot: WeatherSnapshot) -> None:
        self._hit_targets.append((self.CONDITION_BOUNDS, "condition"))
        condition = condition_for_code(snapshot.weather_code)
        is_day = snapshot.is_day is not False
        bob = int(5 * math.sin(self.phase / 3)) if self.animations else 0
        if is_day and condition in {
            WeatherCondition.CLEAR,
            WeatherCondition.MOSTLY_CLEAR,
            WeatherCondition.PARTLY_CLOUDY,
        }:
            self._draw_sun(102, 144 + bob)
        if condition in {
            WeatherCondition.MOSTLY_CLEAR, WeatherCondition.PARTLY_CLOUDY,
            WeatherCondition.CLOUDY,
            WeatherCondition.OVERCAST, WeatherCondition.FOG,
            WeatherCondition.DRIZZLE, WeatherCondition.RAIN,
            WeatherCondition.HEAVY_RAIN, WeatherCondition.FREEZING_RAIN,
            WeatherCondition.SLEET,
            WeatherCondition.SNOW, WeatherCondition.HEAVY_SNOW,
            WeatherCondition.THUNDERSTORM, WeatherCondition.HAIL,
            WeatherCondition.MIXED,
        }:
            count = 2 if condition is WeatherCondition.OVERCAST else 1
            for cloud_index in range(count):
                self._draw_cloud(158 + cloud_index * 65, 140 + bob + cloud_index * 18)
        if condition is WeatherCondition.FOG:
            for y in (178, 198, 218):
                self.canvas.create_line(74, y, 292, y, fill="#91a7b6", width=6)
        elif condition in {WeatherCondition.DRIZZLE, WeatherCondition.RAIN, WeatherCondition.HEAVY_RAIN, WeatherCondition.FREEZING_RAIN, WeatherCondition.SLEET}:
            amount = 4 if condition is WeatherCondition.DRIZZLE else 8
            color = "#66bfff" if condition is not WeatherCondition.FREEZING_RAIN else "#8a9fff"
            for index in range(amount):
                x = 105 + index * 27 + (self.phase * 4 % 18 if self.animations else 0)
                self.canvas.create_line(x, 178, x - 5, 202, fill=color, width=3)
                if condition is WeatherCondition.SLEET and index % 2 == 0:
                    self.canvas.create_oval(x - 8, 205, x + 1, 214, fill=self.WHITE, outline="#9fb9ca")
        elif condition in {WeatherCondition.SNOW, WeatherCondition.HEAVY_SNOW}:
            amount = 10 if condition is WeatherCondition.HEAVY_SNOW else 6
            for index in range(amount):
                x = 92 + index * 34
                y = 180 + ((index * 17 + self.phase * 5) % 62 if self.animations else index % 3 * 20)
                self.canvas.create_text(x, y, text="✻", fill=self.WHITE, font=("Arial", 16, "bold"))
        elif condition in {WeatherCondition.THUNDERSTORM, WeatherCondition.HAIL}:
            self.canvas.create_polygon(190, 172, 169, 210, 190, 205, 172, 239, 222, 190, 198, 194, fill="#ffd93d", outline="")
            if condition is WeatherCondition.HAIL:
                for x in (112, 148, 244, 278):
                    self.canvas.create_oval(x, 196, x + 12, 208, fill=self.WHITE, outline="#9fb9ca")
        if snapshot.wind_gusts is not None and self._wind_is_high(snapshot):
            for y in (93, 116, 232):
                self.canvas.create_arc(40, y, 118, y + 25, start=200, extent=230, style=tk.ARC, outline="#5794bc", width=3)

    def _wind_is_high(self, snapshot: WeatherSnapshot) -> bool:
        if snapshot.wind_gusts is None:
            return False
        return snapshot.wind_gusts >= (30 if snapshot.imperial else 48)

    def _draw_sun(self, x: int, y: int) -> None:
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            self.canvas.create_line(
                x + math.cos(radians) * 43, y + math.sin(radians) * 43,
                x + math.cos(radians) * 60, y + math.sin(radians) * 60,
                fill="#ffbd2f", width=5,
            )
        self.canvas.create_oval(x - 38, y - 38, x + 38, y + 38, fill="#ffd84c", outline="#f0a926", width=3)
        self.canvas.create_oval(x - 15, y - 8, x - 8, y - 1, fill=self.NAVY, outline="")
        self.canvas.create_oval(x + 8, y - 8, x + 15, y - 1, fill=self.NAVY, outline="")
        self.canvas.create_arc(x - 14, y - 1, x + 14, y + 20, start=190, extent=160, style=tk.ARC, outline=self.NAVY, width=2)

    def _draw_cloud(self, x: int, y: int) -> None:
        fill = "#d0d9e4"
        self.canvas.create_oval(x - 80, y - 12, x + 70, y + 45, fill=fill, outline="")
        self.canvas.create_oval(x - 52, y - 48, x + 17, y + 35, fill=fill, outline="")
        self.canvas.create_oval(x - 4, y - 34, x + 59, y + 38, fill=fill, outline="")

    def _draw_current(self, snapshot: WeatherSnapshot) -> None:
        self._hit_targets.append((self.TEMPERATURE_BOUNDS, "temperature"))
        color = self.WHITE if snapshot.is_day is False else self.NAVY
        self.canvas.create_text(
            524, 112, text=f"{round(snapshot.temperature)}°",
            fill=color, font=("Arial Rounded MT Bold", 63, "bold"),
        )
        description = WEATHER_DESCRIPTIONS.get(snapshot.weather_code, "mixed weather")
        self.canvas.create_text(
            524, 160, text=description.upper(), fill=color,
            font=("Arial Rounded MT Bold", 17, "bold"),
        )
        badges = []
        temperature_f = snapshot.temperature if snapshot.imperial else snapshot.temperature * 9 / 5 + 32
        if temperature_f >= 100:
            badges.append("VERY HOT")
        elif temperature_f >= 90:
            badges.append("HOT")
        elif temperature_f <= 32:
            badges.append("FREEZING")
        elif temperature_f < 50:
            badges.append("COLD")
        if self._wind_is_high(snapshot):
            badges.append("HIGH WIND")
        if snapshot.humidity is not None and snapshot.humidity >= 80:
            badges.append("HUMID")
        if badges:
            self.canvas.create_text(
                524, 196, text="  •  ".join(badges), fill="#b32834",
                font=("Arial", 11, "bold"),
            )

    def _draw_alert(self, alert: WeatherAlert) -> None:
        self.canvas.create_rectangle(*self.ALERT_BOUNDS, fill=self.ALERT, outline="")
        self.canvas.create_text(
            400, 255, width=730, text=f"⚠  {alert.event.upper()} — TAP FOR SAFETY INFO",
            fill=self.WHITE, font=("Arial Rounded MT Bold", 12, "bold"),
        )
        self._hit_targets.append((self.ALERT_BOUNDS, "alert"))

    def _draw_cards(self, snapshot: WeatherSnapshot) -> None:
        cards = (
            (self.FEELS_BOUNDS, "feels", "FEELS LIKE", f"{round(snapshot.apparent_temperature)}°", "BODY WEATHER"),
            (self.HIGH_LOW_BOUNDS, "high_low", "HIGH  •  LOW", f"{round(snapshot.high)}°  •  {round(snapshot.low)}°", "TODAY'S RANGE"),
            (self.RAIN_BOUNDS, "rain", "RAIN TODAY", f"{round(snapshot.precipitation_probability_max)}%", "HIGHEST HOURLY"),
        )
        for bounds, key, title, value, helper in cards:
            left, top, right, bottom = bounds
            outline = "#ffbd2f" if self.speaking_key == key else "#9cc9df"
            self.canvas.create_rectangle(left, top, right, bottom, fill=self.CARD, outline=outline, width=4, stipple="gray50" if not self.announcements_available else "")
            self.canvas.create_text((left + right) // 2, top + 17, text=title, fill=self.MUTED, font=("Arial", 10, "bold"))
            self.canvas.create_text((left + right) // 2, top + 49, text=value, fill=self.NAVY, font=("Arial Rounded MT Bold", 24, "bold"))
            self.canvas.create_text((left + right) // 2, bottom - 10, text=helper, fill=self.MUTED, font=("Arial", 8, "bold"))
            self._hit_targets.append((bounds, key))

    def _draw_hourly(self, snapshot: WeatherSnapshot) -> None:
        hours = snapshot.hourly[:4]
        if not hours:
            return
        width = 184
        for index, hour in enumerate(hours):
            left = 18 + index * 194
            bounds = (left, 375, left + width, 437)
            time_label = hour.time.split("T")[-1][:5]
            chance = "" if hour.precipitation_probability is None else f"  ☂ {round(hour.precipitation_probability)}%"
            self.canvas.create_rectangle(*bounds, fill="#ffffff", outline="#b8d9e8", width=2)
            self.canvas.create_text(left + 15, 395, anchor="w", text=time_label, fill=self.MUTED, font=("Arial", 9, "bold"))
            self.canvas.create_text(left + 15, 419, anchor="w", text=f"{round(hour.temperature)}°{chance}", fill=self.NAVY, font=("Arial Rounded MT Bold", 14, "bold"))
            key = f"hour:{index}"
            self._hour_targets[key] = index
            self._hit_targets.append((bounds, key))

    def _draw_subtitle(self) -> None:
        fill = self.WHITE if self.current_data and self.current_data.snapshot.is_day is False else self.NAVY
        text = self.subtitle
        if not self.announcements_available:
            text = "BMO speech is unavailable, but every weather card still works."
        self.canvas.create_text(
            400, 462, width=760, text=text, fill=fill,
            font=("Arial", 10, "bold"),
        )

    @staticmethod
    def _event_point(event: tk.Event) -> tuple[int, int]:
        return int(event.x), int(event.y)

    def _handle_press(self, event: tk.Event) -> str:
        self.gesture.press(*self._event_point(event))
        return "break"

    def _handle_release(self, event: tk.Event) -> str:
        point = self._event_point(event)
        gesture = self.gesture.release(*point)
        if gesture is GestureKind.SWIPE_LEFT and self.carousel is not None:
            self.carousel.swipe_left()
            self._location_changed()
        elif gesture is GestureKind.SWIPE_RIGHT and self.carousel is not None:
            self.carousel.swipe_right()
            self._location_changed()
        elif gesture is GestureKind.TAP:
            if self._contains(self.FACE_BOUNDS, point):
                self.close()
            else:
                self._tap(point)
        return "break"

    def _location_changed(self) -> None:
        self.cancel_announcements()
        self.speaking_key = None
        self.subtitle = "BMO is checking this sky!"
        self._draw()
        self._announce_current_warning()
        self._load_current()

    @staticmethod
    def _contains(bounds: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
        left, top, right, bottom = bounds
        return left <= point[0] <= right and top <= point[1] <= bottom

    def _tap(self, point: tuple[int, int]) -> None:
        for bounds, key in reversed(self._hit_targets):
            if not self._contains(bounds, point):
                continue
            if key == "retry":
                location = self.current_location
                if location is not None:
                    self._errors.pop(location.id, None)
                    self._load_current()
                    self._draw()
                return
            self._speak(key)
            return

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
                snapshot.hourly[self._hour_targets[key]],
                imperial=snapshot.imperial,
            )
        else:
            return
        self.speaking_key = key
        self.subtitle = text
        self._draw()

        def completed() -> None:
            if self.closed or self.speaking_key != key:
                return
            self.speaking_key = None
            self._draw()

        if not self.announce(text, completed):
            self.speaking_key = None
            self._draw()

    def close(self) -> None:
        """Cancel view-owned callbacks and speech, then reveal the menu."""
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
        self.canvas.destroy()
        self.on_close()
