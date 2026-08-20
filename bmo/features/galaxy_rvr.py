"""Menu-only Bluetooth-controller remote for a SunFounder GalaxyRVR."""

from __future__ import annotations

import base64
import errno
import glob
import hashlib
import os
import select
import socket
import struct
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from bmo.features.contracts import (
    DirectAction,
    FeatureMenuContext,
    FeatureMenuItem,
    ToolRequest,
    ToolResult,
)
from bmo.features.galaxy_rvr_config import (
    GalaxyRVRConfig,
    load_galaxy_rvr_config,
)
from bmo.view_factory import NOT_HOSTED, create_hosted_view


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GALAXY_RVR_MENU_ITEM = FeatureMenuItem(
    name="galaxy_rvr",
    label="GalaxyRVR Remote",
    icon_path=PROJECT_ROOT / "graphics" / "icons" / "rc_remote.png",
)
GalaxyRVRAppFactory = Callable[..., Any]
StatusCallback = Callable[["GalaxyRVRStatus"], None]


def _create_galaxy_rvr_app(*args: Any, **kwargs: Any) -> Any:
    hosted = create_hosted_view("galaxy_rvr", args, kwargs)
    if hosted is not NOT_HOSTED:
        return hosted
    from bmo.ui.galaxy_rvr import GalaxyRVRApp

    return GalaxyRVRApp(*args, **kwargs)


class WebSocketError(ConnectionError):
    """Raised when the rover's WebSocket handshake or framing fails."""


class WebSocketTransport:
    """Small RFC 6455 binary client sufficient for the rover LAN protocol."""

    def __init__(self, config: GalaxyRVRConfig) -> None:
        self.config = config
        self.socket: socket.socket | None = None
        self._receive_buffer = bytearray()

    def connect(self) -> None:
        self.close()
        connection = socket.create_connection(
            (self.config.host, self.config.control_port),
            timeout=self.config.connect_timeout_seconds,
        )
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET {self.config.control_path} HTTP/1.1\r\n"
                f"Host: {self.config.host}:{self.config.control_port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            connection.sendall(request)
            response = bytearray()
            while b"\r\n\r\n" not in response:
                chunk = connection.recv(4096)
                if not chunk:
                    raise WebSocketError("The rover closed the handshake.")
                response.extend(chunk)
                if len(response) > 16_384:
                    raise WebSocketError("The rover returned an oversized handshake.")
            header, remainder = response.split(b"\r\n\r\n", 1)
            lines = header.decode("latin-1").split("\r\n")
            if not lines or " 101 " not in f" {lines[0]} ":
                raise WebSocketError("The rover did not accept the WebSocket.")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().casefold()] = value.strip()
            expected = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(
                        "ascii"
                    )
                ).digest()
            ).decode("ascii")
            if headers.get("sec-websocket-accept") != expected:
                raise WebSocketError("The rover returned an invalid WebSocket key.")
            connection.setblocking(False)
            self.socket = connection
            self._receive_buffer = bytearray(remainder)
        except BaseException:
            connection.close()
            raise

    @property
    def connected(self) -> bool:
        return self.socket is not None

    def send_binary(self, payload: bytes) -> None:
        self._send_frame(0x2, payload)

    def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        connection = self.socket
        if connection is None:
            raise WebSocketError("The rover WebSocket is not connected.")
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack(
                "!H", length
            )
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack(
                "!Q", length
            )
        mask = os.urandom(4)
        masked = bytes(
            value ^ mask[index % 4] for index, value in enumerate(payload)
        )
        try:
            connection.sendall(header + mask + masked)
        except (OSError, TimeoutError) as exc:
            self.close()
            raise WebSocketError("The rover connection was lost.") from exc

    def poll(self) -> None:
        """Drain telemetry, answer pings, and detect a closed connection."""
        connection = self.socket
        if connection is None:
            raise WebSocketError("The rover WebSocket is not connected.")
        while True:
            try:
                readable, _, _ = select.select([connection], [], [], 0)
                if not readable:
                    break
                chunk = connection.recv(4096)
            except BlockingIOError:
                break
            except OSError as exc:
                self.close()
                raise WebSocketError("The rover connection was lost.") from exc
            if not chunk:
                self.close()
                raise WebSocketError("The rover connection was closed.")
            self._receive_buffer.extend(chunk)
        self._consume_frames()

    def _consume_frames(self) -> None:
        buffer = self._receive_buffer
        while len(buffer) >= 2:
            first, second = buffer[0], buffer[1]
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            offset = 2
            if length == 126:
                if len(buffer) < 4:
                    return
                length = struct.unpack("!H", buffer[2:4])[0]
                offset = 4
            elif length == 127:
                if len(buffer) < 10:
                    return
                length = struct.unpack("!Q", buffer[2:10])[0]
                offset = 10
            if length > 1_000_000:
                self.close()
                raise WebSocketError("The rover returned an oversized frame.")
            mask = b""
            if masked:
                if len(buffer) < offset + 4:
                    return
                mask = bytes(buffer[offset : offset + 4])
                offset += 4
            if len(buffer) < offset + length:
                return
            payload = bytes(buffer[offset : offset + length])
            del buffer[: offset + length]
            if masked:
                payload = bytes(
                    value ^ mask[index % 4]
                    for index, value in enumerate(payload)
                )
            if opcode == 0x8:
                self.close()
                raise WebSocketError("The rover ended the control session.")
            if opcode == 0x9:
                self._send_frame(0xA, payload)

    def close(self) -> None:
        connection, self.socket = self.socket, None
        self._receive_buffer.clear()
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


