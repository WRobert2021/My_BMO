"""Weather feature configuration, narration, alerts, menu, and UI tests."""

from __future__ import annotations

import json
import queue
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from bmo.features.contracts import FeatureMenuContext
from bmo.features.get_weather import GetWeatherTool, register
from bmo.features.registry import ToolRegistry
from bmo.features.weather_alerts import NWSAlertService, WeatherAlert
from bmo.features.weather_config import (
    WeatherAlertsConfig,
    WeatherFeatureConfig,
    WeatherLocationConfig,
    load_weather_config,
)
from bmo.features.weather_narration import (
    WeatherCondition,
    WeatherSeason,
    condition_for_code,
    narrate_alert,
    narrate_feels_like,
    narrate_rain,
    narrate_temperature,
    season_for,
)
from bmo.location import Location
from bmo.ui.weather import WeatherApp, WeatherCarousel, WeatherPageData
from bmo.weather import HourlyWeather, WeatherSnapshot


def make_snapshot(**changes: object) -> WeatherSnapshot:
    values: dict[str, object] = {
        "location": Location("Tomball, Texas", 30.0972, -95.6161),
        "imperial": True,
        "observed_at": "2026-08-10T11:15",
        "temperature": 87,
        "apparent_temperature": 96,
        "weather_code": 2,
        "high": 93,
        "low": 75,
        "precipitation_probability_max": 45,
        "humidity": 72,
        "wind_speed": 9,
        "wind_gusts": 18,
        "visibility_meters": 24140,
        "precipitation_sum": 0.05,
        "is_day": True,
        "hourly": (
            HourlyWeather("2026-08-10T12:00", 88, 96, 61, 20, True),
        ),
    }
    values.update(changes)
    return WeatherSnapshot(**values)  # type: ignore[arg-type]


