"""Production Qt Teacher Area navigation and mutation tests for Learning."""

from __future__ import annotations

from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bmo.features.learning import CURRICULUM, LearningConfig
from bmo.features.learning.store import LearningStore
from bmo.qt.views.learning import QtLearningView


class _Host:
    def __init__(self) -> None:
        self.view: QtLearningView | None = None
        self.payloads: list[dict[str, object]] = []

    def present(self, view: QtLearningView) -> None:
        self.view = view
        self.payloads.append(view.payload())

    def update(self, view: QtLearningView) -> None:
        self.payloads.append(view.payload())

    def dismiss(self, view: QtLearningView) -> None:
        if self.view is view:
            self.view = None


class QtLearningTeacherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = LearningStore(Path(self.temporary.name) / "learning")
        self.host = _Host()
        self.cancel_announcements = Mock()
        self.on_close = Mock()
        self.view = QtLearningView(
            self.host,
            config=LearningConfig(
                data_directory=Path(self.temporary.name) / "learning",
                teacher_pin="2468",
                default_session_questions=8,
            ),
            catalog=CURRICULUM,
            engine=Mock(),
            store=self.store,
            announce=Mock(),
            cancel_announcements=self.cancel_announcements,
            announcements_available=False,
            on_close=self.on_close,
        )
        self.addCleanup(self.view.close)

    def authenticate(self) -> None:
        self.view.handle_action("learning_teacher", "")
        for digit in "2468":
            self.view.handle_action("learning_teacher_digit", digit)
        self.assertTrue(self.view.teacher_authorized)
        self.assertEqual(self.view.screen, "teacher_home")

    def select_profile(self, name: str = "Ava") -> object:
        profile = self.store.create_profile(name)
        self.view.handle_action("learning_teacher_profile", profile.profile_id)
        self.assertEqual(self.view.screen, "teacher_profile")
        return profile

    def type_name(self, value: str) -> None:
        self.view.handle_action("learning_text_clear", "")
        for character in value:
            self.view.handle_action("learning_text_key", character)

    def test_pin_and_touch_keypad_create_rename_and_cancel(self) -> None:
        self.view.handle_action("learning_teacher", "")
        self.view.handle_action("learning_teacher_digit", "2")
        self.view.handle_action("learning_teacher_backspace", "")
        self.assertEqual(self.view.teacher_pin, "")
        for digit in "2468":
            self.view.handle_action("learning_teacher_digit", digit)

        self.view.handle_action("learning_text_open", "new_profile")
        self.assertEqual(self.view.screen, "teacher_text")
        self.type_name("AVA 2")
        self.view.handle_action("learning_text_save", "")

        profile = self.store.list_profiles()[0]
        self.assertEqual(profile.display_name, "AVA 2")
        self.assertEqual(self.view.screen, "teacher_profile")

        self.view.handle_action("learning_text_open", "rename_profile")
        self.type_name("MIA")
        self.view.handle_action("learning_text_cancel", "")
        self.assertEqual(
            self.store.get_profile(profile.profile_id).display_name,
            "AVA 2",
        )

        self.view.handle_action("learning_text_open", "rename_profile")
        self.type_name("MIA")
        self.view.handle_action("learning_text_save", "")
        self.assertEqual(
            self.store.get_profile(profile.profile_id).display_name,
            "MIA",
        )

    def test_new_plan_chooser_filters_override_and_editor_persist_all_settings(self) -> None:
        self.authenticate()
        profile = self.select_profile()

        self.view.handle_action("learning_text_open", "new_plan")
        self.type_name("LETTER STEPS")
        self.view.handle_action("learning_text_save", "")
        self.assertEqual(self.view.screen, "teacher_lessons")
        self.assertEqual(self.store.list_plans(profile.profile_id), ())

        self.view.handle_action("learning_lesson_filter", "domain")
        self.view.handle_action("learning_set_lesson_filter", "readiness")
        self.view.handle_action("learning_lesson_filter", "family")
        self.view.handle_action("learning_set_lesson_filter", "plant_growth")
        self.view.handle_action("learning_bulk_add_lessons", "")
        self.assertEqual(self.view.plan_draft_lessons, ["readiness.plant_growth"])
        self.view.handle_action("learning_teacher_back", "")
        self.view.handle_action("learning_plan_remove", "readiness.plant_growth")
        self.assertEqual(self.view.plan_draft_lessons, [])
        self.view.handle_action("learning_choose_lessons", "")

        self.view.handle_action("learning_lesson_filter", "domain")
        self.assertEqual(self.view.screen, "teacher_lesson_filter")
        self.view.handle_action("learning_set_lesson_filter", "literacy")
        self.view.handle_action("learning_lesson_filter", "family")
        family_values = {
            item["value"] for item in self.view.payload()["lessonFilterValues"]
        }
        self.assertIn("letter", family_values)
        self.view.handle_action("learning_set_lesson_filter", "letter")
        self.assertTrue(self.view.payload()["lessonChoices"])

        foundation = "literacy.letter.upper.a.single"
        dependent = "literacy.letter.upper.a.multi"
        self.view.handle_action("learning_toggle_lesson", foundation)
        self.view.handle_action("learning_toggle_lesson", dependent)
        self.assertEqual(
            self.view.plan_draft_lessons,
            [foundation, dependent],
        )
        self.view.handle_action("learning_teacher_back", "")
        self.assertEqual(self.view.screen, "teacher_plan_edit")

        self.view.handle_action("learning_plan_adjust", "questions:1")
        self.view.handle_action("learning_plan_adjust", "repetitions:1")
        self.view.handle_action("learning_plan_gate", "")
        self.view.handle_action("learning_plan_move", "1:-1")
        self.view.handle_action("learning_save_plan", "")
        self.assertEqual(self.view.screen, "teacher_confirm")
        self.assertEqual(self.store.list_plans(profile.profile_id), ())

        self.view.handle_action("learning_confirm_cancel", "")
        self.assertEqual(self.view.screen, "teacher_plan_edit")
        self.view.handle_action("learning_save_plan", "")
        self.view.handle_action("learning_confirm", "")

        plan = self.store.list_plans(profile.profile_id)[0]
        self.assertEqual(plan.lesson_ids, (dependent, foundation))
        self.assertEqual(plan.questions_per_session, 9)
        self.assertEqual(plan.repetitions, 2)
        self.assertTrue(plan.mastery_gate)

        self.view.handle_action("learning_edit_plan", "")
        self.view.handle_action("learning_plan_move", "0:1")
        self.view.handle_action("learning_plan_adjust", "questions:-1")
        self.view.handle_action("learning_plan_adjust", "repetitions:-1")
        self.view.handle_action("learning_plan_gate", "")
        self.view.handle_action("learning_text_open", "rename_plan")
        self.type_name("CORE 2")
        self.view.handle_action("learning_text_save", "")
        self.view.handle_action("learning_save_plan", "")

        updated = self.store.get_plan(plan.plan_id)
        self.assertEqual(updated.title, "CORE 2")
        self.assertEqual(updated.lesson_ids, (foundation, dependent))
        self.assertEqual(updated.questions_per_session, 8)
        self.assertEqual(updated.repetitions, 1)
        self.assertFalse(updated.mastery_gate)
        self.assertEqual(len(self.store.list_plans(profile.profile_id)), 1)

    def test_lifecycle_buttons_confirm_once_and_restore_archived_records(self) -> None:
        self.authenticate()
        profile = self.select_profile()
        plan = self.store.create_plan(
            profile.profile_id,
            "Foundations",
            ("literacy.letter.upper.a.single",),
        )
        self.view.handle_action("learning_teacher_plan", plan.plan_id)

        self.view.handle_action("learning_duplicate_plan", "")
        duplicate = self.view.teacher_plan
        self.assertIsNotNone(duplicate)
        self.assertEqual(len(self.store.list_plans(profile.profile_id)), 2)
        self.view.handle_action("learning_toggle_plan", "")
        self.assertFalse(self.view.teacher_plan.enabled)

        with patch.object(
            self.store,
            "reset_progress",
            wraps=self.store.reset_progress,
        ) as reset:
            self.view.handle_action("learning_reset_plan", "")
            reset.assert_not_called()
            self.view.handle_action("learning_confirm_cancel", "")
            reset.assert_not_called()
            self.view.handle_action("learning_reset_plan", "")
            self.view.handle_action("learning_confirm", "")
            reset.assert_called_once_with(
                profile.profile_id,
                plan_id=duplicate.plan_id,
                confirmed=True,
            )
            self.view.handle_action("learning_confirm", "")
            self.assertEqual(reset.call_count, 1)

        with patch.object(
            self.store,
            "archive_plan",
            wraps=self.store.archive_plan,
        ) as archive:
            self.view.handle_action("learning_archive_plan", "")
            archive.assert_not_called()
            self.view.handle_action("learning_confirm", "")
            archive.assert_called_once_with(duplicate.plan_id, confirmed=True)

        self.assertTrue(self.view.teacher_plan.archived)
        self.assertFalse(self.view.teacher_plan.enabled)
        self.view.handle_action("learning_toggle_plan", "")
        self.assertIn("Restore", self.view.error)
        self.assertFalse(self.store.get_plan(duplicate.plan_id).enabled)
        self.view.handle_action("learning_restore_plan", "")
        self.assertFalse(self.view.teacher_plan.archived)

        self.view.handle_action("learning_teacher_back", "")
        with patch.object(
            self.store,
            "archive_profile",
            wraps=self.store.archive_profile,
        ) as archive_profile:
            self.view.handle_action("learning_archive_profile", "")
            archive_profile.assert_not_called()
            self.view.handle_action("learning_confirm", "")
            archive_profile.assert_called_once_with(
                profile.profile_id,
                confirmed=True,
            )
        self.assertTrue(self.view.teacher_profile.archived)
        self.view.handle_action("learning_restore_profile", "")
        self.assertFalse(self.view.teacher_profile.archived)

        with patch.object(
            self.store,
            "reset_progress",
            wraps=self.store.reset_progress,
        ) as reset_profile:
            self.view.handle_action("learning_reset_profile", "")
            reset_profile.assert_not_called()
            self.view.handle_action("learning_confirm", "")
            reset_profile.assert_called_once_with(
                profile.profile_id,
                confirmed=True,
            )

    def test_reports_keep_all_metrics_and_skill_rows_separate(self) -> None:
        self.authenticate()
        profile = self.select_profile()
        plan = self.store.create_plan(
            profile.profile_id,
            "Foundations",
            ("literacy.letter.upper.a.single",),
        )

        self.view.handle_action("learning_teacher_report", "")
        report = self.view.payload()["report"]
        self.assertEqual(len(report["metrics"]), 8)
        self.assertEqual(
            {item["label"] for item in report["metrics"]},
            {
                "ACCURACY",
                "ATTEMPTS",
                "COMPLETE",
                "EVENTUAL",
                "FIRST TRY",
                "GRADE",
                "MINUTES",
                "RECENT",
            },
        )
        self.view.handle_action("learning_teacher_back", "")
        self.view.handle_action("learning_teacher_plan", plan.plan_id)
        self.view.handle_action("learning_teacher_report", "")
        self.assertEqual(self.view.report_return, "teacher_plan")
        self.assertEqual(self.view.payload()["report"]["skills"], [])

        skills = QtLearningView._report_skills(
            SimpleNamespace(
                skills=(
                    SimpleNamespace(
                        skill="letter.upper",
                        status=SimpleNamespace(value="mastered"),
                        percentage_grade=92,
                    ),
                )
            )
        )
        self.assertEqual(
            skills,
            [
                {
                    "label": "letter · upper",
                    "status": "MASTERED",
                    "grade": "92%",
                }
            ],
        )

        normalized = QtLearningView._report_metrics(
            SimpleNamespace(
                completion_percent=62,
                percentage_grade=84,
                accuracy=0.75,
                first_try_accuracy=0.5,
                eventual_accuracy=1.0,
                recent_trend=0.8,
                attempt_count=9,
                practiced_seconds=121,
            )
        )
        values = {item["label"]: item["value"] for item in normalized}
        self.assertEqual(values["COMPLETE"], "62%")
        self.assertEqual(values["GRADE"], "84%")
        self.assertEqual(values["ACCURACY"], "75%")
        self.assertEqual(values["EVENTUAL"], "100%")
        self.assertEqual(values["MINUTES"], "2")

    def test_qml_actions_and_required_teacher_menus_have_production_contracts(self) -> None:
        qml_path = (
            Path(__file__).resolve().parents[1]
            / "bmo"
            / "qt"
            / "qml"
            / "LearningView.qml"
        )
        source = qml_path.read_text(encoding="utf-8")
        actions = set(re.findall(r'root\.send\("(learning_[a-z_]+)"', source))
        adapter_source = Path(QtLearningView.__module__.replace(".", "/") + ".py")
        adapter_source = (
            Path(__file__).resolve().parents[1] / adapter_source
        ).read_text(encoding="utf-8")
        handled_actions = set(
            re.findall(r'action == "(learning_[a-z_]+)"', adapter_source)
        )

        self.assertEqual(actions - QtLearningView.SUPPORTED_ACTIONS, set())
        self.assertEqual(actions - handled_actions, set())
        self.assertTrue(
            {
                "learning_archive_plan",
                "learning_archive_profile",
                "learning_bulk_add_lessons",
                "learning_confirm",
                "learning_duplicate_plan",
                "learning_edit_plan",
                "learning_plan_move",
                "learning_reset_plan",
                "learning_reset_profile",
                "learning_restore_plan",
                "learning_restore_profile",
                "learning_save_plan",
                "learning_text_open",
                "learning_toggle_lesson",
            }.issubset(actions)
        )
        for object_name in (
            "learningTeacherPlanEditPage",
            "learningPlanLessonList",
            "learningTeacherLessonsPage",
            "learningLessonCatalog",
            "learningTeacherLessonFilterPage",
            "learningTeacherTextPage",
            "learningNameKeyboard",
            "learningTeacherConfirmPage",
            "learningReportSkillList",
        ):
            with self.subTest(object_name=object_name):
                self.assertIn(f'objectName: "{object_name}"', source)


if __name__ == "__main__":
    unittest.main()