class LinuxJoystick:
    """Read the dependency-free Linux joystick character-device API."""

    EVENT = struct.Struct("<IhBB")
    BUTTON = 0x01
    AXIS = 0x02
    INITIAL = 0x80
    def __init__(self, configured_path: str) -> None:
        self.configured_path = configured_path
        self.path: str | None = None
        self.file_descriptor: int | None = None
        self.axes: dict[int, float] = {}
        self.buttons: dict[int, bool] = {}

    def open(self) -> None:
        self.close()
        candidates = (
            sorted(glob.glob("/dev/input/js*"))
            if self.configured_path == "auto"
            else [self.configured_path]
        )
        if not candidates:
            raise FileNotFoundError("No Bluetooth controller was found.")
        last_error: OSError | None = None
        for candidate in candidates:
            try:
                descriptor = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as exc:
                last_error = exc
                continue
            self.file_descriptor = descriptor
            self.path = candidate
            return
        if last_error is not None:
            raise last_error
        raise FileNotFoundError("No Bluetooth controller was found.")

    def read_events(self) -> tuple[tuple[str, int, float | bool], ...]:
        descriptor = self.file_descriptor
        if descriptor is None:
            raise OSError(errno.ENODEV, "Controller is not open")
        events: list[tuple[str, int, float | bool]] = []
        while True:
            try:
                data = os.read(descriptor, self.EVENT.size)
            except BlockingIOError:
                break
            if not data:
                raise OSError(errno.ENODEV, "Controller disconnected")
            if len(data) != self.EVENT.size:
                continue
            _, raw_value, event_type, number = self.EVENT.unpack(data)
            event_type &= ~self.INITIAL
            if event_type == self.AXIS:
                value = max(-1.0, min(1.0, raw_value / 32767.0))
                self.axes[number] = value
                events.append(("axis", number, value))
            elif event_type == self.BUTTON:
                pressed = bool(raw_value)
                self.buttons[number] = pressed
                events.append(("button", number, pressed))
        return tuple(events)

    def axis(self, number: int) -> float:
        return self.axes.get(number, 0.0)

    def close(self) -> None:
        descriptor, self.file_descriptor = self.file_descriptor, None
        self.path = None
        self.axes.clear()
        self.buttons.clear()
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass(frozen=True)
class GalaxyRVRStatus:
    """Immutable status safe to pass from the control worker to either UI."""

    rover_connected: bool = False
    controller_connected: bool = False
    controller_path: str = ""
    state: str = "Starting remote..."
    error: str = ""
    left_power: int = 0
    right_power: int = 0
    servo_angle: int = 90
    taking_photo: bool = False
    last_photo: str = ""
    axis_summary: str = ""

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def apply_deadzone(value: float, deadzone: float) -> float:
    """Remove a center deadzone while preserving the remaining full range."""
    if abs(value) <= deadzone:
        return 0.0
    magnitude = (abs(value) - deadzone) / (1.0 - deadzone)
    return (-1.0 if value < 0 else 1.0) * magnitude


def mix_drive(
    left_y: float,
    right_x: float,
    *,
    deadzone: float,
    max_power: int,
    steering_scale: float,
) -> tuple[int, int]:
    """Map separate throttle and steering sticks to differential motors."""
    throttle = -apply_deadzone(left_y, deadzone)
    steering = apply_deadzone(right_x, deadzone) * steering_scale
    left = max(-1.0, min(1.0, throttle + steering))
    right = max(-1.0, min(1.0, throttle - steering))
    return round(left * max_power), round(right * max_power)


