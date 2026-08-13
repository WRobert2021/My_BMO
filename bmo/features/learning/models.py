"""Immutable, UI-independent records for the Learning feature.

The records in this module deliberately contain no Tk, audio, filesystem, or
application imports.  They are the stable boundary between the curriculum,
engine, persistence layer, and touch UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Any, Mapping, Sequence


GENERATION_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")


class LearningDataError(ValueError):
    """Raised when a curriculum or persisted Learning record is invalid."""


class InteractionKind(str, Enum):
    """Small reusable set of interactions understood by the touch UI."""

    SINGLE_CHOICE = "single_choice"
    MULTI_SELECT = "multi_select"
    ALPHABET_GRID = "alphabet_grid"
    MATCHING_PAIRS = "matching_pairs"
    ORDERED_SEQUENCE = "ordered_sequence"
    CATEGORY_SORT = "category_sort"
    PICTURE_CHOICE = "picture_choice"
    LISTEN_HIDDEN = "listen_hidden"
    SCENE_CHOICE = "scene_choice"


class MasteryStatus(str, Enum):
    """Teacher-facing progress state derived from recent evidence."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    MASTERED = "mastered"
    NEEDS_PRACTICE = "needs_practice"


def _clean_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value.strip()):
        raise LearningDataError(f"{label} must be a safe non-empty identifier")
    return value.strip()


def _clean_text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningDataError(f"{label} must be non-empty text")
    cleaned = " ".join(value.split())
    if len(cleaned) > maximum:
        raise LearningDataError(f"{label} is too long")
    return cleaned


