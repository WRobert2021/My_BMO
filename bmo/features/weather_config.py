"""Private, feature-owned configuration for weather locations and UI."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_WEATHER_CONFIG_PATH = Path("config/weather.json")


@dataclass(frozen=True)
class WeatherLocationConfig:
    """One stable, user-labeled location in the weather carousel."""

    id: str
    label: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "auto"

    def home_location(self) -> dict[str, Any]:
        """Return the mapping understood by the neutral location service."""
        values: dict[str, Any] = {
            "name": self.name,
            "timezone": self.timezone,
        }
        if self.latitude is not None and self.longitude is not None:
            values.update(
                latitude=self.latitude,
                longitude=self.longitude,
            )
        return values


@dataclass(frozen=True)
class WeatherAlertsConfig:
    """Optional official-alert behavior for the weather view."""

    enabled: bool = False
    provider: str = "nws"
    announce_warnings: bool = False


@dataclass(frozen=True)
class WeatherFeatureConfig:
    """Validated weather settings with safe fallbacks already applied."""

    units: str = "imperial"
    default_location_id: str | None = None
    season_style: str = "auto"
    animations: bool = True
    debug: bool = False
    alerts: WeatherAlertsConfig = field(default_factory=WeatherAlertsConfig)
    locations: tuple[WeatherLocationConfig, ...] = ()
    issues: tuple[str, ...] = ()
    source_path: Path | None = None

    @property
    def default_location(self) -> WeatherLocationConfig | None:
        """Return the configured default, or the first usable location."""
        if not self.locations:
            return None
        if self.default_location_id is not None:
            for location in self.locations:
                if location.id == self.default_location_id:
                    return location
        return self.locations[0]

    @property
    def default_index(self) -> int:
        """Return the default location's carousel index."""
        default = self.default_location
        if default is None:
            return 0
        return self.locations.index(default)


def _legacy_units(value: object) -> str:
    normalized = str(value or "imperial").strip().lower()
    return normalized if normalized in {"imperial", "metric"} else "imperial"


def _legacy_location(value: object) -> WeatherLocationConfig | None:
    if not isinstance(value, Mapping):
        return None
    name = str(value.get("name") or "").strip()
    latitude = value.get("latitude")
    longitude = value.get("longitude")
    if not name and (latitude is None or longitude is None):
        return None
    try:
        parsed_latitude, parsed_longitude = _coordinates(latitude, longitude)
    except ValueError:
        return None
    return WeatherLocationConfig(
        id="legacy_home",
        label="Home",
        name=name or "Home",
        latitude=parsed_latitude,
        longitude=parsed_longitude,
        timezone=str(value.get("timezone") or "auto").strip() or "auto",
    )


def _coordinates(
    latitude: object,
    longitude: object,
) -> tuple[float | None, float | None]:
    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        raise ValueError("latitude and longitude must be supplied together")
    try:
        parsed_latitude = float(latitude)
        parsed_longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("latitude and longitude must be numbers") from exc
    if not -90 <= parsed_latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= parsed_longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    return parsed_latitude, parsed_longitude


