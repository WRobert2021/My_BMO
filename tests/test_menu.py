"""Tests for BMO's menu navigation and face gestures."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bmo.app import BotGUI, _FeatureMenuAnnouncer, _SpeechQueueItem
from bmo.features import FeatureMenuContext, FeatureMenuItem
from bmo.modes import ModeMenuItem
from bmo.runtime_extensions import RuntimeExtensionCoordinator
from bmo.state import BotStates
from bmo.ui import (
    COMPACT_FACE_CENTER,
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
        Path(f"graphics/icons/{name}.png"),
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
    BOUNDS = MenuBounds(18, 76, 782, 448)

    def test_fifteen_icons_share_one_page_and_sixteenth_starts_next_page(self) -> None:
        items = tuple(icon_item(f"game-{index}") for index in range(16))

        pages = IconMenuPage.paginate(items)

        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].items, items[:15])
        self.assertEqual(pages[1].items, items[15:])
        self.assertEqual(IconMenuPage.CAPACITY, 15)
        self.assertEqual((IconMenuPage.COLUMNS, IconMenuPage.ROWS), (5, 3))

    def test_each_grid_tile_maps_to_its_own_action(self) -> None:
        items = tuple(icon_item(f"game-{index}") for index in range(15))
        page = IconMenuPage(items)

        self.assertEqual(page.action_at((94, 138), self.BOUNDS), "game-0")
        self.assertEqual(page.action_at((246, 138), self.BOUNDS), "game-1")
        self.assertEqual(page.action_at((702, 386), self.BOUNDS), "game-14")
        self.assertIsNone(page.action_at((790, 300), self.BOUNDS))

    @patch("bmo.ui.menu.ImageTk.PhotoImage", return_value=object())
    @patch("bmo.ui.menu.Image.open")
    def test_icon_rendering_is_unframed_and_preserves_png_alpha(
        self,
        open_image: Mock,
        _photo_image: Mock,
    ) -> None:
        source = open_image.return_value.__enter__.return_value
        converted = source.convert.return_value
        page = IconMenuPage((icon_item(),))
        canvas = Mock()

        page.draw(canvas, self.BOUNDS)

        source.convert.assert_called_once_with("RGBA")
        converted.thumbnail.assert_called_once_with(
            (IconMenuPage.ICON_SIZE, IconMenuPage.ICON_SIZE),
            unittest.mock.ANY,
        )
        canvas.create_image.assert_called_once()
        canvas.create_rectangle.assert_not_called()
        canvas.create_text.assert_not_called()


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
        view.compact_face = Mock()
        view.compact_face.contains.side_effect = lambda point: (
            684 <= point[0] <= 792 and 5 <= point[1] <= 70
        )
        return view

    def test_tapping_minimized_bmo_returns_directly_to_face(self) -> None:
        view = self.make_view()
        event = self.event(*map(int, COMPACT_FACE_CENTER))

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
        event = self.event(94, 138)

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
        event = self.event(*map(int, COMPACT_FACE_CENTER))

        view._handle_press(event)
        view._handle_release(event)

        view.close.assert_not_called()
        view.on_select.assert_not_called()
        self.assertEqual(view.navigator.page_index, 1)

    def test_pending_launch_keeps_shared_face_owned_by_menu(self) -> None:
        view = self.make_view()
        view.selection_pending = True

        view.finish_selection()

        view.compact_face.suspend.assert_not_called()
        view.compact_face.destroy.assert_not_called()


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
        gui.tool_router = Mock()
        gui.tool_router.registry.menu_items = (
            FeatureMenuItem(
                name="set_timer",
                label="Timers",
                icon_path=Path("graphics/icons/timer.png"),
            ),
        )
        gui.mode_registry = Mock()
        gui.mode_registry.menu_items = (
            ModeMenuItem(
                name="matching_game",
                label="Matching Game",
                icon_path=Path("graphics/icons/matching_game.png"),
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
        self.assertEqual(kwargs["on_select"], gui._select_menu_item)
        pages = tuple(kwargs["pages"])
        self.assertEqual(len(pages), 1)
        self.assertIsInstance(pages[0], IconMenuPage)
        self.assertEqual(len(pages[0].items), 2)
        self.assertEqual(pages[0].items[0].name, "mode:matching_game")
        self.assertEqual(
            pages[0].items[0].icon_path,
            Path("graphics/icons/matching_game.png"),
        )
        self.assertEqual(pages[0].items[1].name, "feature:set_timer")
        self.assertEqual(
            pages[0].items[1].icon_path,
            Path("graphics/icons/timer.png"),
        )

        kwargs["on_close"]()
        self.assertIsNone(gui.menu_ui)

    def test_menu_selection_queues_mode_and_wakes_interaction_worker(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.mode_registry = Mock()
        gui.mode_registry.menu_items = (
            ModeMenuItem(
                "matching_game",
                "Matching Game",
                Path("matching.png"),
                "Start matching",
            ),
        )
        gui.tool_router = Mock()
        gui.tool_router.registry.menu_items = ()
        gui.extension_runtime = RuntimeExtensionCoordinator(
            gui.mode_registry,
            gui.tool_router.registry,
            launch_feature=gui._open_feature_menu,
        )
        gui.runtime_menu = gui.extension_runtime.menu
        gui.menu_action_event = gui.extension_runtime.wake_event

        gui._select_menu_item("mode:matching_game")

        self.assertTrue(gui.menu_action_event.is_set())
        self.assertTrue(gui._start_pending_menu_mode())
        gui.mode_registry.start_menu_item.assert_called_once_with("matching_game")

    def test_feature_selection_opens_view_and_returns_to_same_menu(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.master = Mock()
        gui.menu_ui = Mock()
        gui.tool_router = Mock()
        gui.tool_router.registry.menu_items = (
            FeatureMenuItem("set_timer", "Timers", Path("timer.png")),
        )
        gui.mode_registry = Mock()
        gui.mode_registry.menu_items = ()
        gui._current_mode_face = Mock(return_value=None)
        gui._queue_menu_vision = Mock()
        originating_menu = gui.menu_ui

        gui._select_menu_item("feature:set_timer")

        gui.tool_router.registry.open_menu_item.assert_called_once()
        name, context = gui.tool_router.registry.open_menu_item.call_args.args
        self.assertEqual(name, "set_timer")
        self.assertIsInstance(context, FeatureMenuContext)
        self.assertIs(context.master, gui.master)
        self.assertIsNone(context.current_face())
        gui._current_mode_face.assert_called_once_with()
        completion = Mock()
        context.request_vision(Path("/tmp/photo.jpg"), completion)
        gui._queue_menu_vision.assert_called_once_with(
            Path("/tmp/photo.jpg"),
            completion,
        )
        originating_menu.finish_selection.assert_not_called()

        context.on_close()

        originating_menu.finish_selection.assert_called_once_with()
        self.assertIs(gui.menu_ui, originating_menu)

    def test_mode_launch_preserves_originating_menu_and_page(self) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.master = Mock()
        gui.mode_registry = Mock()
        feature_registry = Mock()
        feature_registry.menu_items = ()
        gui.extension_runtime = RuntimeExtensionCoordinator(
            gui.mode_registry,
            feature_registry,
            launch_feature=gui._open_feature_menu,
        )
        gui.menu_action_event = gui.extension_runtime.wake_event
        gui.extension_runtime.queue_mode("matching_game")
        gui.menu_ui = Mock()
        gui.menu_ui.navigator.page_index = 1
        originating_menu = gui.menu_ui

        self.assertTrue(gui._start_pending_menu_mode())

        gui.mode_registry.start_menu_item.assert_called_once_with("matching_game")
        gui.master.after.assert_called_once()
        gui.master.after.call_args.args[1]()
        originating_menu.finish_selection.assert_called_once_with()
        self.assertIs(gui.menu_ui, originating_menu)
        self.assertEqual(gui.menu_ui.navigator.page_index, 1)
        self.assertFalse(gui.menu_action_event.is_set())

    def test_menu_vision_runs_on_interaction_worker_and_completes_on_tk(
        self,
    ) -> None:
        gui = BotGUI.__new__(BotGUI)
        gui.mode_registry = Mock()
        feature_registry = Mock()
        feature_registry.menu_items = ()
        gui.extension_runtime = RuntimeExtensionCoordinator(
            gui.mode_registry,
            feature_registry,
            launch_feature=gui._open_feature_menu,
        )
        gui.menu_action_event = gui.extension_runtime.wake_event
        gui.interrupted = threading.Event()
        gui.master = Mock()
        gui._start_interaction = Mock()
        gui.chat_and_respond = Mock()
        gui._finish_interaction = Mock()
        completion = Mock()
        path = Path("/tmp/photo.jpg")
        gui.extension_runtime.queue_vision(path, completion)

        self.assertTrue(gui._start_pending_menu_vision())

        gui._start_interaction.assert_called_once_with("MENU_VISION")
        gui.chat_and_respond.assert_called_once_with(
            "What do you see in this image?",
            image_path=str(path),
        )
        gui._finish_interaction.assert_called_once_with("completed")
        gui.master.after.assert_called_once_with(0, completion)
        self.assertFalse(gui.menu_action_event.is_set())

    def test_typed_debug_loop_also_starts_pending_menu_mode(self) -> None:
        gui = TypedBotGUI.__new__(TypedBotGUI)
        gui.exiting = False
        gui.mode_registry = Mock()
        feature_registry = Mock()
        feature_registry.menu_items = ()
        gui.extension_runtime = RuntimeExtensionCoordinator(
            gui.mode_registry,
            feature_registry,
            launch_feature=gui._open_feature_menu,
        )
        gui.menu_action_event = gui.extension_runtime.wake_event
        gui.extension_runtime.queue_mode("matching_game")

        self.assertTrue(gui._run_typed_interaction())

        gui.mode_registry.start_menu_item.assert_called_once_with("matching_game")


class FeatureMenuAnnouncementTests(unittest.TestCase):
    def make_gui(self) -> BotGUI:
        gui = BotGUI.__new__(BotGUI)
        gui.exiting = False
        gui.speaker = Mock()
        gui.current_interaction = None
        gui.tts_queue_lock = threading.Lock()
        gui.tts_queue = []
        gui.active_tts_item = None
        gui.set_state = Mock()
        return gui

    def test_new_tap_coalesces_only_speech_from_the_same_view(self) -> None:
        gui = self.make_gui()
        unrelated = _SpeechQueueItem("normal reply", None)
        gui.tts_queue.append(unrelated)
        announcer = _FeatureMenuAnnouncer(gui)

        self.assertTrue(announcer.speak("first weather card"))
        first = gui.tts_queue[-1]
        self.assertTrue(announcer.speak("second weather card"))

        self.assertTrue(first.cancelled.is_set())
        self.assertEqual(
            [item.text for item in gui.tts_queue],
            ["normal reply", "second weather card"],
        )
        self.assertFalse(unrelated.cancelled.is_set())
        gui.set_state.assert_called_with(BotStates.SPEAKING, "Speaking...")

    def test_cancel_stops_active_scoped_speech_but_preserves_other_scopes(self) -> None:
        gui = self.make_gui()
        weather = _FeatureMenuAnnouncer(gui)
        album = _FeatureMenuAnnouncer(gui)
        weather.speak("weather talking")
        weather_item = gui.tts_queue.pop()
        gui.active_tts_item = weather_item
        album.speak("album talking")

        weather.cancel()

        self.assertTrue(weather_item.cancelled.is_set())
        self.assertEqual([item.text for item in gui.tts_queue], ["album talking"])
        self.assertTrue(weather.available)
        self.assertEqual(
            gui.set_state.call_args_list,
            [
                unittest.mock.call(BotStates.SPEAKING, "Speaking..."),
                unittest.mock.call(BotStates.SPEAKING, "Speaking..."),
            ],
        )

    def test_scoped_completion_restores_idle_before_feature_callback(self) -> None:
        gui = self.make_gui()
        completion = Mock()
        announcer = _FeatureMenuAnnouncer(gui)
        announcer.speak("weather talking", completion)

        queued_completion = gui.tts_queue[-1].on_complete
        self.assertIsNotNone(queued_completion)
        queued_completion()

        self.assertEqual(
            gui.set_state.call_args_list,
            [
                unittest.mock.call(BotStates.SPEAKING, "Speaking..."),
                unittest.mock.call(BotStates.IDLE, "Ready"),
            ],
        )
        completion.assert_called_once_with()

    def test_context_visibly_disables_announcements_without_runtime_speech(self) -> None:
        context = FeatureMenuContext(master=object(), on_close=lambda: None)

        self.assertFalse(context.announcements_available)
        self.assertFalse(context.announce("Weather card text"))

    def test_tts_worker_speaks_queue_items_and_completes_on_tk_thread(self) -> None:
        gui = self.make_gui()
        gui.interrupted = threading.Event()
        gui.shutdown_event = threading.Event()
        gui.tts_active = threading.Event()
        gui.master = Mock()
        completion = Mock()
        gui.tts_queue.append(
            _SpeechQueueItem(
                "Weather card text",
                Path("speech.wav"),
                scope=object(),
                on_complete=completion,
            )
        )

        def finish_callback(*args: object, **kwargs: object) -> str:
            gui.exiting = True
            return "callback"

        gui.master.after.side_effect = finish_callback

        gui._tts_worker()

        args = gui.speaker.speak.call_args.args
        self.assertEqual(args[0], "Weather card text")
        self.assertFalse(args[1].is_set())
        self.assertIs(args[2], gui.shutdown_event)
        self.assertEqual(
            gui.speaker.speak.call_args.kwargs["archive_path"],
            Path("speech.wav"),
        )
        gui.master.after.assert_called_once_with(0, completion)
        self.assertFalse(gui.tts_active.is_set())


if __name__ == "__main__":
    unittest.main()