def _clean_optional_text(
    value: object,
    label: str,
    *,
    maximum: int = 500,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LearningDataError(f"{label} must be text")
    cleaned = " ".join(value.split())
    if len(cleaned) > maximum:
        raise LearningDataError(f"{label} is too long")
    return cleaned


def _string_tuple(
    values: object,
    label: str,
    *,
    allow_empty: bool = False,
    ids: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise LearningDataError(f"{label} must be a list of strings")
    cleaned: list[str] = []
    for value in values:
        item = _clean_id(value, label) if ids else _clean_text(value, label)
        cleaned.append(item)
    if not cleaned and not allow_empty:
        raise LearningDataError(f"{label} cannot be empty")
    return tuple(cleaned)


def _answer_tuple(
    values: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    """Validate choice IDs and ``choice=category`` response tokens."""

    if isinstance(values, str) or not isinstance(values, Sequence):
        raise LearningDataError(f"{label} must be a list of answer tokens")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise LearningDataError(f"{label} must contain strings")
        token = value.strip()
        parts = token.split("=")
        if len(parts) not in (1, 2) or any(not _SAFE_ID.fullmatch(part) for part in parts):
            raise LearningDataError(f"{label} contains an invalid answer token")
        cleaned.append(token)
    if not cleaned and not allow_empty:
        raise LearningDataError(f"{label} cannot be empty")
    return tuple(cleaned)


def _freeze_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_metadata_value(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_metadata_value(item) for item in value)
    return value


def _pairs(value: object, label: str) -> tuple[tuple[str, Any], ...]:
    """Freeze a shallow metadata mapping while retaining JSON-friendly values."""

    if value is None:
        return ()
    items = value.items() if isinstance(value, Mapping) else value
    try:
        pairs = tuple((str(key), _freeze_metadata_value(item)) for key, item in items)
    except (TypeError, ValueError) as exc:
        raise LearningDataError(f"{label} must be a mapping") from exc
    if any(not key.strip() for key, _ in pairs):
        raise LearningDataError(f"{label} keys cannot be empty")
    if len({key for key, _ in pairs}) != len(pairs):
        raise LearningDataError(f"{label} keys must be unique")
    return tuple(sorted(pairs, key=lambda pair: pair[0]))


def metadata_get(pairs: tuple[tuple[str, Any], ...], key: str, default: Any = None) -> Any:
    """Read one value from frozen metadata without rebuilding a dictionary."""

    return next((value for name, value in pairs if name == key), default)


def _validate_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise LearningDataError(f"{label} must be an ISO 8601 timestamp")
    candidate = value.strip()
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningDataError(f"{label} must be an ISO 8601 timestamp") from exc
    return candidate


@dataclass(frozen=True)
class ContentItem:
    """One locally authored item shared by one or more lesson generators."""

    key: str
    label: str
    spoken: str = ""
    group: str = ""
    attributes: tuple[tuple[str, Any], ...] | Mapping[str, Any] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _clean_id(self.key, "content item key"))
        object.__setattr__(self, "label", _clean_text(self.label, "content item label"))
        object.__setattr__(
            self,
            "spoken",
            _clean_optional_text(self.spoken, "content item spoken text")
            or self.label,
        )
        group = str(self.group).strip()
        if group and not _SAFE_ID.fullmatch(group):
            raise LearningDataError("content item group must be a safe identifier")
        object.__setattr__(self, "group", group)
        object.__setattr__(
            self, "attributes", _pairs(self.attributes, "content item attributes")
        )

    def attribute(self, name: str, default: Any = None) -> Any:
        return metadata_get(self.attributes, name, default)


@dataclass(frozen=True)
class LessonDefinition:
    """A stable, data-driven definition of one teachable skill activity."""

    lesson_id: str
    domain: str
    title: str
    skills: tuple[str, ...]
    prerequisites: tuple[str, ...]
    prompt_templates: tuple[str, ...]
    interaction: InteractionKind
    generator: str
    bank_refs: tuple[str, ...]
    difficulty: int = 1
    choice_count: int = 4
    minimum_correct: int = 1
    maximum_correct: int = 1
    settings: tuple[tuple[str, Any], ...] | Mapping[str, Any] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "lesson_id", _clean_id(self.lesson_id, "lesson id"))
        object.__setattr__(self, "domain", _clean_id(self.domain, "lesson domain"))
        object.__setattr__(self, "title", _clean_text(self.title, "lesson title"))
        object.__setattr__(
            self, "skills", _string_tuple(self.skills, "lesson skills", ids=True)
        )
        object.__setattr__(
            self,
            "prerequisites",
            _string_tuple(
                self.prerequisites,
                "lesson prerequisites",
                allow_empty=True,
                ids=True,
            ),
        )
        object.__setattr__(
            self,
            "prompt_templates",
            _string_tuple(self.prompt_templates, "lesson prompt templates"),
        )
        if not isinstance(self.interaction, InteractionKind):
            try:
                object.__setattr__(self, "interaction", InteractionKind(self.interaction))
            except ValueError as exc:
                raise LearningDataError("unsupported interaction kind") from exc
        object.__setattr__(self, "generator", _clean_id(self.generator, "generator"))
        object.__setattr__(
            self, "bank_refs", _string_tuple(self.bank_refs, "bank references", ids=True)
        )
        for name in ("difficulty", "choice_count", "minimum_correct", "maximum_correct"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise LearningDataError(f"{name} must be an integer")
        if not 1 <= self.difficulty <= 5:
            raise LearningDataError("difficulty must be between 1 and 5")
        if not 2 <= self.choice_count <= 30:
            raise LearningDataError("choice_count must be between 2 and 30")
        if not 1 <= self.minimum_correct <= self.maximum_correct <= self.choice_count:
            raise LearningDataError("correct-answer bounds do not fit choice_count")
        object.__setattr__(self, "settings", _pairs(self.settings, "lesson settings"))

    @property
    def id(self) -> str:
        """Short compatibility alias useful to plan and UI code."""

        return self.lesson_id

    def setting(self, name: str, default: Any = None) -> Any:
        return metadata_get(self.settings, name, default)


@dataclass(frozen=True)
class Choice:
    """One stable answer target rendered as text or programmatic artwork."""

    id: str
    label: str
    spoken: str = ""
    metadata: tuple[tuple[str, Any], ...] | Mapping[str, Any] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _clean_id(self.id, "choice id"))
        object.__setattr__(self, "label", _clean_text(self.label, "choice label"))
        object.__setattr__(
            self,
            "spoken",
            _clean_optional_text(self.spoken, "choice spoken text") or self.label,
        )
        object.__setattr__(self, "metadata", _pairs(self.metadata, "choice metadata"))

    def meta(self, name: str, default: Any = None) -> Any:
        return metadata_get(self.metadata, name, default)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "spoken": self.spoken,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_json(cls, value: object) -> Choice:
        if not isinstance(value, Mapping):
            raise LearningDataError("choice must be an object")
        return cls(
            id=value.get("id", ""),
            label=value.get("label", ""),
            spoken=value.get("spoken", ""),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True)
class Question:
    """A fully generated question; the UI never branches on lesson IDs."""

    question_id: str
    lesson_id: str
    domain: str
    skills: tuple[str, ...]
    interaction: InteractionKind
    prompt: str
    spoken_prompt: str
    choices: tuple[Choice, ...]
    correct_answers: tuple[str, ...]
    hidden_prompt: bool = False
    requires_submit: bool = False
    example: str = ""
    explanation: str = ""
    hint: str = ""
    generation_version: int = GENERATION_VERSION
    metadata: tuple[tuple[str, Any], ...] | Mapping[str, Any] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_id", _clean_id(self.question_id, "question id"))
        object.__setattr__(self, "lesson_id", _clean_id(self.lesson_id, "question lesson id"))
        object.__setattr__(self, "domain", _clean_id(self.domain, "question domain"))
        object.__setattr__(self, "skills", _string_tuple(self.skills, "question skills", ids=True))
        if not isinstance(self.interaction, InteractionKind):
            try:
                object.__setattr__(self, "interaction", InteractionKind(self.interaction))
            except ValueError as exc:
                raise LearningDataError("unsupported question interaction") from exc
        prompt = _clean_text(self.prompt, "question prompt")
        spoken = _clean_text(self.spoken_prompt, "question spoken prompt")
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "spoken_prompt", spoken)
        choices = tuple(self.choices)
        if len(choices) < 2 or any(not isinstance(choice, Choice) for choice in choices):
            raise LearningDataError("question requires at least two typed choices")
        choice_ids = tuple(choice.id for choice in choices)
        if len(set(choice_ids)) != len(choice_ids):
            raise LearningDataError("question choice ids must be unique")
        object.__setattr__(self, "choices", choices)
        answers = _answer_tuple(self.correct_answers, "correct answers")
        answer_choice_ids = tuple(answer.split("=", 1)[0] for answer in answers)
        if any(answer_id not in choice_ids for answer_id in answer_choice_ids):
            raise LearningDataError("every correct answer must refer to a choice")
        if len(set(answers)) != len(answers):
            raise LearningDataError("correct answers cannot contain duplicates")
        object.__setattr__(self, "correct_answers", answers)
        if not isinstance(self.hidden_prompt, bool) or not isinstance(self.requires_submit, bool):
            raise LearningDataError("question visibility flags must be booleans")
        object.__setattr__(self, "example", _clean_optional_text(self.example, "example"))
        object.__setattr__(
            self, "explanation", _clean_optional_text(self.explanation, "explanation")
        )
        object.__setattr__(self, "hint", _clean_optional_text(self.hint, "hint"))
        if (
            isinstance(self.generation_version, bool)
            or not isinstance(self.generation_version, int)
            or self.generation_version < 1
        ):
            raise LearningDataError("generation_version must be a positive integer")
        object.__setattr__(self, "metadata", _pairs(self.metadata, "question metadata"))

    def meta(self, name: str, default: Any = None) -> Any:
        return metadata_get(self.metadata, name, default)

    def choice(self, choice_id: str) -> Choice | None:
        return next((choice for choice in self.choices if choice.id == choice_id), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "lesson_id": self.lesson_id,
            "domain": self.domain,
            "skills": list(self.skills),
            "interaction": self.interaction.value,
            "prompt": self.prompt,
            "spoken_prompt": self.spoken_prompt,
            "choices": [choice.to_json() for choice in self.choices],
            "correct_answers": list(self.correct_answers),
            "hidden_prompt": self.hidden_prompt,
            "requires_submit": self.requires_submit,
            "example": self.example,
            "explanation": self.explanation,
            "hint": self.hint,
            "generation_version": self.generation_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_json(cls, value: object) -> Question:
        if not isinstance(value, Mapping):
            raise LearningDataError("question must be an object")
        return cls(
            question_id=value.get("id", ""),
            lesson_id=value.get("lesson_id", ""),
            domain=value.get("domain", ""),
            skills=tuple(value.get("skills", ())),
            interaction=InteractionKind(value.get("interaction", "")),
            prompt=value.get("prompt", ""),
            spoken_prompt=value.get("spoken_prompt", ""),
            choices=tuple(Choice.from_json(item) for item in value.get("choices", ())),
            correct_answers=tuple(value.get("correct_answers", ())),
            hidden_prompt=value.get("hidden_prompt", False),
            requires_submit=value.get("requires_submit", False),
            example=value.get("example", ""),
            explanation=value.get("explanation", ""),
            hint=value.get("hint", ""),
            generation_version=value.get("generation_version", GENERATION_VERSION),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True)
class Evaluation:
    """Explainable result of checking one response."""

    correct: bool
    normalized_response: tuple[str, ...]
    attempt_number: int
    feedback: str
    try_again: bool
    reveal_answer: bool
    revealed_answers: tuple[str, ...] = ()
    scaffold_used: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.correct, bool):
            raise LearningDataError("evaluation correct must be a boolean")
        object.__setattr__(
            self,
            "normalized_response",
            _answer_tuple(
                self.normalized_response,
                "normalized response",
                allow_empty=True,
            ),
        )
        if not isinstance(self.attempt_number, int) or self.attempt_number < 1:
            raise LearningDataError("attempt_number must be positive")
        object.__setattr__(self, "feedback", _clean_text(self.feedback, "feedback"))
        for name in ("try_again", "reveal_answer", "scaffold_used"):
            if not isinstance(getattr(self, name), bool):
                raise LearningDataError(f"evaluation {name} must be a boolean")
        object.__setattr__(
            self,
            "revealed_answers",
            _answer_tuple(
                self.revealed_answers,
                "revealed answers",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True)
class AttemptRecord:
    """One graded response. Replays are intentionally not attempt records."""

    attempt_id: str
    session_id: str
    profile_id: str
    plan_id: str | None
    lesson_id: str
    skills: tuple[str, ...]
    question_id: str
    correct_answers: tuple[str, ...]
    response: tuple[str, ...]
    correct: bool
    attempt_number: int
    scaffolded: bool
    hint_used: bool
    revealed: bool
    elapsed_seconds: float
    timestamp: str
    generation_version: int = GENERATION_VERSION

    def __post_init__(self) -> None:
        for name in ("attempt_id", "session_id", "profile_id", "lesson_id", "question_id"):
            object.__setattr__(self, name, _clean_id(getattr(self, name), name))
        if self.plan_id is not None:
            object.__setattr__(self, "plan_id", _clean_id(self.plan_id, "plan_id"))
        object.__setattr__(self, "skills", _string_tuple(self.skills, "attempt skills", ids=True))
        object.__setattr__(
            self,
            "correct_answers",
            _answer_tuple(self.correct_answers, "attempt correct answers"),
        )
        object.__setattr__(
            self,
            "response",
            _answer_tuple(self.response, "attempt response", allow_empty=True),
        )
        for name in ("correct", "scaffolded", "hint_used", "revealed"):
            if not isinstance(getattr(self, name), bool):
                raise LearningDataError(f"attempt {name} must be a boolean")
        if not isinstance(self.attempt_number, int) or self.attempt_number < 1:
            raise LearningDataError("attempt number must be positive")
        if isinstance(self.elapsed_seconds, bool) or not isinstance(
            self.elapsed_seconds, (int, float)
        ):
            raise LearningDataError("elapsed seconds must be numeric")
        if not 0 <= float(self.elapsed_seconds) <= 86_400:
            raise LearningDataError("elapsed seconds is outside its safe range")
        object.__setattr__(self, "elapsed_seconds", float(self.elapsed_seconds))
        object.__setattr__(self, "timestamp", _validate_timestamp(self.timestamp, "timestamp"))
        if not isinstance(self.generation_version, int) or self.generation_version < 1:
            raise LearningDataError("generation version must be positive")

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.attempt_id,
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "plan_id": self.plan_id,
            "lesson_id": self.lesson_id,
            "skills": list(self.skills),
            "question_id": self.question_id,
            "correct_answers": list(self.correct_answers),
            "response": list(self.response),
            "correct": self.correct,
            "attempt_number": self.attempt_number,
            "scaffolded": self.scaffolded,
            "hint_used": self.hint_used,
            "revealed": self.revealed,
            "elapsed_seconds": self.elapsed_seconds,
            "timestamp": self.timestamp,
            "generation_version": self.generation_version,
        }

    @property
    def skill_ids(self) -> tuple[str, ...]:
        """Compatibility alias used by persistence/reporting code."""

        return self.skills

    @property
    def correct_targets(self) -> tuple[str, ...]:
        return self.correct_answers

    @property
    def created_at(self) -> str:
        return self.timestamp

    @classmethod
    def from_json(cls, value: object) -> AttemptRecord:
        if not isinstance(value, Mapping):
            raise LearningDataError("attempt must be an object")
        return cls(
            attempt_id=value.get("id", ""),
            session_id=value.get("session_id", ""),
            profile_id=value.get("profile_id", ""),
            plan_id=value.get("plan_id"),
            lesson_id=value.get("lesson_id", ""),
            skills=tuple(value.get("skills", ())),
            question_id=value.get("question_id", ""),
            correct_answers=tuple(value.get("correct_answers", ())),
            response=tuple(value.get("response", ())),
            correct=value.get("correct", False),
            attempt_number=value.get("attempt_number", 0),
            scaffolded=value.get("scaffolded", False),
            hint_used=value.get("hint_used", False),
            revealed=value.get("revealed", False),
            elapsed_seconds=value.get("elapsed_seconds", 0.0),
            timestamp=value.get("timestamp", ""),
            generation_version=value.get("generation_version", GENERATION_VERSION),
        )


