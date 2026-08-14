"""Location resolution for configured and user-supplied place names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bmo.jsonio import load_json


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


JsonRequest = Callable[[str, float], Any]


def request_json(url: str, timeout: float) -> Any:
    """Fetch JSON with a bounded timeout and identifiable user agent."""
    request = Request(url, headers={"User-Agent": "be-more-agent/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return load_json(response)
    except (UnicodeError, ValueError) as exc:
        raise LocationError("online service returned invalid JSON") from exc


class LocationService:
    """Resolve home coordinates or geocode a spoken place name."""

    GEOCODING_URL = "https://nominatim.openstreetmap.org/search"

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
            "Set location.name or location latitude/longitude in "
            "config/settings.json."
        )

    def _geocode(self, place_name: str) -> Location:
        query = urlencode(
            {
                "q": place_name,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "en",
            }
        )
        payload = self._json_request(f"{self.GEOCODING_URL}?{query}", self.timeout)
        if not isinstance(payload, list) or not payload:
            raise LocationError(f"I could not find a place named {place_name}.")

        result = payload[0]
        if not isinstance(result, dict):
            raise LocationError("location service returned an invalid place")
        try:
            latitude = float(result["lat"])
            longitude = float(result["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocationError("location service omitted the coordinates") from exc

        address = result.get("address")
        if not isinstance(address, dict):
            address = {}
        locality = next(
            (
                str(address.get(field) or "").strip()
                for field in (
                    "city",
                    "town",
                    "village",
                    "municipality",
                    "county",
                    "state",
                )
                if str(address.get(field) or "").strip()
            ),
            "",
        )
        label_parts = [
            locality,
            str(address.get("state") or "").strip(),
            str(address.get("country") or "").strip(),
        ]
        label = ", ".join(dict.fromkeys(part for part in label_parts if part))
        return Location(
            name=label or place_name,
            latitude=latitude,
            longitude=longitude,
            timezone="auto",
        )
