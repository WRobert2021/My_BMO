"""Optional official weather alerts owned by the weather feature."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

from bmo.location import JsonRequest, Location, request_json


@dataclass(frozen=True)
class WeatherAlert:
    """A concise subset of one official alert suitable for the small display."""

    event: str
    headline: str
    severity: str
    urgency: str
    instruction: str | None = None
    description: str | None = None


class NWSAlertService:
    """Load and briefly cache active NWS alerts for a geographic point."""

    ALERTS_URL = "https://api.weather.gov/alerts/active"
    MIN_CACHE_SECONDS = 30.0

    def __init__(
        self,
        *,
        timeout: float = 6.0,
        cache_seconds: float = 300.0,
        json_request: JsonRequest = request_json,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = timeout
        self.cache_seconds = max(float(cache_seconds), self.MIN_CACHE_SECONDS)
        self._json_request = json_request
        self._monotonic = monotonic
        self._cache: dict[
            tuple[float, float],
            tuple[float, tuple[WeatherAlert, ...]],
        ] = {}

    def active_alerts(self, location: Location) -> tuple[WeatherAlert, ...]:
        """Return active official alerts, using a cache to respect the provider."""
        key = (round(location.latitude, 4), round(location.longitude, 4))
        now = self._monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self.cache_seconds:
            return cached[1]

        query = urlencode({"point": f"{key[0]},{key[1]}"})
        payload = self._json_request(f"{self.ALERTS_URL}?{query}", self.timeout)
        alerts = self._parse(payload)
        self._cache[key] = (now, alerts)
        return alerts

    @staticmethod
    def _parse(payload: Any) -> tuple[WeatherAlert, ...]:
        if not isinstance(payload, dict):
            raise ValueError("alert service returned invalid data")
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise ValueError("alert service returned invalid data")

        alerts: list[WeatherAlert] = []
        for feature in raw_features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            event = str(properties.get("event") or "").strip()
            headline = str(properties.get("headline") or event).strip()
            if not event or not headline:
                continue
            instruction = str(properties.get("instruction") or "").strip() or None
            description = str(properties.get("description") or "").strip() or None
            alerts.append(
                WeatherAlert(
                    event=event,
                    headline=headline,
                    severity=str(properties.get("severity") or "Unknown").strip(),
                    urgency=str(properties.get("urgency") or "Unknown").strip(),
                    instruction=instruction,
                    description=description,
                )
            )
        return tuple(alerts)

    def clear(self) -> None:
        """Release cached provider data during feature shutdown."""
        self._cache.clear()