@dataclass(frozen=True)
class LearnerProfile:
    """Minimal local learner identity; no sensitive demographic fields."""

    profile_id: str
    display_name: str
    archived: bool = False
    created_at: str = "1970-01-01T00:00:00+00:00"
    updated_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _clean_id(self.profile_id, "profile id"))
        object.__setattr__(
            self, "display_name", _clean_text(self.display_name, "display name", maximum=40)
        )
        if not isinstance(self.archived, bool):
            raise LearningDataError("profile archived must be a boolean")
        for name in ("created_at", "updated_at"):
            object.__setattr__(self, name, _validate_timestamp(getattr(self, name), name))

    @property
    def id(self) -> str:
        return self.profile_id

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "display_name": self.display_name,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, value: object) -> LearnerProfile:
        if not isinstance(value, Mapping):
            raise LearningDataError("learner profile must be an object")
        return cls(
            profile_id=value.get("id", ""),
            display_name=value.get("display_name", ""),
            archived=value.get("archived", False),
            created_at=value.get("created_at", ""),
            updated_at=value.get("updated_at", ""),
        )


@dataclass(frozen=True)
class LearningPlan:
    """Teacher-authored ordered plan with an optional per-step mastery gate."""

    plan_id: str
    profile_id: str
    title: str
    lesson_ids: tuple[str, ...]
    enabled: bool = True
    archived: bool = False
    repetitions: int = 1
    questions_per_session: int = 8
    mastery_gate: bool = False
    created_at: str = "1970-01-01T00:00:00+00:00"
    updated_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _clean_id(self.plan_id, "plan id"))
        object.__setattr__(self, "profile_id", _clean_id(self.profile_id, "profile id"))
        object.__setattr__(self, "title", _clean_text(self.title, "plan title", maximum=80))
        lessons = _string_tuple(self.lesson_ids, "plan lesson ids", ids=True)
        object.__setattr__(self, "lesson_ids", lessons)
        for name in ("enabled", "archived", "mastery_gate"):
            if not isinstance(getattr(self, name), bool):
                raise LearningDataError(f"plan {name} must be a boolean")
        if not isinstance(self.repetitions, int) or not 1 <= self.repetitions <= 10:
            raise LearningDataError("plan repetitions must be between 1 and 10")
        if not isinstance(self.questions_per_session, int) or not 1 <= self.questions_per_session <= 20:
            raise LearningDataError("questions_per_session must be between 1 and 20")
        for name in ("created_at", "updated_at"):
            object.__setattr__(self, name, _validate_timestamp(getattr(self, name), name))

    @property
    def id(self) -> str:
        return self.plan_id

    @property
    def name(self) -> str:
        """Compatibility alias for teacher-facing store and UI terminology."""

        return self.title

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.plan_id,
            "profile_id": self.profile_id,
            "name": self.title,
            "lesson_ids": list(self.lesson_ids),
            "enabled": self.enabled,
            "archived": self.archived,
            "repetitions": self.repetitions,
            "questions_per_session": self.questions_per_session,
            "mastery_gate": self.mastery_gate,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, value: object) -> LearningPlan:
        if not isinstance(value, Mapping):
            raise LearningDataError("learning plan must be an object")
        return cls(
            plan_id=value.get("id", ""),
            profile_id=value.get("profile_id", ""),
            title=value.get("name", value.get("title", "")),
            lesson_ids=tuple(value.get("lesson_ids", ())),
            enabled=value.get("enabled", True),
            archived=value.get("archived", False),
            repetitions=value.get("repetitions", 1),
            questions_per_session=value.get("questions_per_session", 8),
            mastery_gate=value.get("mastery_gate", False),
            created_at=value.get("created_at", ""),
            updated_at=value.get("updated_at", ""),
        )


