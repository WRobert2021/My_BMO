"""GalaxyRVR configuration, protocol, controller, and lifecycle tests."""

from __future__ import annotations

import errno
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bmo.features import FeatureMenuContext, load_feature_registry
from bmo.features.galaxy_rvr import (
    GALAXY_RVR_MENU_ITEM,
    GalaxyRVRSession,
    GalaxyRVRTool,
    LinuxJoystick,
    WebSocketTransport,
    apply_deadzone,
    mix_drive,
    motor_servo_frame,
    next_servo_angle,
    save_snapshot,
)
from bmo.features.galaxy_rvr_config import (
    GalaxyRVRConfig,
    load_galaxy_rvr_config,
)
from bmo.menu_loader import load_menu_catalog
from bmo.prompts import build_routing_prompt, build_system_prompt


JPEG = b"\xff\xd8test-jpeg\xff\xd9"


class GalaxyRVRConfigTests(unittest.TestCase):
    def test_defaults_match_observed_bluetooth_controller_layout(self) -> None:
        config = GalaxyRVRConfig()

        self.assertEqual(config.left_y_axis, 1)
        self.assertEqual(config.right_x_axis, 4)
        self.assertEqual(config.lt_axis, 2)
        self.assertEqual(config.rt_axis, 5)
        self.assertFalse(config.lt_axis_inverted)
        self.assertTrue(config.rt_axis_inverted)
        self.assertEqual(config.preview_fps, 10)

    def test_private_config_loads_network_photos_mapping_and_safety_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "galaxy_rvr.json"
            photo_path = root / "rover photos"
            config_path.write_text(
                json.dumps(
                    {
                        "host": "192.168.50.42",
                        "photo_directory": str(photo_path),
                        "max_motor_power": 60,
                        "right_x_axis": 2,
                        "preview_fps": 3,
                    }
                ),
                encoding="utf-8",
            )

            config = load_galaxy_rvr_config(
                {
                    "config_path": str(config_path),
                    "max_motor_power": 65,
                }
            )

        self.assertEqual(config.host, "192.168.50.42")
        self.assertEqual(config.photo_directory, photo_path)
        self.assertEqual(config.max_motor_power, 65)
        self.assertEqual(config.right_x_axis, 2)
        self.assertEqual(config.preview_fps, 3)
        self.assertEqual(config.websocket_url, "ws://192.168.50.42:30102/")
        self.assertEqual(
            config.capture_url,
            "http://192.168.50.42:9000/capture",
        )

    def test_nonlocal_address_and_unknown_settings_fall_back_safely(self) -> None:
        messages: list[str] = []

        config = load_galaxy_rvr_config(
            {"host": "8.8.8.8", "surprise": True},
            reporter=messages.append,
        )

        self.assertEqual(config, GalaxyRVRConfig())
        self.assertEqual(len(messages), 1)
        self.assertIn("local-network", messages[0])

    def test_servo_limits_and_controller_device_are_validated(self) -> None:
        messages: list[str] = []

        config = load_galaxy_rvr_config(
            {
                "servo_min_angle": 120,
                "servo_max_angle": 20,
                "controller_device": "/tmp/not-a-joystick",
            },
            reporter=messages.append,
        )

        self.assertEqual(config, GalaxyRVRConfig())
        self.assertTrue(messages)


