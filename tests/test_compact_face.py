"""Shared compact-face configuration, rendering, and lifecycle tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from bmo.app import BotGUI
from bmo.ui.compact_face import (
    COMPACT_FACE_BOUNDS,
    CompactFace,
    CompactFaceConfig,
    CompactFaceState,
    load_compact_face_config,
    normalize_face_image,
)
from bmo.ui.weather import WeatherWebBridge


class CompactFaceConfigTests(unittest.TestCase):
    def test_default_layout_is_one_exact_top_right_108_by_65_viewport(self) -> None:
        config = CompactFaceConfig()

        self.assertEqual(config.bounds, (684, 5, 792, 70))
        self.assertEqual(COMPACT_FACE_BOUNDS, config.bounds)
        self.assertEqual(config.center, (738.0, 37.5))
        self.assertEqual(config.artwork_size, (105, 63))
        self.assertEqual(config.artwork_size[0] / config.artwork_size[1], 5 / 3)

    def test_missing_and_malformed_files_use_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = load_compact_face_config(
                root / "missing.json",
                project_root=root,
                reporter=Mock(),
            )
            malformed_path = root / "bad.json"
            malformed_path.write_text("not json", encoding="utf-8")
            reporter = Mock()

            malformed = load_compact_face_config(
                malformed_path,
                project_root=root,
                reporter=reporter,
            )

        self.assertEqual(missing, CompactFaceConfig())
        self.assertEqual(malformed, CompactFaceConfig())
        reporter.assert_called_once()

    def test_config_adds_state_and_discovers_frames_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "faces" / "celebrating"
            frames.mkdir(parents=True)
            for name in ("frame 10.png", "frame 02.PNG", "frame 01.png"):
                (frames / name).write_bytes(b"png")
            path = root / "compact.json"
            path.write_text(
                json.dumps(
                    {
                        "states": {
                            "celebrating": {
                                "directory": "faces/celebrating",
                                "frame_duration_ms": 90,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_compact_face_config(path, project_root=root)
            discovered = config.frame_paths("celebrating", project_root=root)

        self.assertIn("celebrating", config.states or {})
        self.assertEqual([item.name for item in discovered], [
            "frame 01.png",
            "frame 02.PNG",
            "frame 10.png",
        ])
        self.assertEqual(config.state_duration("celebrating"), 90)

    def test_outside_face_path_rejects_entire_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "compact.json"
            path.write_text(
                json.dumps(
                    {
                        "states": {
                            "idle": {
                                "directory": "../private",
                                "frame_duration_ms": 100,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            reporter = Mock()

            config = load_compact_face_config(
                path,
                project_root=root,
                reporter=reporter,
            )

        self.assertEqual(config, CompactFaceConfig())
        reporter.assert_called_once()

    def test_empty_or_missing_state_directory_returns_no_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "faces" / "idle").mkdir(parents=True)
            config = CompactFaceConfig()

            self.assertEqual(config.frame_paths("idle", project_root=root), ())
            self.assertEqual(config.frame_paths("not-configured", project_root=root), ())


class CompactFaceImageTests(unittest.TestCase):
    def test_normalization_letterboxes_without_changing_fixed_outer_size(self) -> None:
        source = Image.new("RGB", (500, 300), "red")

        normalized = normalize_face_image(source)

        self.assertEqual(normalized.size, (108, 65))
        self.assertEqual(normalized.getpixel((0, 0)), (104, 200, 187))
        self.assertEqual(normalized.getpixel((1, 1)), (255, 0, 0))
        self.assertEqual(normalized.getpixel((105, 63)), (255, 0, 0))

    def test_different_source_shapes_never_change_outer_dimensions(self) -> None:
        sizes = {
            normalize_face_image(Image.new("RGB", shape, "blue")).size
            for shape in ((800, 480), (20, 20), (300, 900))
        }

        self.assertEqual(sizes, {(108, 65)})

    def test_application_animation_loader_uses_configured_state_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            idle = root / "idle"
            celebrating = root / "celebrating"
            idle.mkdir()
            celebrating.mkdir()
            Image.new("RGB", (5, 3), "blue").save(idle / "idle.png")
            Image.new("RGB", (5, 3), "red").save(celebrating / "02.png")
            Image.new("RGB", (5, 3), "green").save(celebrating / "01.png")
            gui = BotGUI.__new__(BotGUI)
            gui.compact_face_config = CompactFaceConfig(
                states={
                    "idle": CompactFaceState(idle, 500),
                    "celebrating": CompactFaceState(celebrating, 80),
                }
            )
            gui.animations = {}

            with patch(
                "bmo.app.ImageTk.PhotoImage",
                side_effect=lambda image: image.getpixel((0, 0)),
            ):
                gui.load_animations()

        self.assertEqual(len(gui.animations["idle"]), 1)
        self.assertEqual(len(gui.animations["celebrating"]), 2)
        self.assertEqual(gui.animations["celebrating"][0], (0, 128, 0))
        self.assertEqual(gui.animations["celebrating"][1], (255, 0, 0))


class CompactFaceLifecycleTests(unittest.TestCase):
    def make_canvas(self) -> Mock:
        canvas = Mock()
        canvas.create_image.return_value = 1
        canvas.create_rectangle.return_value = 2
        canvas.create_text.return_value = 3
        return canvas

    @patch("bmo.ui.compact_face.load_compact_face_config", return_value=CompactFaceConfig())
    @patch("bmo.ui.compact_face.ImageTk.PhotoImage", return_value="photo")
    def test_provider_frame_uses_shared_items_and_refresh_schedule(
        self,
        _photo_image: Mock,
        _load_config: Mock,
    ) -> None:
        root = Mock()
        root.after.return_value = "refresh"
        canvas = self.make_canvas()
        canvas.lift.side_effect = AssertionError(
            "Canvas.lift() requires a tag or item on real Tk canvases"
        )
        provider = Mock(return_value=Image.new("RGB", (800, 480), "blue"))

        face = CompactFace(root, canvas, face_provider=provider)

        self.assertEqual(face.bounds, (684, 5, 792, 70))
        canvas.create_image.assert_called_once_with(
            738.0,
            37.5,
            anchor="center",
            tags=("compact-bmo-face",),
        )
        provider.assert_called_once_with()
        canvas.itemconfigure.assert_any_call(1, image="photo")
        canvas.itemconfigure.assert_any_call(3, state="hidden")
        canvas.lift.assert_not_called()
        canvas.tag_raise.assert_called_with("compact-bmo-face")
        root.after.assert_called_once_with(150, face._refresh)

    @patch("bmo.ui.compact_face.load_compact_face_config", return_value=CompactFaceConfig())
    def test_none_or_raising_provider_keeps_fallback_and_keeps_scheduling(
        self,
        _load_config: Mock,
    ) -> None:
        for provider in (Mock(return_value=None), Mock(side_effect=RuntimeError("no face"))):
            with self.subTest(provider=provider):
                root = Mock()
                canvas = self.make_canvas()

                face = CompactFace(root, canvas, face_provider=provider)
                self.addCleanup(face.destroy)

                canvas.itemconfigure.assert_any_call(1, image="")
                canvas.itemconfigure.assert_any_call(3, state="normal")
                root.after.assert_called_once_with(150, face._refresh)

    @patch("bmo.ui.compact_face.load_compact_face_config", return_value=CompactFaceConfig())
    @patch("bmo.ui.compact_face.ImageTk.PhotoImage", return_value="photo")
    def test_provider_loss_clears_stale_frame_and_restores_fallback(
        self,
        _photo_image: Mock,
        _load_config: Mock,
    ) -> None:
        root = Mock()
        canvas = self.make_canvas()
        provider = Mock(
            side_effect=(Image.new("RGB", (5, 3), "blue"), None)
        )
        face = CompactFace(root, canvas, face_provider=provider)

        face._refresh()

        self.assertIsNone(face.image)
        self.assertEqual(
            canvas.itemconfigure.call_args_list[-2:],
            [
                unittest.mock.call(1, image=""),
                unittest.mock.call(3, state="normal"),
            ],
        )
        face.destroy()

    @patch("bmo.ui.compact_face.load_compact_face_config", return_value=CompactFaceConfig())
    def test_suspend_resume_and_destroy_cancel_owned_callbacks(
        self,
        _load_config: Mock,
    ) -> None:
        root = Mock()
        root.after.side_effect = ("first", "second")
        canvas = self.make_canvas()
        face = CompactFace(root, canvas, face_provider=Mock(return_value=None))

        face.suspend()
        face.resume()
        face.destroy()

        self.assertEqual(root.after_cancel.call_args_list, [
            unittest.mock.call("first"),
            unittest.mock.call("second"),
        ])
        self.assertTrue(face.destroyed)
        self.assertFalse(face.mounted)

    @patch("bmo.ui.compact_face.load_compact_face_config", return_value=CompactFaceConfig())
    def test_new_visible_face_pauses_underlay_and_destroy_resumes_it(
        self,
        _load_config: Mock,
    ) -> None:
        root = Mock()
        root.after.side_effect = ("menu", "feature", "menu-resumed")
        menu = CompactFace(root, self.make_canvas(), face_provider=Mock(return_value=None))
        feature = CompactFace(root, self.make_canvas(), face_provider=Mock(return_value=None))

        self.assertFalse(menu.active)
        self.assertTrue(feature.active)
        root.after_cancel.assert_called_once_with("menu")

        feature.destroy()

        self.assertTrue(menu.active)
        self.assertEqual(menu.after_id, "menu-resumed")
        menu.destroy()


class WeatherCompactFaceAdapterTests(unittest.TestCase):
    def test_bridge_publishes_host_frame_as_exact_normalized_raster(self) -> None:
        config = CompactFaceConfig()
        server = Mock()
        server.server_address = ("127.0.0.1", 1234)
        with patch("bmo.ui.weather._WeatherHTTPServer", return_value=server):
            bridge = WeatherWebBridge(Mock(), compact_face_config=config)
        self.addCleanup(bridge.close)

        bridge.set_face(Image.new("RGB", (500, 300), "red"))
        content = bridge.face_content()

        self.assertIsNotNone(content)
        with Image.open(BytesIO(content or b"")) as normalized:
            self.assertEqual(normalized.size, (108, 65))
            self.assertEqual(normalized.getpixel((0, 0)), (104, 200, 187))
            self.assertEqual(normalized.getpixel((1, 1)), (255, 0, 0))
        self.assertEqual(bridge.compact_face_payload["frame_url"], "face/current")
        self.assertNotIn("states", bridge.compact_face_payload)


if __name__ == "__main__":
    unittest.main()
