"""Tests for BMO's menu navigation and face gestures."""

from __future__ import annotations

import queue
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bmo.app import BotGUI
from bmo.modes import ModeMenuItem
from bmo.ui import (
    EmptyMenuPage,
    GestureKind,
    HorizontalSwipeRecognizer,
    IconMenuItem,
    IconMenuPage,
    MenuApp,
    MenuBounds,
    MenuNavigation,
    MenuNavigator,
)
from typed_agent import TypedBotGUI


def icon_item(
    name: str = "matching_game",
    label: str = "Matching Game",
) -> IconMenuItem:
    return IconMenuItem(
        name,
        label,
        Path(f"graphics/Icons/{name}.png"),
    )


class HorizontalSwipeRecognizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gesture = HorizontalSwipeRecognizer()

    def test_right_to_left_motion_is_a_left_swipe(self) -> None:
        self.gesture.press(700, 220)

        result = self.gesture.release(540, 224)

        self.assertEqual(result, GestureKind.SWIPE_LEFT)

    def test_left_to_right_motion_is_a_right_swipe(self) -> None:
        self.gesture.press(100, 220)

        result = self.gesture.release(260, 216)

        self.assertEqual(result, GestureKind.SWIPE_RIGHT)

    def test_small_touch_motion_remains_a_tap(self) -> None:
        self.gesture.press(400, 200)

        result = self.gesture.release(411, 210)

        self.assertEqual(result, GestureKind.TAP)

    def test_vertical_drag_does_not_change_pages(self) -> None:
        self.gesture.press(400, 100)

        result = self.gesture.release(420, 260)

        self.assertEqual(result, GestureKind.OTHER)


class MenuNavigatorTests(unittest.TestCase):
    def test_right_swipes_retrace_every_visited_page_before_face(self) -> None:
        navigator = MenuNavigator(page_count=4)

        self.assertEqual(navigator.swipe_left(), MenuNavigation.PAGE)
        self.assertEqual(navigator.swipe_left(), MenuNavigation.PAGE)
        self.assertEqual(navigator.swipe_left(), MenuNavigation.PAGE)
        self.assertEqual(navigator.page_index, 3)

        visited = []
        for _ in range(3):
            self.assertEqual(navigator.swipe_right(), MenuNavigation.PAGE)
            visited.append(navigator.page_index)

        self.assertEqual(visited, [2, 1, 0])
        self.assertEqual(navigator.swipe_right(), MenuNavigation.FACE)
        self.assertEqual(navigator.page_index, 0)

    def test_swiping_past_the_last_page_does_nothing(self) -> None:
        navigator = MenuNavigator(page_count=1)

        self.assertEqual(navigator.swipe_left(), MenuNavigation.UNCHANGED)
        self.assertEqual(navigator.page_index, 0)

    def test_menu_requires_at_least_one_page(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one page"):
            MenuNavigator(page_count=0)


class IconMenuPageTests(unittest.TestCase):
    BOUNDS = MenuBounds(24, 76, 612, 448)

    def test_six_icons_share_one_page_and_seventh_starts_next_page(self) -> None:
        items = tuple(icon_item(f"game-{index}") for index in range(7))

        pages = IconMenuPage.paginate(items)

        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].items, items[:6])
        self.assertEqual(pages[1].items, items[6:])
        self.assertEqual(IconMenuPage.CAPACITY, 6)
        self.assertLessEqual(IconMenuPage.ICON_SIZE, 120)

    def test_each_grid_tile_maps_to_its_own_action(self) -> None:
        items = tuple(icon_item(f"game-{index}") for index in range(6))
        page = IconMenuPage(items)

        self.assertEqual(page.action_at((122, 169), self.BOUNDS), "game-0")
        self.assertEqual(page.action_at((318, 169), self.BOUNDS), "game-1")
        self.assertEqual(page.action_at((514, 355), self.BOUNDS), "game-5")
        self.assertIsNone(page.action_at((620, 300), self.BOUNDS))


class MenuViewGestureTests(unittest.TestCase):
    @staticmethod
    def event(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y)

    def make_view(self) -> MenuApp:
        view = MenuApp.__new__(MenuApp)
        view.gesture = HorizontalSwipeRecognizer()
        view.navigator = MenuNavigator(page_count=3)
        view.pages = (EmptyMenuPage(), EmptyMenuPage(), EmptyMenuPage())
        view.on_select = Mock()
        view.selection_pending = False
        view.close = Mock()
        view._draw_page = Mock()
        return view

    def test_tapping_minimized_bmo_returns_directly_to_face(self) -> None:
        view = self.make_view()
        event = self.event(714, 123)

        view._handle_press(event)
        view._handle_release(event)

        view.close.assert_called_once_with()
        self.assertEqual(view.navigator.page_index, 0)

    def test_tapping_outside_minimized_bmo_does_not_close_menu(self) -> None:
        view = self.make_view()
        event = self.event(300, 200)

        view._handle_press(event)
        view._handle_release(event)

        view.close.assert_not_called()

    def test_tapping_an_icon_keeps_menu_open_while_selecting_action(self) -> None:
        view = self.make_view()
        view.navigator = MenuNavigator(page_count=1)
        view.pages = (IconMenuPage((icon_item(),)),)
        calls = Mock()
        view.close = calls.close
        view.on_select = calls.select
        event = self.event(122, 169)

        view._handle_press(event)
        view._handle_release(event)

        self.assertEqual(calls.mock_calls, [unittest.mock.call.select("matching_game")])
        self.assertTrue(view.selection_pending)
        self.assertEqual(view.navigator.page_index, 0)

        view.finish_selection()

        self.assertFalse(view.selection_pending)

    def test_tapping_outside_icon_page_does_not_select_it(self) -> None:
        view = self.make_view()
        view.navigator = MenuNavigator(page_count=1)
        view.pages = (IconMenuPage((icon_item(),)),)
        event = self.event(40, 440)

        view._handle_press(event)
        view._handle_release(event)

        view.close.assert_not_called()
        view.on_select.assert_not_called()

    def test_pending_launch_keeps_corner_face_and_navigation_in_place(self) -> None:
        view = self.make_view()
        view.selection_pending = True
        view.navigator.page_index = 1
        event = self.event(714, 123)

        view._handle_press(event)
        view._handle_release(event)

        view.close.assert_not_called()
        view.on_select.assert_not_called()
        self.assertEqual(view.navigator.page_index, 1)

    def test_corner_face_refresh_continues_while_launch_is_pending(self) -> None:
        view = MenuApp.__new__(MenuApp)
        view.closed = False
        view.selection_pending = True
        view.face_provider = Mock(return_value=None)
        view.root = Mock()

        view._refresh_face()

        view.face_provider.assert_called_once_with()
        view.root.after.assert_called_once_with(150, view._refresh_face)
        self.assertEqual(view.face_after_id, view.root.after.return_value)