class WeatherConfigTests(unittest.TestCase):
    def test_config_preserves_location_order_and_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weather.json"
            path.write_text(
                json.dumps(
                    {
                        "units": "metric",
                        "default_location": "school",
                        "season_style": "off",
                        "animations": False,
                        "alerts": {
                            "enabled": True,
                            "provider": "nws",
                            "announce_warnings": True,
                        },
                        "locations": [
                            {
                                "id": "home",
                                "label": "Home",
                                "name": "Tomball, Texas",
                                "latitude": 30.1,
                                "longitude": -95.6,
                            },
                            {
                                "id": "school",
                                "label": "School",
                                "name": "Austin, Texas",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_weather_config(path)

        self.assertEqual([place.id for place in config.locations], ["home", "school"])
        self.assertEqual(config.default_index, 1)
        self.assertEqual(config.units, "metric")
        self.assertEqual(config.season_style, "off")
        self.assertFalse(config.animations)
        self.assertTrue(config.alerts.enabled)
        self.assertTrue(config.alerts.announce_warnings)

    def test_bad_entries_are_skipped_without_echoing_private_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weather.json"
            path.write_text(
                json.dumps(
                    {
                        "locations": [
                            {
                                "id": "private-secret-place",
                                "label": "Top Secret House Name",
                                "name": "",
                                "latitude": 400,
                                "longitude": -95,
                            },
                            {
                                "id": "safe",
                                "label": "Home",
                                "name": "Tomball, Texas",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            config = load_weather_config(path)

        self.assertEqual(tuple(place.id for place in config.locations), ("safe",))
        self.assertTrue(config.issues)
        issue_text = " ".join(config.issues)
        self.assertNotIn("Top Secret", issue_text)
        self.assertNotIn("private-secret-place", issue_text)

    def test_missing_or_malformed_config_falls_back_to_legacy_home(self) -> None:
        legacy = {
            "name": "Legacy Home",
            "latitude": 30.1,
            "longitude": -95.6,
        }
        with TemporaryDirectory() as temp_dir:
            missing = load_weather_config(
                Path(temp_dir) / "missing.json",
                legacy_location=legacy,
                legacy_units="metric",
            )
            malformed_path = Path(temp_dir) / "weather.json"
            malformed_path.write_text("not json", encoding="utf-8")
            malformed = load_weather_config(
                malformed_path,
                legacy_location=legacy,
            )

        self.assertEqual(missing.default_location.name, "Legacy Home")
        self.assertEqual(missing.units, "metric")
        self.assertEqual(malformed.default_location.name, "Legacy Home")
        self.assertTrue(malformed.issues)


class WeatherNarrationTests(unittest.TestCase):
    def test_seasons_are_hemisphere_aware_and_neutral_in_tropics(self) -> None:
        self.assertEqual(season_for(30, 7), WeatherSeason.SUMMER)
        self.assertEqual(season_for(-30, 7), WeatherSeason.WINTER)
        self.assertEqual(season_for(5, 7), WeatherSeason.NEUTRAL)
        self.assertEqual(season_for(30, 7, "off"), WeatherSeason.OFF)

    def test_condition_catalog_includes_cloud_sleet_hail_and_unknown(self) -> None:
        self.assertEqual(condition_for_code(2), WeatherCondition.PARTLY_CLOUDY)
        self.assertEqual(condition_for_code(56), WeatherCondition.SLEET)
        self.assertEqual(condition_for_code(99), WeatherCondition.HAIL)
        self.assertEqual(condition_for_code(1234), WeatherCondition.MIXED)

    def test_temperature_and_feels_like_use_child_friendly_advice(self) -> None:
        snapshot = make_snapshot()
        self.assertIn("bring water", narrate_temperature(snapshot))
        self.assertIn("extra sticky", narrate_feels_like(snapshot))
        self.assertIn("umbrella", narrate_rain(snapshot))

    def test_unsafe_conditions_replace_playful_rain_advice(self) -> None:
        thunder = make_snapshot(weather_code=95, precipitation_probability_max=80)
        sleet = make_snapshot(weather_code=56)
        self.assertIn("grown-up", narrate_rain(thunder))
        self.assertIn("slippery", narrate_rain(sleet))

    def test_alert_narration_is_direct_safety_language(self) -> None:
        alert = WeatherAlert(
            "Tornado Warning",
            "Tornado Warning issued for the area",
            "Extreme",
            "Immediate",
            "Go with a grown-up to your safe place.",
        )
        message = narrate_alert(alert)
        self.assertIn("BMO safety alert", message)
        self.assertIn("safe place", message)


class WeatherAlertTests(unittest.TestCase):
    def test_nws_alerts_are_parsed_and_cached_by_point(self) -> None:
        requests: list[str] = []

        def request(url: str, timeout: float) -> dict:
            requests.append(url)
            self.assertEqual(timeout, 4)
            return {
                "features": [
                    {
                        "properties": {
                            "event": "Tornado Warning",
                            "headline": "Tornado Warning for the test area",
                            "severity": "Extreme",
                            "urgency": "Immediate",
                            "instruction": "Take shelter now.",
                        }
                    }
                ]
            }

        service = NWSAlertService(
            timeout=4,
            json_request=request,
            monotonic=Mock(side_effect=[0.0, 1.0]),
        )
        location = Location("Home", 30.1, -95.6)

        first = service.active_alerts(location)
        second = service.active_alerts(location)

        self.assertEqual(first, second)
        self.assertEqual(first[0].event, "Tornado Warning")
        self.assertEqual(len(requests), 1)
        self.assertIn("point=30.1%2C-95.6", requests[0])


class WeatherMenuTests(unittest.TestCase):
    def test_carousel_wraps_in_both_directions(self) -> None:
        carousel = WeatherCarousel(3, 0)
        self.assertEqual(carousel.swipe_right(), 2)
        self.assertEqual(carousel.swipe_left(), 0)
        self.assertEqual(carousel.swipe_left(), 1)

    @patch("bmo.ui.weather.threading.Thread")
    @patch("bmo.ui.weather.tk.Canvas")
    def test_view_draws_animated_alert_page_and_cleans_up(
        self,
        canvas_type: Mock,
        thread_type: Mock,
    ) -> None:
        root = Mock()
        root.after.return_value = "weather-after"
        cancel_speech = Mock()
        on_close = Mock()
        location = WeatherLocationConfig("home", "Home", "Tomball")
        app = WeatherApp(
            root,
            locations=(location,),
            default_index=0,
            page_provider=Mock(),
            face_provider=Mock(return_value=None),
            announce=Mock(return_value=True),
            cancel_announcements=cancel_speech,
            announcements_available=True,
            on_close=on_close,
        )
        alert = WeatherAlert(
            "Severe Thunderstorm Warning",
            "Severe weather warning",
            "Severe",
            "Immediate",
        )
        app._cache["home"] = WeatherPageData(
            make_snapshot(weather_code=99, wind_gusts=35),
            (alert,),
        )

        app._draw()

        canvas = canvas_type.return_value
        canvas.create_polygon.assert_called()
        self.assertIn("alert", [key for _, key in app._hit_targets])
        self.assertIn("temperature", [key for _, key in app._hit_targets])
        thread_type.return_value.start.assert_called_once_with()

        app.close()

        cancel_speech.assert_called_once_with()
        canvas.destroy.assert_called_once_with()
        on_close.assert_called_once_with()

    def test_tool_opens_one_view_with_scoped_menu_services(self) -> None:
        created: dict[str, object] = {}
        view = Mock()

        def app_factory(root: object, **kwargs: object) -> object:
            created.update(kwargs)
            return view

        location = WeatherLocationConfig("home", "Home", "Tomball, Texas")
        alert_service = Mock()
        tool = GetWeatherTool(
            Mock(),
            feature_config=WeatherFeatureConfig(locations=(location,)),
            alert_service=alert_service,
            app_factory=app_factory,  # type: ignore[arg-type]
        )
        closed = Mock()
        context = FeatureMenuContext(master=object(), on_close=closed)

        tool.open_menu(context)
        tool.open_menu(context)

        self.assertEqual(created["locations"], (location,))
        self.assertFalse(created["announcements_available"])
        self.assertEqual(created["default_index"], 0)
        tool.close()
        view.close.assert_called_once_with()
        alert_service.clear.assert_called_once_with()

    def test_alert_failure_does_not_break_the_forecast_page(self) -> None:
        snapshot = make_snapshot()
        weather_service = Mock()
        weather_service.current_snapshot.return_value = snapshot
        weather_service.location_service = Mock()
        alert_service = Mock()
        alert_service.active_alerts.side_effect = OSError("offline")
        configured = WeatherLocationConfig(
            "home", "Home", "Tomball", 30.1, -95.6
        )
        tool = GetWeatherTool(
            weather_service,
            feature_config=WeatherFeatureConfig(
                alerts=WeatherAlertsConfig(enabled=True),
                locations=(configured,),
            ),
            alert_service=alert_service,
        )

        page = tool._weather_page(configured)

        self.assertIs(page.snapshot, snapshot)
        self.assertEqual(page.alerts, ())
        weather_service.location_service.resolve.assert_not_called()

    def test_registration_can_hide_only_the_menu_item(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weather.json"
            path.write_text(
                json.dumps(
                    {
                        "locations": [
                            {"id": "home", "label": "Home", "name": "Austin"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            visible = ToolRegistry()
            register(visible, {"weather_config_path": str(path)})
            hidden = ToolRegistry()
            register(
                hidden,
                {"weather_config_path": str(path), "show_in_menu": False},
            )

        self.assertEqual(visible.menu_items[0].name, "get_weather")
        self.assertEqual(
            visible.menu_items[0].icon_path.name,
            "weather.png",
        )
        self.assertEqual(visible.menu_items[0].icon_path.parent.name, "Icons")
        self.assertEqual(hidden.menu_items, ())
        self.assertIn("get_weather", hidden.actions)

    def test_malformed_private_config_does_not_prevent_registration(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weather.json"
            path.write_text("not json", encoding="utf-8")
            registry = ToolRegistry()

            register(registry, {"weather_config_path": str(path)})

        self.assertIn("get_weather", registry.actions)
        self.assertEqual(registry.menu_items[0].name, "get_weather")

    def test_stale_async_result_cannot_replace_newer_data(self) -> None:
        location = WeatherLocationConfig("home", "Home", "Tomball")
        stale = WeatherPageData(make_snapshot(temperature=70))
        current = WeatherPageData(make_snapshot(temperature=87))
        app = WeatherApp.__new__(WeatherApp)
        app.closed = False
        app.locations = (location,)
        app.carousel = WeatherCarousel(1)
        app._cache = {}
        app._errors = {}
        app._inflight = {"home"}
        app._tokens = {"home": 2}
        app._results = queue.Queue()
        app._results.put(("home", 1, stale, None))
        app._results.put(("home", 2, current, None))
        app._after_ids = set()
        app.root = Mock()
        app.root.after.return_value = "poll"
        app._draw = Mock()
        app._announce_current_warning = Mock()

        app._poll_results()

        self.assertIs(app._cache["home"], current)
        app._draw.assert_called_once_with()
        app._announce_current_warning.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
