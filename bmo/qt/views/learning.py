"""QML adapter for the offline Learning feature."""

from __future__ import annotations

from typing import Any

from bmo.features.learning.view_model import InteractionController, question_snapshot
from bmo.qt.views.base import QtHostedView


class QtLearningView(QtHostedView):
    kind = "learning"
    title = "Learning"

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
            "readOnly": bool(self.store.is_read_only),
            "error": self.error,
            "teacherPin": "● " * len(self.teacher_pin) + "○ " * (4 - len(self.teacher_pin)),
            "teacherProfiles": [
                {
                    "id": profile.profile_id,
                    "label": profile.display_name,
                    "archived": profile.archived,
                }
                for profile in teacher_profiles
            ],
            "teacherProfileName": getattr(self.teacher_profile, "display_name", ""),
            "teacherPlans": [
                {
                    "id": plan.plan_id,
                    "label": plan.title,
                    "enabled": plan.enabled,
                    "archived": plan.archived,
                    "lessons": len(plan.lesson_ids),
                }
                for plan in teacher_plans
            ],
            "teacherPlanName": getattr(self.teacher_plan, "title", ""),
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
            elif action == "learning_teacher_clear":
                self.teacher_pin = ""
            elif action == "learning_teacher_home":
                if self.teacher_authorized:
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
                name = value.strip()
                if not name:
                    raise ValueError("Enter a learner name.")
                self.teacher_profile = self.store.create_profile(name)
                self.screen = "teacher_profile"
            elif action == "learning_rename_profile":
                self._require_teacher()
                if self.teacher_profile is None or not value.strip():
                    raise ValueError("Enter a learner name.")
                self.teacher_profile = self.store.rename_profile(
                    self.teacher_profile.profile_id,
                    value.strip(),
                )
            elif action == "learning_teacher_report":
                self._require_teacher()
                self._show_teacher_report()
            elif action == "learning_create_plan":
                self._require_teacher()
                self._create_plan(value)
            elif action == "learning_teacher_plan":
                self._require_teacher()
                self.teacher_plan = self.store.get_plan(value)
                self.screen = "teacher_plan"
            elif action == "learning_toggle_plan":
                self._require_teacher()
                if self.teacher_plan is None:
                    return
                self.teacher_plan = self.store.set_plan_enabled(
                    self.teacher_plan.plan_id,
                    not self.teacher_plan.enabled,
                )
            elif action == "learning_teacher_back":
                if self.screen == "teacher_plan":
                    self.teacher_plan = None
                    self.screen = "teacher_profile"
                elif self.screen == "teacher_report":
                    self.report = {}
                    self.screen = self.report_return
                elif self.screen == "teacher_profile":
                    self.teacher_profile = None
                    self.screen = "teacher_home"
                else:
                    self.screen = "profiles"
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
                self.cancel_announcements()
                self.session = None
                self.plan = None
                self.profile = None
                self.teacher_authorized = False
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

    def _create_plan(self, value: str) -> None:
        if self.teacher_profile is None:
            raise ValueError("Choose a learner first.")
        title = value.strip()
        if not title:
            raise ValueError("Enter a plan name.")
        lesson_ids = tuple(self.catalog.lesson_ids)
        self.teacher_plan = self.store.create_plan(
            self.teacher_profile.profile_id,
            title,
            lesson_ids,
            questions_per_session=self.config.default_session_questions,
        )
        self.screen = "teacher_plan"

    def _show_teacher_report(self) -> None:
        if self.teacher_plan is not None:
            stats = self.store.plan_stats(self.teacher_plan.plan_id)
            self.report = {
                "title": self.teacher_plan.title,
                "grade": f"{stats.percentage_grade:.0f}%",
                "completion": f"{stats.completion_percent:.0f}%",
                "attempts": stats.attempt_count,
                "recent": f"{stats.recent_trend * 100:.0f}%",
            }
            self.report_return = "teacher_plan"
        elif self.teacher_profile is not None:
            stats = self.store.profile_stats(self.teacher_profile.profile_id)
            self.report = {
                "title": self.teacher_profile.display_name,
                "grade": f"{float(stats['percentage_grade']):.0f}%",
                "completion": f"{float(stats['completion_percent']):.0f}%",
                "attempts": int(stats["attempt_count"]),
                "recent": f"{float(stats['recent_trend']) * 100:.0f}%",
            }
            self.report_return = "teacher_profile"
        else:
            raise ValueError("Choose a learner first.")
        self.screen = "teacher_report"

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
        if self.session is None or self.selection is None or not self.selection.submit_ready:
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
