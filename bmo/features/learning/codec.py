"""Canonical strict codec for Learning's private persisted documents.

The model ``to_json`` methods remain the public UI/transport representation.
This module exclusively owns the version-one on-disk field names and strict
validation used by :class:`LearningStore`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from bmo.jsonio import duplicate_key_hook

from .errors import LearningCorruptDataError
from .models import (
    AttemptRecord,
    LearnerProfile,
    LearningPlan,
    LearningSession,
    Question,
)


object_without_duplicate_keys = duplicate_key_hook(
    LearningCorruptDataError,
    "JSON objects cannot repeat field names",
)


def reject_json_constant(value: str) -> None:
    raise LearningCorruptDataError(
        f"non-finite JSON number {value} is unsupported"
    )


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LearningCorruptDataError(f"{label} must be an object")
    return value


def _validate_utc_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCorruptDataError(
            f"{label} is not an ISO 8601 UTC timestamp"
        )
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


def _strict_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    if required.difference(value):
        raise LearningCorruptDataError(f"{label} is missing required fields")
    if set(value).difference(required | optional):
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


def profile_to_json(profile: LearnerProfile) -> dict[str, Any]:
    return {
        "id": profile.profile_id,
        "display_name": profile.display_name,
        "archived": profile.archived,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def profile_from_json(value: object) -> LearnerProfile:
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


def plan_to_json(plan: LearningPlan) -> dict[str, Any]:
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


def plan_from_json(value: object) -> LearningPlan:
    record = _required_mapping(value, "plan")
    _strict_keys(
        record,
        required={
            "id", "profile_id", "title", "lesson_ids", "enabled",
            "archived", "repetitions", "questions_per_session",
            "mastery_gate", "created_at", "updated_at",
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


def session_to_json(session: LearningSession) -> dict[str, Any]:
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


def session_from_json(value: object) -> LearningSession:
    record = _required_mapping(value, "session")
    _strict_keys(
        record,
        required={
            "id", "profile_id", "plan_id", "questions", "question_index",
            "current_attempt", "scaffolded", "attempts", "started_at",
            "updated_at", "replay_count",
        },
        label="session",
    )
    _validate_utc_timestamp(record["started_at"], "session started_at")
    _validate_utc_timestamp(record["updated_at"], "session updated_at")
    if not isinstance(record["questions"], list) or not isinstance(
        record["attempts"], list
    ):
        raise LearningCorruptDataError(
            "session questions and attempts must be lists"
        )
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
        attempts=tuple(attempt_from_json(item) for item in record["attempts"]),
        started_at=record["started_at"],
        updated_at=record["updated_at"],
        replay_count=record["replay_count"],
    )


def attempt_from_json(value: object) -> AttemptRecord:
    record = _required_mapping(value, "attempt")
    expected = {
        "id", "session_id", "profile_id", "plan_id", "lesson_id", "skills",
        "question_id", "correct_answers", "response", "correct",
        "attempt_number", "scaffolded", "hint_used", "revealed",
        "elapsed_seconds", "timestamp", "generation_version",
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


__all__ = [
    "attempt_from_json",
    "object_without_duplicate_keys",
    "plan_from_json",
    "plan_to_json",
    "profile_from_json",
    "profile_to_json",
    "reject_json_constant",
    "session_from_json",
    "session_to_json",
]
