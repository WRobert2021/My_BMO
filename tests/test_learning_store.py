"""Focused private-configuration and persistence tests for Learning."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bmo.features.learning.store as learning_store_module
from bmo.features.learning.config import (
    DEFAULT_DATA_DIRECTORY,
    DEFAULT_GRAPHICS_DIRECTORY,
    LearningConfig,
    load_learning_config,
)
from bmo.features.learning.models import (
    AttemptRecord,
    Choice,
    InteractionKind,
    LearningSession,
    Question,
)
from bmo.features.learning.store import (
    MAX_PROFILE_SKILL_SUMMARIES,
    LearningConfirmationRequired,
    LearningPersistenceError,
    LearningReadOnlyError,
    LearningStore,
    LearningStoreError,
)


STAMP = "2026-08-12T12:00:00Z"


def make_question(index: int = 1, lesson_id: str = "letters.uppercase") -> Question:
    return Question(
        question_id=f"question_{index}",
        lesson_id=lesson_id,
        domain="literacy",
        skills=(lesson_id,),
        interaction=InteractionKind.SINGLE_CHOICE,
        prompt="Find A.",
        spoken_prompt="Find the letter A.",
        choices=(Choice("a", "A"), Choice("b", "B")),
        correct_answers=("a",),
    )


def make_attempt(
    index: int,
    profile_id: str,
    plan_id: str | None,
    *,
    session_id: str = "session_one",
    lesson_id: str = "letters.uppercase",
    skills: tuple[str, ...] | None = None,
    question_id: str | None = None,
    attempt_number: int = 1,
    correct: bool = True,
    timestamp: str = STAMP,
) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=f"attempt_{index}",
        session_id=session_id,
        profile_id=profile_id,
        plan_id=plan_id,
        lesson_id=lesson_id,
        skills=skills or (lesson_id,),
        question_id=question_id or f"question_{index}",
        correct_answers=("a",),
        response=("a" if correct else "b",),
        correct=correct,
        attempt_number=attempt_number,
        scaffolded=attempt_number > 1,
        hint_used=False,
        revealed=False,
        elapsed_seconds=2.5,
        timestamp=timestamp,
    )


def make_session(
    profile_id: str,
    plan_id: str | None,
    *,
    question_index: int = 0,
    attempts: tuple[AttemptRecord, ...] = (),
) -> LearningSession:
    return LearningSession(
        session_id="session_one",
        profile_id=profile_id,
        plan_id=plan_id,
        questions=(make_question(),),
        question_index=question_index,
        current_attempt=0,
        scaffolded=False,
        attempts=attempts,
        started_at=STAMP,
        updated_at=STAMP,
    )


class LearningConfigTests(unittest.TestCase):
    def test_defaults_are_private_bounded_and_pin_is_not_in_repr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_learning_config(
                {"config_path": root / "missing.json"},
                project_root=root,
            )

            self.assertEqual(config.data_directory, DEFAULT_DATA_DIRECTORY)
            self.assertEqual(config.graphics_directory, DEFAULT_GRAPHICS_DIRECTORY)
            self.assertTrue(config.show_in_menu)
            self.assertTrue(config.verify_teacher_pin("0000"))
            self.assertFalse(config.verify_teacher_pin(0))
            self.assertNotIn("0000", repr(config))
            self.assertFalse((root / "bmo" / "data").exists())
            self.assertFalse((root / "graphics").exists())

    def test_private_file_and_only_learning_owned_overrides_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "learning.json"
            path.write_text(
                json.dumps(
                    {
                        "data_directory": "data/classroom",
                        "graphics_directory": "graphics/learning",
                        "teacher_pin": "2468",
                        "default_session_questions": 7,
                        "mastery_threshold": 0.85,
                        "mastery_min_evidence": 6,
                        "history_limit": 100,
                        "mastery_history_limit": 12,
                        "font_families": ["DejaVu Sans", "Liberation Sans"],
                        "speech_enabled": False,
                        "debug_seed": 12,
                    }
                ),
                encoding="utf-8",
            )

            config = load_learning_config(
                {
                    "config_path": path,
                    "show_in_menu": False,
                    "unrelated_shared_setting": "ignored",
                },
                project_root=root,
            )

            self.assertEqual(config.data_directory, Path("bmo/data/classroom"))
            self.assertFalse(config.show_in_menu)
            self.assertTrue(config.verify_teacher_pin("2468"))
            self.assertEqual(config.default_session_questions, 7)
            self.assertEqual(config.mastery_threshold, 0.85)
            self.assertEqual(config.font_families, ("DejaVu Sans", "Liberation Sans"))
            self.assertFalse(config.speech_enabled)
            self.assertEqual(config.debug_seed, 12)

    def test_relative_config_path_is_resolved_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_directory = root / "config"
            config_directory.mkdir()
            (config_directory / "learning.json").write_text(
                json.dumps(
                    {
                        "teacher_pin": "8642",
                        "default_session_questions": 6,
                    }
                ),
                encoding="utf-8",
            )

            config = load_learning_config(
                {"config_path": "config/learning.json"},
                project_root=root,
            )

            self.assertTrue(config.verify_teacher_pin("8642"))
            self.assertEqual(config.default_session_questions, 6)
            self.assertEqual(config.data_directory, Path("bmo/data/learning"))

    def test_mastery_history_must_cover_minimum_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[str] = []

            config = load_learning_config(
                {
                    "config_path": root / "missing.json",
                    "mastery_min_evidence": 10,
                    "mastery_history_limit": 5,
                },
                reporter=messages.append,
                project_root=root,
            )

            self.assertEqual(config, LearningConfig())
            self.assertEqual(len(messages), 1)
            self.assertIn("mastery_history_limit", messages[0])

    def test_malformed_or_unknown_private_config_is_preserved_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "malformed.json"
            malformed.write_text('{"teacher_pin":"9753",', encoding="utf-8")
            messages: list[str] = []

            config = load_learning_config(
                {"config_path": malformed},
                reporter=messages.append,
                project_root=root,
            )

            self.assertEqual(config, LearningConfig())
            self.assertEqual(malformed.read_text(encoding="utf-8"), '{"teacher_pin":"9753",')
            self.assertEqual(len(messages), 1)
            self.assertNotIn("9753", messages[0])

            unknown = root / "unknown.json"
            unknown.write_text('{"teacher_pin":"1357","foreign":true}', encoding="utf-8")
            messages.clear()
            config = load_learning_config(
                {"config_path": unknown}, reporter=messages.append, project_root=root
            )
            self.assertEqual(config, LearningConfig())
            self.assertNotIn("1357", messages[0])

    def test_duplicate_or_non_finite_private_config_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "learning.json"
            for payload in (
                '{"teacher_pin":"1111","teacher_pin":"2222"}',
                '{"mastery_threshold":NaN}',
            ):
                messages: list[str] = []
                path.write_text(payload, encoding="utf-8")

                config = load_learning_config(
                    {"config_path": path},
                    reporter=messages.append,
                    project_root=root,
                )

                self.assertEqual(config, LearningConfig())
                self.assertEqual(len(messages), 1)
                self.assertNotIn("1111", messages[0])
                self.assertNotIn("2222", messages[0])

    def test_invalid_bounds_and_path_escapes_fall_back_without_creating_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            messages: list[str] = []
            config = load_learning_config(
                {
                    "data_directory": "outside-learning",
                    "default_session_questions": 99,
                },
                reporter=messages.append,
                project_root=root,
            )
            self.assertEqual(config, LearningConfig())
            self.assertEqual(len(messages), 1)
            self.assertFalse((root / "outside-learning").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_config_rejects_a_learning_directory_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "bmo" / "data").mkdir(parents=True)
            (root / "bmo" / "data" / "jump").symlink_to(
                Path(outside), target_is_directory=True
            )
            messages: list[str] = []

            config = load_learning_config(
                {"data_directory": "bmo/data/jump/learning"},
                reporter=messages.append,
                project_root=root,
            )

            self.assertEqual(config, LearningConfig())
            self.assertEqual(len(messages), 1)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_unsafe_default_data_root_disables_menu_instead_of_writing_outside(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "bmo").mkdir()
            (root / "bmo" / "data").symlink_to(
                Path(outside), target_is_directory=True
            )
            messages: list[str] = []

            config = load_learning_config(
                {"config_path": root / "missing.json"},
                reporter=messages.append,
                project_root=root,
            )

            self.assertFalse(config.show_in_menu)
            self.assertFalse((Path(outside) / "learning").exists())
            self.assertEqual(len(messages), 1)


class LearningStoreTests(unittest.TestCase):
    def make_store(
        self,
        root: Path,
        *,
        history_limit: int = 10,
        reporter=None,
    ) -> LearningStore:
        return LearningStore(
            root,
            history_limit=history_limit,
            mastery_history_limit=5,
            mastery_min_evidence=2,
            reporter=reporter or (lambda _message: None),
            now=lambda: datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
            id_factory=iter(
                (
                    "profileid",
                    "planid",
                    "copyid",
                    "moreid",
                )
            ).__next__,
        )

    def test_constructor_and_empty_reads_do_not_create_the_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bmo" / "data" / "learning"
            store = self.make_store(root)

            self.assertFalse(root.exists())
            self.assertEqual(store.list_profiles(), ())
            self.assertEqual(store.list_plans(), ())
            self.assertFalse(root.exists())

    def test_writes_reuse_each_validated_serialized_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            with patch(
                "bmo.features.learning.store._profile_to_json",
                wraps=learning_store_module._profile_to_json,
            ) as profile_to_json:
                profile = store.create_profile("River")
            self.assertEqual(profile_to_json.call_count, 1)

            with patch(
                "bmo.features.learning.store._plan_to_json",
                wraps=learning_store_module._plan_to_json,
            ) as plan_to_json:
                store.create_plan(
                    profile.profile_id,
                    "Letters",
                    ("letters.uppercase",),
                )
            self.assertEqual(plan_to_json.call_count, 1)

    def test_profile_and_plan_crud_round_trip_with_stable_ids_and_utc_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            store = self.make_store(root)
            profile = store.create_profile("River")
            renamed = store.rename_profile(profile.profile_id, "Rae")
            plan = store.create_plan(
                profile.profile_id,
                "Letter Start",
                ("letters.uppercase", "letters.lowercase"),
                questions_per_session=7,
            )
            reordered = store.reorder_plan_lessons(
                plan.plan_id, ("letters.lowercase", "letters.uppercase")
            )
            copy = store.duplicate_plan(plan.plan_id)
            store.set_plan_enabled(copy.plan_id, False)

            reloaded = self.make_store(root)
            self.assertEqual(reloaded.get_profile(profile.profile_id), renamed)
            self.assertEqual(reloaded.get_plan(plan.plan_id), reordered)
            self.assertEqual(len(reloaded.list_plans(profile.profile_id)), 2)
            self.assertTrue(profile.created_at.endswith("Z"))
            self.assertEqual(profile.profile_id, "learner_profileid")
            self.assertEqual(plan.plan_id, "plan_planid")

    def test_lesson_mastery_uses_lesson_identity_and_resume_can_filter_lesson(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Riley")
            plan = store.create_plan(
                profile.profile_id,
                "Letters",
                ("letters.uppercase", "letters.lowercase"),
            )
            for index in (1, 2):
                store.append_attempt(
                    make_attempt(
                        index,
                        profile.profile_id,
                        plan.plan_id,
                        session_id=f"session_{index}",
                        lesson_id="letters.uppercase",
                        skills=("letter.recognition",),
                    )
                )
            uppercase = make_session(profile.profile_id, plan.plan_id)
            lowercase = replace(
                make_session(profile.profile_id, plan.plan_id),
                session_id="session_two",
                questions=(make_question(2, "letters.lowercase"),),
                updated_at="2026-08-12T12:01:00Z",
            )
            store.save_session(uppercase)
            store.save_session(lowercase)

            mastery = store.lesson_mastery(
                profile.profile_id,
                "letters.uppercase",
                plan_id=plan.plan_id,
            )

            self.assertEqual(mastery.status.value, "mastered")
            self.assertEqual(mastery.skill, "letters.uppercase")
            self.assertEqual(
                store.resumable_session(
                    profile.profile_id,
                    plan.plan_id,
                    "letters.uppercase",
                ),
                uppercase,
            )
            self.assertEqual(
                store.resumable_session(
                    profile.profile_id,
                    plan.plan_id,
                    "letters.lowercase",
                ),
                lowercase,
            )

    def test_archive_delete_and_progress_reset_require_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Kai")
            plan = store.create_plan(profile.profile_id, "Plan", ("letters.uppercase",))

            with self.assertRaises(LearningConfirmationRequired):
                store.archive_profile(profile.profile_id)
            with self.assertRaises(LearningConfirmationRequired):
                store.archive_plan(plan.plan_id)
            with self.assertRaises(LearningConfirmationRequired):
                store.reset_progress(profile.profile_id)

            archived = store.archive_plan(plan.plan_id, confirmed=True)
            self.assertTrue(archived.archived)
            self.assertEqual(store.list_plans(profile.profile_id), ())
            self.assertEqual(
                store.list_plans(profile.profile_id, include_archived=True),
                (archived,),
            )

    def test_transition_is_one_atomic_progress_write_and_resumes_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            store = self.make_store(root)
            profile = store.create_profile("Lee")
            plan = store.create_plan(profile.profile_id, "Letters", ("letters.uppercase",))
            attempt = make_attempt(1, profile.profile_id, plan.plan_id)
            session = make_session(profile.profile_id, plan.plan_id, attempts=(attempt,))

            store.record_transition(attempt, session)

            document = json.loads(store.progress_path.read_text(encoding="utf-8"))
            self.assertEqual(document["version"], 1)
            self.assertEqual(len(document["attempts"]), 1)
            self.assertEqual(len(document["sessions"]), 1)
            reloaded = self.make_store(root)
            self.assertEqual(reloaded.list_attempts(), (attempt,))
            self.assertEqual(
                reloaded.resumable_session(profile.profile_id, plan.plan_id), session
            )

    def test_completed_session_is_not_offered_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Lee")
            session = make_session(profile.profile_id, None, question_index=1)
            store.save_session(session)
            self.assertIsNone(store.resumable_session(profile.profile_id))

    def test_history_is_bounded_and_reset_is_narrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning", history_limit=10)
            profile = store.create_profile("Dee")
            plan = store.create_plan(
                profile.profile_id,
                "Mixed",
                ("letters.uppercase", "letters.lowercase"),
            )
            for index in range(12):
                lesson = "letters.uppercase" if index % 2 == 0 else "letters.lowercase"
                store.append_attempt(
                    make_attempt(
                        index,
                        profile.profile_id,
                        plan.plan_id,
                        lesson_id=lesson,
                    )
                )

            self.assertEqual(len(store.list_attempts()), 10)
            removed = store.reset_progress(
                profile.profile_id,
                plan_id=plan.plan_id,
                lesson_id="letters.uppercase",
                confirmed=True,
            )
            self.assertEqual(removed, 5)
            self.assertEqual(
                {item.lesson_id for item in store.list_attempts()},
                {"letters.lowercase"},
            )

    def test_stats_separate_completion_and_explain_first_try_eventual_grade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Sky")
            plan = store.create_plan(
                profile.profile_id,
                "Two Lessons",
                ("letters.uppercase", "letters.lowercase"),
            )
            # Question one is eventually correct; question two is first-try correct.
            records = (
                make_attempt(
                    1,
                    profile.profile_id,
                    plan.plan_id,
                    question_id="shared_question",
                    correct=False,
                ),
                make_attempt(
                    2,
                    profile.profile_id,
                    plan.plan_id,
                    question_id="shared_question",
                    attempt_number=2,
                    correct=True,
                ),
                make_attempt(3, profile.profile_id, plan.plan_id, correct=True),
            )
            for record in records:
                store.append_attempt(record)

            mastery = store.skill_mastery(
                profile.profile_id,
                "letters.uppercase",
                plan_id=plan.plan_id,
            )
            report = store.plan_stats(plan.plan_id)

            self.assertEqual(mastery.evidence_count, 2)
            self.assertEqual(mastery.first_try_accuracy, 0.5)
            self.assertEqual(mastery.eventual_accuracy, 1.0)
            self.assertAlmostEqual(mastery.percentage_grade, 70.0)
            self.assertEqual(report.percentage_grade, 70.0)
            self.assertEqual(report.completion_percent, 0.0)
            self.assertLess(report.completion_percent, report.percentage_grade)

    def test_profile_stats_include_recent_trend_and_canonical_skill_mastery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Ari")
            outcomes = (
                ("skill.strong", True),
                ("skill.strong", True),
                ("skill.weak", False),
                ("skill.weak", False),
                ("skill.strong", True),
                ("skill.weak", True),
            )
            for index, (skill, correct) in enumerate(outcomes, start=1):
                store.append_attempt(
                    make_attempt(
                        index,
                        profile.profile_id,
                        None,
                        session_id=f"session_{index}",
                        skills=(skill,),
                        correct=correct,
                        timestamp=f"2026-08-12T12:00:{index:02d}Z",
                    )
                )

            stats = store.profile_stats(profile.profile_id)

            self.assertEqual(stats["recent_trend"], 0.6)
            self.assertEqual(
                [item["skill"] for item in stats["skills"]],
                ["skill.strong", "skill.weak"],
            )
            self.assertEqual(
                [item["status"] for item in stats["skills"]],
                ["mastered", "needs_practice"],
            )
            self.assertEqual(stats["skills"][0]["evidence_count"], 3)
            self.assertEqual(stats["skills"][1]["eventual_accuracy"], 0.3333)
            json.dumps(stats)

    def test_profile_skill_summaries_are_sorted_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Sam")
            skills = tuple(
                f"skill.{index:03d}"
                for index in reversed(range(MAX_PROFILE_SKILL_SUMMARIES + 1))
            )
            store.append_attempt(
                make_attempt(
                    1,
                    profile.profile_id,
                    None,
                    skills=skills,
                )
            )

            summaries = store.profile_stats(profile.profile_id)["skills"]

            self.assertEqual(len(summaries), MAX_PROFILE_SKILL_SUMMARIES)
            self.assertEqual(summaries[0]["skill"], "skill.000")
            self.assertEqual(summaries[-1]["skill"], "skill.099")

    def test_corrupt_file_is_preserved_reported_without_names_and_blocks_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            root.mkdir()
            raw = (
                '{"version":1,"updated_at":"2026-08-12T12:00:00Z",'
                '"profiles":[{"display_name":"Secret Child"}]}'
            )
            path = root / "profiles.json"
            path.write_text(raw, encoding="utf-8")
            messages: list[str] = []
            store = self.make_store(root, reporter=messages.append)

            self.assertEqual(store.list_profiles(), ())
            self.assertTrue(store.is_read_only)
            self.assertEqual(path.read_text(encoding="utf-8"), raw)
            self.assertEqual(len(messages), 1)
            self.assertNotIn("Secret Child", messages[0])
            with self.assertRaises(LearningReadOnlyError):
                store.create_profile("New Child")
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_unsupported_schema_is_read_only_and_never_migrated_silently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            root.mkdir()
            path = root / "plans.json"
            original = '{"version":99,"updated_at":"2026-08-12T12:00:00Z","plans":[]}'
            path.write_text(original, encoding="utf-8")
            store = self.make_store(root)

            self.assertEqual(store.list_plans(), ())
            self.assertTrue(store.is_read_only)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_data_file_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            root.mkdir()
            outside = Path(directory) / "outside.json"
            outside.write_text("private", encoding="utf-8")
            (root / "profiles.json").symlink_to(outside)
            store = self.make_store(root)

            self.assertEqual(store.list_profiles(), ())
            self.assertTrue(store.is_read_only)
            self.assertEqual(outside.read_text(encoding="utf-8"), "private")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_data_root_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            outside = base / "outside"
            outside.mkdir()
            root = base / "learning"
            root.symlink_to(outside, target_is_directory=True)
            store = self.make_store(root)

            self.assertEqual(store.list_profiles(), ())
            self.assertTrue(store.is_read_only)
            with self.assertRaises(LearningReadOnlyError):
                store.create_profile("No write")
            self.assertEqual(tuple(outside.iterdir()), ())

    def test_failed_atomic_replace_keeps_cache_and_existing_document_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            store = self.make_store(root)
            profile = store.create_profile("First")
            original = store.profiles_path.read_bytes()

            with patch(
                "bmo.features.learning.store.os.replace",
                side_effect=OSError("read only"),
            ), self.assertRaises(LearningPersistenceError):
                store.rename_profile(profile.profile_id, "Changed")

            self.assertEqual(store.get_profile(profile.profile_id).display_name, "First")
            self.assertEqual(store.profiles_path.read_bytes(), original)
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_failed_first_write_does_not_leave_a_learning_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bmo" / "data" / "learning"
            store = self.make_store(root)

            with patch(
                "bmo.features.learning.store.os.replace",
                side_effect=OSError("read only"),
            ), self.assertRaises(LearningPersistenceError):
                store.create_profile("Not Saved")

            self.assertFalse(root.exists())
            self.assertEqual(store.list_profiles(), ())

    def test_non_utc_persisted_timestamp_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            root.mkdir()
            path = root / "profiles.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "2026-08-12T12:00:00",
                        "profiles": [],
                    }
                ),
                encoding="utf-8",
            )
            store = self.make_store(root)
            self.assertEqual(store.list_profiles(), ())
            self.assertTrue(store.is_read_only)

    def test_boolean_numeric_fields_are_rejected_as_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "learning"
            root.mkdir()
            (root / "profiles.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": STAMP,
                        "profiles": [
                            {
                                "id": "learner_one",
                                "display_name": "One",
                                "archived": False,
                                "created_at": STAMP,
                                "updated_at": STAMP,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "plans.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": STAMP,
                        "plans": [
                            {
                                "id": "plan_one",
                                "profile_id": "learner_one",
                                "title": "Plan",
                                "lesson_ids": ["letters.uppercase"],
                                "enabled": True,
                                "archived": False,
                                "repetitions": True,
                                "questions_per_session": 8,
                                "mastery_gate": False,
                                "created_at": STAMP,
                                "updated_at": STAMP,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            store = self.make_store(root)
            self.assertEqual(store.list_plans(), ())
            self.assertTrue(store.is_read_only)

    def test_delete_profile_requires_empty_scope_and_explicit_progress_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory) / "learning")
            profile = store.create_profile("Noah")
            plan = store.create_plan(profile.profile_id, "Plan", ("letters.uppercase",))
            with self.assertRaises(LearningConfirmationRequired):
                store.delete_profile(profile.profile_id)
            with self.assertRaises(LearningStoreError):
                store.delete_profile(profile.profile_id, confirmed=True)
            store.delete_plan(plan.plan_id, confirmed=True)
            store.delete_profile(profile.profile_id, confirmed=True)
            self.assertEqual(store.list_profiles(include_archived=True), ())


if __name__ == "__main__":
    unittest.main()