def motor_servo_frame(left: int, right: int, servo_angle: int) -> bytes:
    """Build a checked binary packet consumed by GalaxyRVR firmware 2.x."""
    for value in (left, right):
        if not -100 <= value <= 100:
            raise ValueError("GalaxyRVR motor power must be between -100 and 100")
    if not 0 <= servo_angle <= 140:
        raise ValueError("GalaxyRVR servo angle must be between 0 and 140")
    entities = bytes((0x01, left & 0xFF, right & 0xFF, 0x03, servo_angle))
    checksum = 0
    for value in entities:
        checksum ^= value
    return bytes((0xA0, len(entities), checksum)) + entities + bytes((0xA1,))


def next_servo_angle(
    current_angle: int,
    lt_value: float,
    rt_value: float,
    elapsed_seconds: float,
    config: GalaxyRVRConfig,
    *,
    lt_rest_value: float | None = None,
    rt_rest_value: float | None = None,
) -> int:
    """Move camera tilt from LT/RT while enforcing configured hard limits."""
    lt_pressed = (
        abs(lt_value - lt_rest_value) > config.trigger_threshold
        if lt_rest_value is not None
        else (
            lt_value < -config.trigger_threshold
            if config.lt_axis_inverted
            else lt_value > config.trigger_threshold
        )
    )
    rt_pressed = (
        abs(rt_value - rt_rest_value) > config.trigger_threshold
        if rt_rest_value is not None
        else (
            rt_value < -config.trigger_threshold
            if config.rt_axis_inverted
            else rt_value > config.trigger_threshold
        )
    )
    direction = int(lt_pressed) - int(rt_pressed)
    if not config.servo_up_increases_angle:
        direction *= -1
    angle = round(
        current_angle
        + direction * config.servo_degrees_per_second * elapsed_seconds
    )
    return max(config.servo_min_angle, min(config.servo_max_angle, angle))


