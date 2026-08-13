"""Crash-safe, private persistence and derived statistics for Learning.

The store owns only fixed JSON documents immediately below its configured
root.  It never creates the directory while importing, constructing, or
reading an empty store; the first successful mutation creates it lazily.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, TypeVar
from uuid import uuid4

from .models import (
    AttemptRecord,
    LearnerProfile,
    LearningDataError,
    LearningPlan,
    LearningSession,
    PlanReport,
    SkillMastery,
)


SCHEMA_VERSION = 1
MAX_DATA_FILE_BYTES = 32 * 1024 * 1024
MAX_SESSION_HISTORY = 100
MAX_PROFILE_SKILL_SUMMARIES = 100


class LearningStoreError(RuntimeError):
    """Base class for expected local Learning persistence failures."""


class LearningCorruptDataError(LearningStoreError):
    """Raised when an existing document cannot safely be interpreted."""


class LearningReadOnlyError(LearningStoreError):
    """Raised when a mutation would overwrite unreadable local data."""


class LearningPersistenceError(LearningStoreError):
    """Raised when a validated mutation cannot be committed durably."""


class LearningConfirmationRequired(LearningStoreError):
    """Raised when a destructive operation lacks explicit confirmation."""


def utc_now_iso() -> str:
    """Return a compact, timezone-explicit ISO 8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _as_utc_iso(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise LearningStoreError("the store clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validate_utc_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCorruptDataError(f"{label} is not an ISO 8601 UTC timestamp")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningCorruptDataError(
            f"{label} is not an ISO 8601 UTC timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise LearningCorruptDataError(f"{label} must include the UTC offset")
    return candidate


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LearningCorruptDataError(f"{label} must be an object")
    return value


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LearningCorruptDataError("JSON objects cannot repeat field names")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise LearningCorruptDataError(f"non-finite JSON number {value} is unsupported")


def _strict_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    missing = required.difference(value)
    unknown = set(value).difference(required | optional)
    if missing:
        raise LearningCorruptDataError(f"{label} is missing required fields")
    if unknown:
        raise LearningCorruptDataError(f"{label} contains unknown fields")


def _strict_integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningCorruptDataError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise LearningCorruptDataError(f"{label} is outside its safe range")
    return value


def _profile_to_json(profile: LearnerProfile) -> dict[str, Any]:
    return {
        "id": profile.profile_id,
        "display_name": profile.display_name,
        "archived": profile.archived,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _profile_from_json(value: object) -> LearnerProfile:
    record = _required_mapping(value, "profile")
    _strict_keys(
        record,
        required={"id", "display_name", "archived", "created_at", "updated_at"},
        label="profile",
    )
    _validate_utc_timestamp(record["created_at"], "profile created_at")
    _validate_utc_timestamp(record["updated_at"], "profile updated_at")
    return LearnerProfile(
        profile_id=record["id"],
        display_name=record["display_name"],
        archived=record["archived"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _plan_to_json(plan: LearningPlan) -> dict[str, Any]:
    return {
        "id": plan.plan_id,
        "profile_id": plan.profile_id,
        "title": plan.title,
        "lesson_ids": list(plan.lesson_ids),
        "enabled": plan.enabled,
        "archived": plan.archived,
        "repetitions": plan.repetitions,
        "questions_per_session": plan.questions_per_session,
        "mastery_gate": plan.mastery_gate,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _plan_from_json(value: object) -> LearningPlan:
    record = _required_mapping(value, "plan")
    _strict_keys(
        record,
        required={
            "id",
            "profile_id",
            "title",
            "lesson_ids",
            "enabled",
            "archived",
            "repetitions",
            "questions_per_session",
            "mastery_gate",
            "created_at",
            "updated_at",
        },
        label="plan",
    )
    _validate_utc_timestamp(record["created_at"], "plan created_at")
    _validate_utc_timestamp(record["updated_at"], "plan updated_at")
    _strict_integer(record["repetitions"], "plan repetitions", minimum=1, maximum=10)
    _strict_integer(
        record["questions_per_session"],
        "plan questions_per_session",
        minimum=1,
        maximum=20,
    )
    return LearningPlan(
        plan_id=record["id"],
        profile_id=record["profile_id"],
        title=record["title"],
        lesson_ids=tuple(record["lesson_ids"]),
        enabled=record["enabled"],
        archived=record["archived"],
        repetitions=record["repetitions"],
        questions_per_session=record["questions_per_session"],
        mastery_gate=record["mastery_gate"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _session_to_json(session: LearningSession) -> dict[str, Any]:
    return {
        "id": session.session_id,
        "profile_id": session.profile_id,
        "plan_id": session.plan_id,
        "questions": [question.to_json() for question in session.questions],
        "question_index": session.question_index,
        "current_attempt": session.current_attempt,
        "scaffolded": session.scaffolded,
        "attempts": [attempt.to_json() for attempt in session.attempts],
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "replay_count": session.replay_count,
    }


def _session_from_json(value: object) -> LearningSession:
    # Importing Question here avoids making the persistence surface duplicate
    # the curriculum model's question validation.
    from .models import Question

    record = _required_mapping(value, "session")
    _strict_keys(
        record,
        required={
            "id",
            "profile_id",
            "plan_id",
            "questions",
            "question_index",
            "current_attempt",
            "scaffolded",
            "attempts",
            "started_at",
            "updated_at",
            "replay_count",
        },
        label="session",
    )
    _validate_utc_timestamp(record["started_at"], "session started_at")
    _validate_utc_timestamp(record["updated_at"], "session updated_at")
    if not isinstance(record["questions"], list) or not isinstance(
        record["attempts"], list
    ):
        raise LearningCorruptDataError("session questions and attempts must be lists")
    _strict_integer(
        record["question_index"],
        "session question_index",
        maximum=len(record["questions"]),
    )
    _strict_integer(record["current_attempt"], "session current_attempt")
    _strict_integer(record["replay_count"], "session replay_count")
    return LearningSession(
        session_id=record["id"],
        profile_id=record["profile_id"],
        plan_id=record["plan_id"],
        questions=tuple(Question.from_json(item) for item in record["questions"]),
        question_index=record["question_index"],
        current_attempt=record["current_attempt"],
        scaffolded=record["scaffolded"],
        attempts=tuple(_attempt_from_json(item) for item in record["attempts"]),
        started_at=record["started_at"],
        updated_at=record["updated_at"],
        replay_count=record["replay_count"],
    )


def _attempt_from_json(value: object) -> AttemptRecord:
    record = _required_mapping(value, "attempt")
    expected = {
        "id",
        "session_id",
        "profile_id",
        "plan_id",
        "lesson_id",
        "skills",
        "question_id",
        "correct_answers",
        "response",
        "correct",
        "attempt_number",
        "scaffolded",
        "hint_used",
        "revealed",
        "elapsed_seconds",
        "timestamp",
        "generation_version",
    }
    _strict_keys(record, required=expected, label="attempt")
    _validate_utc_timestamp(record["timestamp"], "attempt timestamp")
    _strict_integer(record["attempt_number"], "attempt number", minimum=1)
    _strict_integer(
        record["generation_version"],
        "attempt generation_version",
        minimum=1,
    )
    return AttemptRecord.from_json(record)


T = TypeVar("T")


class LearningStore:
    """Own Learning profiles, plans, attempts, sessions, and reports.

    Existing malformed data switches the instance to read-only mode.  Valid
    documents remain available for inspection, while every mutation raises a
    typed error rather than silently replacing the malformed document.
    """

    def __init__(
        self,
        data_directory: str | Path,
        *,
        history_limit: int = 2_000,
        mastery_history_limit: int = 20,
        mastery_threshold: float = 0.8,
        mastery_min_evidence: int = 5,
        reporter: Callable[[str], None] = print,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if isinstance(history_limit, bool) or not 10 <= history_limit <= 10_000:
            raise ValueError("history_limit must be between 10 and 10000")
        if (
            isinstance(mastery_history_limit, bool)
            or not 3 <= mastery_history_limit <= 100
        ):
            raise ValueError("mastery_history_limit must be between 3 and 100")
        if isinstance(mastery_threshold, bool) or not 0.5 <= float(mastery_threshold) <= 1.0:
            raise ValueError("mastery_threshold must be between 0.5 and 1.0")
        if (
            isinstance(mastery_min_evidence, bool)
            or not 2 <= mastery_min_evidence <= 20
        ):
            raise ValueError("mastery_min_evidence must be between 2 and 20")
        if mastery_history_limit < mastery_min_evidence:
            raise ValueError(
                "mastery_history_limit must be at least mastery_min_evidence"
            )
        root = Path(data_directory).expanduser()
        if not str(root).strip() or root.name in {"", ".", ".."}:
            raise ValueError("Learning data_directory must name a dedicated folder")
        self.data_directory = root
        self.profiles_path = root / "profiles.json"
        self.plans_path = root / "plans.json"
        self.progress_path = root / "progress.json"
        self.history_limit = history_limit
        self.session_history_limit = min(history_limit, MAX_SESSION_HISTORY)
        self.mastery_history_limit = mastery_history_limit
        self.mastery_threshold = float(mastery_threshold)
        self.mastery_min_evidence = mastery_min_evidence
        self._reporter = reporter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._profiles: tuple[LearnerProfile, ...] = ()
        self._plans: tuple[LearningPlan, ...] = ()
        self._attempts: tuple[AttemptRecord, ...] = ()
        self._sessions: tuple[LearningSession, ...] = ()
        self._errors: list[str] = []
        self._loaded = False

    @property
    def read_only_error(self) -> str | None:
        self.load()
        return "; ".join(self._errors) or None

    @property
    def errors(self) -> tuple[str, ...]:
        self.load()
        return tuple(self._errors)

    @property
    def is_read_only(self) -> bool:
        return self.read_only_error is not None

    def _timestamp(self) -> str:
        return _as_utc_iso(self._now())

    def _new_id(self, prefix: str) -> str:
        raw = self._id_factory()
        if not isinstance(raw, str) or not raw.strip():
            raise LearningStoreError("the Learning id factory returned an invalid id")
        candidate = f"{prefix}_{raw.strip()}"
        # Model construction performs the canonical safe-ID validation.
        return candidate

    def _safe_path(self, path: Path) -> Path:
        root = self.data_directory.absolute()
        candidate = path.absolute()
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise LearningPersistenceError("Learning data path escapes its root") from exc
        if len(relative.parts) != 1:
            raise LearningPersistenceError("Learning data files must be direct children")
        if (
            self.data_directory.is_symlink()
            or self.data_directory.parent.is_symlink()
            or path.is_symlink()
        ):
            raise LearningPersistenceError("Learning data paths cannot be symlinks")
        if self.data_directory.exists() and not self.data_directory.is_dir():
            raise LearningPersistenceError("Learning data root is not a directory")
        if self.data_directory.exists():
            resolved_root = self.data_directory.resolve(strict=True)
            resolved_parent = path.parent.resolve(strict=True)
            if resolved_parent != resolved_root:
                raise LearningPersistenceError("Learning data path escapes its root")
        return path

    def _mark_unavailable(self, label: str) -> None:
        message = f"{label} data is unavailable or malformed"
        if message not in self._errors:
            self._errors.append(message)
            self._reporter(
                f"[LEARNING] {label.capitalize()} data could not be loaded; "
                "progress is read-only until the local file is repaired."
            )

    def _read_document(self, path: Path, label: str) -> Mapping[str, Any] | None:
        try:
            self._safe_path(path)
            if not path.exists():
                return None
            if path.stat().st_size > MAX_DATA_FILE_BYTES:
                raise LearningCorruptDataError("data file is too large")
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(
                    handle,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            document = _required_mapping(value, f"{label} document")
            if document.get("version") != SCHEMA_VERSION:
                raise LearningCorruptDataError(f"unsupported {label} schema")
            _validate_utc_timestamp(document.get("updated_at"), f"{label} updated_at")
            return document
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            LearningDataError,
            LearningStoreError,
            TypeError,
            ValueError,
        ):
            self._mark_unavailable(label)
            return None

    def load(self) -> None:
        """Load every existing document once without creating anything."""
        if self._loaded:
            return
        try:
            if self.data_directory.is_symlink() or (
                self.data_directory.parent.is_symlink()
            ) or (
                self.data_directory.exists() and not self.data_directory.is_dir()
            ):
                raise LearningPersistenceError("unsafe Learning data root")
        except (OSError, LearningPersistenceError):
            self._mark_unavailable("storage")
            self._loaded = True
            return

        profiles_doc = self._read_document(self.profiles_path, "profiles")
        plans_doc = self._read_document(self.plans_path, "plans")
        progress_doc = self._read_document(self.progress_path, "progress")

        if profiles_doc is not None:
            try:
                _strict_keys(
                    profiles_doc,
                    required={"version", "updated_at", "profiles"},
                    label="profiles document",
                )
                values = profiles_doc["profiles"]
                if not isinstance(values, list):
                    raise LearningCorruptDataError("profiles must be a list")
                profiles = tuple(_profile_from_json(item) for item in values)
                self._assert_unique(profiles, lambda item: item.profile_id, "profile")
                self._profiles = profiles
            except (LearningDataError, LearningStoreError, TypeError, ValueError):
                self._profiles = ()
                self._mark_unavailable("profiles")

        if plans_doc is not None:
            try:
                _strict_keys(
                    plans_doc,
                    required={"version", "updated_at", "plans"},
                    label="plans document",
                )
                values = plans_doc["plans"]
                if not isinstance(values, list):
                    raise LearningCorruptDataError("plans must be a list")
                plans = tuple(_plan_from_json(item) for item in values)
                self._assert_unique(plans, lambda item: item.plan_id, "plan")
                if any(
                    len(plan.lesson_ids) != len(set(plan.lesson_ids))
                    for plan in plans
                ):
                    raise LearningCorruptDataError(
                        "plan lesson ids must be unique"
                    )
                self._plans = plans
            except (LearningDataError, LearningStoreError, TypeError, ValueError):
                self._plans = ()
                self._mark_unavailable("plans")

        if progress_doc is not None:
            try:
                _strict_keys(
                    progress_doc,
                    required={"version", "updated_at", "attempts", "sessions"},
                    label="progress document",
                )
                attempts_value = progress_doc["attempts"]
                sessions_value = progress_doc["sessions"]
                if not isinstance(attempts_value, list) or not isinstance(
                    sessions_value, list
                ):
                    raise LearningCorruptDataError(
                        "progress attempts and sessions must be lists"
                    )
                attempts = tuple(_attempt_from_json(item) for item in attempts_value)
                sessions = tuple(_session_from_json(item) for item in sessions_value)
                self._assert_unique(attempts, lambda item: item.attempt_id, "attempt")
                self._assert_unique(sessions, lambda item: item.session_id, "session")
                self._assert_unique_attempt_numbers(attempts)
                for session in sessions:
                    self._assert_unique_attempt_numbers(session.attempts)
                self._attempts = attempts[-self.history_limit :]
                self._sessions = sessions[-self.session_history_limit :]
            except (LearningDataError, LearningStoreError, TypeError, ValueError):
                self._attempts = ()
                self._sessions = ()
                self._mark_unavailable("progress")
        self._validate_loaded_relationships()
        self._loaded = True

    def _validate_loaded_relationships(self) -> None:
        profile_ids = {profile.profile_id for profile in self._profiles}
        if "profiles data is unavailable or malformed" not in self._errors:
            if any(plan.profile_id not in profile_ids for plan in self._plans):
                self._plans = ()
                self._mark_unavailable("plans")

        plan_ids = {plan.plan_id for plan in self._plans}
        profiles_available = "profiles data is unavailable or malformed" not in self._errors
        plans_available = "plans data is unavailable or malformed" not in self._errors
        progress_invalid = False
        if profiles_available:
            progress_invalid = any(
                attempt.profile_id not in profile_ids for attempt in self._attempts
            ) or any(session.profile_id not in profile_ids for session in self._sessions)
        if not progress_invalid and plans_available:
            progress_invalid = any(
                attempt.plan_id is not None and attempt.plan_id not in plan_ids
                for attempt in self._attempts
            ) or any(
                session.plan_id is not None and session.plan_id not in plan_ids
                for session in self._sessions
            )
        if not progress_invalid:
            progress_invalid = any(
                nested.session_id != session.session_id
                or nested.profile_id != session.profile_id
                or nested.plan_id != session.plan_id
                for session in self._sessions
                for nested in session.attempts
            )
        if progress_invalid:
            self._attempts = ()
            self._sessions = ()
            self._mark_unavailable("progress")

    @staticmethod
    def _assert_unique(
        items: Iterable[T], key: Callable[[T], str], label: str
    ) -> None:
        identifiers = [key(item) for item in items]
        if len(identifiers) != len(set(identifiers)):
            raise LearningCorruptDataError(f"{label} ids must be unique")

    @staticmethod
    def _assert_unique_attempt_numbers(attempts: Iterable[AttemptRecord]) -> None:
        keys = [
            (item.session_id, item.question_id, item.attempt_number)
            for item in attempts
        ]
        if len(keys) != len(set(keys)):
            raise LearningCorruptDataError(
                "each question attempt number must be unique within a session"
            )

    def _ensure_writable(self) -> None:
        self.load()
        if self._errors:
            raise LearningReadOnlyError(
                "Learning data is read-only until malformed local data is repaired"
            )

    def _atomic_write(self, path: Path, value: Mapping[str, Any]) -> None:
        self._ensure_writable()
        temporary: Path | None = None
        descriptor: int | None = None
        root_existed = self.data_directory.exists()
        try:
            self.data_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._safe_path(path)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=self.data_directory,
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(
                    value,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
            try:
                directory_fd = os.open(self.data_directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # The file itself is already flushed and replaced. Some
                # platforms/filesystems do not permit directory fsync.
                pass
        except (OSError, TypeError, ValueError, LearningStoreError) as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
            if not root_existed:
                try:
                    self.data_directory.rmdir()
                except OSError:
                    pass
            if isinstance(exc, LearningReadOnlyError):
                raise
            raise LearningPersistenceError(
                f"Could not save Learning {path.stem} data"
            ) from exc

    def _write_profiles(self, profiles: Sequence[LearnerProfile]) -> None:
        supplied = tuple(profiles)
        if any(not isinstance(item, LearnerProfile) for item in supplied):
            raise TypeError("profiles must be LearnerProfile records")
        for profile in supplied:
            _profile_from_json(_profile_to_json(profile))
        self._assert_unique(supplied, lambda item: item.profile_id, "profile")
        timestamp = self._timestamp()
        self._atomic_write(
            self.profiles_path,
            {
                "version": SCHEMA_VERSION,
                "updated_at": timestamp,
                "profiles": [_profile_to_json(profile) for profile in supplied],
            },
        )
        self._profiles = supplied

    def _write_plans(self, plans: Sequence[LearningPlan]) -> None:
        supplied = tuple(plans)
        if any(not isinstance(item, LearningPlan) for item in supplied):
            raise TypeError("plans must be LearningPlan records")
        for plan in supplied:
            _plan_from_json(_plan_to_json(plan))
        self._assert_unique(supplied, lambda item: item.plan_id, "plan")
        profile_ids = {profile.profile_id for profile in self._profiles}
        if any(plan.profile_id not in profile_ids for plan in supplied):
            raise LearningStoreError("every plan must belong to an existing learner")
        if any(len(plan.lesson_ids) != len(set(plan.lesson_ids)) for plan in supplied):
            raise LearningStoreError("plan lesson ids must be unique")
        self._atomic_write(
            self.plans_path,
            {
                "version": SCHEMA_VERSION,
                "updated_at": self._timestamp(),
                "plans": [_plan_to_json(plan) for plan in supplied],
            },
        )
        self._plans = supplied

    def _write_progress(
        self,
        attempts: Sequence[AttemptRecord],
        sessions: Sequence[LearningSession],
    ) -> None:
        bounded_attempts = tuple(attempts)[-self.history_limit :]
        bounded_sessions = tuple(sessions)[-self.session_history_limit :]
        if any(not isinstance(item, AttemptRecord) for item in bounded_attempts):
            raise TypeError("attempts must be AttemptRecord records")
        if any(not isinstance(item, LearningSession) for item in bounded_sessions):
            raise TypeError("sessions must be LearningSession records")
        for attempt in bounded_attempts:
            _attempt_from_json(attempt.to_json())
        for session in bounded_sessions:
            _session_from_json(_session_to_json(session))
        self._assert_unique(bounded_attempts, lambda item: item.attempt_id, "attempt")
        self._assert_unique(bounded_sessions, lambda item: item.session_id, "session")
        self._assert_unique_attempt_numbers(bounded_attempts)
        for session in bounded_sessions:
            self._assert_unique_attempt_numbers(session.attempts)
        self._atomic_write(
            self.progress_path,
            {
                "version": SCHEMA_VERSION,
                "updated_at": self._timestamp(),
                "attempts": [attempt.to_json() for attempt in bounded_attempts],
                "sessions": [_session_to_json(session) for session in bounded_sessions],
            },
        )
        self._attempts = bounded_attempts
        self._sessions = bounded_sessions

    # -- Profiles ---------------------------------------------------------

    def list_profiles(self, *, include_archived: bool = False) -> tuple[LearnerProfile, ...]:
        self.load()
        return tuple(
            profile
            for profile in self._profiles
            if include_archived or not profile.archived
        )

    def get_profile(self, profile_id: str) -> LearnerProfile:
        self.load()
        profile = next(
            (item for item in self._profiles if item.profile_id == profile_id), None
        )
        if profile is None:
            raise KeyError(profile_id)
        return profile

    def create_profile(self, display_name: str) -> LearnerProfile:
        self._ensure_writable()
        timestamp = self._timestamp()
        profile = LearnerProfile(
            profile_id=self._new_id("learner"),
            display_name=display_name,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._write_profiles((*self._profiles, profile))
        return profile

    def rename_profile(self, profile_id: str, display_name: str) -> LearnerProfile:
        self._ensure_writable()
        profile = self.get_profile(profile_id)
        updated = replace(
            profile,
            display_name=display_name,
            updated_at=self._timestamp(),
        )
        self._write_profiles(
            tuple(updated if item.profile_id == profile_id else item for item in self._profiles)
        )
        return updated

    def archive_profile(
        self, profile_id: str, *, confirmed: bool = False
    ) -> LearnerProfile:
        self._require_confirmation(confirmed, "archive learner profile")
        self._ensure_writable()
        profile = self.get_profile(profile_id)
        updated = replace(profile, archived=True, updated_at=self._timestamp())
        self._write_profiles(
            tuple(updated if item.profile_id == profile_id else item for item in self._profiles)
        )
        return updated

    def restore_profile(self, profile_id: str) -> LearnerProfile:
        self._ensure_writable()
        profile = self.get_profile(profile_id)
        updated = replace(profile, archived=False, updated_at=self._timestamp())
        self._write_profiles(
            tuple(updated if item.profile_id == profile_id else item for item in self._profiles)
        )
        return updated

    def delete_profile(self, profile_id: str, *, confirmed: bool = False) -> None:
        """Delete an empty profile; progress must first be reset explicitly."""
        self._require_confirmation(confirmed, "delete learner profile")
        self._ensure_writable()
        self.get_profile(profile_id)
        if any(plan.profile_id == profile_id for plan in self._plans) or any(
            attempt.profile_id == profile_id for attempt in self._attempts
        ) or any(session.profile_id == profile_id for session in self._sessions):
            raise LearningStoreError(
                "archive this learner or explicitly remove their plans and progress first"
            )
        self._write_profiles(
            tuple(item for item in self._profiles if item.profile_id != profile_id)
        )

    # -- Plans ------------------------------------------------------------

    def list_plans(
        self,
        profile_id: str | None = None,
        *,
        include_archived: bool = False,
    ) -> tuple[LearningPlan, ...]:
        self.load()
        return tuple(
            plan
            for plan in self._plans
            if (profile_id is None or plan.profile_id == profile_id)
            and (include_archived or not plan.archived)
        )

    def get_plan(self, plan_id: str) -> LearningPlan:
        self.load()
        plan = next((item for item in self._plans if item.plan_id == plan_id), None)
        if plan is None:
            raise KeyError(plan_id)
        return plan

    def create_plan(
        self,
        profile_id: str,
        title: str,
        lesson_ids: Sequence[str],
        *,
        enabled: bool = True,
        repetitions: int = 1,
        questions_per_session: int | None = None,
        question_count: int | None = None,
        session_size: int | None = None,
        mastery_gate: bool = False,
    ) -> LearningPlan:
        self._ensure_writable()
        self.get_profile(profile_id)
        if len(lesson_ids) != len(set(lesson_ids)):
            raise LearningStoreError("plan lesson ids must be unique")
        supplied_counts = tuple(
            value
            for value in (questions_per_session, question_count, session_size)
            if value is not None
        )
        if len(set(supplied_counts)) > 1:
            raise LearningStoreError("conflicting plan question counts were supplied")
        effective_question_count = supplied_counts[0] if supplied_counts else 8
        if (
            isinstance(effective_question_count, bool)
            or not isinstance(effective_question_count, int)
            or not 1 <= effective_question_count <= 20
        ):
            raise LearningStoreError("plan question count must be between 1 and 20")
        timestamp = self._timestamp()
        plan = LearningPlan(
            plan_id=self._new_id("plan"),
            profile_id=profile_id,
            title=title,
            lesson_ids=tuple(lesson_ids),
            enabled=enabled,
            repetitions=repetitions,
            questions_per_session=effective_question_count,
            mastery_gate=mastery_gate,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._write_plans((*self._plans, plan))
        return plan

    def update_plan(self, plan: LearningPlan) -> LearningPlan:
        if not isinstance(plan, LearningPlan):
            raise TypeError("plan must be a LearningPlan")
        self._ensure_writable()
        existing = self.get_plan(plan.plan_id)
        if plan.profile_id != existing.profile_id:
            raise LearningStoreError("a plan cannot be moved between learner profiles")
        if len(plan.lesson_ids) != len(set(plan.lesson_ids)):
            raise LearningStoreError("plan lesson ids must be unique")
        updated = replace(
            plan,
            created_at=existing.created_at,
            updated_at=self._timestamp(),
        )
        self._write_plans(
            tuple(updated if item.plan_id == plan.plan_id else item for item in self._plans)
        )
        return updated

    def reorder_plan_lessons(
        self, plan_id: str, lesson_ids: Sequence[str]
    ) -> LearningPlan:
        return self.update_plan(replace(self.get_plan(plan_id), lesson_ids=tuple(lesson_ids)))

    def set_plan_enabled(self, plan_id: str, enabled: bool) -> LearningPlan:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        return self.update_plan(replace(self.get_plan(plan_id), enabled=enabled))

    def duplicate_plan(
        self,
        plan_id: str,
        *,
        title: str | None = None,
        name: str | None = None,
    ) -> LearningPlan:
        self._ensure_writable()
        source = self.get_plan(plan_id)
        if title is not None and name is not None and title != name:
            raise LearningStoreError("conflicting duplicate plan names were supplied")
        return self.create_plan(
            source.profile_id,
            title or name or f"{source.title} Copy",
            source.lesson_ids,
            enabled=source.enabled,
            repetitions=source.repetitions,
            questions_per_session=source.questions_per_session,
            mastery_gate=source.mastery_gate,
        )

    def archive_plan(self, plan_id: str, *, confirmed: bool = False) -> LearningPlan:
        self._require_confirmation(confirmed, "archive learning plan")
        return self.update_plan(replace(self.get_plan(plan_id), archived=True, enabled=False))

    def restore_plan(self, plan_id: str) -> LearningPlan:
        return self.update_plan(replace(self.get_plan(plan_id), archived=False))

    def delete_plan(self, plan_id: str, *, confirmed: bool = False) -> None:
        """Delete an empty plan; its progress must first be explicitly reset."""
        self._require_confirmation(confirmed, "delete learning plan")
        self._ensure_writable()
        self.get_plan(plan_id)
        if any(attempt.plan_id == plan_id for attempt in self._attempts) or any(
            session.plan_id == plan_id for session in self._sessions
        ):
            raise LearningStoreError(
                "archive this plan or explicitly reset its progress first"
            )
        self._write_plans(tuple(item for item in self._plans if item.plan_id != plan_id))

    # -- Attempts and resumable sessions ---------------------------------

    def list_attempts(
        self,
        profile_id: str | None = None,
        plan_id: str | None = None,
        lesson_id: str | None = None,
    ) -> tuple[AttemptRecord, ...]:
        self.load()
        return tuple(
            attempt
            for attempt in self._attempts
            if (profile_id is None or attempt.profile_id == profile_id)
            and (plan_id is None or attempt.plan_id == plan_id)
            and (lesson_id is None or attempt.lesson_id == lesson_id)
        )

    def list_sessions(
        self,
        profile_id: str | None = None,
        plan_id: str | None = None,
    ) -> tuple[LearningSession, ...]:
        self.load()
        return tuple(
            session
            for session in self._sessions
            if (profile_id is None or session.profile_id == profile_id)
            and (plan_id is None or session.plan_id == plan_id)
        )

    def resumable_session(
        self,
        profile_id: str,
        plan_id: str | None = None,
        lesson_id: str | None = None,
    ) -> LearningSession | None:
        candidates = tuple(
            session
            for session in self.list_sessions(profile_id, plan_id)
            if not session.complete
            and (
                lesson_id is None
                or any(
                    question.lesson_id == lesson_id
                    for question in session.questions
                )
            )
        )
        return max(candidates, key=lambda item: item.updated_at, default=None)

    # Alias reads naturally in UI/controller code.
    get_resumable_session = resumable_session

    def append_attempt(self, attempt: AttemptRecord) -> AttemptRecord:
        if not isinstance(attempt, AttemptRecord):
            raise TypeError("attempt must be an AttemptRecord")
        self._ensure_writable()
        _validate_utc_timestamp(attempt.timestamp, "attempt timestamp")
        self._validate_attempt_ownership(attempt)
        if any(item.attempt_id == attempt.attempt_id for item in self._attempts):
            raise LearningStoreError("attempt id already exists")
        self._write_progress((*self._attempts, attempt), self._sessions)
        return attempt

    def save_session(self, session: LearningSession) -> LearningSession:
        if not isinstance(session, LearningSession):
            raise TypeError("session must be a LearningSession")
        self._ensure_writable()
        _validate_utc_timestamp(session.started_at, "session started_at")
        _validate_utc_timestamp(session.updated_at, "session updated_at")
        self._validate_session_ownership(session)
        sessions = tuple(
            item for item in self._sessions if item.session_id != session.session_id
        ) + (session,)
        self._write_progress(self._attempts, sessions)
        return session

    def record_transition(
        self, attempt: AttemptRecord, session: LearningSession
    ) -> LearningSession:
        """Atomically commit a graded attempt and its new resumable state."""
        if not isinstance(attempt, AttemptRecord) or not isinstance(
            session, LearningSession
        ):
            raise TypeError("record_transition requires an attempt and session")
        self._ensure_writable()
        self._validate_attempt_ownership(attempt)
        self._validate_session_ownership(session)
        if attempt.session_id != session.session_id:
            raise LearningStoreError("attempt and session ids do not match")
        if attempt.profile_id != session.profile_id or attempt.plan_id != session.plan_id:
            raise LearningStoreError("attempt and session ownership do not match")
        if any(item.attempt_id == attempt.attempt_id for item in self._attempts):
            raise LearningStoreError("attempt id already exists")
        if attempt not in session.attempts:
            raise LearningStoreError(
                "updated session must contain the graded attempt"
            )
        sessions = tuple(
            item for item in self._sessions if item.session_id != session.session_id
        ) + (session,)
        self._write_progress((*self._attempts, attempt), sessions)
        return session

    def discard_session(self, session_id: str, *, confirmed: bool = False) -> bool:
        self._require_confirmation(confirmed, "discard learning session")
        self._ensure_writable()
        retained = tuple(
            item for item in self._sessions if item.session_id != session_id
        )
        if len(retained) == len(self._sessions):
            return False
        self._write_progress(self._attempts, retained)
        return True

    def reset_progress(
        self,
        profile_id: str,
        *,
        plan_id: str | None = None,
        lesson_id: str | None = None,
        confirmed: bool = False,
    ) -> int:
        """Reset only the explicitly selected learner progress scope.

        A learner id is always required, preventing an accidental global reset.
        Selecting a lesson also removes sessions that contain that lesson,
        because their resume cursor would otherwise recreate removed progress.
        """
        self._require_confirmation(confirmed, "reset learner progress")
        self._ensure_writable()
        self.get_profile(profile_id)
        if plan_id is not None:
            plan = self.get_plan(plan_id)
            if plan.profile_id != profile_id:
                raise LearningStoreError("plan does not belong to learner")
        def selected_attempt(item: AttemptRecord) -> bool:
            return (
                item.profile_id == profile_id
                and (plan_id is None or item.plan_id == plan_id)
                and (lesson_id is None or item.lesson_id == lesson_id)
            )

        def selected_session(item: LearningSession) -> bool:
            if item.profile_id != profile_id or (
                plan_id is not None and item.plan_id != plan_id
            ):
                return False
            if lesson_id is None:
                return True
            return any(question.lesson_id == lesson_id for question in item.questions)

        retained_attempts = tuple(item for item in self._attempts if not selected_attempt(item))
        retained_sessions = tuple(item for item in self._sessions if not selected_session(item))
        removed = (len(self._attempts) - len(retained_attempts)) + (
            len(self._sessions) - len(retained_sessions)
        )
        if removed:
            self._write_progress(retained_attempts, retained_sessions)
        return removed

    def _validate_attempt_ownership(self, attempt: AttemptRecord) -> None:
        self.get_profile(attempt.profile_id)
        if attempt.plan_id is not None:
            plan = self.get_plan(attempt.plan_id)
            if plan.profile_id != attempt.profile_id:
                raise LearningStoreError("attempt plan does not belong to learner")

    def _validate_session_ownership(self, session: LearningSession) -> None:
        self.get_profile(session.profile_id)
        if session.plan_id is not None:
            plan = self.get_plan(session.plan_id)
            if plan.profile_id != session.profile_id:
                raise LearningStoreError("session plan does not belong to learner")

    @staticmethod
    def _require_confirmation(confirmed: bool, operation: str) -> None:
        if confirmed is not True:
            raise LearningConfirmationRequired(
                f"Explicit confirmation is required to {operation}"
            )

    # -- Rebuildable statistics ------------------------------------------

    @staticmethod
    def _question_evidence(
        attempts: Sequence[AttemptRecord],
    ) -> tuple[tuple[AttemptRecord, ...], ...]:
        groups: dict[tuple[str, str], list[AttemptRecord]] = {}
        for attempt in attempts:
            groups.setdefault((attempt.session_id, attempt.question_id), []).append(attempt)
        ordered = sorted(
            groups.values(),
            key=lambda group: max(item.timestamp for item in group),
        )
        return tuple(
            tuple(sorted(group, key=lambda item: item.attempt_number))
            for group in ordered
        )

    def skill_mastery(
        self, profile_id: str, skill: str, *, plan_id: str | None = None
    ) -> SkillMastery:
        """Derive mastery from recent distinct questions.

        The engine owns the canonical 60% first-try plus 40% eventual formula
        and its multi-evidence mastery rule. Replays are absent from attempt
        history and therefore cannot change any score.
        """
        from .engine import summarize_mastery

        attempts = self.list_attempts(profile_id)
        if plan_id is not None:
            plan = self.get_plan(plan_id)
            if plan.profile_id != profile_id:
                raise LearningStoreError("plan does not belong to learner")
            attempts = tuple(
                attempt
                for attempt in attempts
                if attempt.plan_id in {None, plan_id}
            )
        return summarize_mastery(
            attempts,
            skill=skill,
            mastery_threshold=self.mastery_threshold,
            minimum_evidence=self.mastery_min_evidence,
            recent_evidence_limit=self.mastery_history_limit,
        )

    def lesson_mastery(
        self,
        profile_id: str,
        lesson_id: str,
        *,
        plan_id: str | None = None,
    ) -> SkillMastery:
        """Derive mastery from questions generated by one lesson."""
        from .engine import summarize_mastery

        self.get_profile(profile_id)
        attempts = tuple(
            attempt
            for attempt in self.list_attempts(profile_id, plan_id)
            if attempt.lesson_id == lesson_id
        )
        return summarize_mastery(
            attempts,
            skill=lesson_id,
            mastery_threshold=self.mastery_threshold,
            minimum_evidence=self.mastery_min_evidence,
            recent_evidence_limit=self.mastery_history_limit,
        )

    # Compatibility alias for callers that use a noun-based lookup.
    mastery = skill_mastery

    def plan_stats(self, plan_id: str) -> PlanReport:
        from .engine import summarize_plan

        plan = self.get_plan(plan_id)
        return summarize_plan(
            plan,
            self.list_attempts(plan.profile_id),
            mastery_threshold=self.mastery_threshold,
            minimum_evidence=self.mastery_min_evidence,
            recent_evidence_limit=self.mastery_history_limit,
        )

    plan_report = plan_stats

    def profile_stats(self, profile_id: str) -> dict[str, Any]:
        """Return JSON-friendly totals derived entirely from source records."""
        from .engine import summarize_mastery

        self.get_profile(profile_id)
        attempts = self.list_attempts(profile_id)
        evidence = self._question_evidence(attempts)
        first = (
            sum(
                bool(group[0].correct and group[0].attempt_number == 1)
                for group in evidence
            )
            / len(evidence)
            if evidence
            else 0.0
        )
        eventual = (
            sum(any(item.correct for item in group) for group in evidence) / len(evidence)
            if evidence
            else 0.0
        )
        recent = evidence[-min(5, len(evidence)) :]
        recent_trend = (
            round(
                sum(any(item.correct for item in group) for group in recent)
                / len(recent),
                4,
            )
            if recent
            else 0.0
        )
        skill_ids = tuple(
            sorted({skill for attempt in attempts for skill in attempt.skills})
        )[:MAX_PROFILE_SKILL_SUMMARIES]
        mastery_records = tuple(
            summarize_mastery(
                attempts,
                skill=skill,
                mastery_threshold=self.mastery_threshold,
                minimum_evidence=self.mastery_min_evidence,
                recent_evidence_limit=self.mastery_history_limit,
            )
            for skill in skill_ids
        )
        skills = [
            {
                "skill": mastery.skill,
                "status": mastery.status.value,
                "evidence_count": mastery.evidence_count,
                "attempt_count": mastery.attempt_count,
                "first_try_accuracy": mastery.first_try_accuracy,
                "eventual_accuracy": mastery.eventual_accuracy,
                "percentage_grade": mastery.percentage_grade,
                "recent_trend": mastery.recent_trend,
                "practiced_seconds": mastery.practiced_seconds,
            }
            for mastery in mastery_records
        ]
        plans = self.list_plans(profile_id, include_archived=True)
        return {
            "profile_id": profile_id,
            "plan_count": len(plans),
            "attempt_count": len(attempts),
            "evidence_count": len(evidence),
            "accuracy": (
                sum(item.correct for item in attempts) / len(attempts)
                if attempts
                else 0.0
            ),
            "first_try_accuracy": first,
            "eventual_accuracy": eventual,
            "recent_trend": recent_trend,
            "percentage_grade": round(
                (0.6 * first + 0.4 * eventual) * 100.0,
                2,
            ),
            "practiced_seconds": sum(item.elapsed_seconds for item in attempts),
            "practice_seconds": sum(item.elapsed_seconds for item in attempts),
            "completion_percent": (
                sum(self.plan_stats(plan.plan_id).completion_percent for plan in plans)
                / len(plans)
                if plans
                else 0.0
            ),
            "skills": skills,
        }


__all__ = [
    "MAX_DATA_FILE_BYTES",
    "MAX_PROFILE_SKILL_SUMMARIES",
    "MAX_SESSION_HISTORY",
    "SCHEMA_VERSION",
    "LearningConfirmationRequired",
    "LearningCorruptDataError",
    "LearningPersistenceError",
    "LearningReadOnlyError",
    "LearningStore",
    "LearningStoreError",
    "utc_now_iso",
]