class GalaxyRVRProtocolTests(unittest.TestCase):
    def test_deadzone_and_drive_mixing_match_requested_sticks(self) -> None:
        self.assertEqual(apply_deadzone(0.1, 0.12), 0.0)
        self.assertEqual(
            mix_drive(
                -1.0,
                0.0,
                deadzone=0.12,
                max_power=75,
                steering_scale=0.75,
            ),
            (75, 75),
        )
        self.assertEqual(
            mix_drive(
                1.0,
                0.0,
                deadzone=0.12,
                max_power=75,
                steering_scale=0.75,
            ),
            (-75, -75),
        )
        left, right = mix_drive(
            0.0,
            1.0,
            deadzone=0.12,
            max_power=80,
            steering_scale=0.5,
        )
        self.assertGreater(left, 0)
        self.assertLess(right, 0)

    def test_binary_packet_wraps_signed_motor_entities_for_firmware_parser(
        self,
    ) -> None:
        frame = motor_servo_frame(75, -40, 90)

        self.assertEqual(frame[0], 0xA0)
        self.assertEqual(frame[1], 5)
        self.assertEqual(frame[3:-1], bytes((0x01, 75, 216, 0x03, 90)))
        self.assertEqual(frame[2], 0x01 ^ 75 ^ 216 ^ 0x03 ^ 90)
        self.assertEqual(frame[-1], 0xA1)
        with self.assertRaises(ValueError):
            motor_servo_frame(101, 0, 90)

    def test_lt_and_rt_move_camera_in_opposite_bounded_directions(self) -> None:
        config = GalaxyRVRConfig()

        resting = {"lt_rest_value": -1.0, "rt_rest_value": 1.0}
        self.assertEqual(
            next_servo_angle(90, 1.0, 1.0, 1.0, config, **resting),
            35,
        )
        self.assertEqual(
            next_servo_angle(90, -1.0, -1.0, 1.0, config, **resting),
            140,
        )
        self.assertEqual(
            next_servo_angle(90, 1.0, -1.0, 1.0, config, **resting),
            90,
        )
        self.assertEqual(
            next_servo_angle(5, 1.0, 1.0, 1.0, config, **resting),
            0,
        )

    def test_linux_axis_map_resolves_physical_controls_by_semantics(self) -> None:
        joystick = LinuxJoystick("auto")
        joystick.axis_codes = {
            1: LinuxJoystick.ABS_Y,
            3: 0x04,
            4: LinuxJoystick.ABS_RX,
            5: LinuxJoystick.ABS_RZ,
        }

        self.assertEqual(
            joystick.axis_number((LinuxJoystick.ABS_RX,), fallback=3),
            4,
        )
        self.assertEqual(
            joystick.axis_number((LinuxJoystick.ABS_RZ,), fallback=4),
            5,
        )

    def test_websocket_client_masks_binary_frames(self) -> None:
        sent: list[bytes] = []
        fake_socket = SimpleNamespace(sendall=sent.append, close=Mock())
        transport = WebSocketTransport(GalaxyRVRConfig())
        transport.socket = fake_socket

        with patch("bmo.features.galaxy_rvr.os.urandom", return_value=b"mask"):
            transport.send_binary(b"\x01\x02\x03")

        frame = sent[0]
        self.assertEqual(frame[:2], bytes((0x82, 0x83)))
        self.assertEqual(frame[2:6], b"mask")
        decoded = bytes(
            value ^ b"mask"[index % 4]
            for index, value in enumerate(frame[6:])
        )
        self.assertEqual(decoded, b"\x01\x02\x03")


class GalaxyRVRSnapshotTests(unittest.TestCase):
    class Response:
        headers = SimpleNamespace(get_content_type=lambda: "image/jpeg")

        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int) -> bytes:
            del size
            payload, self.payload = self.payload, b""
            return payload

    def test_snapshot_is_saved_under_configured_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                GalaxyRVRConfig(),
                photo_directory=Path(directory) / "photos",
            )
            with patch(
                "bmo.features.galaxy_rvr.urlopen",
                return_value=self.Response(JPEG),
            ) as open_url:
                saved = save_snapshot(config)

            self.assertEqual(saved.parent, config.photo_directory.resolve())
            self.assertEqual(saved.read_bytes(), JPEG)
            self.assertEqual(list(saved.parent.glob("*.tmp")), [])
            self.assertEqual(open_url.call_args.args[0].full_url, config.capture_url)

    def test_invalid_camera_payload_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                GalaxyRVRConfig(),
                photo_directory=Path(directory) / "photos",
            )
            with patch(
                "bmo.features.galaxy_rvr.urlopen",
                return_value=self.Response(b"not a jpeg"),
            ):
                with self.assertRaisesRegex(ValueError, "invalid JPEG"):
                    save_snapshot(config)
            self.assertFalse(config.photo_directory.exists())