def save_snapshot(config: GalaxyRVRConfig) -> Path:
    """Download one camera JPEG and atomically persist it to the photo folder."""
    request = Request(
        config.capture_url,
        headers={"User-Agent": "BMO-GalaxyRVR/1"},
        method="GET",
    )
    with urlopen(request, timeout=config.snapshot_timeout_seconds) as response:
        content_type = response.headers.get_content_type()
        if content_type != "image/jpeg":
            raise ValueError("The rover camera did not return a JPEG image.")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(65_536, config.max_snapshot_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > config.max_snapshot_bytes:
                raise ValueError("The rover camera image was too large.")
    image = b"".join(chunks)
    if len(image) < 4 or not image.startswith(b"\xff\xd8") or not image.endswith(
        b"\xff\xd9"
    ):
        raise ValueError("The rover camera returned an invalid JPEG image.")

    directory = config.photo_directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = directory / f"galaxy-rvr-{stamp}.jpg"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".galaxy-rvr-",
        suffix=".tmp",
        dir=directory,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(image)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


class GalaxyRVRSession:
    """Own controller polling, LAN control, snapshots, and safe shutdown."""

    def __init__(
        self,
        config: GalaxyRVRConfig,
        on_status: StatusCallback,
        *,
        transport_factory: Callable[[GalaxyRVRConfig], Any] = WebSocketTransport,
        joystick_factory: Callable[[str], Any] = LinuxJoystick,
        snapshot_saver: Callable[[GalaxyRVRConfig], Path] = save_snapshot,
    ) -> None:
        if not callable(on_status):
            raise TypeError("GalaxyRVR status callback must be callable.")
        self.config = config
        self.on_status = on_status
        self.transport_factory = transport_factory
        self.joystick_factory = joystick_factory
        self.snapshot_saver = snapshot_saver
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._photo_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = GalaxyRVRStatus(servo_angle=config.servo_start_angle)
        self._last_snap_pressed = False

    @property
    def status(self) -> GalaxyRVRStatus:
        with self._lock:
            return self._status

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="galaxy-rvr-control",
            daemon=True,
        )
        self._thread.start()

    def _publish(self, **changes: Any) -> None:
        with self._lock:
            self._status = replace(self._status, **changes)
            status = self._status
        self.on_status(status)

    def _run(self) -> None:
        transport: Any | None = None
        joystick: Any | None = None
        next_connect = 0.0
        next_controller = 0.0
        left_y_axis = self.config.left_y_axis
        right_x_axis = self.config.right_x_axis
        lt_axis = self.config.lt_axis
        rt_axis = self.config.rt_axis
        trigger_rest: dict[str, float] = {}
        last_tick = time.monotonic()
        interval = 1.0 / self.config.command_rate_hz
        self._publish(state="Waiting for rover and controller...")
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if transport is None and now >= next_connect:
                    candidate = self.transport_factory(self.config)
                    try:
                        candidate.connect()
                        transport = candidate
                        self._publish(
                            rover_connected=True,
                            state=(
                                "Rover connected; waiting for controller..."
                                if joystick is None
                                else "Ready to drive."
                            ),
                            error="",
                        )
                    except (OSError, ConnectionError, TimeoutError) as exc:
                        candidate.close()
                        next_connect = now + self.config.reconnect_seconds
                        self._publish(
                            rover_connected=False,
                            state="Waiting for GalaxyRVR...",
                            error=str(exc) or type(exc).__name__,
                        )

                if joystick is None and now >= next_controller:
                    candidate = self.joystick_factory(
                        self.config.controller_device
                    )
                    try:
                        candidate.open()
                        joystick = candidate
                        trigger_rest.clear()
                        self._publish(
                            controller_connected=True,
                            controller_path=str(candidate.path or "controller"),
                            state=(
                                "Ready to drive."
                                if transport is not None
                                else "Controller ready; waiting for rover..."
                            ),
                            error="",
                        )
                    except OSError as exc:
                        candidate.close()
                        next_controller = now + self.config.reconnect_seconds
                        self._publish(
                            controller_connected=False,
                            controller_path="",
                            state="Waiting for Bluetooth controller...",
                            error=str(exc) or type(exc).__name__,
                        )

                if joystick is not None:
                    try:
                        events = joystick.read_events()
                    except OSError as exc:
                        joystick.close()
                        joystick = None
                        next_controller = now + self.config.reconnect_seconds
                        self._last_snap_pressed = False
                        trigger_rest.clear()
                        if transport is not None:
                            self._safe_stop(transport)
                        self._publish(
                            controller_connected=False,
                            controller_path="",
                            state="Controller disconnected; rover stopped.",
                            error=str(exc) or "Controller disconnected.",
                            left_power=0,
                            right_power=0,
                        )
                        events = ()
                    for event_kind, number, value in events:
                        if (
                            event_kind == "button"
                            and number == self.config.snap_button
                        ):
                            pressed = bool(value)
                            if pressed and not self._last_snap_pressed:
                                self.request_snapshot()
                            self._last_snap_pressed = pressed

                elapsed = max(0.0, min(0.25, now - last_tick))
                last_tick = now
                left = right = 0
                servo = self.status.servo_angle
                axis_summary = ""
                if joystick is not None:
                    left_y = joystick.axis(left_y_axis)
                    right_x = joystick.axis(right_x_axis)
                    lt_value = joystick.axis(lt_axis)
                    rt_value = joystick.axis(rt_axis)
                    trigger_rest.setdefault("lt", lt_value)
                    trigger_rest.setdefault("rt", rt_value)
                    left, right = mix_drive(
                        left_y,
                        right_x,
                        deadzone=self.config.deadzone,
                        max_power=self.config.max_motor_power,
                        steering_scale=self.config.steering_scale,
                    )
                    servo = next_servo_angle(
                        servo,
                        lt_value,
                        rt_value,
                        elapsed,
                        self.config,
                        lt_rest_value=trigger_rest["lt"],
                        rt_rest_value=trigger_rest["rt"],
                    )
                    axis_summary = (
                        f"LY{left_y_axis} {left_y:+.2f}  "
                        f"RX{right_x_axis} {right_x:+.2f}  "
                        f"LT{lt_axis} {lt_value:+.2f}  "
                        f"RT{rt_axis} {rt_value:+.2f}"
                    )

                if transport is not None:
                    try:
                        transport.send_binary(motor_servo_frame(left, right, servo))
                        transport.poll()
                    except (OSError, ConnectionError, TimeoutError) as exc:
                        transport.close()
                        transport = None
                        next_connect = now + self.config.reconnect_seconds
                        left = right = 0
                        self._publish(
                            rover_connected=False,
                            state="Rover disconnected; reconnecting...",
                            error=str(exc) or type(exc).__name__,
                            left_power=0,
                            right_power=0,
                            servo_angle=servo,
                            axis_summary=axis_summary,
                        )
                    else:
                        self._publish(
                            state=(
                                "Rover connected; waiting for controller..."
                                if joystick is None
                                else "Ready to drive."
                            ),
                            error="",
                            left_power=left,
                            right_power=right,
                            servo_angle=servo,
                            axis_summary=axis_summary,
                        )
                self._stop.wait(interval)
        finally:
            if transport is not None:
                self._safe_stop(transport)
                transport.close()
            if joystick is not None:
                joystick.close()
            self._publish(
                rover_connected=False,
                controller_connected=False,
                controller_path="",
                state="Remote closed; rover stopped.",
                left_power=0,
                right_power=0,
                axis_summary="",
            )

    def _safe_stop(self, transport: Any) -> None:
        try:
            transport.send_binary(
                motor_servo_frame(0, 0, self.status.servo_angle)
            )
        except (OSError, ConnectionError, TimeoutError):
            pass

    def request_snapshot(self) -> bool:
        with self._lock:
            if self._status.taking_photo or self._stop.is_set():
                return False
            self._status = replace(
                self._status,
                taking_photo=True,
                state="Saving rover photo...",
                error="",
            )
            status = self._status
        self.on_status(status)
        self._photo_thread = threading.Thread(
            target=self._save_snapshot,
            name="galaxy-rvr-snapshot",
            daemon=True,
        )
        self._photo_thread.start()
        return True

    def _save_snapshot(self) -> None:
        try:
            destination = self.snapshot_saver(self.config)
        except (OSError, ValueError, TimeoutError) as exc:
            self._publish(
                taking_photo=False,
                state="Photo failed; driving is still available.",
                error=str(exc) or type(exc).__name__,
            )
        else:
            self._publish(
                taking_photo=False,
                state=f"Saved {destination.name}",
                error="",
                last_photo=str(destination),
            )

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self.config.connect_timeout_seconds + 1.0)


