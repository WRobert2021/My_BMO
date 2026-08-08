"""Location resolution for configured and user-supplied place names."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LocationError(RuntimeError):
    """Base error for location lookups."""


class LocationNotConfigured(LocationError):
    """Raised when a request needs a home location that has not been set."""


@dataclass(frozen=True)
class Location:
    """A resolved place suitable for weather queries."""

    name: str
    latitude: float
    longitude: float
    timezone: str = "auto"


JsonRequest = Callable[[str, float], dict[str, Any]]


def request_json(url: str, timeout: float) -> dict[str, Any]:
    """Fetch a JSON object with a bounded timeout and identifiable user agent."""
    request = Request(url, headers={"User-Agent": "be-more-agent/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise LocationError("location service returned an invalid response")
    return payload


class LocationService:
    """Resolve home coordinates or geocode a spoken place name."""

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(
        self,
        home_location: dict[str, Any] | None = None,
        timeout: float = 6.0,
        json_request: JsonRequest = request_json,
    ) -> None:
        self.home_location = home_location or {}
        self.timeout = timeout
        self._json_request = json_request

    def resolve(self, place_name: str | None = None) -> Location:
        """Resolve a named place, or fall back to the configured home location."""
        requested_name = (place_name or "").strip()
        if requested_name:
            return self._geocode(requested_name)

        configured_name = str(self.home_location.get("name") or "").strip()
        latitude = self.home_location.get("latitude")
        longitude = self.home_location.get("longitude")
        if latitude is not None and longitude is not None:
            try:
                return Location(
                    name=configured_name or "your configured location",
                    latitude=float(latitude),
                    longitude=float(longitude),
                    timezone=str(self.home_location.get("timezone") or "auto"),
                )
            except (TypeError, ValueError) as exc:
                raise LocationError(
                    "configured latitude and longitude must be numbers"
                ) from exc

        if configured_name:
            return self._geocode(configured_name)

        raise LocationNotConfigured(
            "Set location.name or location latitude/longitude in config.json."
        )

    def _geocode(self, place_name: str) -> Location:
        query = urlencode(
            {
                "name": place_name,
                "count": 1,
                "language": "en",
                "format": "json",
            }
        )
        payload = self._json_request(f"{self.GEOCODING_URL}?{query}", self.timeout)
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise LocationError(f"I could not find a place named {place_name}.")

        result = results[0]
        if not isinstance(result, dict):
            raise LocationError("location service returned an invalid place")
        try:
            latitude = float(result["latitude"])
            longitude = float(result["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocationError("location service omitted the coordinates") from exc

        label_parts = [
            str(result.get("name") or "").strip(),
            str(result.get("admin1") or "").strip(),
            str(result.get("country") or "").strip(),
        ]
        label = ", ".join(dict.fromkeys(part for part in label_parts if part))
        return Location(
            name=label or place_name,
            latitude=latitude,
            longitude=longitude,
            timezone=str(result.get("timezone") or "auto"),
        )
