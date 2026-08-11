"""Weather feature configuration, narration, alerts, menu, and UI tests."""

from __future__ import annotations

import json
import queue
import signal
import threading
import unittest
from datetime import datetime, timedelta
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
    narrate_condition,
    narrate_feels_like,
    narrate_rain,
    narrate_temperature,
    season_for,
)
from bmo.location import Location
from bmo.ui.weather import (
    ChromiumSession,
    MOON_PHASES,
    WeatherApp,
    WeatherCarousel,
    WeatherPageData,
    WeatherWebBridge,
    day_period_for,
    moon_phase_for,
    select_upcoming_hours,
    weather_web_state,
)
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
                        "debug": True,
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
        self.assertTrue(config.debug)
        self.assertTrue(config.alerts.enabled)
        self.assertTrue(config.alerts.announce_warnings)

    def test_bad_entries_are_skipped_without_echoing_private_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "weather.json"
            path.write_text(
                json.dumps(
                    {
                        "debug": "yes",
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
        self.assertFalse(config.debug)
        self.assertIn("debug must be true or false", issue_text)

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

    def test_clear_night_narration_mentions_the_moon_not_the_sun(self) -> None:
        message = narrate_condition(
            make_snapshot(weather_code=0, is_day=False)
        )

        self.assertIn("moon is smiling", message)
        self.assertNotIn("sun is smiling", message)


class WeatherSceneStateTests(unittest.TestCase):
    def test_moon_phase_catalog_covers_the_eight_basic_phases(self) -> None:
        reference = datetime(2000, 1, 6, 18, 14)
        offsets = (0, 3.7, 7.4, 11.1, 14.77, 18.46, 22.15, 25.84)

        phases = tuple(
            moon_phase_for(reference + timedelta(days=offset))
            for offset in offsets
        )

        self.assertEqual(
            phases,
            (
                "new",
                "waxing_crescent",
                "first_quarter",
                "waxing_gibbous",
                "full",
                "waning_gibbous",
                "last_quarter",
                "waning_crescent",
            ),
        )

    def test_day_period_uses_local_sunrise_and_sunset(self) -> None:
        snapshot = make_snapshot(
            sunrise="2026-08-10T06:45",
            sunset="2026-08-10T20:05",
        )

        self.assertEqual(day_period_for(snapshot, datetime(2026, 8, 10, 8)), "morning")
        self.assertEqual(day_period_for(snapshot, datetime(2026, 8, 10, 12)), "midday")
        self.assertEqual(day_period_for(snapshot, datetime(2026, 8, 10, 16)), "afternoon")
        self.assertEqual(day_period_for(snapshot, datetime(2026, 8, 10, 19)), "sunset")
        self.assertEqual(day_period_for(snapshot, datetime(2026, 8, 10, 21)), "night")

    def test_upcoming_hour_strip_drops_passed_slots(self) -> None:
        hours = tuple(
            HourlyWeather(
                f"2026-08-10T{hour:02d}:00",
                80 + hour,
                80 + hour,
                0,
                5,
                True,
            )
            for hour in range(12, 18)
        )
        snapshot = make_snapshot(hourly=hours)

        selected = select_upcoming_hours(
            snapshot,
            datetime(2026, 8, 10, 13, 1),
        )

        self.assertEqual(
            tuple(hour.time for hour in selected),
            (
                "2026-08-10T14:00",
                "2026-08-10T15:00",
                "2026-08-10T16:00",
                "2026-08-10T17:00",
            ),
        )


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
    def test_view_publishes_animated_alert_page_and_cleans_up(
        self,
        thread_type: Mock,
    ) -> None:
        root = Mock()
        root.after.return_value = "weather-after"
        cancel_speech = Mock()
        on_close = Mock()
        bridge = Mock(url="http://127.0.0.1:1234/token/")
        browser = Mock()
        browser.poll.return_value = None
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
            browser_launcher=Mock(return_value=browser),
            bridge_factory=Mock(return_value=bridge),
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

        app._publish_state()

        published = bridge.set_state.call_args.args[0]
        self.assertEqual(published["condition"], "severe")
        self.assertEqual(published["alert"], "Severe Thunderstorm Warning")
        self.assertTrue(published["speech_available"])
        bridge.start.assert_called_once_with()
        thread_type.return_value.start.assert_called_once_with()

        app.close()

        cancel_speech.assert_called_once_with()
        browser.close.assert_called_once_with()
        bridge.close.assert_called_once_with()
        on_close.assert_called_once_with()

    @patch("bmo.ui.weather.threading.Thread")
    def test_weather_remains_visible_and_speech_targets_disable_without_provider(
        self,
        thread_type: Mock,
    ) -> None:
        root = Mock()
        root.after.return_value = "weather-after"
        bridge = Mock(url="http://127.0.0.1:1234/token/")
        browser = Mock()
        browser.poll.return_value = None
        location = WeatherLocationConfig("home", "Home", "Tomball")
        app = WeatherApp(
            root,
            locations=(location,),
            default_index=0,
            page_provider=Mock(),
            face_provider=Mock(return_value=None),
            announce=Mock(return_value=False),
            cancel_announcements=Mock(),
            announcements_available=False,
            on_close=Mock(),
            browser_launcher=Mock(return_value=browser),
            bridge_factory=Mock(return_value=bridge),
        )
        app._cache["home"] = WeatherPageData(make_snapshot())

        app._publish_state()

        published = bridge.set_state.call_args.args[0]
        self.assertFalse(published["speech_available"])
        self.assertEqual(tuple(app._hour_targets), ("hour:0",))
        thread_type.return_value.start.assert_called_once_with()

    def test_debug_preview_starts_without_a_configured_location(self) -> None:
        root = Mock()
        root.after.return_value = "weather-after"
        bridge = Mock(url="http://127.0.0.1:1234/token/")
        browser = Mock()
        browser.poll.return_value = None

        app = WeatherApp(
            root,
            locations=(),
            default_index=0,
            page_provider=Mock(),
            face_provider=Mock(),
            announce=Mock(return_value=False),
            cancel_announcements=Mock(),
            announcements_available=False,
            debug=True,
            on_close=Mock(),
            browser_launcher=Mock(return_value=browser),
            bridge_factory=Mock(return_value=bridge),
        )

        published = bridge.set_state.call_args.args[0]
        self.assertEqual(published["status"], "empty")
        self.assertTrue(published["debug"])
        app.close()

    def test_cached_page_is_refetched_after_refresh_interval(self) -> None:
        location = WeatherLocationConfig("home", "Home", "Tomball")
        app = WeatherApp.__new__(WeatherApp)
        app.locations = (location,)
        app.carousel = WeatherCarousel(1)
        app._cache = {"home": WeatherPageData(make_snapshot())}
        app._loaded_at = {"home": 100.0}
        app._load_current = Mock()

        with patch(
            "bmo.ui.weather.time.monotonic",
            return_value=100.0 + WeatherApp.REFRESH_SECONDS + 1,
        ):
            app._refresh_if_stale()

        app._load_current.assert_called_once_with(force=True)

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
        self.assertFalse(created["debug"])
        tool.close()
        view.close.assert_called_once_with()
        alert_service.clear.assert_called_once_with()

    def test_tool_can_reopen_after_the_previous_weather_view_closes(self) -> None:
        views: list[Mock] = []

        def app_factory(_root: object, **kwargs: object) -> Mock:
            view = Mock()
            view.close.side_effect = kwargs["on_close"]
            views.append(view)
            return view

        tool = GetWeatherTool(
            Mock(),
            feature_config=WeatherFeatureConfig(
                locations=(WeatherLocationConfig("home", "Home", "Tomball"),)
            ),
            app_factory=app_factory,  # type: ignore[arg-type]
        )
        context = FeatureMenuContext(master=object(), on_close=Mock())

        tool.open_menu(context)
        views[0].close()
        tool.open_menu(context)
        views[1].close()

        self.assertEqual(len(views), 2)
        self.assertIsNone(tool._menu_ui)
        self.assertEqual(context.on_close.call_count, 2)

    def test_browser_failure_returns_to_menu_and_preserves_feature_isolation(self) -> None:
        announcer = Mock(available=True)

        def speak(_text: str, on_complete: object) -> bool:
            assert callable(on_complete)
            on_complete()
            return True

        announcer.speak.side_effect = speak
        context = FeatureMenuContext(
            master=object(),
            on_close=Mock(),
            announcer=announcer,
        )
        tool = GetWeatherTool(
            Mock(),
            feature_config=WeatherFeatureConfig(
                locations=(WeatherLocationConfig("home", "Home", "Tomball"),)
            ),
            app_factory=Mock(side_effect=RuntimeError("browser unavailable")),
        )

        tool.open_menu(context)

        context.on_close.assert_called_once_with()
        announcer.cancel.assert_called_once_with()
        announcer.speak.assert_called_once()
        self.assertIsNone(tool._menu_ui)

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
        self.assertEqual(visible.menu_items[0].icon_path.parent.name, "icons")
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
        bridge = Mock(url="http://127.0.0.1:1234/token/")
        browser = Mock()
        browser.poll.return_value = None
        root = Mock()
        root.after.return_value = "poll"
        with patch("bmo.ui.weather.threading.Thread"):
            app = WeatherApp(
                root,
                locations=(location,),
                default_index=0,
                page_provider=Mock(),
                face_provider=Mock(),
                announce=Mock(return_value=False),
                cancel_announcements=Mock(),
                announcements_available=False,
                on_close=Mock(),
                browser_launcher=Mock(return_value=browser),
                bridge_factory=Mock(return_value=bridge),
            )
        app._tokens["home"] = 2
        app._results.put(("home", 1, stale, None))
        app._results.put(("home", 2, current, None))
        app._announce_current_warning = Mock()

        app._poll()

        self.assertIs(app._cache["home"], current)
        app._announce_current_warning.assert_called_once_with()


class WeatherWebRendererTests(unittest.TestCase):
    def test_live_state_covers_season_time_moon_hourly_and_debug(self) -> None:
        snapshot = make_snapshot(
            weather_code=0,
            is_day=False,
            observed_at="2026-12-23T21:00",
            sunrise="2026-12-23T07:00",
            sunset="2026-12-23T17:30",
        )

        state = weather_web_state(
            WeatherPageData(snapshot),
            datetime(2026, 12, 23, 21),
            season_style="auto",
            animations=True,
            debug=True,
            speech_available=True,
            page_index=1,
            page_count=3,
        )

        self.assertEqual(state["condition"], "sunny")
        self.assertEqual(state["time"], "night")
        self.assertEqual(state["season"], "winter")
        self.assertIn(state["phase"], {phase.replace("_", "-") for phase in MOON_PHASES})
        self.assertTrue(state["debug"])
        self.assertTrue(state["speech_available"])
        self.assertEqual(state["page_index"], 1)

    def test_hot_clear_night_uses_moon_art_and_night_advice(self) -> None:
        snapshot = make_snapshot(
            weather_code=0,
            temperature=101,
            apparent_temperature=106,
            is_day=False,
            observed_at="2026-08-10T22:00",
            sunrise="2026-08-10T06:30",
            sunset="2026-08-10T20:00",
        )

        state = weather_web_state(
            WeatherPageData(snapshot),
            datetime(2026, 8, 10, 22),
            season_style="auto",
            animations=True,
            debug=False,
            speech_available=True,
            page_index=0,
            page_count=1,
        )

        self.assertEqual(state["condition"], "hot")
        self.assertEqual(state["time"], "night")
        self.assertIn("warm night", state["speech"])
        self.assertIn("moon", state["modifier"])

    def test_debug_asset_lists_every_visual_condition_and_no_emoji_icons(self) -> None:
        asset = Path("bmo/ui/weather_web/index.html").read_text(encoding="utf-8")
        for condition in (
            "sunny",
            "mostly-clear",
            "partly",
            "cloudy",
            "overcast",
            "fog",
            "drizzle",
            "rain",
            "heavy-rain",
            "freezing-rain",
            "storm",
            "snow",
            "heavy-snow",
            "sleet",
            "hail",
            "wind",
            "hot",
            "cold",
            "mixed",
            "severe",
        ):
            self.assertIn(f'data-value="{condition}"', asset)
        self.assertIn("function hourIconSvg", asset)
        self.assertIn('data-bmo-face-image src="face/idle"', asset)
        self.assertIn("new URL('face/speaking-3'", asset)
        self.assertIn("setBmoSpeaking(Boolean(live && data.speaking))", asset)
        self.assertNotIn("☀️", asset)
        self.assertNotIn("🌧", asset)

    def test_loopback_bridge_exposes_only_named_core_face_frames(self) -> None:
        with TemporaryDirectory() as temp_dir:
            face_root = Path(temp_dir)
            idle = face_root / "idle" / "idle 01.png"
            idle.parent.mkdir()
            idle.write_bytes(b"canonical-idle-frame")
            bridge = WeatherWebBridge.__new__(WeatherWebBridge)
            bridge.face_assets = {
                "idle": idle,
                "speaking-1": face_root / "speaking" / "speaking 01.png",
            }

            self.assertEqual(bridge.face_asset("idle"), idle)
            self.assertEqual(
                bridge.face_asset("idle").read_bytes(),  # type: ignore[union-attr]
                b"canonical-idle-frame",
            )
            self.assertIsNone(bridge.face_asset("../../config/settings.json"))
            self.assertIsNone(bridge.face_asset("not-a-frame"))

    def test_loopback_action_validation_rejects_unbounded_or_unknown_input(self) -> None:
        self.assertEqual(
            WeatherWebBridge._validated_action(
                {"name": "navigate", "direction": 1}
            ),
            {"name": "navigate", "direction": 1},
        )
        self.assertEqual(
            WeatherWebBridge._validated_action(
                {"name": "speak", "key": "hour:3"}
            ),
            {"name": "speak", "key": "hour:3"},
        )
        with self.assertRaises(ValueError):
            WeatherWebBridge._validated_action({"name": "open_url"})
        with self.assertRaises(ValueError):
            WeatherWebBridge._validated_action({"name": []})
        with self.assertRaises(ValueError):
            WeatherWebBridge._validated_action(
                {"name": "navigate", "direction": True}
            )
        with self.assertRaises(ValueError):
            WeatherWebBridge._validated_action(
                {"name": "speak", "key": "../../secret"}
            )

    def test_renderer_lifecycle_actions_have_no_user_controlled_fields(self) -> None:
        self.assertEqual(
            WeatherWebBridge._validated_action({"name": "ready"}),
            {"name": "ready"},
        )
        self.assertEqual(
            WeatherWebBridge._validated_action({"name": "heartbeat"}),
            {"name": "heartbeat"},
        )

    def test_renderer_watchdog_recovers_from_a_blank_kiosk_page(self) -> None:
        app = WeatherApp.__new__(WeatherApp)
        app._renderer_started_at = 100.0
        app._renderer_last_seen = None

        with patch("bmo.ui.weather.time.monotonic", return_value=109.0):
            self.assertTrue(app._renderer_is_healthy())
        with patch("bmo.ui.weather.time.monotonic", return_value=111.0):
            self.assertFalse(app._renderer_is_healthy())

        app._renderer_last_seen = 200.0
        with patch("bmo.ui.weather.time.monotonic", return_value=211.0):
            self.assertFalse(app._renderer_is_healthy())

    def test_chromium_session_uses_isolated_profile_and_sandbox(self) -> None:
        process = Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = 0
        popen = Mock(return_value=process)

        with patch("bmo.ui.weather.os.killpg") as kill_group:
            session = ChromiumSession(
                "http://127.0.0.1:1234/token/",
                executable=Path("/usr/bin/chromium"),
                popen=popen,
            )
            command = popen.call_args.args[0]
            self.assertIn("--kiosk", command)
            self.assertTrue(
                any(value.startswith("--user-data-dir=") for value in command)
            )
            self.assertIn("--password-store=basic", command)
            self.assertIn("--use-mock-keychain", command)
            self.assertNotIn("--no-sandbox", command)
            session.close()

        kill_group.assert_called_once_with(4321, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
