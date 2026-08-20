"""Private configuration owned by the GalaxyRVR remote feature."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Any

from bmo.jsonio import load_json


DEFAULT_GALAXY_RVR_CONFIG_PATH = Path("config/galaxy_rvr.json")


@dataclass(frozen=True)
class GalaxyRVRConfig:
    """Validated network, controller, camera, and safety settings."""

    host: str = "192.168.4.1"
    control_port: int = 30102
    control_path: str = "/"
    camera_port: int = 9000
    photo_directory: Path = Path("~/Pictures/bmo/galaxy_rvr")
    controller_device: str = "auto"
    left_y_axis: int = 1
    right_x_axis: int = 4
    lt_axis: int = 2
    rt_axis: int = 5
    lt_axis_inverted: bool = False
    rt_axis_inverted: bool = True
    snap_button: int = 0
    deadzone: float = 0.12
    trigger_threshold: float = 0.2
    max_motor_power: int = 75
    steering_scale: float = 0.75
    servo_min_angle: int = 0
    servo_max_angle: int = 140
    servo_start_angle: int = 90
    servo_degrees_per_second: float = 55.0
    servo_up_increases_angle: bool = False
    command_rate_hz: int = 20
    reconnect_seconds: float = 2.0
    connect_timeout_seconds: float = 3.0
    snapshot_timeout_seconds: float = 5.0
    max_snapshot_bytes: int = 8_000_000
    preview_enabled: bool = True
    preview_fps: int = 10
    show_in_menu: bool = True

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.control_port}{self.control_path}"

    @property
    def capture_url(self) -> str:
        return f"http://{self.host}:{self.camera_port}/capture"


def _integer(
    values: Mapping[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"GalaxyRVR {key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"GalaxyRVR {key} must be between {minimum} and {maximum}"
        )
    return value


def _number(
    values: Mapping[str, Any],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"GalaxyRVR {key} must be a number")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(
            f"GalaxyRVR {key} must be between {minimum} and {maximum}"
        )
    return parsed


def _boolean(values: Mapping[str, Any], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"GalaxyRVR {key} must be true or false")
    return value


def _parse(values: Mapping[str, Any]) -> GalaxyRVRConfig:
    defaults = GalaxyRVRConfig()
    allowed = set(defaults.__dataclass_fields__)
    unknown = set(values).difference(allowed)
    if unknown:
        raise ValueError(
            "unknown GalaxyRVR setting(s): " + ", ".join(sorted(unknown))
        )

    host_value = values.get("host", defaults.host)
    if not isinstance(host_value, str) or not host_value.strip():
        raise TypeError("GalaxyRVR host must be a non-empty IPv4 address")
    try:
        host = ip_address(host_value.strip())
    except ValueError as exc:
        raise ValueError("GalaxyRVR host must be an IPv4 address") from exc
    if not isinstance(host, IPv4Address):
        raise ValueError("GalaxyRVR host must be an IPv4 address")
    if host.is_unspecified or host.is_multicast:
        raise ValueError("GalaxyRVR host must identify one local device")
    if not (host.is_private or host.is_link_local or host.is_loopback):
        raise ValueError("GalaxyRVR host must be a local-network IPv4 address")

    control_path = values.get("control_path", defaults.control_path)
    if (
        not isinstance(control_path, str)
        or not control_path.startswith("/")
        or any(character in control_path for character in "\r\n?#")
    ):
        raise ValueError("GalaxyRVR control_path must be an absolute URL path")

    photo_directory = values.get(
        "photo_directory",
        str(defaults.photo_directory),
    )
    if not isinstance(photo_directory, str) or not photo_directory.strip():
        raise TypeError("GalaxyRVR photo_directory must be a non-empty path")

    controller_device = values.get(
        "controller_device",
        defaults.controller_device,
    )
    if not isinstance(controller_device, str) or not controller_device.strip():
        raise TypeError("GalaxyRVR controller_device must be a non-empty string")
    controller_device = controller_device.strip()
    if controller_device != "auto" and not controller_device.startswith(
        "/dev/input/js"
    ):
        raise ValueError(
            "GalaxyRVR controller_device must be 'auto' or /dev/input/jsN"
        )

    servo_min = _integer(values, "servo_min_angle", defaults.servo_min_angle, 0, 140)
    servo_max = _integer(values, "servo_max_angle", defaults.servo_max_angle, 0, 140)
    if servo_min >= servo_max:
        raise ValueError("GalaxyRVR servo_min_angle must be below servo_max_angle")
    servo_start = _integer(
        values,
        "servo_start_angle",
        defaults.servo_start_angle,
        servo_min,
        servo_max,
    )

    return GalaxyRVRConfig(
        host=str(host),
        control_port=_integer(values, "control_port", defaults.control_port, 1, 65535),
        control_path=control_path,
        camera_port=_integer(values, "camera_port", defaults.camera_port, 1, 65535),
        photo_directory=Path(photo_directory).expanduser(),
        controller_device=controller_device,
        left_y_axis=_integer(values, "left_y_axis", defaults.left_y_axis, 0, 31),
        right_x_axis=_integer(values, "right_x_axis", defaults.right_x_axis, 0, 31),
        lt_axis=_integer(values, "lt_axis", defaults.lt_axis, 0, 31),
        rt_axis=_integer(values, "rt_axis", defaults.rt_axis, 0, 31),
        lt_axis_inverted=_boolean(
            values,
            "lt_axis_inverted",
            defaults.lt_axis_inverted,
        ),
        rt_axis_inverted=_boolean(
            values,
            "rt_axis_inverted",
            defaults.rt_axis_inverted,
        ),
        snap_button=_integer(values, "snap_button", defaults.snap_button, 0, 63),
        deadzone=_number(values, "deadzone", defaults.deadzone, 0.0, 0.5),
        trigger_threshold=_number(
            values,
            "trigger_threshold",
            defaults.trigger_threshold,
            -0.9,
            0.9,
        ),
        max_motor_power=_integer(
            values,
            "max_motor_power",
            defaults.max_motor_power,
            1,
            100,
        ),
        steering_scale=_number(
            values,
            "steering_scale",
            defaults.steering_scale,
            0.0,
            1.0,
        ),
        servo_min_angle=servo_min,
        servo_max_angle=servo_max,
        servo_start_angle=servo_start,
        servo_degrees_per_second=_number(
            values,
            "servo_degrees_per_second",
            defaults.servo_degrees_per_second,
            1.0,
            180.0,
        ),
        servo_up_increases_angle=_boolean(
            values,
            "servo_up_increases_angle",
            defaults.servo_up_increases_angle,
        ),
        command_rate_hz=_integer(
            values,
            "command_rate_hz",
            defaults.command_rate_hz,
            5,
            50,
        ),
        reconnect_seconds=_number(
            values,
            "reconnect_seconds",
            defaults.reconnect_seconds,
            0.25,
            30.0,
        ),
        connect_timeout_seconds=_number(
            values,
            "connect_timeout_seconds",
            defaults.connect_timeout_seconds,
            0.25,
            15.0,
        ),
        snapshot_timeout_seconds=_number(
            values,
            "snapshot_timeout_seconds",
            defaults.snapshot_timeout_seconds,
            0.25,
            30.0,
        ),
        max_snapshot_bytes=_integer(
            values,
            "max_snapshot_bytes",
            defaults.max_snapshot_bytes,
            100_000,
            50_000_000,
        ),
        preview_enabled=_boolean(
            values,
            "preview_enabled",
            defaults.preview_enabled,
        ),
        preview_fps=_integer(
            values,
            "preview_fps",
            defaults.preview_fps,
            1,
            10,
        ),
        show_in_menu=_boolean(
            values,
            "show_in_menu",
            defaults.show_in_menu,
        ),
    )


def load_galaxy_rvr_config(
    settings: Mapping[str, Any],
    *,
    reporter=print,
) -> GalaxyRVRConfig:
    """Load the private JSON file and apply feature-owned entry overrides."""
    raw_path = settings.get("config_path", DEFAULT_GALAXY_RVR_CONFIG_PATH)
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        reporter("[GALAXY RVR] Invalid config_path. Using defaults.")
        return GalaxyRVRConfig()
    path = Path(raw_path).expanduser()
    file_values: Mapping[str, Any] = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                loaded = load_json(handle)
            if not isinstance(loaded, Mapping):
                raise ValueError("configuration root must be an object")
            file_values = loaded
        except (OSError, ValueError) as exc:
            reporter(
                f"[GALAXY RVR] Could not load configuration: "
                f"{type(exc).__name__}. Using defaults."
            )
            return GalaxyRVRConfig()

    owned_keys = set(GalaxyRVRConfig.__dataclass_fields__)
    overrides = {
        key: value for key, value in settings.items() if key in owned_keys
    }
    try:
        return _parse({**file_values, **overrides})
    except (TypeError, ValueError) as exc:
        reporter(f"[GALAXY RVR] Invalid settings: {exc}. Using defaults.")
        return GalaxyRVRConfig()


__all__ = [
    "DEFAULT_GALAXY_RVR_CONFIG_PATH",
    "GalaxyRVRConfig",
    "load_galaxy_rvr_config",
]