class BotGuiMenuIntegrationTests(unittest.TestCase):
    @staticmethod
    def event(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x_root=x, y_root=y)

    def test_left_swipe_on_full_face_opens_menu_without_toggling_hud(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.face_gesture = HorizontalSwipeRecognizer()
        gui.open_menu = Mock()
        gui.toggle_hud_visibility = Mock()

        gui._handle_face_press(self.event(700, 220))
        gui._handle_face_release(self.event(500, 220))

        gui.open_menu.assert_called_once_with()
        gui.toggle_hud_visibility.assert_not_called()

    def test_face_tap_keeps_existing_hud_behavior(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.face_gesture = HorizontalSwipeRecognizer()
        gui.open_menu = Mock()
        gui.toggle_hud_visibility = Mock()

        gui._handle_face_press(self.event(400, 220))
        gui._handle_face_release(self.event(405, 224))

        gui.toggle_hud_visibility.assert_called_once_with()
        gui.open_menu.assert_not_called()

    @patch("bmo.app.MenuApp")
    def test_open_menu_composes_view_once_and_close_releases_it(
        self,
        menu_app: Mock,
    ) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.menu_ui = None
        gui.master = Mock()
        gui.mode_registry = Mock()
        gui.mode_registry.menu_items = (
            ModeMenuItem(
                name="matching_game",
                label="Matching Game",
                icon_path=Path("graphics/Icons/Matching_Game.png"),
                start_request="Start the matching game",
            ),
        )

        gui.open_menu()
        opened_view = gui.menu_ui
        gui.open_menu()

        menu_app.assert_called_once()
        self.assertIs(opened_view, menu_app.return_value)
        self.assertIs(gui.menu_ui, opened_view)
        kwargs = menu_app.call_args.kwargs
        self.assertEqual(kwargs["on_close"], gui._handle_menu_close)
        self.assertEqual(kwargs["face_provider"], gui._current_mode_face)
        self.assertEqual(kwargs["on_select"], gui._queue_menu_mode)
        pages = tuple(kwargs["pages"])
        self.assertEqual(len(pages), 1)
        self.assertIsInstance(pages[0], IconMenuPage)
        self.assertEqual(len(pages[0].items), 1)
        self.assertEqual(pages[0].items[0].name, "matching_game")
        self.assertEqual(
            pages[0].items[0].icon_path,
            Path("graphics/Icons/Matching_Game.png"),
        )

        kwargs["on_close"]()
        self.assertIsNone(gui.menu_ui)

    def test_menu_selection_queues_mode_and_wakes_interaction_worker(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.menu_mode_requests = queue.Queue()
        gui.menu_mode_event = threading.Event()

        gui._queue_menu_mode("matching_game")

        self.assertEqual(gui.menu_mode_requests.get_nowait(), "matching_game")
        self.assertTrue(gui.menu_mode_event.is_set())

    def test_mode_launch_preserves_originating_menu_and_page(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.menu_mode_requests = queue.Queue()
        gui.menu_mode_requests.put("matching_game")
        gui.menu_mode_event = threading.Event()
        gui.menu_mode_event.set()
        gui.mode_registry = Mock()
        gui.menu_ui = Mock()
        gui.menu_ui.navigator.page_index = 1
        originating_menu = gui.menu_ui

        self.assertTrue(gui._start_pending_menu_mode())

        gui.mode_registry.start_menu_item.assert_called_once_with("matching_game")
        originating_menu.finish_selection.assert_called_once_with()
        self.assertIs(gui.menu_ui, originating_menu)
        self.assertEqual(gui.menu_ui.navigator.page_index, 1)
        self.assertFalse(gui.menu_mode_event.is_set())

    def test_typed_debug_loop_also_starts_pending_menu_mode(self) -> None:
        gui = TypedBotGUI.__new__(TypedBotGUI)
        gui.menu_mode_requests = queue.Queue()
        gui.menu_mode_requests.put("matching_game")
        gui.menu_mode_event = threading.Event()
        gui.menu_mode_event.set()
        gui.mode_registry = Mock()

        self.assertTrue(gui._run_typed_interaction())

        gui.mode_registry.start_menu_item.assert_called_once_with("matching_game")


if __name__ == "__main__":
    unittest.main()
