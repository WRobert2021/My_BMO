"""Headless tests for Learning's data-driven touch presentation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from random import Random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from bmo.ui.learning import (
    HitRegion,
    InteractionController,
    LearningApp,
    LearningScreen,
    PageCursor,
    PinEntry,
    Rect,
    TEXT_ENTRY_KEYS,
    TextEntry,
    TouchTracker,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    bulk_missing_prerequisites,
    contrast_ratio,
    evaluation_snapshot,
    filter_lessons,
    format_percent,
    hit_test,
    lesson_filter_domains,
    lesson_filter_families,
    lesson_snapshot,
    missing_prerequisites,
    ordered_plan_lessons,
    plan_snapshot,
    question_snapshot,
    reorder_item,
    safe_choice_text_color,
    teacher_report_metrics,
)


def question(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "question_id": "q-1",
        "lesson_id": "letters.a",
        "interaction": "single_choice",
        "prompt": "Find the letter A.",
        "spoken_prompt": "Find the letter A.",
        "choices": (
            SimpleNamespace(id="a", label="A", spoken="A", metadata=()),
            SimpleNamespace(id="b", label="B", spoken="B", metadata=()),
            SimpleNamespace(id="c", label="C", spoken="C", metadata=()),
            SimpleNamespace(id="d", label="D", spoken="D", metadata=()),
        ),
        "correct_answers": ("a",),
        "hidden_prompt": False,
        "requires_submit": False,
        "metadata": (),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class GeometryAndTouchTests(unittest.TestCase):
    def test_rectangles_are_inclusive_and_validate_viewport_bounds(self) -> None:
        bounds = Rect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)

        self.assertTrue(bounds.contains((0, 0)))
        self.assertTrue(bounds.contains((WINDOW_WIDTH, WINDOW_HEIGHT)))
        self.assertTrue(bounds.inside())
        self.assertEqual(bounds.center, (400, 240))
        with self.assertRaises(ValueError):
            Rect(20, 20, 20, 40)

    def test_hit_test_prefers_topmost_enabled_region(self) -> None:
        regions = (
            HitRegion("under", Rect(10, 10, 100, 100)),
            HitRegion("disabled", Rect(20, 20, 90, 90), enabled=False),
            HitRegion("top", Rect(30, 30, 80, 80)),
        )

        self.assertEqual(hit_test(regions, (40, 40)), "top")
        self.assertEqual(hit_test(regions, (25, 25)), "under")
        self.assertIsNone(hit_test(regions, (200, 200)))

    def test_drag_does_not_become_an_answer_tap(self) -> None:
        touch = TouchTracker(tap_slop=18)
        touch.press((100, 100))

        self.assertIsNone(touch.release((125, 100)))

        touch.press((100, 100))
        self.assertEqual(touch.release((114, 110)), (114, 110))
        self.assertIsNone(touch.release((114, 110)))


class QuestionBoundaryTests(unittest.TestCase):
    def test_typed_question_and_frozen_metadata_are_normalized(self) -> None:
        raw = question(
            interaction=SimpleNamespace(value="picture_choice"),
            hidden_prompt=True,
            metadata=(("art", "book"),),
            choices=(
                SimpleNamespace(
                    id="book",
                    label="Book",
                    spoken="book",
                    metadata=(("shape", "square"),),
                ),
                "Ball",
            ),
        )

        result = question_snapshot(raw)

        self.assertEqual(result.interaction, "picture_choice")
        self.assertTrue(result.hidden_prompt)
        self.assertEqual(result.metadata["art"], "book")
        self.assertEqual(result.choices[0].metadata["shape"], "square")
        self.assertEqual(result.choices[1].choice_id, "Ball")

    def test_engine_interaction_aliases_map_to_generic_renderers(self) -> None:
        cases = {
            "category_sort": "category_sorting",
            # Engine listen-hidden questions carry answer choices, so the
            # generic single-choice renderer hides only the written prompt.
            "listen_hidden": "single_choice",
            "scene_choice": "scene_prediction",
            "order": "ordered_sequence",
        }

        for supplied, expected in cases.items():
            with self.subTest(supplied=supplied):
                self.assertEqual(
                    question_snapshot(question(interaction=supplied)).interaction,
                    expected,
                )

    def test_hidden_question_keeps_spoken_prompt_without_visual_hint(self) -> None:
        result = question_snapshot(
            question(
                prompt="Find all the letter A choices.",
                spoken_prompt="Find all the letter A choices.",
                hidden_prompt=True,
            )
        )

        self.assertTrue(result.hidden_prompt)
        self.assertEqual(result.spoken_prompt, "Find all the letter A choices.")

    def test_plan_aliases_cover_store_model_names(self) -> None:
        raw = SimpleNamespace(
            plan_id="plan-1",
            profile_id="learner-1",
            title="Letter Steps",
            lesson_ids=("a", "b"),
            enabled=True,
            archived=False,
            questions_per_session=7,
            repetitions=3,
            mastery_gate=True,
        )

        result = plan_snapshot(raw)

        self.assertEqual(result.name, "Letter Steps")
        self.assertEqual(result.question_count, 7)
        self.assertEqual(result.repetitions, 3)
        self.assertTrue(result.mastery_gate)

        raw.repetitions = 99
        self.assertEqual(plan_snapshot(raw).repetitions, 10)

    def test_actual_typed_question_keeps_glyph_art_and_count_metadata(self) -> None:
        from bmo.features.learning.models import Choice, InteractionKind, Question

        typed = Question(
            question_id="typed-q",
            lesson_id="typed-lesson",
            domain="literacy",
            skills=("letter.upper",),
            interaction=InteractionKind.PICTURE_CHOICE,
            prompt="Choose one.",
            spoken_prompt="Choose one.",
            choices=(
                Choice(
                    "c0",
                    "A",
                    metadata={
                        "font": "DejaVu Sans",
                        "color": "#124559",
                        "picture": "shape-circle",
                    },
                ),
                Choice("c1", "B", metadata={"picture": "shape-square"}),
            ),
            correct_answers=("c0",),
            metadata={"count": 4, "prompt_picture": "four-blocks"},
        )

        result = question_snapshot(typed)

        self.assertEqual(result.choices[0].metadata["font"], "DejaVu Sans")
        self.assertEqual(result.choices[0].metadata["picture"], "shape-circle")
        self.assertEqual(result.metadata["count"], 4)
        self.assertEqual(result.metadata["prompt_picture"], "four-blocks")


class InteractionControllerTests(unittest.TestCase):
    def test_single_choice_is_immediate_and_locks_against_double_taps(self) -> None:
        controller = InteractionController(question_snapshot(question()))

        selected = controller.choose("a")

        self.assertTrue(selected.accepted)
        self.assertTrue(selected.submit_immediately)
        self.assertEqual(selected.response, "a")
        controller.locked = True
        rejected = controller.choose("b")
        self.assertFalse(rejected.accepted)
        self.assertEqual(controller.response(), "a")

    def test_multi_select_toggles_and_requires_explicit_submit(self) -> None:
        controller = InteractionController(
            question_snapshot(
                question(
                    interaction="multi_select",
                    correct_answers=("a", "c"),
                    requires_submit=True,
                )
            )
        )

        first = controller.choose("a")
        second = controller.choose("c")

        self.assertFalse(first.submit_immediately)
        self.assertFalse(second.submit_immediately)
        self.assertTrue(controller.submit_ready)
        self.assertEqual(controller.response(), ("a", "c"))
        controller.choose("a")
        self.assertEqual(controller.response(), ("c",))

    def test_ordering_requires_every_item_and_can_rewind_from_one_item(self) -> None:
        controller = InteractionController(
            question_snapshot(
                question(
                    interaction="ordered_sequence",
                    choices=("first", "second", "third"),
                    correct_answers=("first", "second", "third"),
                )
            )
        )

        controller.choose("second")
        controller.choose("first")
        self.assertFalse(controller.submit_ready)
        controller.choose("third")
        self.assertTrue(controller.submit_ready)
        self.assertEqual(controller.response(), ("second", "first", "third"))

        controller.choose("first")
        self.assertEqual(controller.response(), ("second",))

    def test_category_sort_cycles_assignments_and_waits_for_all_objects(self) -> None:
        controller = InteractionController(
            question_snapshot(
                question(
                    interaction="category_sort",
                    choices=("cat", "car"),
                    correct_answers=("cat=animal", "car=vehicle"),
                    metadata=(("categories", ("animal", "vehicle")),),
                )
            )
        )

        controller.choose("cat")
        self.assertEqual(controller.response(), {"cat": "animal"})
        self.assertFalse(controller.submit_ready)
        controller.choose("cat")
        self.assertEqual(controller.response(), {"cat": "vehicle"})
        controller.choose("car")
        self.assertTrue(controller.submit_ready)

    def test_alphabet_grid_uses_single_choice_semantics(self) -> None:
        controller = InteractionController(
            question_snapshot(question(interaction="alphabet_grid"))
        )

        result = controller.choose("d")

        self.assertTrue(result.submit_immediately)
        self.assertEqual(result.response, "d")


class TeacherStateHelperTests(unittest.TestCase):
    def test_assigned_lessons_lock_prerequisites_and_move_mastered_to_end(self) -> None:
        foundation = lesson_snapshot(
            SimpleNamespace(
                lesson_id="foundation",
                domain="literacy",
                title="Foundation",
                prerequisites=(),
            )
        )
        advanced = lesson_snapshot(
            SimpleNamespace(
                lesson_id="advanced",
                domain="literacy",
                title="Advanced",
                prerequisites=("foundation",),
            )
        )
        open_lesson = lesson_snapshot(
            SimpleNamespace(
                lesson_id="open",
                domain="math",
                title="Open",
                prerequisites=(),
            )
        )

        locked = ordered_plan_lessons(
            ("foundation", "advanced", "open"),
            (foundation, advanced, open_lesson),
            {"foundation": "in_progress"},
        )
        unlocked = ordered_plan_lessons(
            ("foundation", "advanced", "open"),
            (foundation, advanced, open_lesson),
            {"foundation": "mastered"},
        )

        self.assertEqual(
            tuple(item.lesson.lesson_id for item in locked),
            ("foundation", "advanced", "open"),
        )
        self.assertTrue(locked[1].locked)
        self.assertEqual(locked[1].unmet_prerequisites, ("foundation",))
        self.assertEqual(
            tuple(item.lesson.lesson_id for item in unlocked),
            ("advanced", "open", "foundation"),
        )
        self.assertTrue(unlocked[-1].mastered)
        self.assertFalse(unlocked[0].locked)

    def test_name_keyboard_includes_letters_and_all_digits(self) -> None:
        self.assertEqual(TEXT_ENTRY_KEYS[:26], "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        self.assertEqual(TEXT_ENTRY_KEYS[26:], "0123456789")

    def test_pin_display_and_repr_never_expose_entered_digits(self) -> None:
        pin = PinEntry()
        pin.push("2")
        pin.push("4")

        self.assertNotIn("2", pin.masked)
        self.assertNotIn("4", pin.masked)
        self.assertNotIn("24", repr(pin))
        pin.push("6")
        pin.push("8")
        self.assertTrue(pin.complete)
        self.assertEqual(pin.consume(), "2468")
        self.assertFalse(pin.complete)

    def test_teacher_text_entry_accepts_digits_and_normalizes_spacing(self) -> None:
        entry = TextEntry(maximum=16)
        for character in "ADA  LOVELACE1":
            entry.push(character)

        self.assertIn("1", entry.value)
        self.assertFalse(entry.value.startswith(" "))
        self.assertEqual(entry.cleaned, "ADA LOVELACE1")

    def test_page_cursor_clamps_and_reorder_keeps_every_lesson(self) -> None:
        cursor = PageCursor(3)
        values = tuple(range(7))

        self.assertEqual(cursor.current(values), (0, 1, 2))
        self.assertTrue(cursor.next())
        self.assertTrue(cursor.next())
        self.assertFalse(cursor.next())
        cursor.set_count(2)
        self.assertEqual(cursor.page_index, 0)
        self.assertEqual(reorder_item(("a", "b", "c"), 1, -1), ("b", "a", "c"))
        self.assertEqual(reorder_item(("a", "b", "c"), 0, -1), ("a", "b", "c"))

    def test_prerequisite_warning_is_narrow_and_teacher_can_override(self) -> None:
        lessons = (
            SimpleNamespace(lesson_id="letters", prerequisites=()),
            SimpleNamespace(lesson_id="words", prerequisites=("letters",)),
        )

        self.assertEqual(
            missing_prerequisites("words", (), lessons),
            ("letters",),
        )
        self.assertEqual(missing_prerequisites("words", ("letters",), lessons), ())

    def test_lesson_selector_filters_large_catalog_by_domain_and_family(self) -> None:
        lessons = tuple(
            lesson_snapshot(item)
            for item in (
                SimpleNamespace(
                    lesson_id="literacy.letter.a",
                    domain="literacy",
                    title="Letter A",
                    prerequisites=(),
                ),
                SimpleNamespace(
                    lesson_id="literacy.sight.one",
                    domain="literacy",
                    title="Sight Word One",
                    prerequisites=("literacy.letter.a",),
                ),
                SimpleNamespace(
                    lesson_id="math.count.zero",
                    domain="math",
                    title="Count Zero",
                    prerequisites=(),
                ),
            )
        )

        self.assertEqual(lesson_filter_domains(lessons), ("literacy", "math"))
        self.assertEqual(
            lesson_filter_families(lessons, "literacy"),
            ("letter", "sight"),
        )
        self.assertEqual(
            tuple(
                item.lesson_id
                for item in filter_lessons(
                    lessons,
                    domain="literacy",
                    family="letter",
                )
            ),
            ("literacy.letter.a",),
        )

    def test_bulk_selection_warns_only_for_foundations_outside_bulk_set(self) -> None:
        foundation = lesson_snapshot(
            SimpleNamespace(
                lesson_id="literacy.letter.a",
                domain="literacy",
                title="Letter A",
                prerequisites=(),
            )
        )
        word = lesson_snapshot(
            SimpleNamespace(
                lesson_id="literacy.sight.one",
                domain="literacy",
                title="Sight Word One",
                prerequisites=(foundation.lesson_id,),
            )
        )

        self.assertEqual(bulk_missing_prerequisites((word,), ()), (foundation.lesson_id,))
        self.assertEqual(bulk_missing_prerequisites((foundation, word), ()), ())
        self.assertEqual(
            bulk_missing_prerequisites((word,), (foundation.lesson_id,)),
            (),
        )

    def test_plan_question_count_clamps_and_mastery_gate_toggles(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._plan_draft_question_count = 1
        app._plan_draft_repetitions = 1
        app._plan_draft_mastery_gate = False
        app._show_plan_editor = Mock()

        app._adjust_plan_questions(-1)
        self.assertEqual(app._plan_draft_question_count, 1)
        app._adjust_plan_questions(50)
        self.assertEqual(app._plan_draft_question_count, 20)
        app._adjust_plan_repetitions(-1)
        self.assertEqual(app._plan_draft_repetitions, 1)
        app._adjust_plan_repetitions(50)
        self.assertEqual(app._plan_draft_repetitions, 10)
        app._toggle_draft_mastery()
        self.assertTrue(app._plan_draft_mastery_gate)

    def test_plan_reorder_pagination_follows_a_lesson_across_pages(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._plan_draft_lessons = ["a", "b", "c", "d", "e", "f"]
        app._plan_lesson_pages = PageCursor(4)
        app._plan_lesson_pages.set_count(6)
        app._show_plan_editor = Mock()

        app._move_lesson(3, 1)

        self.assertEqual(app._plan_draft_lessons, ["a", "b", "c", "e", "d", "f"])
        self.assertEqual(app._plan_lesson_pages.page_index, 1)
        app._show_plan_editor.assert_called_once_with()

    def test_domain_and_family_open_as_selection_lists(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._lessons = tuple(
            lesson_snapshot(item)
            for item in (
                SimpleNamespace(lesson_id="literacy.letter.a", domain="literacy", title="A"),
                SimpleNamespace(lesson_id="literacy.sight.one", domain="literacy", title="One"),
                SimpleNamespace(lesson_id="math.count.one", domain="math", title="One"),
            )
        )
        app._lesson_domain_filter = "literacy"
        app._lesson_family_filter = "letter"
        app._filter_picker_pages = PageCursor(4)
        app._lesson_pages = PageCursor(4)
        app._show_lesson_filter_picker = Mock()
        app._show_lesson_selector = Mock()

        app._open_lesson_filter("family")

        self.assertEqual(app._filter_picker_values, ("all", "letter", "sight"))
        app._show_lesson_filter_picker.assert_called_once_with()
        app._select_lesson_filter("sight")
        self.assertEqual(app._lesson_family_filter, "sight")
        app._show_lesson_selector.assert_called_once_with()

    def test_report_metrics_keep_points_and_fraction_semantics_distinct(self) -> None:
        metrics = dict(
            teacher_report_metrics(
                {
                    "completion_percent": 1.0,
                    "percentage_grade": 1.0,
                    "accuracy": 1.0,
                    "first_try_accuracy": 0.5,
                    "recent_trend": 0.6,
                    "attempt_count": 4,
                    "practiced_seconds": 121,
                }
            )
        )

        self.assertEqual(format_percent(1.0), "1%")
        self.assertEqual(format_percent(0.6, fractional=True), "60%")
        self.assertEqual(metrics["PLAN COMPLETE"], "1%")
        self.assertEqual(metrics["GRADE"], "1%")
        self.assertEqual(metrics["ACCURACY"], "100%")
        self.assertEqual(metrics["FIRST TRY"], "50%")
        self.assertEqual(metrics["RECENT TREND"], "60%")

    def test_authored_choice_color_requires_wcag_contrast_in_both_states(self) -> None:
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0)
        self.assertEqual(safe_choice_text_color("#124559"), "#124559")
        self.assertEqual(safe_choice_text_color("#FFFF00"), "#17324D")
        self.assertEqual(safe_choice_text_color("not-a-color"), "#17324D")

    def test_choice_button_applies_only_safe_authored_text_color(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.canvas = Mock()
        app.font_family = "Arial"
        app.font_families = ("Arial",)
        app._action_serial = 0
        app._regions = []
        app._callbacks = {}
        app._input_locked = False
        app._draw_scene = Mock(return_value=False)
        choice = question_snapshot(
            question(
                choices=(
                    SimpleNamespace(
                        id="safe",
                        label="Safe",
                        spoken="Safe",
                        metadata=(("color", "#124559"),),
                    ),
                )
            )
        ).choices[0]

        app._choice_button(Rect(20, 20, 180, 100), choice, "Safe", False, Mock())

        self.assertEqual(app.canvas.create_text.call_args.kwargs["fill"], "#124559")


class EvaluationAndSpeechTests(unittest.TestCase):
    def test_first_miss_gives_retry_feedback_and_second_miss_reveals(self) -> None:
        snapshot = question_snapshot(question())

        first = evaluation_snapshot(
            SimpleNamespace(correct=False, feedback="Notice the straight lines."),
            snapshot,
            1,
        )
        second = evaluation_snapshot(SimpleNamespace(correct=False), snapshot, 2)

        self.assertEqual(first.feedback, "Notice the straight lines.")
        self.assertIn("answer is A", second.feedback)
        self.assertEqual(second.reveal, "A")

    def make_speech_app(self, accepted: bool) -> LearningApp:
        app = LearningApp.__new__(LearningApp)
        app.closed = False
        app.speech_available = True
        app._speech_failed = False
        app.announce = Mock(return_value=accepted)
        return app

    def test_scoped_replay_uses_injected_announcer_and_completion(self) -> None:
        app = self.make_speech_app(True)
        completed = Mock()

        self.assertTrue(app._speak("Find A.", completed))

        app.announce.assert_called_once()
        text, callback = app.announce.call_args.args
        self.assertEqual(text, "Find A.")
        callback()
        completed.assert_called_once_with()

    def test_rejected_or_failed_announcement_redraws_lesson_with_replay_disabled(self) -> None:
        announcers = (
            Mock(return_value=False),
            Mock(side_effect=RuntimeError("voice unavailable")),
        )
        for announcer in announcers:
            with self.subTest(side_effect=announcer.side_effect):
                app = self.make_speech_app(True)
                app.announce = announcer
                app.screen = LearningScreen.LESSON
                app.canvas = Mock()
                app._show_lesson = Mock()

                self.assertFalse(app._speak("Find A.", None))

                self.assertTrue(app._speech_failed)
                self.assertFalse(app.replay_enabled)
                app._show_lesson.assert_called_once_with()

    def test_retry_clears_the_overlapping_lesson_notice(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._question_controller = Mock()
        app._input_locked = True
        app._status = "old retry banner"
        app._show_lesson = Mock()

        app._retry_question()

        self.assertEqual(app._status, "")
        app._question_controller.reset_for_retry.assert_called_once_with()

    def test_feedback_badge_keeps_wrapped_centered_text(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.canvas = Mock()
        app._feedback_retry = True
        app.font_family = "Arial"

        app._draw_feedback_badge()

        call = app.canvas.create_text.call_args
        self.assertEqual(call.args[:2], (400, 197))
        self.assertEqual(call.kwargs["text"], "TRY\nAGAIN")
        self.assertEqual(call.kwargs["justify"], "center")

    def test_speakable_word_has_a_separate_hear_touch_target(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.canvas = Mock()
        app.font_family = "Arial"
        app.font_families = ("Arial",)
        app._action_serial = 0
        app._regions = []
        app._callbacks = {}
        app._input_locked = False
        app.closed = False
        app.speech_available = True
        app._speech_failed = False
        app._draw_scene = Mock(return_value=False)
        app._speak = Mock(return_value=True)
        select = Mock()
        choice = question_snapshot(
            question(
                choices=(
                    SimpleNamespace(
                        id="cat",
                        label="cat",
                        spoken="cat",
                        metadata=(("speakable", True),),
                    ),
                )
            )
        ).choices[0]

        app._choice_button(Rect(20, 20, 180, 110), choice, "cat", False, select)

        hear_key = next(region.key for region in app._regions if region.key.startswith("speak-choice"))
        app._callbacks[hear_key]()
        app._speak.assert_called_once_with("cat", None)
        select.assert_not_called()

    def test_unavailable_word_speech_is_grey_and_does_not_select_through(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.canvas = Mock()
        app.font_family = "Arial"
        app.font_families = ("Arial",)
        app._action_serial = 0
        app._regions = []
        app._callbacks = {}
        app._input_locked = False
        app.closed = False
        app.speech_available = False
        app._speech_failed = False
        app._draw_scene = Mock(return_value=False)
        select = Mock()
        choice = question_snapshot(
            question(
                choices=(
                    SimpleNamespace(
                        id="cat",
                        label="cat",
                        spoken="cat",
                        metadata=(("speakable", True),),
                    ),
                )
            )
        ).choices[0]

        app._choice_button(Rect(20, 20, 180, 110), choice, "cat", False, select)

        speaker = next(
            region for region in app._regions if region.key.startswith("speak-choice")
        )
        self.assertEqual(hit_test(app._regions, speaker.bounds.center), speaker.key)
        self.assertNotIn(speaker.key, app._callbacks)
        select.assert_not_called()


class PersistenceAndLifecycleTests(unittest.TestCase):
    def test_new_plan_persists_repetitions_with_session_settings(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._selected_profile = SimpleNamespace(profile_id="learner")
        app._plan_draft_name = "Reading Practice"
        app._plan_draft_lessons = ["literacy.letter.a"]
        app._plan_draft_question_count = 6
        app._plan_draft_repetitions = 4
        app._plan_draft_mastery_gate = True
        create_plan = Mock()
        app.store = SimpleNamespace(create_plan=create_plan)
        app._load_plans = Mock()
        app._show_teacher_plans = Mock()
        app._show_error = Mock()

        app._save_new_plan()

        create_plan.assert_called_once_with(
            "learner",
            "Reading Practice",
            ("literacy.letter.a",),
            question_count=6,
            questions_per_session=6,
            session_size=6,
            repetitions=4,
            mastery_gate=True,
        )

    def test_plan_edit_persists_changed_repetitions(self) -> None:
        raw = {
            "plan_id": "plan",
            "profile_id": "learner",
            "name": "Foundations",
            "lesson_ids": ("a", "b"),
            "enabled": True,
            "question_count": 5,
            "repetitions": 1,
            "mastery_gate": False,
            "archived": False,
        }
        reordered = {**raw, "lesson_ids": ("b", "a")}
        saved = {**reordered, "repetitions": 3}
        app = LearningApp.__new__(LearningApp)
        app._selected_plan = plan_snapshot(raw)
        app._plan_draft_lessons = ["b", "a"]
        app._plan_draft_question_count = 5
        app._plan_draft_repetitions = 3
        app._plan_draft_mastery_gate = False
        app.default_question_count = 8
        app._plans = ()
        app.store = SimpleNamespace(
            reorder_plan_lessons=Mock(return_value=reordered),
            update_plan=Mock(return_value=saved),
        )
        app._load_plans = Mock()
        app._show_teacher_plan = Mock()
        app._show_error = Mock()

        app._save_plan_lessons()

        app.store.reorder_plan_lessons.assert_called_once_with("plan", ("b", "a"))
        update_payload = app.store.update_plan.call_args.args[0]
        self.assertEqual(update_payload["repetitions"], 3)

    def test_report_entry_resets_mastery_pagination(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._selected_plan = SimpleNamespace(plan_id="plan", name="Foundations")
        app.store = SimpleNamespace(plan_stats=Mock(return_value={"skills": range(8)}))
        app._mastery_pages = PageCursor(3)
        app._mastery_pages.set_count(8)
        app._mastery_pages.page_index = 2
        app._draw_stats = Mock()
        app._show_error = Mock()

        app._show_plan_stats()

        self.assertEqual(app._mastery_pages.page_index, 0)
        self.assertIs(app.previous_screen, LearningScreen.TEACHER_PLAN)
        app._draw_stats.assert_called_once_with("REPORT: FOUNDATIONS")

    def test_screen_header_mounts_shared_compact_face(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.canvas = Mock()
        app.font_family = "Arial"
        app.closed = False
        app.screen = LearningScreen.HOME
        app.compact_face = Mock()
        app.close = Mock()
        app._action_serial = 0
        app._regions = []
        app._callbacks = {}

        app._header("LEARNING")

        app.compact_face.mount.assert_called_once_with()

    def test_atomic_transition_is_preferred_over_two_separate_writes(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._session = object()
        app.store = SimpleNamespace(
            record_transition=Mock(),
            append_attempt=Mock(),
            save_session=Mock(),
        )
        attempt = object()

        self.assertTrue(app._persist_answer(attempt))

        app.store.record_transition.assert_called_once_with(attempt, app._session)
        app.store.append_attempt.assert_not_called()
        app.store.save_session.assert_not_called()

    def test_failed_transition_reports_unsaved_without_faking_success(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._session = object()
        app.store = SimpleNamespace(
            record_transition=Mock(side_effect=OSError("read only")),
        )

        self.assertFalse(app._persist_answer(object()))

    def test_close_cancels_speech_callbacks_and_returns_to_menu_once(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.closed = False
        app.cancel_announcements = Mock()
        app.on_close = Mock()
        app.root = Mock()
        canvas = Mock()
        app.canvas = canvas
        app._after_ids = {"feedback"}
        app.compact_face = Mock()

        app.close()
        app.close()

        app.cancel_announcements.assert_called_once_with()
        app.root.after_cancel.assert_called_once_with("feedback")
        app.compact_face.destroy.assert_called_once_with()
        canvas.destroy.assert_called_once_with()
        app.on_close.assert_called_once_with()
        self.assertTrue(app.closed)

    def test_constructor_uses_exact_kiosk_canvas_size(self) -> None:
        fake_canvas = Mock()
        root = Mock()
        config = SimpleNamespace(
            speech_enabled=False,
            font_families=("Arial",),
            default_session_questions=5,
        )
        store = SimpleNamespace(list_profiles=Mock(return_value=()))

        with (
            patch("bmo.ui.learning.tk.Canvas", return_value=fake_canvas) as canvas_type,
            patch.object(LearningApp, "_show_home"),
            patch("bmo.ui.learning.CompactFace") as compact_face,
        ):
            app = LearningApp(
                root,
                config=config,
                catalog=(),
                engine=object(),
                store=store,
                face_provider=lambda: None,
                announce=Mock(return_value=False),
                cancel_announcements=Mock(),
                announcements_available=False,
                on_close=Mock(),
            )

        canvas_type.assert_called_once_with(
            root,
            width=800,
            height=480,
            bg=LearningApp.BACKGROUND,
            highlightthickness=0,
        )
        fake_canvas.place.assert_called_once_with(x=0, y=0, width=800, height=480)
        compact_face.assert_called_once()
        self.assertFalse(app.replay_enabled)

    def test_invoke_filters_optional_adapter_keywords(self) -> None:
        called: list[tuple[str, int]] = []

        def method(name: str, question_count: int = 3) -> tuple[str, int]:
            called.append((name, question_count))
            return called[-1]

        result = LearningApp._invoke(
            method,
            "letters",
            question_count=7,
            unsupported="ignored",
        )

        self.assertEqual(result, ("letters", 7))

    def test_elapsed_time_is_bounded_and_passed_to_engine(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app.engine = SimpleNamespace(submit=Mock(return_value="transition"))
        app._session = object()
        app._question_started_at = 10.0

        with patch("bmo.ui.learning.time.monotonic", return_value=13.25):
            result = app._engine_submit("c0", 1)

        self.assertEqual(result, "transition")
        app.engine.submit.assert_called_once_with(
            app._session,
            "c0",
            elapsed_seconds=3.25,
        )

    def test_selected_lesson_starts_only_its_per_lesson_question_count(self) -> None:
        app = LearningApp.__new__(LearningApp)
        raw_plan = SimpleNamespace(plan_id="plan", profile_id="learner")
        app._selected_profile = SimpleNamespace(profile_id="learner")
        app._selected_plan = SimpleNamespace(
            plan_id="plan",
            lesson_ids=("foundation", "later"),
            mastery_gate=True,
            question_count=4,
            repetitions=1,
            raw=raw_plan,
        )
        app._selected_lesson_id = "later"
        app.config = SimpleNamespace(
            mastery_threshold=0.8,
            mastery_min_evidence=5,
        )
        app.store = object()
        app.engine = SimpleNamespace(
            eligible_lesson_ids=Mock(return_value=("foundation",)),
            start_session=Mock(return_value="session"),
        )
        app._status = ""
        app._persist_session = Mock(return_value=True)
        app._resume_session = Mock()
        app._show_error = Mock()

        app._start_new_session()

        app.engine.eligible_lesson_ids.assert_not_called()
        app.engine.start_session.assert_called_once_with(
            profile_id="learner",
            plan_id="plan",
            lesson_ids=("later",),
            question_count=4,
            repetitions=1,
        )

    def test_plan_name_can_be_changed_from_edit_flow(self) -> None:
        raw = {
            "plan_id": "plan",
            "profile_id": "learner",
            "name": "Old Name",
            "lesson_ids": ("foundation",),
            "enabled": True,
            "question_count": 4,
            "repetitions": 1,
            "mastery_gate": False,
            "archived": False,
        }
        app = LearningApp.__new__(LearningApp)
        app._selected_plan = plan_snapshot(raw)
        app._text_entry = TextEntry(value="New Plan 2")
        app._text_purpose = "rename_plan"
        app._plan_draft_name = "Old Name"
        app.default_question_count = 8
        app.store = SimpleNamespace(update_plan=Mock(side_effect=lambda value: value))
        app._load_plans = Mock()
        app._show_plan_editor = Mock()
        app._show_error = Mock()

        app._save_text_entry()

        payload = app.store.update_plan.call_args.args[0]
        self.assertEqual(payload["name"], "New Plan 2")
        self.assertEqual(app._plan_draft_name, "New Plan 2")
        self.assertEqual(app._selected_plan.name, "New Plan 2")
        app._show_plan_editor.assert_called_once_with()

    def test_new_session_surfaces_nonfatal_initial_save_failure(self) -> None:
        app = LearningApp.__new__(LearningApp)
        app._selected_profile = SimpleNamespace(profile_id="learner")
        app._selected_plan = SimpleNamespace(
            plan_id="plan",
            lesson_ids=("foundation",),
            mastery_gate=False,
            question_count=4,
            repetitions=1,
            raw=object(),
        )
        app.engine = SimpleNamespace(start_session=Mock(return_value="session"))
        app.store = object()
        app._status = ""
        app._persist_session = Mock(return_value=False)
        app._resume_session = Mock()
        app._show_error = Mock()

        app._start_new_session()

        self.assertFalse(app._progress_saved)
        app._resume_session.assert_called_once_with()

    def test_actual_engine_store_flow_resumes_and_builds_report(self) -> None:
        from bmo.features.learning.curriculum import CURRICULUM
        from bmo.features.learning.engine import LearningEngine
        from bmo.features.learning.store import LearningStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            store = LearningStore(root, mastery_min_evidence=2)
            profile = store.create_profile("Test Learner")
            plan = store.create_plan(
                profile.profile_id,
                "Foundations",
                ("literacy.letter.upper.a.single", "math.count.0_10"),
                questions_per_session=3,
            )
            engine = LearningEngine(CURRICULUM, rng=Random(7))
            session = engine.start_session(
                profile.profile_id,
                plan.plan_id,
                lesson_ids=plan.lesson_ids,
                question_count=plan.questions_per_session,
            )
            store.save_session(session)
            current = engine.current_question(session)
            assert current is not None
            transition = engine.submit(
                session,
                current.correct_answers[0],
                elapsed_seconds=1.25,
            )

            store.record_transition(transition.attempt, transition.session)

            resumed = store.resumable_session(profile.profile_id, plan.plan_id)
            report = store.plan_stats(plan.plan_id)
            self.assertIsNotNone(resumed)
            assert resumed is not None
            self.assertEqual(resumed.question_index, 1)
            self.assertEqual(report.attempt_count, 1)
            self.assertEqual(report.percentage_grade, 100.0)
            self.assertTrue(root.is_dir())


if __name__ == "__main__":
    unittest.main()
