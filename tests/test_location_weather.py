"""Unit tests for location and weather services."""

from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch

from bmo.location import (
    LocationError,
    LocationNotConfigured,
    LocationService,
    request_json,
)
from bmo.network import online_timeout_seconds
from bmo.tools import ToolRouter
from bmo.weather import WeatherService


class LocationServiceTests(unittest.TestCase):
    def test_online_timeout_rejects_boolean_and_non_finite_values(self) -> None:
        for invalid in (True, "nan", "inf", "-inf", object()):
            messages: list[str] = []
            with self.subTest(value=invalid):
                self.assertEqual(
                    online_timeout_seconds(
                        {"online_timeout_seconds": invalid},
                        reporter=messages.append,
                    ),
                    6.0,
                )
                self.assertEqual(len(messages), 1)

        self.assertEqual(
            online_timeout_seconds({"online_timeout_seconds": 0}),
            1.0,
        )
        self.assertEqual(
            online_timeout_seconds({"online_timeout_seconds": 60}),
            30.0,
        )

    def test_network_json_rejects_duplicate_fields(self) -> None:
        response = BytesIO(b'{"value":1,"value":2}')
        with patch("bmo.location.urlopen", return_value=response):
            with self.assertRaisesRegex(LocationError, "invalid JSON"):
                request_json("https://example.invalid", 1.0)

    def test_configured_coordinates_do_not_make_network_request(self) -> None:
        def fail_request(url: str, timeout: float) -> dict:
            raise AssertionError(f"unexpected request: {url}, {timeout}")

        service = LocationService(
            {
                "name": "Dallas, Texas",
                "latitude": 32.7767,
                "longitude": -96.797,
                "timezone": "America/Chicago",
            },
            json_request=fail_request,
        )

        location = service.resolve()

        self.assertEqual(location.name, "Dallas, Texas")
        self.assertEqual(location.timezone, "America/Chicago")

    def test_named_place_is_geocoded(self) -> None:
        def fake_request(url: str, timeout: float) -> dict:
            self.assertIn("q=Austin", url)
            self.assertEqual(timeout, 6.0)
            return [
                {
                    "lat": "30.2672",
                    "lon": "-97.7431",
                    "address": {
                        "city": "Austin",
                        "state": "Texas",
                        "country": "United States",
                    },
                }
            ]

        location = LocationService(json_request=fake_request).resolve("Austin")

        self.assertEqual(location.name, "Austin, Texas, United States")
        self.assertAlmostEqual(location.latitude, 30.2672)

    def test_city_and_state_is_resolved_as_one_place_query(self) -> None:
        def fake_request(url: str, timeout: float) -> dict:
            self.assertIn("q=Houston%2C+Texas", url)
            return [
                {
                    "lat": "29.7633",
                    "lon": "-95.3633",
                    "address": {
                        "city": "Houston",
                        "state": "Texas",
                        "country": "United States",
                    },
                }
            ]

        location = LocationService(json_request=fake_request).resolve(
            "Houston, Texas"
        )

        self.assertEqual(location.name, "Houston, Texas, United States")
        self.assertAlmostEqual(location.latitude, 29.7633)

    def test_state_name_resolves_as_administrative_region(self) -> None:
        def fake_request(url: str, timeout: float) -> list:
            self.assertIn("q=California", url)
            return [
                {
                    "lat": "36.7015",
                    "lon": "-118.7559",
                    "address": {
                        "state": "California",
                        "country": "United States",
                    },
                }
            ]

        location = LocationService(json_request=fake_request).resolve(
            "California"
        )

        self.assertEqual(location.name, "California, United States")

    def test_missing_home_location_is_explicit(self) -> None:
        with self.assertRaises(LocationNotConfigured):
            LocationService().resolve()


