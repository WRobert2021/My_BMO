"""UI-independent behavior for the touch timer list."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from bmo.ui.timer import (
    TimerApp,
    TimerViewItem,
    VerticalScrollController,
    format_countdown,
)


class TimerFormattingTests(unittest.TestCase):
    def test_countdown_rounds_up_until_expiration(self) -> None:
        self.assertEqual(format_countdown(0), "00:00")
        self.assertEqual(format_countdown(0.01), "00:01")
        self.assertEqual(format_countdown(65), "01:05")
        self.assertEqual(format_countdown(3661), "01:01:01")
        self.assertEqual(format_countdown(90061), "1 day  01:01:01")


class VerticalScrollControllerTests(unittest.TestCase):
    def test_vertical_finger_drag_scrolls_and_clamps_content(self) -> None:
        scroller = VerticalScrollController(100)
        scroller.set_content_height(400)

        scroller.press(90)
        self.assertTrue(scroller.drag(20))
        self.assertFalse(scroller.release(20))
        self.assertEqual(scroller.offset, 70)

        scroller.press(20)
        scroller.drag(500)
        scroller.release(500)
        self.assertEqual(scroller.offset, 0)

        self.assertTrue(scroller.scroll_by(1000))
        self.assertEqual(scroller.offset, 300)

    def test_short_stationary_touch_remains_a_tap(self) -> None:
        scroller = VerticalScrollController(100)
        scroller.set_content_height(400)
        scroller.press(40)

        self.assertTrue(scroller.release(50))


class TimerAppInteractionTests(unittest.TestCase):
    @staticmethod
    def event(x: int, y: int, *, delta: int = 0) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y, delta=delta)

    def make_app(self) -> TimerApp:
        app = TimerApp.__new__(TimerApp)
        app._list_press_x = None
        app.scroller = VerticalScrollController(TimerApp.LIST_HEIGHT)
        app.scroller.set_content_height(TimerApp.LIST_HEIGHT + 200)
        app._delete_bounds = {7: (618, 14, 714, 64)}
        app.cancel_timer = Mock(return_value=True)
        app._draw_list = Mock()
        app._refresh_items_now = Mock()
        return app

    def test_delete_button_cancels_its_timer_after_a_tap(self) -> None:
        app = self.make_app()

        app._handle_list_press(self.event(660, 35))
        app._handle_list_release(self.event(660, 35))

        app.cancel_timer.assert_called_once_with(7)
        app._refresh_items_now.assert_called_once_with()

    def test_dragging_across_delete_button_only_scrolls(self) -> None:
        app = self.make_app()

        app._handle_list_press(self.event(660, 60))
        app._handle_list_motion(self.event(660, 20))
        app._handle_list_release(self.event(660, 20))

        app.cancel_timer.assert_not_called()
        self.assertGreater(app.scroller.offset, 0)

    def test_refresh_polls_provider_and_schedules_next_countdown_update(self) -> None:
        app = TimerApp.__new__(TimerApp)
        app.closed = False
        app.timer_provider = Mock(
            return_value=(TimerViewItem(1, "tea", 4.5),)
        )
        app.scroller = VerticalScrollController(TimerApp.LIST_HEIGHT)
        app._draw_list = Mock()
        app.canvas = Mock()
        app.count_item = 4
        app.root = Mock()

        app._refresh()

        self.assertEqual(app._items[0].remaining_seconds, 4.5)
        app._draw_list.assert_called_once_with()
        app.canvas.itemconfigure.assert_called_once_with(4, text="1 ACTIVE")
        app.root.after.assert_called_once_with(TimerApp.REFRESH_MS, app._refresh)


if __name__ == "__main__":
    unittest.main()