class GalaxyRVRSessionTests(unittest.TestCase):
    def test_semantic_axes_drive_steer_and_calibrate_inverted_rt(self) -> None:
        frames: list[bytes] = []
        statuses: list[object] = []
        controls_seen = threading.Event()

        class Transport:
            def __init__(self, _config) -> None:
                return None

            def connect(self) -> None:
                return None

            def send_binary(self, frame: bytes) -> None:
                frames.append(frame)

            def poll(self) -> None:
                return None

            def close(self) -> None:
                return None

        class Joystick:
            path = "/dev/input/js-test"

            def __init__(self, _path) -> None:
                self.read_count = 0

            def open(self) -> None:
                return None

            def axis_number(self, codes, fallback: int) -> int:
                del fallback
                return {
                    (LinuxJoystick.ABS_Y,): 6,
                    (LinuxJoystick.ABS_RX,): 7,
                    (LinuxJoystick.ABS_Z, LinuxJoystick.ABS_BRAKE): 8,
                    (LinuxJoystick.ABS_RZ, LinuxJoystick.ABS_GAS): 9,
                }[codes]

            def read_events(self):
                self.read_count += 1
                return ()

            def axis(self, number: int) -> float:
                if number == 7 and self.read_count == 2:
                    return 1.0
                if number == 8:
                    return -1.0
                if number == 9:
                    return -1.0 if self.read_count >= 3 else 1.0
                return 0.0

            def close(self) -> None:
                return None

        def status_changed(status) -> None:
            statuses.append(status)
            steered = any(frame[4] > 0 and frame[5] > 127 for frame in frames)
            if steered and status.servo_angle > 90:
                controls_seen.set()

        session = GalaxyRVRSession(
            replace(GalaxyRVRConfig(), command_rate_hz=50),
            status_changed,
            transport_factory=Transport,
            joystick_factory=Joystick,
        )
        session.start()

        self.assertTrue(controls_seen.wait(1.0))
        session.close()

        self.assertTrue(any("RX7" in status.axis_summary for status in statuses))
        self.assertTrue(any("RT9" in status.axis_summary for status in statuses))

    def test_controller_disconnect_and_close_send_motor_stop(self) -> None:
        frames: list[bytes] = []
        disconnected = threading.Event()

        class Transport:
            def __init__(self, _config) -> None:
                self.connected = False

            def connect(self) -> None:
                self.connected = True

            def send_binary(self, frame: bytes) -> None:
                frames.append(frame)

            def poll(self) -> None:
                return None

            def close(self) -> None:
                self.connected = False

        class Joystick:
            path = "/dev/input/js-test"

            def __init__(self, _path) -> None:
                self.read_count = 0

            def open(self) -> None:
                return None

            def read_events(self):
                self.read_count += 1
                if self.read_count > 18:
                    raise OSError(errno.ENODEV, "controller gone")
                return ()

            def axis(self, number: int) -> float:
                if number == 1 and self.read_count > 14:
                    return -1.0
                return 0.0

            def close(self) -> None:
                return None

        def status_changed(status) -> None:
            if status.state.startswith("Controller disconnected"):
                disconnected.set()

        config = replace(
            GalaxyRVRConfig(),
            command_rate_hz=50,
            reconnect_seconds=10.0,
            connect_timeout_seconds=0.25,
        )
        session = GalaxyRVRSession(
            config,
            status_changed,
            transport_factory=Transport,
            joystick_factory=Joystick,
        )
        session.start()

        self.assertTrue(disconnected.wait(1.0))
        session.close()

        motor_pairs = [(frame[4], frame[5]) for frame in frames]
        self.assertIn((75, 75), motor_pairs)
        self.assertEqual(motor_pairs[-1], (0, 0))
        self.assertFalse(session.status.rover_connected)
        self.assertFalse(session.status.controller_connected)

    def test_snapshot_requests_are_single_flight(self) -> None:
        release = threading.Event()
        saved = threading.Event()

        def saver(_config: GalaxyRVRConfig) -> Path:
            release.wait(1.0)
            saved.set()
            return Path("/tmp/photo.jpg")

        session = GalaxyRVRSession(
            GalaxyRVRConfig(),
            Mock(),
            snapshot_saver=saver,
        )

        self.assertTrue(session.request_snapshot())
        self.assertFalse(session.request_snapshot())
        release.set()
        self.assertTrue(saved.wait(1.0))


class GalaxyRVRFeatureTests(unittest.TestCase):
    def test_feature_is_menu_only_and_uses_requested_icon(self) -> None:
        config = {
            "features": [
                {
                    "module": "bmo.features.galaxy_rvr",
                    "settings": {"host": "192.168.4.1"},
                }
            ],
            "modes": [],
        }
        result = load_feature_registry(config)
        self.addCleanup(result.registry.close)
        catalog = load_menu_catalog(config)

        self.assertEqual(result.failures, ())
        self.assertEqual(result.registry.actions, set())
        self.assertEqual(
            tuple(item.name for item in result.registry.menu_items),
            ("galaxy_rvr",),
        )
        self.assertEqual(catalog.failures, ())
        self.assertEqual(catalog.catalog.items[0].name, "feature:galaxy_rvr")
        self.assertEqual(
            GALAXY_RVR_MENU_ITEM.icon_path.name,
            "rc_remote.png",
        )
        for prompt in (
            build_routing_prompt(result.registry),
            build_system_prompt({}, result.registry),
        ):
            self.assertNotIn("galaxy_rvr", prompt)

    def test_hidden_feature_registers_no_tool_or_menu_metadata(self) -> None:
        config = {
            "features": [
                {
                    "module": "bmo.features.galaxy_rvr",
                    "settings": {"show_in_menu": False},
                }
            ],
            "modes": [],
        }

        result = load_feature_registry(config)
        catalog = load_menu_catalog(config)

        self.assertEqual(result.registry.menu_items, ())
        self.assertEqual(catalog.catalog.items, ())

    def test_tool_closes_session_and_returns_to_originating_menu(self) -> None:
        app = Mock()
        app_factory = Mock(return_value=app)
        tool = GalaxyRVRTool(GalaxyRVRConfig(), app_factory=app_factory)
        on_close = Mock()
        context = FeatureMenuContext(master="HOST", on_close=on_close)

        tool.open_menu(context)
        close_callback = app_factory.call_args.kwargs["on_close"]
        close_callback()
        tool.close()

        on_close.assert_called_once_with()
        app.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