class WeatherServiceTests(unittest.TestCase):
    def test_current_report_is_speech_friendly(self) -> None:
        location_service = LocationService(
            {
                "name": "Dallas, Texas",
                "latitude": 32.7767,
                "longitude": -96.797,
                "timezone": "America/Chicago",
            }
        )

        def fake_weather(url: str, timeout: float) -> dict:
            self.assertIn("temperature_unit=fahrenheit", url)
            self.assertEqual(timeout, 6.0)
            return {
                "current": {
                    "time": "2026-08-10T11:15",
                    "temperature_2m": 88.4,
                    "apparent_temperature": 94.2,
                    "weather_code": 2,
                    "relative_humidity_2m": 72,
                    "wind_speed_10m": 9.5,
                    "wind_gusts_10m": 18.0,
                    "visibility": 24140,
                    "cloud_cover": 83,
                    "is_day": 1,
                    "precipitation": 0.01,
                },
                "hourly": {
                    "time": ["2026-08-10T11:00", "2026-08-10T12:00"],
                    "temperature_2m": [88, 90],
                    "apparent_temperature": [94, 96],
                    "weather_code": [2, 61],
                    "precipitation_probability": [5, 20],
                    "is_day": [1, 1],
                },
                "daily": {
                    "temperature_2m_max": [96.1],
                    "temperature_2m_min": [77.7],
                    "precipitation_probability_max": [30],
                    "precipitation_sum": [0.05],
                    "sunrise": ["2026-08-10T06:45"],
                    "sunset": ["2026-08-10T20:05"],
                },
            }

        report = WeatherService(
            location_service,
            json_request=fake_weather,
        ).current_report()

        self.assertIn("88 degrees F and partly cloudy", report)
        self.assertIn(
            "highest hourly rain chance today is 30 percent",
            report,
        )

    def test_current_snapshot_exposes_gui_fields_and_future_hours(self) -> None:
        location_service = LocationService(
            {"name": "Home", "latitude": 30.1, "longitude": -95.6}
        )

        def fake_weather(url: str, timeout: float) -> dict:
            self.assertIn("relative_humidity_2m", url)
            self.assertIn("precipitation_sum", url)
            return {
                "current": {
                    "time": "2026-08-10T11:15",
                    "temperature_2m": 87,
                    "apparent_temperature": 89,
                    "weather_code": 3,
                    "relative_humidity_2m": 72,
                    "wind_speed_10m": 10,
                    "wind_gusts_10m": 22,
                    "visibility": 24140,
                    "cloud_cover": 90,
                    "precipitation": 0,
                    "is_day": 1,
                },
                "hourly": {
                    "time": ["2026-08-10T11:00", "2026-08-10T12:00"],
                    "temperature_2m": [87, 88],
                    "apparent_temperature": [89, 91],
                    "weather_code": [3, 61],
                    "precipitation_probability": [5, 10],
                    "is_day": [1, 1],
                },
                "daily": {
                    "temperature_2m_max": [91],
                    "temperature_2m_min": [76],
                    "precipitation_probability_max": [45],
                    "precipitation_sum": [0.05],
                    "sunrise": ["2026-08-10T06:45"],
                    "sunset": ["2026-08-10T20:05"],
                },
            }

        snapshot = WeatherService(
            location_service,
            json_request=fake_weather,
        ).current_snapshot()

        self.assertEqual(snapshot.humidity, 72)
        self.assertEqual(snapshot.visibility_meters, 24140)
        self.assertEqual(snapshot.precipitation_sum, 0.05)
        self.assertTrue(snapshot.is_day)
        self.assertEqual(len(snapshot.hourly), 1)
        self.assertEqual(snapshot.hourly[0].time, "2026-08-10T12:00")


class ToolRouterTests(unittest.TestCase):
    def test_home_weather_routes_without_the_language_model(self) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action("What's the weather?"),
            {"action": "get_weather"},
        )

    def test_named_weather_routes_with_location(self) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action("Weather in Austin, Texas"),
            {"action": "get_weather", "location": "austin, texas"},
        )

    def test_weather_like_in_routes_with_location(self) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action(
                "What's the weather like in Houston, Texas?"
            ),
            {"action": "get_weather", "location": "houston, texas"},
        )

    def test_direct_weather_location_excludes_time_qualifier(self) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action(
                "What's the weather like in California right now?"
            ),
            {"action": "get_weather", "location": "california"},
        )

    def test_location_request_routes_without_the_language_model(self) -> None:
        self.assertEqual(
            ToolRouter.match_direct_action("Where am I?"),
            {"action": "get_location"},
        )


if __name__ == "__main__":
    unittest.main()
