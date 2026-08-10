"""Tests for BMO's menu navigation and face gestures."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bmo.app import BotGUI
from bmo.ui import (
    GestureKind,
    HorizontalSwipeRecognizer,
    MenuApp,
    MenuNavigation,
    MenuNavigator,
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


class MenuViewGestureTests(unittest.TestCase):
    @staticmethod
    def event(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y)

    def make_view(self) -> MenuApp:
        view = MenuApp.__new__(MenuApp)
        view.gesture = HorizontalSwipeRecognizer()
        view.navigator = MenuNavigator(page_count=3)
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

        gui.open_menu()
        opened_view = gui.menu_ui
        gui.open_menu()

        menu_app.assert_called_once()
        self.assertIs(opened_view, menu_app.return_value)
        self.assertIs(gui.menu_ui, opened_view)
        kwargs = menu_app.call_args.kwargs
        self.assertEqual(kwargs["on_close"], gui._handle_menu_close)
        self.assertEqual(kwargs["face_provider"], gui._current_mode_face)

        kwargs["on_close"]()
        self.assertIsNone(gui.menu_ui)


if __name__ == "__main__":
    unittest.main()