def _parse_location(raw: object, index: int) -> WeatherLocationConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"locations[{index}] must be an object")
    location_id = str(raw.get("id") or "").strip().lower()
    label = str(raw.get("label") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not location_id:
        raise ValueError(f"locations[{index}].id must be a nonempty string")
    if not label:
        raise ValueError(f"locations[{index}].label must be a nonempty string")
    if not name:
        raise ValueError(f"locations[{index}].name must be a nonempty string")
    latitude, longitude = _coordinates(
        raw.get("latitude"),
        raw.get("longitude"),
    )
    timezone = str(raw.get("timezone") or "auto").strip() or "auto"
    return WeatherLocationConfig(
        id=location_id,
        label=label,
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
    )


def _parse_alerts(raw: object, issues: list[str]) -> WeatherAlertsConfig:
    if raw is None:
        return WeatherAlertsConfig()
    if not isinstance(raw, Mapping):
        issues.append("alerts must be an object; official alerts are disabled")
        return WeatherAlertsConfig()
    enabled = raw.get("enabled", False)
    announce = raw.get("announce_warnings", False)
    provider = str(raw.get("provider") or "nws").strip().lower()
    if not isinstance(enabled, bool):
        issues.append(
            "alerts.enabled must be true or false; official alerts are disabled"
        )
        enabled = False
    if not isinstance(announce, bool):
        issues.append("alerts.announce_warnings must be true or false; using false")
        announce = False
    if provider != "nws":
        issues.append("alerts.provider must be 'nws'; official alerts are disabled")
        enabled = False
        provider = "nws"
    return WeatherAlertsConfig(enabled, provider, announce)


def _fallback_config(
    *,
    legacy_location: object,
    legacy_units: object,
    issues: Sequence[str] = (),
    source_path: Path | None = None,
) -> WeatherFeatureConfig:
    location = _legacy_location(legacy_location)
    locations = (location,) if location is not None else ()
    return WeatherFeatureConfig(
        units=_legacy_units(legacy_units),
        default_location_id=location.id if location is not None else None,
        locations=locations,
        issues=tuple(issues),
        source_path=source_path,
    )


def load_weather_config(
    path: str | Path | None,
    *,
    legacy_location: object = None,
    legacy_units: object = "imperial",
) -> WeatherFeatureConfig:
    """Load private weather settings without exposing their configured values."""
    if path is None:
        return _fallback_config(
            legacy_location=legacy_location,
            legacy_units=legacy_units,
        )

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return _fallback_config(
            legacy_location=legacy_location,
            legacy_units=legacy_units,
            source_path=config_path,
        )
    except (OSError, json.JSONDecodeError) as exc:
        return _fallback_config(
            legacy_location=legacy_location,
            legacy_units=legacy_units,
            issues=(f"could not read weather configuration: {type(exc).__name__}",),
            source_path=config_path,
        )

    if not isinstance(raw, Mapping):
        return _fallback_config(
            legacy_location=legacy_location,
            legacy_units=legacy_units,
            issues=("weather configuration root must be an object",),
            source_path=config_path,
        )

    issues: list[str] = []
    units = str(raw.get("units") or _legacy_units(legacy_units)).strip().lower()
    if units not in {"imperial", "metric"}:
        issues.append("units must be 'imperial' or 'metric'; using legacy units")
        units = _legacy_units(legacy_units)

    season_style = str(raw.get("season_style") or "auto").strip().lower()
    if season_style not in {"auto", "off"}:
        issues.append("season_style must be 'auto' or 'off'; using auto")
        season_style = "auto"

    animations = raw.get("animations", True)
    if not isinstance(animations, bool):
        issues.append("animations must be true or false; using true")
        animations = True

    debug = raw.get("debug", False)
    if not isinstance(debug, bool):
        issues.append("debug must be true or false; using false")
        debug = False

    locations: list[WeatherLocationConfig] = []
    seen_ids: set[str] = set()
    raw_locations = raw.get("locations", [])
    if not isinstance(raw_locations, Sequence) or isinstance(
        raw_locations,
        (str, bytes),
    ):
        issues.append("locations must be a list")
        raw_locations = []
    for index, raw_location in enumerate(raw_locations):
        try:
            location = _parse_location(raw_location, index)
            if location.id in seen_ids:
                raise ValueError(f"locations[{index}].id must be unique")
        except ValueError as exc:
            issues.append(str(exc))
            continue
        seen_ids.add(location.id)
        locations.append(location)

    default_id_raw = raw.get("default_location")
    default_id = (
        str(default_id_raw).strip().lower()
        if default_id_raw is not None
        else None
    )
    if not default_id:
        default_id = None
    if default_id and default_id not in seen_ids:
        issues.append("default_location must match a configured location id")
        default_id = None
    if default_id is None and locations:
        default_id = locations[0].id

    if not locations:
        legacy = _legacy_location(legacy_location)
        if legacy is not None:
            locations.append(legacy)
            default_id = legacy.id

    return WeatherFeatureConfig(
        units=units,
        default_location_id=default_id,
        season_style=season_style,
        animations=animations,
        debug=debug,
        alerts=_parse_alerts(raw.get("alerts"), issues),
        locations=tuple(locations),
        issues=tuple(issues),
        source_path=config_path,
    )