@dataclass(frozen=True)
class LearningSession:
    """Serializable immutable session state supporting resume after closure."""

    session_id: str
    profile_id: str
    plan_id: str | None
    questions: tuple[Question, ...]
    question_index: int
    current_attempt: int
    scaffolded: bool
    attempts: tuple[AttemptRecord, ...]
    started_at: str
    updated_at: str
    replay_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _clean_id(self.session_id, "session id"))
        object.__setattr__(self, "profile_id", _clean_id(self.profile_id, "profile id"))
        if self.plan_id is not None:
            object.__setattr__(self, "plan_id", _clean_id(self.plan_id, "plan id"))
        questions = tuple(self.questions)
        if not questions or any(not isinstance(item, Question) for item in questions):
            raise LearningDataError("session must contain generated questions")
        if len({item.question_id for item in questions}) != len(questions):
            raise LearningDataError("session question ids must be unique")
        object.__setattr__(self, "questions", questions)
        if not isinstance(self.question_index, int) or not 0 <= self.question_index <= len(questions):
            raise LearningDataError("session question index is outside its range")
        if not isinstance(self.current_attempt, int) or self.current_attempt < 0:
            raise LearningDataError("current attempt cannot be negative")
        if not isinstance(self.scaffolded, bool):
            raise LearningDataError("session scaffolded must be a boolean")
        attempts = tuple(self.attempts)
        if any(not isinstance(item, AttemptRecord) for item in attempts):
            raise LearningDataError("session attempts must be typed attempt records")
        object.__setattr__(self, "attempts", attempts)
        for name in ("started_at", "updated_at"):
            object.__setattr__(self, name, _validate_timestamp(getattr(self, name), name))
        if not isinstance(self.replay_count, int) or self.replay_count < 0:
            raise LearningDataError("replay count cannot be negative")

    @property
    def complete(self) -> bool:
        return self.question_index >= len(self.questions)

    @property
    def current_question(self) -> Question | None:
        if self.complete:
            return None
        return self.questions[self.question_index]

    @property
    def lesson_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(question.lesson_id for question in self.questions))

    @property
    def status(self) -> str:
        return "completed" if self.complete else "active"

    @property
    def completed_count(self) -> int:
        return self.question_index

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "profile_id": self.profile_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "questions": [question.to_json() for question in self.questions],
            "question_index": self.question_index,
            "current_attempt": self.current_attempt,
            "scaffolded": self.scaffolded,
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "replay_count": self.replay_count,
        }

    @classmethod
    def from_json(cls, value: object) -> LearningSession:
        if not isinstance(value, Mapping):
            raise LearningDataError("learning session must be an object")
        return cls(
            session_id=value.get("id", ""),
            profile_id=value.get("profile_id", ""),
            plan_id=value.get("plan_id"),
            questions=tuple(Question.from_json(item) for item in value.get("questions", ())),
            question_index=value.get("question_index", 0),
            current_attempt=value.get("current_attempt", 0),
            scaffolded=value.get("scaffolded", False),
            attempts=tuple(AttemptRecord.from_json(item) for item in value.get("attempts", ())),
            started_at=value.get("started_at", ""),
            updated_at=value.get("updated_at", ""),
            replay_count=value.get("replay_count", 0),
        )


