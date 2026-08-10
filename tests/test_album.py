"""Contained album storage, menu-only routing, and touch behavior tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote

from PIL import Image

from bmo.features import FeatureMenuContext, ToolResult, load_feature_registry
from bmo.features.album import (
    ALBUM_MENU_ITEM,
    AlbumLibrary,
    AlbumTool,
)
from bmo.prompts import build_routing_prompt, build_system_prompt
from bmo.tools import ToolRouter
from bmo.ui.album import AlbumApp, AlbumPaginator
from bmo.ui.gestures import HorizontalSwipeRecognizer


def make_image(path: Path, color: str = "blue") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 8), color=color).save(path)
    return path.resolve()


class AlbumLibraryTests(unittest.TestCase):
    def test_recursive_scan_returns_only_contained_supported_photos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pictures = root / "Pictures"
            trash = root / "Trash"
            first = make_image(pictures / "first.jpg")
            second = make_image(pictures / "nested" / "second.PNG", "red")
            (pictures / "nested" / "notes.txt").write_text(
                "not a photo",
                encoding="utf-8",
            )
            outside = make_image(root / "outside.jpg", "green")
            escaped_link = pictures / "outside-link.jpg"
            escaped_link.symlink_to(outside)
            library = AlbumLibrary(pictures, trash)

            photos = library.photo_paths()

            self.assertEqual(set(photos), {first, second})
            self.assertNotIn(outside, photos)
            self.assertNotIn(escaped_link, photos)

    def test_outside_and_symbolic_link_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pictures = root / "Pictures"
            outside = make_image(root / "outside.jpg")
            inside = make_image(pictures / "inside.jpg")
            link = pictures / "inside-link.jpg"
            link.symlink_to(inside)
            library = AlbumLibrary(pictures, root / "Trash")

            with self.assertRaisesRegex(PermissionError, "configured photo root"):
                library.require_photo(outside)
            with self.assertRaisesRegex(PermissionError, "symbolic links"):
                library.require_photo(link)

    def test_delete_moves_photo_to_freedesktop_wastebasket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pictures = root / "Pictures"
            trash = root / ".local" / "share" / "Trash"
            source = make_image(pictures / "nested" / "photo one.jpg")
            library = AlbumLibrary(pictures, trash)

            destination = library.move_to_wastebasket(source)

            self.assertFalse(source.exists())
            resolved_trash = trash.resolve()
            self.assertEqual(
                destination,
                resolved_trash / "files" / "photo one.jpg",
            )
            self.assertTrue(destination.is_file())
            info_path = (
                resolved_trash / "info" / "photo one.jpg.trashinfo"
            )
            info = info_path.read_text(encoding="utf-8")
            self.assertIn("[Trash Info]", info)
            self.assertIn(f"Path={quote(str(source), safe='/')}", info)
            self.assertRegex(
                info,
                r"DeletionDate=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            )
            self.assertEqual(library.photo_paths(), ())

    def test_wastebasket_name_collision_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pictures = root / "Pictures"
            trash = root / "Trash"
            source = make_image(pictures / "photo.jpg")
            existing = make_image(trash / "files" / "photo.jpg", "red")
            library = AlbumLibrary(pictures, trash)

            destination = library.move_to_wastebasket(source)

            self.assertEqual(destination.name, "photo.1.jpg")
            self.assertTrue(existing.exists())
            self.assertTrue(
                (trash / "info" / "photo.1.jpg.trashinfo").exists()
            )


class AlbumPaginatorTests(unittest.TestCase):
    def test_multiple_photos_paginate_and_swipes_clamp_at_each_end(self) -> None:
        photos = tuple(Path(f"photo-{index}.jpg") for index in range(13))
        paginator = AlbumPaginator(photos_per_page=6)
        paginator.replace(photos)

        self.assertEqual(paginator.page_count, 3)
        self.assertEqual(paginator.current_photos, photos[:6])
        self.assertTrue(paginator.swipe_left())
        self.assertEqual(paginator.current_photos, photos[6:12])
        self.assertTrue(paginator.swipe_left())
        self.assertEqual(paginator.current_photos, photos[12:])
        self.assertFalse(paginator.swipe_left())
        self.assertTrue(paginator.swipe_right())
        self.assertTrue(paginator.swipe_right())
        self.assertFalse(paginator.swipe_right())

    def test_refresh_clamps_page_after_last_photo_is_deleted(self) -> None:
        paginator = AlbumPaginator(photos_per_page=2)
        paginator.replace(tuple(Path(f"photo-{index}.jpg") for index in range(3)))
        paginator.swipe_left()

        paginator.replace((Path("photo-0.jpg"), Path("photo-1.jpg")))

        self.assertEqual(paginator.page_index, 0)
        self.assertEqual(paginator.page_count, 1)


class AlbumAppInteractionTests(unittest.TestCase):
    @staticmethod
    def event(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y)

    def make_app(self) -> AlbumApp:
        app = AlbumApp.__new__(AlbumApp)
        app.gesture = HorizontalSwipeRecognizer()
        app.paginator = AlbumPaginator(photos_per_page=2)
        app.paginator.replace(
            (Path("one.jpg"), Path("two.jpg"), Path("three.jpg"))
        )
        app.view = "grid"
        app.selected_photo = None
        app.closed = False
        app._photo_bounds = (((20, 80, 200, 220), Path("one.jpg")),)
        app._show_grid = Mock()
        app._show_photo = Mock()
        app._show_action_menu = Mock()
        app._delete_selected_photo = Mock()
        app._begin_analysis = Mock()
        app.close = Mock()
        return app

    def test_grid_swipes_between_photo_pages(self) -> None:
        app = self.make_app()

        app._handle_press(self.event(500, 200))
        app._handle_release(self.event(300, 200))

        self.assertEqual(app.paginator.page_index, 1)
        app._show_grid.assert_called_once_with()

        app._handle_press(self.event(300, 200))
        app._handle_release(self.event(500, 200))

        self.assertEqual(app.paginator.page_index, 0)
        self.assertEqual(app._show_grid.call_count, 2)

    def test_tapping_photo_opens_fullscreen_and_tapping_again_opens_actions(
        self,
    ) -> None:
        app = self.make_app()

        app._handle_press(self.event(100, 140))
        app._handle_release(self.event(100, 140))

        app._show_photo.assert_called_once_with(Path("one.jpg"))

        app.view = "photo"
        app._handle_press(self.event(400, 240))
        app._handle_release(self.event(400, 240))

        app._show_action_menu.assert_called_once_with()

    def test_action_menu_routes_back_delete_and_bmo_buttons(self) -> None:
        app = self.make_app()
        app.view = "actions"
        cases = (
            ((120, 410), app._show_grid),
            ((400, 410), app._delete_selected_photo),
            ((650, 410), app._begin_analysis),
        )

        for point, expected in cases:
            with self.subTest(point=point):
                app._handle_press(self.event(*point))
                app._handle_release(self.event(*point))
                expected.assert_called_once_with()

    def test_fullscreen_photo_hides_bmo_until_analysis_begins(self) -> None:
        app = AlbumApp.__new__(AlbumApp)
        app.selected_photo = Path("selected.jpg")
        app.view = "actions"
        app.closed = False
        app._draw_fullscreen_photo = Mock()
        app.request_vision = Mock()

        app._show_photo(app.selected_photo)

        app._draw_fullscreen_photo.assert_called_once_with(show_bmo=False)
        app._draw_fullscreen_photo.reset_mock()

        app._begin_analysis()

        self.assertEqual(app.view, "analyzing")
        app._draw_fullscreen_photo.assert_called_once_with(show_bmo=True)
        completion = app.request_vision.call_args.args[1]

        completion()

        self.assertEqual(app.view, "photo")
        app._draw_fullscreen_photo.assert_called_with(show_bmo=False)

    def test_album_stays_above_runtime_overlay_during_vision(self) -> None:
        app = AlbumApp.__new__(AlbumApp)
        app.closed = False
        app.canvas = Mock()
        app.root = Mock()
        app.face_item = None
        app.face_fallback_item = None

        app._refresh_face()

        app.canvas.lift.assert_called_once_with()
        app.root.after.assert_called_once_with(
            AlbumApp.FACE_REFRESH_MS,
            app._refresh_face,
        )


class AlbumFeatureTests(unittest.TestCase):
    def test_album_is_registered_for_menu_but_not_voice_or_model_routing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "features": [
                    {
                        "module": "bmo.features.album",
                        "enabled": True,
                        "settings": {
                            "photo_root": str(root / "Pictures"),
                            "wastebasket_root": str(root / "Trash"),
                            "photos_per_page": 4,
                        },
                    }
                ]
            }
            router = ToolRouter(config)
            self.addCleanup(router.close)

            self.assertEqual(router.VALID_TOOLS, set())
            self.assertEqual(router.ALIASES, {})
            self.assertEqual(router.registry.menu_items, (ALBUM_MENU_ITEM,))
            self.assertIsNone(router.match_direct_action("Open the album"))
            self.assertIsNone(
                router.registry.prepare_model_request({"action": "album"})
            )
            self.assertEqual(
                router.execute({"action": "album"}),
                ToolResult.invalid_action(),
            )
            self.assertNotIn("album", build_routing_prompt(router.registry))
            self.assertNotIn(
                "album",
                build_system_prompt(config, router.registry).lower(),
            )

    def test_invalid_album_settings_are_isolated_at_registration(self) -> None:
        result = load_feature_registry(
            {
                "features": [
                    {
                        "module": "bmo.features.album",
                        "enabled": True,
                        "settings": {"photos_per_page": 1},
                    }
                ]
            },
            reporter=Mock(),
        )

        self.assertEqual(result.registry.actions, set())
        self.assertEqual(result.registry.menu_items, ())
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "register")

    def test_album_open_wires_contained_services_from_feature_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = make_image(root / "Pictures" / "photo.jpg")
            library = AlbumLibrary(root / "Pictures", root / "Trash")
            app = Mock()
            app_factory = Mock(return_value=app)
            tool = AlbumTool(
                library,
                bmo_button_path=root / "capturing.png",
                photos_per_page=4,
                app_factory=app_factory,
            )
            face = Mock(return_value=None)
            vision = Mock()
            on_close = Mock()
            context = FeatureMenuContext(
                master="ROOT",
                on_close=on_close,
                face_provider=face,
                vision_requester=vision,
            )

            tool.open_menu(context)

            kwargs = app_factory.call_args.kwargs
            self.assertEqual(app_factory.call_args.args, ("ROOT",))
            self.assertEqual(tuple(kwargs["photo_provider"]()), (photo,))
            self.assertEqual(kwargs["photos_per_page"], 4)
            self.assertEqual(
                kwargs["bmo_button_path"],
                root / "capturing.png",
            )
            self.assertIsNone(kwargs["face_provider"]())
            face.assert_called_once_with()
            completion = Mock()

            kwargs["request_vision"](photo, completion)

            vision.assert_called_once_with(photo, completion)
            tool.close()
            app.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