class GalaxyRVRTool:
    """Register the remote as a menu-only feature with isolated resources."""

    action = "galaxy_rvr"
    aliases: tuple[str, ...] = ()
    menu_only = True
    description = ""
    schemas: tuple[str, ...] = ()
    prompt_guidance: tuple[str, ...] = ()
    prompt_examples: tuple[tuple[str, str], ...] = ()

    def __init__(
        self,
        config: GalaxyRVRConfig,
        *,
        app_factory: GalaxyRVRAppFactory = _create_galaxy_rvr_app,
        session_factory: Callable[..., GalaxyRVRSession] = GalaxyRVRSession,
        menu_item: FeatureMenuItem = GALAXY_RVR_MENU_ITEM,
    ) -> None:
        self.config = config
        self._app_factory = app_factory
        self._session_factory = session_factory
        self.menu_item = menu_item
        self._menu_ui: Any | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        del request
        return ToolResult.invalid_action()

    def match_direct_action(self, user_text: str) -> DirectAction | None:
        del user_text
        return None

    def open_menu(self, context: FeatureMenuContext) -> None:
        if self._menu_ui is not None:
            return

        def handle_close() -> None:
            self._menu_ui = None
            context.on_close()

        def make_session(callback: StatusCallback) -> GalaxyRVRSession:
            return self._session_factory(self.config, callback)

        try:
            self._menu_ui = self._app_factory(
                context.master,
                config=self.config,
                session_factory=make_session,
                face_provider=context.current_face,
                on_close=handle_close,
            )
        except Exception:
            self._menu_ui = None
            context.on_close()
            raise

    def close(self) -> None:
        menu_ui = self._menu_ui
        if menu_ui is not None:
            menu_ui.close()


def register(registry: Any, settings: Mapping[str, Any]) -> None:
    """Register the configured GalaxyRVR remote when its menu is enabled."""
    config = load_galaxy_rvr_config(settings)
    if config.show_in_menu:
        registry.register(GalaxyRVRTool(config))


def register_menu_metadata(registry: Any, settings: Mapping[str, Any]) -> None:
    """Contribute only resource-free icon metadata for menu construction."""
    config = load_galaxy_rvr_config(settings)
    if config.show_in_menu:
        registry.register(GALAXY_RVR_MENU_ITEM)


__all__ = [
    "GALAXY_RVR_MENU_ITEM",
    "GalaxyRVRSession",
    "GalaxyRVRStatus",
    "GalaxyRVRTool",
    "LinuxJoystick",
    "WebSocketError",
    "WebSocketTransport",
    "apply_deadzone",
    "mix_drive",
    "motor_servo_frame",
    "next_servo_angle",
    "register",
    "register_menu_metadata",
    "save_snapshot",
]