@dataclass(frozen=True)
class SessionTransition:
    """One atomic engine transition ready for persistence and presentation."""

    session: LearningSession
    evaluation: Evaluation
    attempt: AttemptRecord
    next_question: Question | None

    @property
    def complete(self) -> bool:
        return self.session.complete


@dataclass(frozen=True)
class SkillMastery:
    """Explainable recent-evidence summary for one skill or lesson."""

    skill: str
    status: MasteryStatus
    evidence_count: int
    attempt_count: int
    first_try_accuracy: float
    eventual_accuracy: float
    percentage_grade: float
    recent_trend: float
    practiced_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill", _clean_id(self.skill, "mastery skill"))
        if not isinstance(self.status, MasteryStatus):
            object.__setattr__(self, "status", MasteryStatus(self.status))
        for name in ("evidence_count", "attempt_count"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise LearningDataError(f"{name} cannot be negative")
        for name in ("first_try_accuracy", "eventual_accuracy", "recent_trend"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise LearningDataError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)
        grade = float(self.percentage_grade)
        if not 0.0 <= grade <= 100.0:
            raise LearningDataError("percentage grade must be between 0 and 100")
        object.__setattr__(self, "percentage_grade", grade)
        seconds = float(self.practiced_seconds)
        if seconds < 0:
            raise LearningDataError("practiced seconds cannot be negative")
        object.__setattr__(self, "practiced_seconds", seconds)


@dataclass(frozen=True)
class PlanReport:
    """Teacher-facing grade and completion; the two are intentionally separate."""

    plan_id: str
    status: MasteryStatus
    total_lessons: int
    started_lessons: int
    mastered_lessons: int
    completion_percent: float
    percentage_grade: float
    accuracy: float
    first_try_accuracy: float
    eventual_accuracy: float
    attempt_count: int
    evidence_count: int
    recent_trend: float
    practiced_seconds: float
    skills: tuple[SkillMastery, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _clean_id(self.plan_id, "report plan id"))
        if not isinstance(self.status, MasteryStatus):
            object.__setattr__(self, "status", MasteryStatus(self.status))
        for name in (
            "total_lessons",
            "started_lessons",
            "mastered_lessons",
            "attempt_count",
            "evidence_count",
        ):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise LearningDataError(f"{name} cannot be negative")
        for name in (
            "completion_percent",
            "percentage_grade",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 100.0:
                raise LearningDataError(f"{name} must be between 0 and 100")
            object.__setattr__(self, name, value)
        for name in ("accuracy", "first_try_accuracy", "eventual_accuracy", "recent_trend"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise LearningDataError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "practiced_seconds", float(self.practiced_seconds))
        skills = tuple(self.skills)
        if any(not isinstance(item, SkillMastery) for item in skills):
            raise LearningDataError("plan report skills must be mastery records")
        object.__setattr__(self, "skills", skills)


__all__ = [
    "GENERATION_VERSION",
    "AttemptRecord",
    "Choice",
    "ContentItem",
    "Evaluation",
    "InteractionKind",
    "LearnerProfile",
    "LearningDataError",
    "LearningPlan",
    "LearningSession",
    "LessonDefinition",
    "MasteryStatus",
    "PlanReport",
    "Question",
    "SessionTransition",
    "SkillMastery",
    "metadata_get",
]
