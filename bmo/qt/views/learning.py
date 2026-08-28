"""QML adapter for the offline Learning feature."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from bmo.features.learning.curriculum import prerequisite_warnings
from bmo.features.learning.view_model import InteractionController, question_snapshot
from bmo.qt.views.base import QtHostedView


_NAME_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_PLAN_QUESTION_MINIMUM = 3
_PLAN_QUESTION_MAXIMUM = 20
_PLAN_REPETITION_MINIMUM = 1
_PLAN_REPETITION_MAXIMUM = 10


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _percent(value: Any, *, fractional: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if fractional:
        number *= 100.0
    return f"{max(0.0, min(100.0, number)):.0f}%"


def _minutes(value: Any) -> str:
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        seconds = 0.0
    return str(round(seconds / 60.0))


class QtLearningView(QtHostedView):
    kind = "learning"
    title = "Learning"

    # A static QML contract test uses this set to prove that every rendered
    # button reaches production Python instead of becoming a silent no-op.
    SUPPORTED_ACTIONS = frozenset(
        {
            "learning_archive_plan",
            "learning_archive_profile",
            "learning_back",
            "learning_bulk_add_lessons",
            "learning_cancel_plan",
            "learning_choice",
            "learning_choose_lessons",
            "learning_confirm",
            "learning_confirm_cancel",
            "learning_continue",
            "learning_create_plan",
            "learning_create_profile",
            "learning_duplicate_plan",
            "learning_edit_plan",
            "learning_home",
            "learning_lesson_filter",
            "learning_plan",
            "learning_plan_adjust",
            "learning_plan_gate",
            "learning_plan_move",
            "learning_plan_remove",
            "learning_profile",
            "learning_quick_start",
            "learning_rename_profile",
            "learning_replay",
            "learning_reset_plan",
            "learning_reset_profile",
            "learning_restore_plan",
            "learning_restore_profile",
            "learning_save_plan",
            "learning_set_lesson_filter",
            "learning_submit",
            "learning_teacher",
            "learning_teacher_back",
            "learning_teacher_backspace",
            "learning_teacher_clear",
            "learning_teacher_digit",
            "learning_teacher_home",
            "learning_teacher_plan",
            "learning_teacher_profile",
            "learning_teacher_report",
            "learning_text_backspace",
            "learning_text_cancel",
            "learning_text_clear",
            "learning_text_key",
            "learning_text_open",
            "learning_text_save",
            "learning_toggle_lesson",
            "learning_toggle_plan",
        }
    )

    def __init__(
        self,
        host: Any,
        *,
        config: Any,
        catalog: Any,
        engine: Any,
        store: Any,
        announce: Any,
        cancel_announcements: Any,
        announcements_available: bool,
        on_close: Any,
        face_provider: Any = None,
    ) -> None:
        del face_provider
        self.config = config
        self.catalog = catalog
        self.engine = engine
        self.store = store
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.announcements_available = bool(announcements_available)
        self.profile: Any | None = None
        self.plan: Any | None = None
        self.session: Any | None = None
        self.screen = "profiles"
        self.selection: InteractionController | None = None
        self.feedback = ""
        self.try_again = False
        self.error = str(getattr(store, "read_only_error", "") or "")

        self.teacher_authorized = False
        self.teacher_pin = ""
        self.teacher_profile: Any | None = None
        self.teacher_plan: Any | None = None
        self.plan_draft_name = ""
        self.plan_draft_lessons: list[str] = []
        self.plan_draft_questions = self._bounded_questions(
            getattr(config, "default_session_questions", 8)
        )
        self.plan_draft_repetitions = 1
        self.plan_draft_mastery_gate = False
        self.editing_plan_id: str | None = None
        self.lesson_domain_filter = "all"
        self.lesson_family_filter = "all"
        self.lesson_filter_kind = "domain"

        self.text_title = ""
        self.text_value = ""
        self.text_purpose = ""
        self.text_return = "teacher_home"
        self.confirmation: dict[str, object] = {}
        self.confirm_return = "teacher_home"
        self.confirm_operation = ""
        self.confirm_values: tuple[str, ...] = ()
        self.report: dict[str, object] = {}
        self.report_return = "teacher_home"
        super().__init__(host, on_close=on_close)

    def payload(self) -> dict[str, object]:
        profiles = tuple(self.store.list_profiles())
        plans = (
            tuple(self.store.list_plans(profile_id=self.profile.profile_id))
            if self.profile is not None
            else ()
        )
        question = self.session.current_question if self.session is not None else None
        teacher_profiles = tuple(self.store.list_profiles(include_archived=True))
        teacher_plans = (
            tuple(
                self.store.list_plans(
                    profile_id=self.teacher_profile.profile_id,
                    include_archived=True,
                )
            )
            if self.teacher_profile is not None
            else ()
        )
        filtered_lessons = self._filtered_lessons()
        return {
            "screen": self.screen,
            "profiles": [
                {"id": profile.profile_id, "label": profile.display_name}
                for profile in profiles
            ],
            "profileName": getattr(self.profile, "display_name", ""),
            "plans": [
                {
                    "id": plan.plan_id,
                    "label": plan.title,
                    "lessons": len(plan.lesson_ids),
                    "enabled": plan.enabled,
                }
                for plan in plans
                if plan.enabled
            ],
            "planName": getattr(self.plan, "title", ""),
            "prompt": getattr(question, "prompt", ""),
            "choices": [
                {
                    "id": choice.id,
                    "label": choice.label,
                    "selected": (
                        self.selection is not None
                        and choice.id in self.selection.selected
                    ),
                    "assignment": (
                        self.selection.assignments.get(choice.id, "")
                        if self.selection is not None
                        else ""
                    ),
                    "order": (
                        self.selection.selected.index(choice.id) + 1
                        if self.selection is not None
                        and choice.id in self.selection.selected
                        and self.selection.question.interaction == "ordered_sequence"
                        else 0
                    ),
                }
                for choice in getattr(question, "choices", ())
            ],
            "requiresSubmit": bool(
                self.selection is not None and self.selection.needs_submit
            ),
            "submitReady": bool(
                self.selection is not None and self.selection.submit_ready
            ),
            "progress": (
                f"{self.session.question_index + 1} / {len(self.session.questions)}"
                if self.session is not None and not self.session.complete
                else ""
            ),
            "feedback": self.feedback,
            "tryAgain": self.try_again,
            "canAnnounce": self.announcements_available,
            "readOnly": bool(getattr(self.store, "is_read_only", False)),
            "error": self.error,
            "teacherPin": "● " * len(self.teacher_pin)
            + "○ " * (4 - len(self.teacher_pin)),
            "teacherProfiles": [
                {
                    "id": profile.profile_id,
                    "label": profile.display_name,
                    "archived": profile.archived,
                }
                for profile in teacher_profiles
            ],
            "teacherProfileName": getattr(self.teacher_profile, "display_name", ""),
            "teacherProfileArchived": bool(
                getattr(self.teacher_profile, "archived", False)
            ),
            "teacherPlans": [self._plan_payload(plan) for plan in teacher_plans],
            "teacherPlanName": getattr(self.teacher_plan, "title", ""),
            "teacherPlan": self._plan_payload(self.teacher_plan),
            "planDraft": {
                "name": self.plan_draft_name,
                "questions": self.plan_draft_questions,
                "repetitions": self.plan_draft_repetitions,
                "masteryGate": self.plan_draft_mastery_gate,
                "lessonCount": len(self.plan_draft_lessons),
                "isNew": self.editing_plan_id is None,
                "saveReady": bool(
                    self.plan_draft_name.strip() and self.plan_draft_lessons
                ),
            },
            "planDraftLessons": [
                self._lesson_payload(lesson_id, index=index)
                for index, lesson_id in enumerate(self.plan_draft_lessons)
            ],
            "lessonChoices": [
                self._lesson_payload(
                    lesson.lesson_id,
                    selected=lesson.lesson_id in self.plan_draft_lessons,
                )
                for lesson in filtered_lessons
            ],
            "lessonDomain": self.lesson_domain_filter,
            "lessonFamily": self.lesson_family_filter,
            "lessonFilterTitle": (
                "Choose a lesson family"
                if self.lesson_filter_kind == "family"
                else "Choose a learning domain"
            ),
            "lessonFilterValues": self._lesson_filter_payload(),
            "lessonFilteredCount": len(filtered_lessons),
            "textTitle": self.text_title,
            "textValue": self.text_value,
            "textKeys": _NAME_KEYS,
            "textCanSave": bool(self.text_value.strip()),
            "confirmation": self.confirmation,
            "report": self.report,
        }

    def handle_action(self, action: str, value: str) -> None:
        self.error = ""
        try:
            if action == "learning_profile":
                self.profile = self.store.get_profile(value)
                self.screen = "plans"
            elif action == "learning_teacher":
                self.teacher_pin = ""
                self.screen = "teacher_pin"
            elif action == "learning_teacher_digit":
                self._teacher_digit(value)
            elif action == "learning_teacher_backspace":
                self.teacher_pin = self.teacher_pin[:-1]
            elif action == "learning_teacher_clear":
                self.teacher_pin = ""
            elif action == "learning_teacher_home":
                self._require_teacher()
                self.teacher_profile = None
                self.teacher_plan = None
                self.report = {}
                self.screen = "teacher_home"
            elif action == "learning_teacher_profile":
                self._require_teacher()
                self.teacher_profile = self.store.get_profile(value)
                self.teacher_plan = None
                self.screen = "teacher_profile"
            elif action == "learning_create_profile":
                self._require_teacher()
                self._create_profile(value)
            elif action == "learning_rename_profile":
                self._require_teacher()
                self._rename_profile(value)
            elif action == "learning_archive_profile":
                self._require_teacher()
                self._confirm_archive_profile()
            elif action == "learning_restore_profile":
                self._require_teacher()
                self._restore_profile()
            elif action == "learning_reset_profile":
                self._require_teacher()
                self._confirm_reset_profile()
            elif action == "learning_teacher_report":
                self._require_teacher()
                self._show_teacher_report()
            elif action == "learning_create_plan":
                self._require_teacher()
                self._begin_new_plan(value)
            elif action == "learning_teacher_plan":
                self._require_teacher()
                self.teacher_plan = self.store.get_plan(value)
                self.screen = "teacher_plan"
            elif action == "learning_toggle_plan":
                self._require_teacher()
                self._toggle_plan()
            elif action == "learning_edit_plan":
                self._require_teacher()
                self._begin_edit_plan()
            elif action == "learning_duplicate_plan":
                self._require_teacher()
                self._duplicate_plan()
            elif action == "learning_archive_plan":
                self._require_teacher()
                self._confirm_archive_plan()
            elif action == "learning_restore_plan":
                self._require_teacher()
                self._restore_plan()
            elif action == "learning_reset_plan":
                self._require_teacher()
                self._confirm_reset_plan()
            elif action == "learning_plan_adjust":
                self._require_teacher()
                self._adjust_plan(value)
            elif action == "learning_plan_gate":
                self._require_teacher()
                self.plan_draft_mastery_gate = not self.plan_draft_mastery_gate
            elif action == "learning_plan_move":
                self._require_teacher()
                self._move_plan_lesson(value)
            elif action == "learning_plan_remove":
                self._require_teacher()
                self._remove_plan_lesson(value)
            elif action == "learning_choose_lessons":
                self._require_teacher()
                self.screen = "teacher_lessons"
            elif action == "learning_lesson_filter":
                self._require_teacher()
                self._open_lesson_filter(value)
            elif action == "learning_set_lesson_filter":
                self._require_teacher()
                self._set_lesson_filter(value)
            elif action == "learning_toggle_lesson":
                self._require_teacher()
                self._toggle_lesson(value)
            elif action == "learning_bulk_add_lessons":
                self._require_teacher()
                self._request_add_lessons(
                    lesson.lesson_id for lesson in self._filtered_lessons()
                )
            elif action == "learning_save_plan":
                self._require_teacher()
                self._request_save_plan()
            elif action == "learning_cancel_plan":
                self._require_teacher()
                self._cancel_plan_edit()
            elif action == "learning_text_open":
                self._require_teacher()
                self._open_text_editor(value)
            elif action == "learning_text_key":
                self._require_teacher()
                self._text_key(value)
            elif action == "learning_text_backspace":
                self._require_teacher()
                self.text_value = self.text_value[:-1]
            elif action == "learning_text_clear":
                self._require_teacher()
                self.text_value = ""
            elif action == "learning_text_cancel":
                self._require_teacher()
                self.screen = self.text_return
            elif action == "learning_text_save":
                self._require_teacher()
                self._save_text()
            elif action == "learning_confirm":
                self._require_teacher()
                self._complete_confirmation()
            elif action == "learning_confirm_cancel":
                self._require_teacher()
                self._cancel_confirmation()
            elif action == "learning_teacher_back":
                self._teacher_back()
            elif action == "learning_plan":
                if self.profile is None:
                    return
                self.plan = self.store.get_plan(value)
                self._start_session()
            elif action == "learning_quick_start":
                if self.profile is None:
                    return
                self.plan = None
                self._start_session()
            elif action == "learning_choice":
                self._choose(value)
            elif action == "learning_submit":
                self._submit()
            elif action == "learning_continue":
                if self.session is None:
                    return
                if self.try_again:
                    self.screen = "lesson"
                    self._reset_selection()
                elif self.session.complete:
                    self.screen = "complete"
                else:
                    self.screen = "lesson"
                    self._reset_selection()
                    self._speak_question()
            elif action == "learning_replay":
                if self.session is not None:
                    self.announce(self.engine.replay(self.session), None)
            elif action == "learning_home":
                self._leave_learning_session()
                self.teacher_authorized = False
                self.teacher_pin = ""
                self.teacher_profile = None
                self.teacher_plan = None
                self.screen = "profiles"
            elif action == "learning_back":
                self.cancel_announcements()
                self.session = None
                self.plan = None
                self.screen = "plans" if self.profile is not None else "profiles"
            else:
                super().handle_action(action, value)
                return
        except Exception as exc:
            self.error = str(exc) or "Learning could not complete that action."
        self.refresh()

    def _start_session(self) -> None:
        assert self.profile is not None
        if self.plan is None:
            self.session = self.engine.start_session(self.profile.profile_id)
        else:
            self.session = self.engine.start_session(
                self.profile.profile_id,
                self.plan,
            )
        self.store.save_session(self.session)
        self.screen = "lesson"
        self._reset_selection()
        self.feedback = ""
        self._speak_question()

    def _teacher_digit(self, value: str) -> None:
        if len(self.teacher_pin) >= 4 or not str(value).isdigit():
            return
        self.teacher_pin += str(value)[0]
        if len(self.teacher_pin) != 4:
            return
        if not self.config.verify_teacher_pin(self.teacher_pin):
            self.teacher_pin = ""
            raise ValueError("That teacher PIN did not match.")
        self.teacher_authorized = True
        self.teacher_pin = ""
        self.screen = "teacher_home"

    def _require_teacher(self) -> None:
        if not self.teacher_authorized:
            raise PermissionError("Enter the teacher PIN first.")

    def _create_profile(self, value: str) -> None:
        name = value.strip()
        if not name:
            raise ValueError("Enter a learner name.")
        self.teacher_profile = self.store.create_profile(name)
        self.screen = "teacher_profile"

    def _rename_profile(self, value: str) -> None:
        if self.teacher_profile is None or not value.strip():
            raise ValueError("Enter a learner name.")
        self.teacher_profile = self.store.rename_profile(
            self.teacher_profile.profile_id,
            value.strip(),
        )

    def _confirm_archive_profile(self) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        self._ask_confirmation(
            title="Archive learner?",
            message=(
                f"Archive {self.teacher_profile.display_name}? Their plans and "
                "learning history will stay safely on this kiosk."
            ),
            label="ARCHIVE",
            operation="archive_profile",
            return_screen="teacher_profile",
        )

    def _restore_profile(self) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        self.teacher_profile = self.store.restore_profile(
            self.teacher_profile.profile_id
        )
        self.screen = "teacher_profile"

    def _confirm_reset_profile(self) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        self._ask_confirmation(
            title="Reset all progress?",
            message=(
                f"Remove every saved answer and unfinished lesson for "
                f"{self.teacher_profile.display_name}? This cannot be undone."
            ),
            label="RESET",
            operation="reset_profile",
            return_screen="teacher_profile",
        )

    def _begin_new_plan(self, value: str) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        if self.teacher_profile.archived:
            raise ValueError("Restore this learner before adding a plan.")
        title = value.strip()
        if not title:
            raise ValueError("Enter a plan name.")
        self.plan_draft_name = title
        self.plan_draft_lessons = []
        self.plan_draft_questions = self._bounded_questions(
            getattr(self.config, "default_session_questions", 8)
        )
        self.plan_draft_repetitions = 1
        self.plan_draft_mastery_gate = False
        self.editing_plan_id = None
        self.lesson_domain_filter = "all"
        self.lesson_family_filter = "all"
        self.screen = "teacher_lessons"

    def _begin_edit_plan(self) -> None:
        plan = self.teacher_plan
        if plan is None:
            raise ValueError("Choose a plan first.")
        if plan.archived:
            raise ValueError("Restore this plan before editing it.")
        self.editing_plan_id = plan.plan_id
        self.plan_draft_name = plan.title
        self.plan_draft_lessons = list(plan.lesson_ids)
        self.plan_draft_questions = self._bounded_questions(
            plan.questions_per_session
        )
        self.plan_draft_repetitions = max(
            _PLAN_REPETITION_MINIMUM,
            min(_PLAN_REPETITION_MAXIMUM, int(plan.repetitions)),
        )
        self.plan_draft_mastery_gate = bool(plan.mastery_gate)
        self.lesson_domain_filter = "all"
        self.lesson_family_filter = "all"
        self.screen = "teacher_plan_edit"

    @staticmethod
    def _bounded_questions(value: Any) -> int:
        try:
            supplied = int(value)
        except (TypeError, ValueError):
            supplied = 8
        return max(
            _PLAN_QUESTION_MINIMUM,
            min(_PLAN_QUESTION_MAXIMUM, supplied),
        )

    def _adjust_plan(self, value: str) -> None:
        try:
            setting, raw_offset = value.split(":", 1)
            offset = int(raw_offset)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("That plan setting was not understood.") from exc
        if setting == "questions":
            self.plan_draft_questions = max(
                _PLAN_QUESTION_MINIMUM,
                min(_PLAN_QUESTION_MAXIMUM, self.plan_draft_questions + offset),
            )
        elif setting == "repetitions":
            self.plan_draft_repetitions = max(
                _PLAN_REPETITION_MINIMUM,
                min(
                    _PLAN_REPETITION_MAXIMUM,
                    self.plan_draft_repetitions + offset,
                ),
            )
        else:
            raise ValueError("That plan setting was not understood.")

    def _move_plan_lesson(self, value: str) -> None:
        try:
            raw_index, raw_offset = value.split(":", 1)
            index = int(raw_index)
            offset = int(raw_offset)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("That lesson move was not understood.") from exc
        destination = index + offset
        if not 0 <= index < len(self.plan_draft_lessons):
            return
        if not 0 <= destination < len(self.plan_draft_lessons):
            return
        item = self.plan_draft_lessons.pop(index)
        self.plan_draft_lessons.insert(destination, item)

    def _remove_plan_lesson(self, lesson_id: str) -> None:
        if lesson_id in self.plan_draft_lessons:
            self.plan_draft_lessons.remove(lesson_id)

    def _open_lesson_filter(self, value: str) -> None:
        self.lesson_filter_kind = "family" if value == "family" else "domain"
        self.screen = "teacher_lesson_filter"

    def _set_lesson_filter(self, value: str) -> None:
        allowed = {item["value"] for item in self._lesson_filter_payload()}
        if value not in allowed:
            raise ValueError("That lesson filter is unavailable.")
        if self.lesson_filter_kind == "domain":
            self.lesson_domain_filter = value
            self.lesson_family_filter = "all"
        else:
            self.lesson_family_filter = value
        self.screen = "teacher_lessons"

    def _toggle_lesson(self, lesson_id: str) -> None:
        self.catalog.get(lesson_id)
        if lesson_id in self.plan_draft_lessons:
            self.plan_draft_lessons.remove(lesson_id)
            return
        self._request_add_lessons((lesson_id,))

    def _request_add_lessons(self, lesson_ids: Iterable[str]) -> None:
        additions = tuple(
            lesson_id
            for lesson_id in lesson_ids
            if lesson_id not in self.plan_draft_lessons
        )
        if not additions:
            return
        proposed = (*self.plan_draft_lessons, *additions)
        warnings = prerequisite_warnings(self.catalog, proposed)
        addition_set = set(additions)
        relevant = tuple(pair for pair in warnings if pair[0] in addition_set)
        if relevant:
            self._ask_confirmation(
                title="Foundation warning",
                message=(
                    f"Recommended first: {self._warning_titles(relevant)}. Add "
                    "the selected lesson(s) anyway?"
                ),
                label="ADD ANYWAY",
                operation="add_lessons",
                return_screen="teacher_lessons",
                values=additions,
                danger=False,
            )
            return
        self._add_lessons(additions)

    def _add_lessons(self, lesson_ids: Iterable[str]) -> None:
        for lesson_id in lesson_ids:
            self.catalog.get(lesson_id)
            if lesson_id not in self.plan_draft_lessons:
                self.plan_draft_lessons.append(lesson_id)
        self.screen = "teacher_lessons"

    def _request_save_plan(self) -> None:
        if not self.plan_draft_name.strip():
            raise ValueError("Enter a plan name.")
        if not self.plan_draft_lessons:
            raise ValueError("Choose at least one lesson before saving.")
        warnings = prerequisite_warnings(self.catalog, self.plan_draft_lessons)
        if warnings:
            self._ask_confirmation(
                title="Foundation warning",
                message=(
                    f"Recommended first: {self._warning_titles(warnings)}. "
                    "Save this order anyway?"
                ),
                label="SAVE ANYWAY",
                operation="save_plan",
                return_screen="teacher_plan_edit",
                danger=False,
            )
            return
        self._save_plan()

    def _save_plan(self) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        if self.editing_plan_id is None:
            self.teacher_plan = self.store.create_plan(
                self.teacher_profile.profile_id,
                self.plan_draft_name.strip(),
                tuple(self.plan_draft_lessons),
                repetitions=self.plan_draft_repetitions,
                questions_per_session=self.plan_draft_questions,
                mastery_gate=self.plan_draft_mastery_gate,
            )
        else:
            current = self.store.get_plan(self.editing_plan_id)
            self.teacher_plan = self.store.update_plan(
                replace(
                    current,
                    title=self.plan_draft_name.strip(),
                    lesson_ids=tuple(self.plan_draft_lessons),
                    repetitions=self.plan_draft_repetitions,
                    questions_per_session=self.plan_draft_questions,
                    mastery_gate=self.plan_draft_mastery_gate,
                )
            )
        self.editing_plan_id = self.teacher_plan.plan_id
        self.screen = "teacher_plan"

    def _cancel_plan_edit(self) -> None:
        if self.editing_plan_id is None:
            self.teacher_plan = None
            self.screen = "teacher_profile"
        else:
            self.teacher_plan = self.store.get_plan(self.editing_plan_id)
            self.screen = "teacher_plan"

    def _toggle_plan(self) -> None:
        if self.teacher_plan is None:
            raise ValueError("Choose a plan first.")
        if self.teacher_plan.archived:
            raise ValueError("Restore this plan before turning it on.")
        self.teacher_plan = self.store.set_plan_enabled(
            self.teacher_plan.plan_id,
            not self.teacher_plan.enabled,
        )

    def _duplicate_plan(self) -> None:
        if self.teacher_plan is None:
            raise ValueError("Choose a plan first.")
        self.teacher_plan = self.store.duplicate_plan(self.teacher_plan.plan_id)
        self.screen = "teacher_plan"

    def _confirm_archive_plan(self) -> None:
        if self.teacher_plan is None:
            raise ValueError("Choose a plan first.")
        self._ask_confirmation(
            title="Archive plan?",
            message=(
                f"Archive {self.teacher_plan.title}? Its learning history "
                "will stay safely on this kiosk."
            ),
            label="ARCHIVE",
            operation="archive_plan",
            return_screen="teacher_plan",
        )

    def _restore_plan(self) -> None:
        if self.teacher_plan is None:
            raise ValueError("Choose a plan first.")
        self.teacher_plan = self.store.restore_plan(self.teacher_plan.plan_id)
        self.screen = "teacher_plan"

    def _confirm_reset_plan(self) -> None:
        if self.teacher_plan is None:
            raise ValueError("Choose a plan first.")
        self._ask_confirmation(
            title="Reset this plan?",
            message=(
                f"Remove saved answers and unfinished lessons for "
                f"{self.teacher_plan.title}? This cannot be undone."
            ),
            label="RESET PLAN",
            operation="reset_plan",
            return_screen="teacher_plan",
        )

    def _open_text_editor(self, purpose: str) -> None:
        allowed = {"new_profile", "new_plan", "rename_plan", "rename_profile"}
        if purpose not in allowed:
            raise ValueError("That name action is unavailable.")
        if purpose in {"rename_profile", "new_plan"} and self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        if purpose == "rename_plan" and self.screen != "teacher_plan_edit":
            raise ValueError("Open the plan editor first.")
        values = {
            "new_profile": ("New learner name", "", "teacher_home"),
            "rename_profile": (
                "Rename learner",
                getattr(self.teacher_profile, "display_name", ""),
                "teacher_profile",
            ),
            "new_plan": ("New plan name", "", "teacher_profile"),
            "rename_plan": (
                "Rename learning plan",
                self.plan_draft_name,
                "teacher_plan_edit",
            ),
        }
        self.text_title, self.text_value, self.text_return = values[purpose]
        self.text_purpose = purpose
        self.screen = "teacher_text"

    def _text_key(self, value: str) -> None:
        supplied = str(value).upper()
        if supplied not in _NAME_KEYS and supplied != " ":
            return
        if len(self.text_value) < 80:
            self.text_value += supplied

    def _save_text(self) -> None:
        value = " ".join(self.text_value.split())
        if not value:
            raise ValueError("Enter a name first.")
        purpose = self.text_purpose
        if purpose == "new_profile":
            self._create_profile(value)
        elif purpose == "rename_profile":
            self._rename_profile(value)
            self.screen = "teacher_profile"
        elif purpose == "new_plan":
            self._begin_new_plan(value)
        elif purpose == "rename_plan":
            self.plan_draft_name = value
            self.screen = "teacher_plan_edit"
        else:
            raise ValueError("That name action is unavailable.")

    def _ask_confirmation(
        self,
        *,
        title: str,
        message: str,
        label: str,
        operation: str,
        return_screen: str,
        values: Iterable[str] = (),
        danger: bool = True,
    ) -> None:
        self.confirmation = {
            "title": title,
            "message": message,
            "label": label,
            "danger": danger,
        }
        self.confirm_operation = operation
        self.confirm_return = return_screen
        self.confirm_values = tuple(values)
        self.screen = "teacher_confirm"

    def _cancel_confirmation(self) -> None:
        return_screen = self.confirm_return
        self._clear_confirmation()
        self.screen = return_screen

    def _complete_confirmation(self) -> None:
        operation = self.confirm_operation
        if not operation:
            return
        values = self.confirm_values
        return_screen = self.confirm_return
        self._clear_confirmation()
        self.screen = return_screen
        if operation == "archive_profile":
            if self.teacher_profile is None:
                raise ValueError("Choose a learner first.")
            self.teacher_profile = self.store.archive_profile(
                self.teacher_profile.profile_id,
                confirmed=True,
            )
        elif operation == "reset_profile":
            if self.teacher_profile is None:
                raise ValueError("Choose a learner first.")
            self.store.reset_progress(
                self.teacher_profile.profile_id,
                confirmed=True,
            )
        elif operation == "archive_plan":
            if self.teacher_plan is None:
                raise ValueError("Choose a plan first.")
            self.teacher_plan = self.store.archive_plan(
                self.teacher_plan.plan_id,
                confirmed=True,
            )
        elif operation == "reset_plan":
            if self.teacher_profile is None or self.teacher_plan is None:
                raise ValueError("Choose a plan first.")
            self.store.reset_progress(
                self.teacher_profile.profile_id,
                plan_id=self.teacher_plan.plan_id,
                confirmed=True,
            )
        elif operation == "add_lessons":
            self._add_lessons(values)
        elif operation == "save_plan":
            self._save_plan()
        else:
            raise ValueError("That confirmation has expired.")

    def _clear_confirmation(self) -> None:
        self.confirmation = {}
        self.confirm_operation = ""
        self.confirm_values = ()

    def _teacher_back(self) -> None:
        if self.screen == "teacher_confirm":
            self._cancel_confirmation()
        elif self.screen == "teacher_lesson_filter":
            self.screen = "teacher_lessons"
        elif self.screen == "teacher_lessons":
            self.screen = "teacher_plan_edit"
        elif self.screen == "teacher_plan_edit":
            self._cancel_plan_edit()
        elif self.screen == "teacher_text":
            self.screen = self.text_return
        elif self.screen == "teacher_plan":
            self.teacher_plan = None
            self.screen = "teacher_profile"
        elif self.screen == "teacher_report":
            self.report = {}
            self.screen = self.report_return
        elif self.screen == "teacher_profile":
            self.teacher_profile = None
            self.teacher_plan = None
            self.screen = "teacher_home"
        elif self.screen == "teacher_home":
            self.teacher_authorized = False
            self.screen = "profiles"
        elif self.screen == "teacher_pin":
            self.teacher_pin = ""
            self.screen = "profiles"
        else:
            self.screen = "profiles"

    def _show_teacher_report(self) -> None:
        if self.teacher_plan is not None:
            stats = self.store.plan_stats(self.teacher_plan.plan_id)
            title = self.teacher_plan.title
            self.report_return = "teacher_plan"
        elif self.teacher_profile is not None:
            stats = self.store.profile_stats(self.teacher_profile.profile_id)
            title = self.teacher_profile.display_name
            self.report_return = "teacher_profile"
        else:
            raise ValueError("Choose a learner first.")
        self.report = {
            "title": title,
            "metrics": self._report_metrics(stats),
            "skills": self._report_skills(stats),
        }
        self.screen = "teacher_report"

    @staticmethod
    def _report_metrics(stats: Any) -> list[dict[str, str]]:
        colors = (
            "#35a99a",
            "#4e7dcc",
            "#8a6dc1",
            "#d26483",
            "#e58b5f",
            "#69a94f",
            "#3978c3",
            "#b27731",
        )
        values = (
            ("COMPLETE", _percent(_field(stats, "completion_percent", 0))),
            ("GRADE", _percent(_field(stats, "percentage_grade", 0))),
            (
                "ACCURACY",
                _percent(_field(stats, "accuracy", 0), fractional=True),
            ),
            (
                "FIRST TRY",
                _percent(
                    _field(stats, "first_try_accuracy", 0), fractional=True
                ),
            ),
            (
                "EVENTUAL",
                _percent(
                    _field(stats, "eventual_accuracy", 0), fractional=True
                ),
            ),
            (
                "RECENT",
                _percent(_field(stats, "recent_trend", 0), fractional=True),
            ),
            ("ATTEMPTS", str(_field(stats, "attempt_count", 0))),
            ("MINUTES", _minutes(_field(stats, "practiced_seconds", 0))),
        )
        return [
            {"label": label, "value": value, "color": colors[index]}
            for index, (label, value) in enumerate(values)
        ]

    @staticmethod
    def _report_skills(stats: Any) -> list[dict[str, str]]:
        skills = _field(stats, "skills", ()) or ()
        values = skills.values() if isinstance(skills, Mapping) else skills
        result: list[dict[str, str]] = []
        for item in values:
            skill = str(_field(item, "skill", "Skill"))
            status = _field(item, "status", "not_started")
            status = getattr(status, "value", status)
            result.append(
                {
                    "label": skill.replace("_", " ").replace(".", " · "),
                    "status": str(status).replace("_", " ").upper(),
                    "grade": _percent(_field(item, "percentage_grade", 0)),
                }
            )
        return result

    def _plan_payload(self, plan: Any | None) -> dict[str, object]:
        if plan is None:
            return {}
        return {
            "id": plan.plan_id,
            "label": plan.title,
            "enabled": bool(plan.enabled),
            "archived": bool(plan.archived),
            "lessons": len(plan.lesson_ids),
            "questions": int(plan.questions_per_session),
            "repetitions": int(plan.repetitions),
            "masteryGate": bool(plan.mastery_gate),
        }

    def _lesson_payload(
        self,
        lesson_id: str,
        *,
        index: int = -1,
        selected: bool = False,
    ) -> dict[str, object]:
        try:
            lesson = self.catalog.get(lesson_id)
            domain = str(lesson.domain)
            title = str(lesson.title)
            family = self._lesson_family(lesson)
        except KeyError:
            domain = "unknown"
            title = lesson_id
            family = "other"
        return {
            "id": lesson_id,
            "title": title,
            "domain": domain,
            "family": family,
            "index": index,
            "selected": selected,
            "canMoveUp": index > 0,
            "canMoveDown": 0 <= index < len(self.plan_draft_lessons) - 1,
        }

    @staticmethod
    def _lesson_family(lesson: Any) -> str:
        parts = tuple(part for part in str(lesson.lesson_id).split(".") if part)
        if len(parts) >= 2 and parts[0] == str(lesson.domain):
            return parts[1]
        return parts[1] if len(parts) >= 2 else "other"

    def _lesson_domains(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(str(lesson.domain) for lesson in self.catalog.lessons)
        )

    def _lesson_families(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                self._lesson_family(lesson)
                for lesson in self.catalog.lessons
                if self.lesson_domain_filter == "all"
                or str(lesson.domain) == self.lesson_domain_filter
            )
        )

    def _filtered_lessons(self) -> tuple[Any, ...]:
        domains = {"all", *self._lesson_domains()}
        if self.lesson_domain_filter not in domains:
            self.lesson_domain_filter = "all"
        families = {"all", *self._lesson_families()}
        if self.lesson_family_filter not in families:
            self.lesson_family_filter = "all"
        return tuple(
            lesson
            for lesson in self.catalog.lessons
            if (
                self.lesson_domain_filter == "all"
                or str(lesson.domain) == self.lesson_domain_filter
            )
            and (
                self.lesson_family_filter == "all"
                or self._lesson_family(lesson) == self.lesson_family_filter
            )
        )

    def _lesson_filter_payload(self) -> list[dict[str, object]]:
        values = (
            self._lesson_families()
            if self.lesson_filter_kind == "family"
            else self._lesson_domains()
        )
        current = (
            self.lesson_family_filter
            if self.lesson_filter_kind == "family"
            else self.lesson_domain_filter
        )
        return [
            {
                "value": value,
                "label": "ALL"
                if value == "all"
                else value.replace("_", " ").upper(),
                "selected": value == current,
            }
            for value in ("all", *values)
        ]

    def _warning_titles(self, warnings: Iterable[tuple[str, str]]) -> str:
        missing = tuple(dict.fromkeys(prerequisite for _, prerequisite in warnings))
        titles: list[str] = []
        for lesson_id in missing[:3]:
            try:
                titles.append(str(self.catalog.get(lesson_id).title))
            except KeyError:
                titles.append(lesson_id)
        if len(missing) > 3:
            titles.append(f"and {len(missing) - 3} more")
        return ", ".join(titles)

    def _leave_learning_session(self) -> None:
        self.cancel_announcements()
        self.session = None
        self.plan = None
        self.profile = None

    def _choose(self, choice_id: str) -> None:
        if self.session is None or self.session.current_question is None:
            return
        if self.selection is None:
            self._reset_selection()
        assert self.selection is not None
        if not self.selection.choose(choice_id).accepted:
            return
        if not self.selection.needs_submit and self.selection.submit_ready:
            self._submit()

    def _submit(self) -> None:
        if (
            self.session is None
            or self.selection is None
            or not self.selection.submit_ready
        ):
            self.error = "Choose an answer first."
            return
        response = self.selection.response()
        transition = self.engine.submit(self.session, response)
        self.store.record_transition(transition.attempt, transition.session)
        self.session = transition.session
        self.feedback = transition.evaluation.feedback
        self.try_again = transition.evaluation.try_again
        self.screen = "feedback"
        self.selection = None
        if self.announcements_available:
            self.announce(self.feedback, None)

    def _speak_question(self) -> None:
        if (
            self.announcements_available
            and self.session is not None
            and self.session.current_question is not None
        ):
            self.announce(self.session.current_question.spoken_prompt, None)

    def _reset_selection(self) -> None:
        question = self.session.current_question if self.session is not None else None
        self.selection = (
            InteractionController(question_snapshot(question))
            if question is not None
            else None
        )

    def close(self) -> None:
        self.cancel_announcements()
        super().close()


__all__ = ["QtLearningView"]
