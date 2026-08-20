"""Current-weather voice action and child-friendly menu view."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
    normalize_direct_text,
)
from bmo.features.weather_alerts import NWSAlertService
from bmo.features.weather_config import (
    DEFAULT_WEATHER_CONFIG_PATH,
    WeatherFeatureConfig,
    WeatherLocationConfig,
    load_weather_config,
)
from bmo.features.weather_view import WeatherPageData
from bmo.location import (
    Location,
    LocationError,
    LocationNotConfigured,
    LocationService,
)
from bmo.network import online_timeout_seconds
from bmo.weather import WeatherError, WeatherService
from bmo.view_factory import NOT_HOSTED, create_hosted_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEATHER_MENU_ITEM = FeatureMenuItem(
    name="get_weather",
    label="Weather",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "weather.png",
)
WeatherAppFactory = Callable[..., Any]


def _create_weather_app(*args: Any, **kwargs: Any) -> Any:
    """Construct the Tk weather view only when its menu item is launched."""
    hosted = create_hosted_view("weather", args, kwargs)
    if hosted is not NOT_HOSTED:
        return hosted
    from bmo.ui.weather import WeatherApp

    return WeatherApp(*args, **kwargs)


WEATHER_AT_HOME = frozenset(
    {
        "weather",
        "weather today",
        "today's weather",
        "todays weather",
        "what is the weather",
        "what's the weather",
        "whats the weather",
        "what is the weather like today",
        "what's the weather like today",
        "whats the weather like today",
        "how is the weather",
        "how's the weather",
        "hows the weather",
        "what is it like outside",
        "what's it like outside",
        "whats it like outside",
    }
)

WEATHER_PREFIXES = (
    "what is the weather in ",
    "what's the weather in ",
    "whats the weather in ",
    "what is the weather like in ",
    "what's the weather like in ",
    "whats the weather like in ",
    "how is the weather in ",
    "how's the weather in ",
    "hows the weather in ",
    "weather in ",
    "weather for ",
    "forecast for ",
    "forecast in ",
)

_TEMPORAL_SUFFIX = re.compile(
    r"(?:\s*,?\s+)"
    r"(?:today|right now|currently|now|at the moment|"
    r"this (?:morning|afternoon|evening|weekend))$",
    re.IGNORECASE,
)


def clean_weather_location(place_name: str) -> str:
    """Remove time qualifiers that are not part of a place name."""
    cleaned = place_name.strip().rstrip("?.!")
    while True:
        updated = _TEMPORAL_SUFFIX.sub("", cleaned).strip()
        if updated == cleaned:
            return cleaned
        cleaned = updated


class GetWeatherTool:
    """Report current weather and own the optional weather menu lifecycle."""

    action = "get_weather"
    aliases = ("weather", "forecast", "check_weather")
    description = "Report current weather for a named or configured place."
    schemas = (
        '{"action":"get_weather"}',
        '{"action":"get_weather","location":"city, state or country"}',
    )
    prompt_guidance = (
        "Use get_weather for current weather or today's forecast.",
        "Include location only when the user names a place, excluding time "
        "words such as today and right now.",
    )
    prompt_examples = (
        ("What's the weather?", '{"action":"get_weather"}'),
        (
            "What's the weather in Austin?",
            '{"action":"get_weather","location":"Austin, Texas"}',
        ),
    )
    direct_phrases = WEATHER_AT_HOME
    direct_prefixes = WEATHER_PREFIXES

    def __init__(
        self,
        weather_service: WeatherService,
        *,
        feature_config: WeatherFeatureConfig | None = None,
        alert_service: NWSAlertService | None = None,
        app_factory: WeatherAppFactory = _create_weather_app,
        menu_item: FeatureMenuItem | None = None,
    ) -> None:
        self.weather_service = weather_service
        self.feature_config = feature_config or WeatherFeatureConfig()
        self.alert_service = alert_service
        self._app_factory = app_factory
        self.menu_item = menu_item
        self._menu_ui: Any | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        value = request.get("value") or request.get("query")
        place_name = clean_weather_location(
            str(request.get("location") or value or "")
        )
        try:
            return ToolResult.model_summarized(
                self.weather_service.current_report(place_name or None)
            )
        except LocationNotConfigured:
            return ToolResult.model_summarized(
                "I need a location in config/weather.json, or you can ask "
                "for the weather in a named city."
            )
        except LocationError as exc:
            print(f"[LOCATION] Weather place lookup failed: {exc}", flush=True)
            return ToolResult.model_summarized(str(exc))
        except (WeatherError, OSError, TimeoutError) as exc:
            print(f"[WEATHER] Lookup failed: {exc}", flush=True)
            return ToolResult.model_summarized(
                "I cannot reach the weather service right now."
            )
        except Exception as exc:
            print(f"[WEATHER] Unexpected lookup error: {exc}", flush=True)
            return ToolResult.model_summarized(
                "I cannot reach the weather service right now."
            )

    def open_menu(self, context: FeatureMenuContext) -> None:
        """Open one weather carousel while leaving voice routing unchanged."""
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            self._menu_ui = None
            context.cancel_announcements()
            context.on_close()

        try:
            self._menu_ui = self._app_factory(
                context.master,
                locations=self.feature_config.locations,
                default_index=self.feature_config.default_index,
                page_provider=self._weather_page,
                face_provider=context.current_face,
                announce=context.announce,
                cancel_announcements=context.cancel_announcements,
                announcements_available=context.announcements_available,
                season_style=self.feature_config.season_style,
                animations=self.feature_config.animations,
                debug=self.feature_config.debug,
                announce_warnings=self.feature_config.alerts.announce_warnings,
                on_close=handle_close,
            )
        except Exception as exc:
            self._menu_ui = None
            print(
                f"[WEATHER] Display unavailable: {type(exc).__name__}",
                flush=True,
            )

            def finish_failure() -> None:
                context.cancel_announcements()
                context.on_close()

            if context.announcements_available and context.announce(
                "BMO cannot open the weather screen right now.",
                finish_failure,
            ):
                return
            finish_failure()

    def _weather_page(self, configured: WeatherLocationConfig) -> WeatherPageData:
        """Load one location and isolate optional official-alert failures."""
        if configured.latitude is not None and configured.longitude is not None:
            location = Location(
                configured.name,
                configured.latitude,
                configured.longitude,
                configured.timezone,
            )
        else:
            location = self.weather_service.location_service.resolve(
                configured.name
            )
        snapshot = self.weather_service.current_snapshot(location=location)
        alerts = ()
        if self.alert_service is not None:
            try:
                alerts = self.alert_service.active_alerts(snapshot.location)
            except Exception as exc:
                print(
                    f"[WEATHER] Official alerts unavailable: {type(exc).__name__}",
                    flush=True,
                )
        return WeatherPageData(snapshot, alerts)

    def close(self) -> None:
        """Close the view and release feature-owned provider caches."""
        if self._menu_ui is not None:
            self._menu_ui.close()
        if self.alert_service is not None:
            self.alert_service.clear()

    @staticmethod
    def normalize_request(request: ToolRequest) -> dict[str, Any]:
        """Normalize a model-supplied place without changing other fields."""
        normalized = dict(request)
        location = clean_weather_location(str(request.get("location") or ""))
        if location:
            normalized["location"] = location
        else:
            normalized.pop("location", None)
        return normalized

    @classmethod
    def match_direct_action(cls, user_text: str) -> DirectAction | None:
        normalized = normalize_direct_text(user_text)
        if normalized in cls.direct_phrases:
            return {"action": cls.action}

        for prefix in cls.direct_prefixes:
            if normalized.startswith(prefix):
                place_name = normalized[len(prefix):].strip()
                if place_name:
                    return {
                        "action": cls.action,
                        "location": clean_weather_location(place_name),
                    }
        return None


def _weather_config_path(settings: Mapping[str, Any]) -> Path | None:
    value = settings.get("weather_config_path")
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        print(
            "[CONFIG] weather_config_path must not be empty; "
            "using config/weather.json.",
            flush=True,
        )
        return DEFAULT_WEATHER_CONFIG_PATH
    if not isinstance(value, (str, Path)):
        print(
            "[CONFIG] weather_config_path must be a path; using config/weather.json.",
            flush=True,
        )
        return DEFAULT_WEATHER_CONFIG_PATH
    return Path(value)


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register voice and menu weather behavior with owned dependencies."""
    timeout = online_timeout_seconds(settings)
    feature_config = load_weather_config(
        _weather_config_path(settings),
        legacy_location=settings.get("location"),
        legacy_units=settings.get("weather_units", "imperial"),
    )
    for issue in feature_config.issues:
        print(f"[CONFIG] Weather: {issue}.", flush=True)

    default_location = feature_config.default_location
    home_location = (
        default_location.home_location()
        if default_location is not None
        else settings.get("location")
    )
    location_service = LocationService(home_location, timeout=timeout)
    weather_service = WeatherService(
        location_service,
        timeout=timeout,
        units=feature_config.units,
    )
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("weather show_in_menu must be true or false")
    alert_service = (
        NWSAlertService(timeout=timeout)
        if feature_config.alerts.enabled
        else None
    )
    registry.register(
        GetWeatherTool(
            weather_service,
            feature_config=feature_config,
            alert_service=alert_service,
            menu_item=WEATHER_MENU_ITEM if show_in_menu else None,
        )
    )


def register_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register weather routing metadata without private config or clients."""
    timeout = online_timeout_seconds(settings)
    location_service = LocationService(
        settings.get("location"),
        timeout=timeout,
    )
    registry.register(
        GetWeatherTool(
            WeatherService(location_service, timeout=timeout),
        )
    )


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute Weather menu metadata without clients or private config."""
    show_in_menu = settings.get("show_in_menu", True)
    if not isinstance(show_in_menu, bool):
        raise TypeError("weather show_in_menu must be true or false")
    if show_in_menu:
        registry.register(WEATHER_MENU_ITEM)
