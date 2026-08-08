"""Unit tests for location and weather services."""

from __future__ import annotations

import unittest

from bmo.location import LocationService, LocationNotConfigured
from bmo.tools import ToolRouter
from bmo.weather import WeatherService


class LocationServiceTests(unittest.TestCase):
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
                    "temperature_2m": 88.4,
                    "apparent_temperature": 94.2,
                    "weather_code": 2,
                },
                "daily": {
                    "temperature_2m_max": [96.1],
                    "temperature_2m_min": [77.7],
                    "precipitation_probability_max": [30],
                },
            }

        report = WeatherService(
            location_service,
            json_request=fake_weather,
        ).current_report()

        self.assertIn("88 degrees F and partly cloudy", report)
        self.assertIn("rain chance is 30 percent", report)


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
