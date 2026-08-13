"""Touch-first, data-driven UI for the menu-only Pre-K Learning feature.

The feature package owns curriculum, scoring, configuration, and persistence.
This module deliberately accepts those services through structural (duck-typed)
boundaries so adding a lesson never adds a lesson-ID branch to Tk code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass, replace
from enum import Enum
import inspect
import time
import tkinter as tk
from typing import Any

from PIL import Image, ImageTk


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480
FACE_REFRESH_MS = 150
MAX_QUESTION_ATTEMPTS = 2

Point = tuple[int, int]


@dataclass(frozen=True)
class Rect:
    """Inclusive rectangular touch target independent from Tk."""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("A touch rectangle must have positive area.")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> Point:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    def contains(self, point: Point) -> bool:
        return (
            self.left <= point[0] <= self.right
            and self.top <= point[1] <= self.bottom
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def inside(self, width: int = WINDOW_WIDTH, height: int = WINDOW_HEIGHT) -> bool:
        return (
            0 <= self.left < self.right <= width
            and 0 <= self.top < self.bottom <= height
        )


@dataclass(frozen=True)
class HitRegion:
    """One named, optionally disabled action in the current canvas frame."""

    key: str
    bounds: Rect
    enabled: bool = True


def hit_test(regions: Iterable[HitRegion], point: Point) -> str | None:
    """Return the topmost enabled region at ``point``."""
    for region in reversed(tuple(regions)):
        if region.enabled and region.bounds.contains(point):
            return region.key
    return None


class TouchTracker:
    """Separate deliberate taps from drags and rapid duplicate releases."""

    def __init__(self, tap_slop: int = 18) -> None:
        if tap_slop < 0:
            raise ValueError("tap_slop cannot be negative")
        self.tap_slop = tap_slop
        self.press_point: Point | None = None

    def press(self, point: Point) -> None:
        self.press_point = point

    def release(self, point: Point) -> Point | None:
        pressed = self.press_point
        self.press_point = None
        if pressed is None:
            return None
        if (
            abs(point[0] - pressed[0]) > self.tap_slop
            or abs(point[1] - pressed[1]) > self.tap_slop
        ):
            return None
        return point

    def cancel(self) -> None:
        self.press_point = None


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _metadata_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        return {str(key): item for key, item in value}
    except (TypeError, ValueError):
        return {}


def _identifier(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    result = str(value).strip()
    return result or fallback


def _interaction_name(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    name = str(value or "single_choice").strip().lower().replace("-", "_")
    aliases = {
        "single": "single_choice",
        "choice": "single_choice",
        "multiple_choice": "multi_select",
        "multiple_select": "multi_select",
        "alphabet": "alphabet_grid",
        "picture": "picture_choice",
        "matching": "matching_pairs",
        "order": "ordered_sequence",
        "sequence": "ordered_sequence",
        "sort": "category_sorting",
        "sorting": "category_sorting",
        "category_sort": "category_sorting",
        "listen": "listen_only",
        "listen_hidden": "listen_hidden",
        "scene": "scene_prediction",
        "scene_choice": "scene_prediction",
    }
    return aliases.get(name, name)


@dataclass(frozen=True)
class ChoiceSnapshot:
    """Small rendering boundary accepted from mappings or frozen models."""

    choice_id: str
    label: str
    spoken: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuestionSnapshot:
    """UI-ready question without importing the curriculum implementation."""

    question_id: str
    lesson_id: str
    interaction: str
    prompt: str
    spoken_prompt: str
    choices: tuple[ChoiceSnapshot, ...]
    correct_answers: frozenset[str]
    hidden_prompt: bool
    requires_submit: bool
    example: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def choice_snapshot(value: Any, index: int = 0) -> ChoiceSnapshot:
    """Normalize a typed choice, mapping, or plain display string."""
    if isinstance(value, str):
        label = value.strip()
        return ChoiceSnapshot(label or f"choice-{index}", label, label)
    label = _identifier(_field(value, "label", "text", "name"))
    choice_id = _identifier(
        _field(value, "id", "choice_id", "value", "key"),
        fallback=label or f"choice-{index}",
    )
    spoken = _identifier(_field(value, "spoken", "speech"), fallback=label)
    metadata = _metadata_mapping(_field(value, "metadata", default={}))
    return ChoiceSnapshot(choice_id, label or choice_id, spoken, metadata)


def question_snapshot(value: Any) -> QuestionSnapshot:
    """Normalize the curriculum's typed question into a stable UI model."""
    raw_choices = _field(value, "choices", "options", default=()) or ()
    choices = tuple(choice_snapshot(choice, index) for index, choice in enumerate(raw_choices))
    metadata = _metadata_mapping(_field(value, "metadata", default={}))
    prompt = _identifier(_field(value, "prompt", "instruction"))
    spoken = _identifier(
        _field(value, "spoken_prompt", "spoken", "narration"),
        fallback=prompt,
    )
    correct = _field(
        value,
        "correct_answers",
        "correct_answer_ids",
        "answers",
        default=(),
    )
    if isinstance(correct, (str, int)):
        correct = (correct,)
    correct_answers = frozenset(str(answer) for answer in (correct or ()))
    interaction = _interaction_name(_field(value, "interaction", "kind", "type"))
    if interaction == "listen_hidden":
        interaction = "single_choice" if choices else "listen_only"
    hidden = bool(_field(value, "hidden_prompt", "hide_prompt", default=False))
    explicit_submit = _field(value, "requires_submit", default=None)
    requires_submit = (
        interaction
        in {
            "multi_select",
            "matching_pairs",
            "ordered_sequence",
            "category_sorting",
        }
        if explicit_submit is None
        else bool(explicit_submit)
    )
    lesson_id = _identifier(
        _field(value, "lesson_id", default=metadata.get("lesson_id", ""))
    )
    question_id = _identifier(
        _field(value, "question_id", "id", default=metadata.get("question_id", "")),
        fallback=f"{lesson_id}:{prompt}",
    )
    example_value = _field(value, "example", default=None)
    example = None if example_value is None else str(example_value)
    metadata = dict(metadata)
    explanation = _identifier(_field(value, "explanation"))
    hint = _identifier(_field(value, "hint"))
    if explanation:
        metadata.setdefault("explanation", explanation)
    if hint:
        metadata.setdefault("hint", hint)
    return QuestionSnapshot(
        question_id=question_id,
        lesson_id=lesson_id,
        interaction=interaction,
        prompt=prompt,
        spoken_prompt=spoken,
        choices=choices,
        correct_answers=correct_answers,
        hidden_prompt=hidden,
        requires_submit=requires_submit,
        example=example,
        metadata=metadata,
    )


@dataclass(frozen=True)
class SelectionResult:
    """Effect of one choice tap, useful to both Tk and headless tests."""

    accepted: bool
    submit_ready: bool
    submit_immediately: bool
    response: Any = None


class InteractionController:
    """Generic selection state for every curriculum interaction type."""

    SUBMIT_KINDS = frozenset(
        {"multi_select", "matching_pairs", "ordered_sequence", "category_sorting"}
    )

    def __init__(self, question: QuestionSnapshot) -> None:
        self.question = question
        self.choice_ids = tuple(choice.choice_id for choice in question.choices)
        self.selected: list[str] = []
        self.assignments: dict[str, str] = {}
        categories = question.metadata.get("categories", ())
        self.categories = tuple(
            _identifier(_field(category, "id", "value", "label"), fallback=str(category))
            for category in categories
        )
        self.locked = False

    @property
    def needs_submit(self) -> bool:
        return self.question.requires_submit or self.question.interaction in self.SUBMIT_KINDS

    @property
    def submit_ready(self) -> bool:
        kind = self.question.interaction
        if kind == "category_sorting":
            return bool(self.choice_ids) and all(
                choice_id in self.assignments for choice_id in self.choice_ids
            )
        if kind == "ordered_sequence":
            return bool(self.choice_ids) and len(self.selected) == len(self.choice_ids)
        if kind == "listen_only":
            return True
        return bool(self.selected)

    def choose(self, choice_id: str) -> SelectionResult:
        choice_id = str(choice_id)
        if self.locked or choice_id not in self.choice_ids:
            return SelectionResult(False, self.submit_ready, False)
        kind = self.question.interaction
        if kind == "category_sorting":
            if not self.categories:
                return SelectionResult(False, False, False)
            previous = self.assignments.get(choice_id)
            index = -1 if previous not in self.categories else self.categories.index(previous)
            self.assignments[choice_id] = self.categories[(index + 1) % len(self.categories)]
        elif kind == "ordered_sequence":
            if choice_id in self.selected:
                removed_at = self.selected.index(choice_id)
                del self.selected[removed_at:]
            else:
                self.selected.append(choice_id)
        elif kind in {"multi_select", "matching_pairs"}:
            if choice_id in self.selected:
                self.selected.remove(choice_id)
            else:
                self.selected.append(choice_id)
        else:
            self.selected[:] = [choice_id]
        response = self.response()
        return SelectionResult(
            True,
            self.submit_ready,
            self.submit_ready and not self.needs_submit,
            response,
        )

    def response(self) -> Any:
        kind = self.question.interaction
        if kind == "category_sorting":
            return dict(self.assignments)
        if kind in {"multi_select", "matching_pairs", "ordered_sequence"}:
            return tuple(self.selected)
        if kind == "listen_only":
            return ()
        return self.selected[0] if self.selected else None

    def reset_for_retry(self) -> None:
        self.selected.clear()
        self.assignments.clear()
        self.locked = False


@dataclass
class PinEntry:
    """Four-digit teacher PIN buffer whose display never reveals digits."""

    length: int = 4
    _entered: str = field(default="", repr=False)

    def push(self, digit: str) -> bool:
        if len(digit) != 1 or digit not in "0123456789":
            return False
        if len(self._entered) >= self.length:
            return False
        self._entered += digit
        return True

    def backspace(self) -> None:
        self._entered = self._entered[:-1]

    def clear(self) -> None:
        self._entered = ""

    @property
    def complete(self) -> bool:
        return len(self._entered) == self.length

    @property
    def masked(self) -> str:
        return "  ".join("FILLED" if index < len(self._entered) else "EMPTY" for index in range(self.length))

    def consume(self) -> str:
        value = self._entered
        self.clear()
        return value


@dataclass
class TextEntry:
    """Small on-screen teacher text-entry buffer."""

    maximum: int = 24
    value: str = ""

    def push(self, character: str) -> bool:
        if len(self.value) >= self.maximum:
            return False
        if character == " ":
            if not self.value or self.value.endswith(" "):
                return False
        elif len(character) != 1 or not character.isalpha():
            return False
        self.value += character
        return True

    def backspace(self) -> None:
        self.value = self.value[:-1]

    @property
    def cleaned(self) -> str:
        return " ".join(self.value.split()).strip()


@dataclass
class PageCursor:
    """Bounded pagination shared by learner and teacher card lists."""

    page_size: int
    item_count: int = 0
    page_index: int = 0

    def __post_init__(self) -> None:
        if self.page_size < 1:
            raise ValueError("page_size must be positive")

    @property
    def page_count(self) -> int:
        return max(1, (self.item_count + self.page_size - 1) // self.page_size)

    def set_count(self, item_count: int) -> None:
        self.item_count = max(0, int(item_count))
        self.page_index = min(self.page_index, self.page_count - 1)

    def current(self, values: Sequence[Any]) -> tuple[Any, ...]:
        self.set_count(len(values))
        start = self.page_index * self.page_size
        return tuple(values[start : start + self.page_size])

    def next(self) -> bool:
        if self.page_index >= self.page_count - 1:
            return False
        self.page_index += 1
        return True

    def previous(self) -> bool:
        if self.page_index <= 0:
            return False
        self.page_index -= 1
        return True


def reorder_item(values: Sequence[str], index: int, offset: int) -> tuple[str, ...]:
    """Move one item by one or more positions while clamping at the ends."""
    result = list(values)
    if not result or index < 0 or index >= len(result):
        return tuple(result)
    destination = max(0, min(len(result) - 1, index + offset))
    item = result.pop(index)
    result.insert(destination, item)
    return tuple(result)


def _rgb(color: object) -> tuple[int, int, int] | None:
    if not isinstance(color, str):
        return None
    value = color.strip()
    if len(value) == 4 and value.startswith("#"):
        value = "#" + "".join(character * 2 for character in value[1:])
    if len(value) != 7 or not value.startswith("#"):
        return None
    try:
        return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
    except ValueError:
        return None


def contrast_ratio(foreground: object, background: object) -> float:
    """Return WCAG relative contrast, or zero for an invalid color."""

    def luminance(color: object) -> float | None:
        rgb = _rgb(color)
        if rgb is None:
            return None
        channels = []
        for value in rgb:
            normalized = value / 255.0
            channels.append(
                normalized / 12.92
                if normalized <= 0.04045
                else ((normalized + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    first = luminance(foreground)
    second = luminance(background)
    if first is None or second is None:
        return 0.0
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def safe_choice_text_color(
    candidate: object,
    *,
    normal_background: str = "#FFFFFF",
    selected_background: str = "#F4CA55",
    fallback: str = "#17324D",
    minimum_ratio: float = 4.5,
) -> str:
    """Honor authored color only when readable in both choice states."""
    if _rgb(candidate) is None:
        return fallback
    normalized = str(candidate).strip().upper()
    if (
        contrast_ratio(normalized, normal_background) < minimum_ratio
        or contrast_ratio(normalized, selected_background) < minimum_ratio
    ):
        return fallback
    return normalized


def missing_prerequisites(
    lesson_id: str,
    selected_lesson_ids: Iterable[str],
    lessons: Iterable[Any],
) -> tuple[str, ...]:
    """Return unselected direct prerequisites for a teacher selection."""
    selected = set(selected_lesson_ids)
    for lesson in lessons:
        current_id = _identifier(_field(lesson, "lesson_id", "id"))
        if current_id != lesson_id:
            continue
        prerequisites = _field(lesson, "prerequisites", default=()) or ()
        return tuple(str(item) for item in prerequisites if str(item) not in selected)
    return ()


def bulk_missing_prerequisites(
    lessons: Iterable["LessonSnapshot"],
    selected_lesson_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return prerequisites absent from both the plan and proposed bulk set."""
    proposed = tuple(lessons)
    available = set(selected_lesson_ids)
    available.update(lesson.lesson_id for lesson in proposed)
    missing: list[str] = []
    for lesson in proposed:
        for prerequisite in lesson.prerequisites:
            if prerequisite not in available and prerequisite not in missing:
                missing.append(prerequisite)
    return tuple(missing)


@dataclass(frozen=True)
class ProfileSnapshot:
    profile_id: str
    display_name: str
    archived: bool
    raw: Any = field(compare=False, repr=False)


@dataclass(frozen=True)
class PlanSnapshot:
    plan_id: str
    profile_id: str
    name: str
    lesson_ids: tuple[str, ...]
    enabled: bool
    question_count: int
    repetitions: int
    mastery_gate: bool
    archived: bool
    raw: Any = field(compare=False, repr=False)


@dataclass(frozen=True)
class LessonSnapshot:
    lesson_id: str
    domain: str
    title: str
    prerequisites: tuple[str, ...]
    raw: Any = field(compare=False, repr=False)


def profile_snapshot(value: Any) -> ProfileSnapshot:
    profile_id = _identifier(_field(value, "profile_id", "id"))
    name = _identifier(_field(value, "display_name", "name"), fallback="Learner")
    return ProfileSnapshot(profile_id, name, bool(_field(value, "archived", default=False)), value)


def plan_snapshot(value: Any, *, default_questions: int = 8) -> PlanSnapshot:
    return PlanSnapshot(
        plan_id=_identifier(_field(value, "plan_id", "id")),
        profile_id=_identifier(_field(value, "profile_id")),
        name=_identifier(_field(value, "name", "title"), fallback="Learning Plan"),
        lesson_ids=tuple(str(item) for item in (_field(value, "lesson_ids", "lessons", default=()) or ())),
        enabled=bool(_field(value, "enabled", default=True)),
        question_count=int(
            _field(
                value,
                "question_count",
                "questions_per_session",
                "session_size",
                default=default_questions,
            )
        ),
        repetitions=max(1, min(10, int(_field(value, "repetitions", default=1)))),
        mastery_gate=bool(_field(value, "mastery_gate", "require_mastery", default=False)),
        archived=bool(_field(value, "archived", default=False)),
        raw=value,
    )


def lesson_snapshot(value: Any) -> LessonSnapshot:
    lesson_id = _identifier(_field(value, "lesson_id", "id"))
    return LessonSnapshot(
        lesson_id=lesson_id,
        domain=_identifier(_field(value, "domain"), fallback="Foundations"),
        title=_identifier(_field(value, "title", "name"), fallback=lesson_id),
        prerequisites=tuple(str(item) for item in (_field(value, "prerequisites", default=()) or ())),
        raw=value,
    )


def lesson_family(lesson: LessonSnapshot) -> str:
    """Derive a stable curriculum family without hard-coded lesson names."""
    parts = tuple(part for part in lesson.lesson_id.split(".") if part)
    if len(parts) >= 2 and parts[0] == lesson.domain:
        return parts[1]
    return parts[1] if len(parts) >= 2 else "other"


def lesson_filter_domains(lessons: Iterable[LessonSnapshot]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(lesson.domain for lesson in lessons))


def lesson_filter_families(
    lessons: Iterable[LessonSnapshot],
    domain: str,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            lesson_family(lesson)
            for lesson in lessons
            if domain == "all" or lesson.domain == domain
        )
    )


def filter_lessons(
    lessons: Iterable[LessonSnapshot],
    *,
    domain: str = "all",
    family: str = "all",
) -> tuple[LessonSnapshot, ...]:
    return tuple(
        lesson
        for lesson in lessons
        if (domain == "all" or lesson.domain == domain)
        and (family == "all" or lesson_family(lesson) == family)
    )


def format_percent(value: Any, *, fractional: bool = False) -> str:
    """Format either percentage points or a zero-to-one fraction."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if fractional:
        number *= 100
    return f"{max(0.0, min(100.0, number)):.0f}%"


def teacher_report_metrics(stats: Any) -> tuple[tuple[str, str], ...]:
    """Normalize mapping or typed reports into the seven kiosk metrics."""
    practiced = _field(
        stats,
        "practiced_seconds",
        "practice_seconds",
        "time_practiced",
        default=0,
    )
    try:
        practiced_minutes = round(float(practiced or 0) / 60)
    except (TypeError, ValueError):
        practiced_minutes = 0
    return (
        (
            "PLAN COMPLETE",
            format_percent(
                _field(
                    stats,
                    "completion_percent",
                    "completion",
                    "completion_rate",
                    default=0,
                )
            ),
        ),
        ("GRADE", format_percent(_field(stats, "grade", "percentage_grade", default=0))),
        (
            "ACCURACY",
            format_percent(_field(stats, "accuracy", default=0), fractional=True),
        ),
        (
            "FIRST TRY",
            format_percent(
                _field(stats, "first_try_accuracy", default=0),
                fractional=True,
            ),
        ),
        (
            "RECENT TREND",
            format_percent(
                _field(stats, "recent_trend", "trend", default=0),
                fractional=True,
            ),
        ),
        ("ATTEMPTS", str(_field(stats, "attempts", "attempt_count", default=0))),
        ("PRACTICE MIN", str(max(0, practiced_minutes))),
    )


@dataclass(frozen=True)
class EvaluationSnapshot:
    correct: bool
    feedback: str
    explanation: str
    reveal: str | None
    try_again: bool
    complete: bool
    raw: Any = field(compare=False, repr=False)


def evaluation_snapshot(value: Any, question: QuestionSnapshot, attempt: int) -> EvaluationSnapshot:
    correct = bool(_field(value, "correct", "is_correct", default=False))
    explanation = _identifier(_field(value, "explanation", "reason", "hint"))
    reveal_value = _field(
        value,
        "revealed_answers",
        "reveal",
        "correct_answer",
        "answer",
        default=None,
    )
    if isinstance(reveal_value, (tuple, list, set, frozenset)):
        reveal = ", ".join(str(item) for item in reveal_value)
    elif reveal_value is None:
        reveal = None
    else:
        reveal = str(reveal_value)
    if not reveal and question.correct_answers:
        labels = {
            choice.choice_id: choice.label for choice in question.choices
        }
        reveal = ", ".join(
            labels.get(answer, answer) for answer in sorted(question.correct_answers)
        )
    feedback = _identifier(_field(value, "feedback", "message"))
    if not feedback:
        if correct:
            feedback = f"That's right. {reveal or 'You found it'} matches the question."
        elif attempt < MAX_QUESTION_ATTEMPTS:
            feedback = explanation or "Look at each choice carefully, then try once more."
        else:
            feedback = f"Let's learn it together. The answer is {reveal or 'shown here'}."
    return EvaluationSnapshot(
        correct=correct,
        feedback=feedback,
        explanation=explanation,
        reveal=reveal,
        try_again=bool(
            _field(
                value,
                "try_again",
                default=not correct and attempt < MAX_QUESTION_ATTEMPTS,
            )
        ),
        complete=bool(_field(value, "complete", "session_complete", default=False)),
        raw=value,
    )


class LearningScreen(str, Enum):
    HOME = "home"
    PLANS = "plans"
    RESUME = "resume"
    LESSON = "lesson"
    FEEDBACK = "feedback"
    COMPLETE = "complete"
    TEACHER_PIN = "teacher_pin"
    TEACHER_HOME = "teacher_home"
    TEACHER_PROFILES = "teacher_profiles"
    TEACHER_PROFILE = "teacher_profile"
    TEACHER_PLANS = "teacher_plans"
    TEACHER_PLAN = "teacher_plan"
    TEACHER_PLAN_EDIT = "teacher_plan_edit"
    TEACHER_LESSONS = "teacher_lessons"
    TEACHER_STATS = "teacher_stats"
    TEXT_ENTRY = "text_entry"
    CONFIRM = "confirm"
    ERROR = "error"


@dataclass
class PendingConfirmation:
    title: str
    message: str
    confirm_label: str
    confirm: Callable[[], None]
    cancel: Callable[[], None]


class LearningApp:
    """Render Learning above its originating menu on an 800x480 canvas.

    ``config``, ``catalog``, ``engine``, and ``store`` are Learning-owned
    objects. The remaining callbacks are the narrow services supplied by
    :class:`FeatureMenuContext`; this class never creates speech machinery.
    """

    BACKGROUND = "#EAF8F4"
    PANEL = "#FFFFFF"
    INK = "#17324D"
    MUTED = "#5A7185"
    NAVY = "#12325B"
    TEAL = "#16847D"
    BLUE = "#356EBA"
    SKY = "#CFEFFF"
    YELLOW = "#F4CA55"
    CORAL = "#E66A62"
    GREEN = "#3B8E63"
    RED = "#B83D4A"
    DISABLED = "#AAB8C4"
    WHITE = "#FFFFFF"
    FACE_BOUNDS = Rect(680, 7, 792, 59)

    def __init__(
        self,
        root: tk.Misc,
        *,
        config: Any,
        catalog: Any,
        engine: Any,
        store: Any,
        face_provider: Callable[[], Image.Image | None],
        announce: Callable[[str, Callable[[], None] | None], bool],
        cancel_announcements: Callable[[], None],
        announcements_available: bool,
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.config = config
        self.catalog = catalog
        self.engine = engine
        self.store = store
        self.face_provider = face_provider
        self.announce = announce
        self.cancel_announcements = cancel_announcements
        self.on_close = on_close
        speech_enabled = bool(_field(config, "speech_enabled", default=True))
        self.speech_available = bool(announcements_available and speech_enabled)
        fonts = _field(config, "font_families", default=("Arial",)) or ("Arial",)
        self.font_families = tuple(str(item) for item in fonts if str(item).strip()) or ("Arial",)
        self.font_family = self.font_families[0]
        self.default_question_count = int(
            _field(config, "default_session_questions", default=8)
        )

        self.closed = False
        self.screen = LearningScreen.HOME
        self.previous_screen = LearningScreen.HOME
        self.touch = TouchTracker()
        self._regions: list[HitRegion] = []
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._action_serial = 0
        self._after_ids: set[str] = set()
        self._face_after_id: str | None = None
        self._face_image: ImageTk.PhotoImage | None = None
        self._face_item: int | None = None
        self._fallback_items: tuple[int, ...] = ()
        self._face_speaking = False
        self._speech_failed = False
        self._input_locked = False
        self._status = ""
        self._data_error = ""
        self._profiles: tuple[ProfileSnapshot, ...] = ()
        self._plans: tuple[PlanSnapshot, ...] = ()
        self._lessons: tuple[LessonSnapshot, ...] = self._catalog_lessons()
        self._profile_pages = PageCursor(4)
        self._plan_pages = PageCursor(3)
        self._teacher_pages = PageCursor(3)
        self._lesson_pages = PageCursor(4)
        self._mastery_pages = PageCursor(3)
        self._selected_profile: ProfileSnapshot | None = None
        self._selected_plan: PlanSnapshot | None = None
        self._session: Any = None
        self._question: QuestionSnapshot | None = None
        self._question_controller: InteractionController | None = None
        self._question_attempts: dict[str, int] = {}
        self._question_started_at = time.monotonic()
        self._session_index = 0
        self._session_total = self.default_question_count
        self._pending_evaluation: EvaluationSnapshot | None = None
        self._pending_question: Any = None
        self._feedback_ready = False
        self._feedback_retry = False
        self._progress_saved = True
        self._auto_spoken: set[str] = set()
        self._pin = PinEntry()
        self._pin_error = False
        self._text_entry = TextEntry()
        self._text_purpose = ""
        self._text_return = LearningScreen.TEACHER_HOME
        self._confirmation: PendingConfirmation | None = None
        self._plan_draft_name = ""
        self._plan_draft_lessons: list[str] = []
        self._plan_draft_question_count = self.default_question_count
        self._plan_draft_repetitions = 1
        self._plan_draft_mastery_gate = False
        self._lesson_domain_filter = "all"
        self._lesson_family_filter = "all"
        self._editing_plan_id: str | None = None
        self._stats: Any = None

        self.canvas: tk.Canvas | None = None
        try:
            self.canvas = tk.Canvas(
                root,
                width=WINDOW_WIDTH,
                height=WINDOW_HEIGHT,
                bg=self.BACKGROUND,
                highlightthickness=0,
            )
            self.canvas.place(x=0, y=0, width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
            self.canvas.bind("<ButtonPress-1>", self._handle_press)
            self.canvas.bind("<B1-Motion>", self._handle_motion)
            self.canvas.bind("<ButtonRelease-1>", self._handle_release)
            self._load_profiles()
            self._show_home()
            self._refresh_face()
        except Exception:
            self._dispose(notify=False)
            raise

    def _font(self, size: int, *, bold: bool = False, family: str | None = None) -> tuple[str, int, str]:
        return (family or self.font_family, size, "bold" if bold else "normal")

    @staticmethod
    def _safe_percent(value: Any) -> str:
        return format_percent(value)

    @staticmethod
    def _invoke(method: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """Pass only keyword arguments accepted by a duck-typed service."""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(*args, **kwargs)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        accepted = kwargs if accepts_kwargs else {
            name: value for name, value in kwargs.items() if name in signature.parameters
        }
        return method(*args, **accepted)

    def _catalog_lessons(self) -> tuple[LessonSnapshot, ...]:
        catalog = self.catalog
        values: Any = ()
        if isinstance(catalog, Mapping):
            values = catalog.values()
        else:
            for name in ("lessons", "definitions", "items"):
                candidate = getattr(catalog, name, None)
                if candidate is not None:
                    values = candidate.values() if isinstance(candidate, Mapping) else candidate
                    break
            else:
                try:
                    values = tuple(catalog)
                except TypeError:
                    values = ()
        return tuple(lesson_snapshot(item) for item in values)

    def _load_profiles(self) -> None:
        try:
            values = self.store.list_profiles(include_archived=False)
            self._profiles = tuple(profile_snapshot(item) for item in values)
            self._data_error = self._store_read_only_notice()
        except Exception:
            self._profiles = ()
            self._data_error = "Learning records could not be read. Teacher tools may be unavailable."
        self._profile_pages.set_count(len(self._profiles))
        self._teacher_pages.set_count(len(self._profiles))

    def _store_read_only_notice(self) -> str:
        try:
            problem = getattr(self.store, "read_only_error", None)
            if callable(problem):
                problem = problem()
            if not problem:
                errors = getattr(self.store, "errors", ())
                if callable(errors):
                    errors = errors()
                problem = "; ".join(str(item) for item in (errors or ()))
        except Exception:
            problem = "unavailable local records"
        if not problem:
            return ""
        return "Learning data is read-only until a teacher repairs the local records."

    def _load_plans(self) -> None:
        profile = self._selected_profile
        if profile is None:
            self._plans = ()
            return
        try:
            values = self.store.list_plans(profile.profile_id, include_archived=False)
            self._plans = tuple(
                plan_snapshot(item, default_questions=self.default_question_count)
                for item in values
            )
            self._data_error = self._store_read_only_notice()
        except Exception:
            self._plans = ()
            self._data_error = "Learning plans could not be read right now."
        self._plan_pages.set_count(len(self._plans))
        self._teacher_pages.set_count(len(self._plans))

    def _clear(self) -> None:
        canvas = self.canvas
        if canvas is None:
            return
        canvas.configure(bg=self.BACKGROUND)
        canvas.delete("all")
        self._regions.clear()
        self._callbacks.clear()
        self._action_serial = 0
        self._face_item = None
        self._fallback_items = ()
        self._face_image = None

    def _header(self, title: str, *, home: bool = True) -> None:
        canvas = self.canvas
        assert canvas is not None
        canvas.create_rectangle(0, 0, WINDOW_WIDTH, 66, fill=self.NAVY, outline="")
        self._button(Rect(8, 7, 92, 59), "MENU", self.close, color=self.BLUE, font_size=11)
        if home and self.screen is not LearningScreen.HOME:
            self._button(Rect(100, 7, 184, 59), "HOME", self._show_home, color=self.TEAL, font_size=11)
        title_x = 390 if home and self.screen is not LearningScreen.HOME else 330
        canvas.create_text(
            title_x,
            31,
            text=title,
            fill=self.WHITE,
            font=self._font(22, bold=True),
        )
        self._draw_face_panel()

    def _draw_face_panel(self) -> None:
        canvas = self.canvas
        assert canvas is not None
        bounds = self.FACE_BOUNDS
        canvas.create_rectangle(*bounds.as_tuple(), fill="#68C8BB", outline=self.WHITE, width=2)
        self._face_item = canvas.create_image(*bounds.center, anchor=tk.CENTER)
        left_eye = canvas.create_oval(714, 21, 722, 34, fill=self.NAVY, outline="")
        right_eye = canvas.create_oval(750, 21, 758, 34, fill=self.NAVY, outline="")
        mouth = canvas.create_line(730, 43, 742, 43, fill=self.NAVY, width=3)
        label = canvas.create_text(693, 33, text="B", fill=self.NAVY, font=self._font(9, bold=True))
        self._fallback_items = (left_eye, right_eye, mouth, label)

    def _button(
        self,
        bounds: Rect,
        label: str,
        callback: Callable[[], None],
        *,
        color: str | None = None,
        enabled: bool = True,
        font_size: int = 13,
        outline: str | None = None,
    ) -> None:
        if not bounds.inside():
            raise ValueError(f"Learning control is outside 800x480: {bounds}")
        canvas = self.canvas
        assert canvas is not None
        fill = (color or self.BLUE) if enabled else self.DISABLED
        canvas.create_rectangle(
            *bounds.as_tuple(),
            fill=fill,
            outline=outline or self.WHITE,
            width=3,
        )
        canvas.create_text(
            *bounds.center,
            text=label,
            fill=self.WHITE,
            width=max(30, bounds.width - 12),
            justify=tk.CENTER,
            font=self._font(font_size, bold=True),
        )
        key = f"action-{self._action_serial}"
        self._action_serial += 1
        self._regions.append(HitRegion(key, bounds, enabled=enabled))
        if enabled:
            self._callbacks[key] = callback

    def _page_buttons(self, cursor: PageCursor, redraw: Callable[[], None]) -> None:
        self._button(
            Rect(16, 404, 102, 468),
            "PREV",
            lambda: self._turn_page(cursor, -1, redraw),
            color=self.NAVY,
            enabled=cursor.page_index > 0,
            font_size=10,
        )
        self._button(
            Rect(698, 404, 784, 468),
            "NEXT",
            lambda: self._turn_page(cursor, 1, redraw),
            color=self.NAVY,
            enabled=cursor.page_index < cursor.page_count - 1,
            font_size=10,
        )
        assert self.canvas is not None
        self.canvas.create_text(
            400,
            452,
            text=f"PAGE {cursor.page_index + 1} OF {cursor.page_count}",
            fill=self.MUTED,
            font=self._font(9, bold=True),
        )

    @staticmethod
    def _turn_page(cursor: PageCursor, direction: int, redraw: Callable[[], None]) -> None:
        changed = cursor.next() if direction > 0 else cursor.previous()
        if changed:
            redraw()

    def _draw_notice(self, message: str, *, danger: bool = False) -> None:
        if not message:
            return
        assert self.canvas is not None
        self.canvas.create_rectangle(
            188,
            407,
            612,
            440,
            fill="#F8E8C7" if not danger else "#F8DDE0",
            outline=self.RED if danger else self.YELLOW,
            width=2,
        )
        self.canvas.create_text(
            400,
            423,
            text=message,
            fill=self.RED if danger else self.INK,
            width=405,
            font=self._font(9, bold=True),
        )

    def _show_home(self) -> None:
        if self.closed:
            return
        pin = getattr(self, "_pin", None)
        if pin is not None:
            pin.clear()
        self.screen = LearningScreen.HOME
        self._selected_plan = None
        self._clear()
        self._header("LEARNING", home=False)
        assert self.canvas is not None
        self.canvas.create_text(
            400,
            101,
            text="Who is learning today?",
            fill=self.INK,
            font=self._font(24, bold=True),
        )
        profiles = self._profile_pages.current(self._profiles)
        if not profiles:
            self._draw_empty_character(400, 244)
            self.canvas.create_text(
                400,
                342,
                text="A teacher can add the first learner.",
                fill=self.MUTED,
                font=self._font(13, bold=True),
            )
        else:
            card_width = 170
            gap = 18
            total = len(profiles) * card_width + max(0, len(profiles) - 1) * gap
            start_x = (WINDOW_WIDTH - total) // 2
            for index, profile in enumerate(profiles):
                left = start_x + index * (card_width + gap)
                self._profile_card(Rect(left, 145, left + card_width, 330), profile)
        self._button(
            Rect(612, 400, 784, 468),
            "TEACHER",
            self._show_teacher_pin,
            color=self.NAVY,
            font_size=12,
        )
        if self._profile_pages.page_count > 1:
            self._page_buttons(self._profile_pages, self._show_home)
        self._draw_notice(self._data_error, danger=True)

    def _draw_empty_character(self, center_x: int, center_y: int) -> None:
        assert self.canvas is not None
        self.canvas.create_rectangle(center_x - 76, center_y - 62, center_x + 76, center_y + 62, fill="#78D0BF", outline=self.NAVY, width=4)
        self.canvas.create_oval(center_x - 39, center_y - 25, center_x - 25, center_y - 5, fill=self.NAVY, outline="")
        self.canvas.create_oval(center_x + 25, center_y - 25, center_x + 39, center_y - 5, fill=self.NAVY, outline="")
        self.canvas.create_arc(center_x - 26, center_y + 1, center_x + 26, center_y + 35, start=200, extent=140, style=tk.ARC, outline=self.NAVY, width=4)

    def _profile_card(self, bounds: Rect, profile: ProfileSnapshot) -> None:
        assert self.canvas is not None
        self.canvas.create_rectangle(*bounds.as_tuple(), fill=self.PANEL, outline="#8CC7C1", width=4)
        center_x, _ = bounds.center
        self.canvas.create_oval(center_x - 31, bounds.top + 24, center_x + 31, bounds.top + 86, fill=self.YELLOW, outline=self.INK, width=2)
        self.canvas.create_oval(center_x - 42, bounds.top + 84, center_x + 42, bounds.top + 142, fill=self.SKY, outline=self.INK, width=2)
        self.canvas.create_text(center_x, bounds.bottom - 24, text=profile.display_name, fill=self.INK, width=bounds.width - 14, font=self._font(15, bold=True))
        key = f"profile-{profile.profile_id}-{self._action_serial}"
        self._action_serial += 1
        self._regions.append(HitRegion(key, bounds))
        self._callbacks[key] = lambda selected=profile: self._choose_profile(selected)

    def _choose_profile(self, profile: ProfileSnapshot) -> None:
        self._selected_profile = profile
        self._load_plans()
        self._show_plans()

    def _show_plans(self) -> None:
        self.screen = LearningScreen.PLANS
        self._clear()
        profile = self._selected_profile
        self._header(f"{profile.display_name.upper() if profile else 'LEARNER'}'S PLANS")
        assert self.canvas is not None
        self.canvas.create_text(400, 95, text="Pick a learning adventure", fill=self.INK, font=self._font(21, bold=True))
        plans = tuple(plan for plan in self._plan_pages.current(self._plans) if not plan.archived)
        if not plans:
            self.canvas.create_text(400, 236, text="No active plans yet", fill=self.INK, font=self._font(21, bold=True))
            self.canvas.create_text(400, 274, text="Ask a teacher to build one from the lesson library.", fill=self.MUTED, font=self._font(12, bold=True))
        for index, plan in enumerate(plans):
            top = 126 + index * 86
            enabled = plan.enabled and bool(plan.lesson_ids)
            color = self.TEAL if enabled else self.DISABLED
            self._button(
                Rect(100, top, 700, top + 70),
                f"{plan.name}    {len(plan.lesson_ids)} LESSONS",
                lambda selected=plan: self._choose_plan(selected),
                color=color,
                enabled=enabled,
                font_size=15,
            )
        if self._plan_pages.page_count > 1:
            self._page_buttons(self._plan_pages, self._show_plans)
        self._draw_notice(self._data_error, danger=True)

    def _choose_plan(self, plan: PlanSnapshot) -> None:
        self._selected_plan = plan
        profile = self._selected_profile
        resumable = None
        if profile is not None:
            method = getattr(self.store, "resumable_session", None)
            if callable(method):
                try:
                    resumable = self._invoke(method, profile.profile_id, plan.plan_id)
                except Exception:
                    self._status = "A saved session could not be opened."
        if resumable is not None:
            self._session = resumable
            self._show_resume()
        else:
            self._start_new_session()

    def _show_resume(self) -> None:
        self.screen = LearningScreen.RESUME
        self._clear()
        self._header("WELCOME BACK")
        assert self.canvas is not None
        self._draw_empty_character(400, 207)
        self.canvas.create_text(400, 302, text="Keep going where you stopped?", fill=self.INK, font=self._font(22, bold=True))
        self._button(Rect(90, 365, 378, 455), "RESUME", self._resume_session, color=self.GREEN, font_size=18)
        self._button(Rect(422, 365, 710, 455), "START OVER", self._confirm_start_over, color=self.BLUE, font_size=16)

    def _confirm_start_over(self) -> None:
        self._ask_confirmation(
            "START OVER?",
            "The saved session stays in history, but this plan will begin a new session.",
            "START NEW",
            self._start_new_session,
            self._show_resume,
        )

    def _start_new_session(self) -> None:
        profile = self._selected_profile
        plan = self._selected_plan
        if profile is None or plan is None or not plan.lesson_ids:
            self._show_error("This plan needs at least one lesson before it can start.", self._show_plans)
            return
        method = getattr(self.engine, "start_session", None)
        if not callable(method):
            self._show_error("The lesson engine is unavailable.", self._show_plans)
            return
        try:
            eligible_lesson_ids = plan.lesson_ids
            if plan.mastery_gate:
                eligibility = getattr(self.engine, "eligible_lesson_ids", None)
                attempts_reader = getattr(self.store, "list_attempts", None)
                if callable(eligibility) and callable(attempts_reader):
                    attempts = self._invoke(
                        attempts_reader,
                        profile.profile_id,
                        plan.plan_id,
                    )
                    eligible_lesson_ids = tuple(
                        self._invoke(
                            eligibility,
                            plan.raw,
                            attempts,
                            mastery_threshold=float(
                                _field(self.config, "mastery_threshold", default=0.8)
                            ),
                            minimum_evidence=int(
                                _field(
                                    self.config,
                                    "mastery_min_evidence",
                                    default=5,
                                )
                            ),
                        )
                    )
                    if len(eligible_lesson_ids) < len(plan.lesson_ids):
                        self._status = (
                            "Later lessons unlock as foundation skills are mastered."
                        )
            if not eligible_lesson_ids:
                self._show_error(
                    "This plan is waiting for a foundation lesson to be mastered.",
                    self._show_plans,
                )
                return
            self._session = self._invoke(
                method,
                profile_id=profile.profile_id,
                plan_id=plan.plan_id,
                lesson_ids=eligible_lesson_ids,
                question_count=plan.question_count,
                repetitions=int(_field(plan, "repetitions", default=1)),
            )
            self._session_index = 0
            self._session_total = max(1, plan.question_count)
            if not self._persist_session():
                self._status = (
                    "Progress cannot be saved right now. Please tell a teacher."
                )
            self._resume_session()
        except Exception:
            self._show_error("This learning session could not be started.", self._show_plans)

    def _resume_session(self) -> None:
        try:
            raw_question = self._engine_current_question()
        except Exception:
            self._show_error("The next question could not be prepared.", self._show_plans)
            return
        if raw_question is None:
            self._show_complete()
            return
        self._set_question(raw_question)

    def _engine_current_question(self) -> Any:
        method = getattr(self.engine, "current_question", None)
        if callable(method):
            return self._invoke(method, self._session)
        return _field(self._session, "current_question", "question", default=None)

    def _set_question(self, raw_question: Any) -> None:
        self._question = question_snapshot(raw_question)
        self._question_controller = InteractionController(self._question)
        self._input_locked = False
        self._question_started_at = time.monotonic()
        self._pending_question = None
        self._show_lesson()
        if self._question.question_id not in self._auto_spoken:
            self._auto_spoken.add(self._question.question_id)
            self._schedule(120, self._replay_question)

    def _show_lesson(self) -> None:
        question = self._question
        controller = self._question_controller
        if question is None or controller is None:
            self._show_error("No question is ready.", self._show_plans)
            return
        self.screen = LearningScreen.LESSON
        self._clear()
        self._header("LEARNING TIME")
        self._draw_progress()
        assert self.canvas is not None
        prompt = "Tap REPLAY to hear the question." if question.hidden_prompt else question.prompt
        self.canvas.create_text(
            332,
            112,
            text=prompt,
            fill=self.INK,
            width=540,
            font=self._font(17, bold=True),
            justify=tk.CENTER,
        )
        self._button(
            Rect(684, 78, 784, 144),
            "REPLAY",
            self._replay_question,
            color=self.CORAL,
            enabled=self.replay_enabled,
            font_size=10,
        )
        if question.example:
            self.canvas.create_text(400, 153, text=question.example, fill="#000000", font=self._font(28, bold=True))
        self._draw_question_controls(question, controller)
        if self._status:
            self._draw_notice(self._status, danger=True)

    @property
    def replay_enabled(self) -> bool:
        return self.speech_available and not self._speech_failed and not self.closed

    def _draw_progress(self) -> None:
        assert self.canvas is not None
        index = _field(self._session, "question_index", "current_index", default=self._session_index)
        questions = _field(self._session, "questions", default=()) or ()
        total = _field(
            self._session,
            "question_count",
            "total_questions",
            default=len(questions) or self._session_total,
        )
        try:
            index_number = max(0, int(index))
            total_number = max(1, int(total))
        except (TypeError, ValueError):
            index_number, total_number = self._session_index, max(1, self._session_total)
        shown = min(total_number, index_number + 1)
        left, right = 198, 602
        self.canvas.create_rectangle(left, 72, right, 82, fill="#C7D7DF", outline="")
        filled = left + int((right - left) * min(1.0, shown / total_number))
        self.canvas.create_rectangle(left, 72, filled, 82, fill=self.YELLOW, outline="")
        self.canvas.create_text(626, 77, text=f"{shown}/{total_number}", fill=self.MUTED, font=self._font(9, bold=True))

    def _draw_question_controls(self, question: QuestionSnapshot, controller: InteractionController) -> None:
        kind = question.interaction
        if kind == "listen_only" and not question.choices:
            self._draw_scene(Rect(220, 174, 580, 356), question.metadata)
            self._button(Rect(260, 386, 540, 462), "I'M READY", self._submit_current, color=self.GREEN, font_size=17)
            return
        has_prompt_scene = self._has_prompt_scene(question)
        if has_prompt_scene:
            scene_metadata = dict(question.metadata)
            if "prompt_picture" in scene_metadata:
                scene_metadata["picture"] = scene_metadata["prompt_picture"]
            self._draw_scene(Rect(270, 139, 530, 218), scene_metadata)
        if kind == "alphabet_grid" or len(question.choices) > 10:
            self._draw_alphabet_grid(question, controller)
        else:
            self._draw_choice_grid(
                question,
                controller,
                top=226 if has_prompt_scene else 171,
            )
        if controller.needs_submit:
            self._button(
                Rect(282, 408, 518, 468),
                "SUBMIT",
                self._submit_current,
                color=self.GREEN,
                enabled=controller.submit_ready and not self._input_locked,
                font_size=15,
            )

    @staticmethod
    def _has_prompt_scene(question: QuestionSnapshot) -> bool:
        keys = {
            "picture",
            "prompt_picture",
            "count",
            "left_count",
            "sequence",
            "left",
            "pattern_type",
        }
        return bool(keys.intersection(question.metadata))

    def _draw_choice_grid(
        self,
        question: QuestionSnapshot,
        controller: InteractionController,
        *,
        top: int,
    ) -> None:
        choices = question.choices
        count = len(choices)
        if count <= 4:
            columns = 2
            rows = max(1, (count + 1) // 2)
        else:
            columns = min(5, count)
            rows = (count + columns - 1) // columns
        area_left, area_top, area_right = 30, top, 770
        area_bottom = 392 if controller.needs_submit else 463
        gap = 10
        cell_width = (area_right - area_left - gap * (columns - 1)) // columns
        cell_height = (area_bottom - area_top - gap * (rows - 1)) // rows
        picture_count = sum(
            bool(_identifier(item.metadata.get("picture")))
            for item in question.choices
        )
        allow_art = picture_count in {0, len(question.choices)}
        for index, choice in enumerate(choices):
            row, column = divmod(index, columns)
            left = area_left + column * (cell_width + gap)
            top = area_top + row * (cell_height + gap)
            bounds = Rect(left, top, left + cell_width, top + cell_height)
            selected = choice.choice_id in controller.selected or choice.choice_id in controller.assignments
            label = choice.label
            if question.interaction == "ordered_sequence" and choice.choice_id in controller.selected:
                label = f"{controller.selected.index(choice.choice_id) + 1}. {label}"
            elif question.interaction == "category_sorting" and choice.choice_id in controller.assignments:
                label = f"{label}\nTO: {controller.assignments[choice.choice_id]}"
            self._choice_button(
                bounds,
                choice,
                label,
                selected,
                lambda selected_id=choice.choice_id: self._choose_answer(selected_id),
                allow_art=allow_art,
            )

    def _draw_alphabet_grid(self, question: QuestionSnapshot, controller: InteractionController) -> None:
        columns = 9
        left, top, gap = 28, 164, 6
        width = 76
        height = 68 if len(question.choices) <= 18 else 62
        for index, choice in enumerate(question.choices):
            row, column = divmod(index, columns)
            bounds = Rect(left + column * (width + gap), top + row * (height + gap), left + column * (width + gap) + width, top + row * (height + gap) + height)
            if bounds.bottom > (397 if controller.needs_submit else 468):
                continue
            selected = choice.choice_id in controller.selected
            self._choice_button(bounds, choice, choice.label, selected, lambda selected_id=choice.choice_id: self._choose_answer(selected_id), compact=True)

    def _choice_button(
        self,
        bounds: Rect,
        choice: ChoiceSnapshot,
        label: str,
        selected: bool,
        callback: Callable[[], None],
        *,
        compact: bool = False,
        allow_art: bool = True,
    ) -> None:
        assert self.canvas is not None
        fill = self.YELLOW if selected else self.PANEL
        outline = self.TEAL if selected else "#87B3C4"
        self.canvas.create_rectangle(*bounds.as_tuple(), fill=fill, outline=outline, width=4)
        has_art = allow_art and self._draw_scene(
            bounds,
            choice.metadata,
            choice_label=choice.label,
        )
        font_name = _identifier(
            choice.metadata.get("font_family", choice.metadata.get("font")),
            fallback=self.font_family,
        )
        if font_name not in self.font_families:
            font_name = self.font_family
        text_y = bounds.center[1] if not has_art else bounds.bottom - 20
        text_color = safe_choice_text_color(
            choice.metadata.get("color"),
            normal_background=self.PANEL,
            selected_background=self.YELLOW,
            fallback=self.INK,
        )
        self.canvas.create_text(
            bounds.center[0],
            text_y,
            text=label,
            fill=text_color,
            width=bounds.width - 12,
            justify=tk.CENTER,
            font=self._font(22 if compact else min(22, max(12, bounds.height // 4)), bold=True, family=font_name),
        )
        key = f"choice-{choice.choice_id}-{self._action_serial}"
        self._action_serial += 1
        enabled = not self._input_locked
        self._regions.append(HitRegion(key, bounds, enabled=enabled))
        if enabled:
            self._callbacks[key] = callback

    def _draw_scene(self, bounds: Rect, metadata: Mapping[str, Any], choice_label: str = "") -> bool:
        """Draw deterministic original primitives described by question metadata."""
        assert self.canvas is not None
        art = _identifier(
            metadata.get(
                "prompt_picture",
                metadata.get("art", metadata.get("shape", metadata.get("picture", ""))),
            )
        ).lower()
        count_value = metadata.get("count")
        if count_value is not None:
            try:
                count = max(0, min(20, int(count_value)))
            except (TypeError, ValueError):
                count = 0
            if count:
                columns = min(5, count)
                rows = (count + columns - 1) // columns
                radius = max(5, min(13, bounds.width // (columns * 3), bounds.height // (rows * 3)))
                for index in range(count):
                    row, column = divmod(index, columns)
                    x_value = bounds.left + (column + 1) * bounds.width // (columns + 1)
                    y_value = bounds.top + 12 + (row + 1) * max(20, (bounds.height - 35) // (rows + 1))
                    self.canvas.create_oval(x_value - radius, y_value - radius, x_value + radius, y_value + radius, fill=self.CORAL, outline=self.INK, width=1)
                return True
            self.canvas.create_rectangle(
                bounds.left + 10,
                bounds.top + 10,
                bounds.right - 10,
                bounds.bottom - 10,
                fill=self.WHITE,
                outline=self.MUTED,
                width=2,
            )
            self.canvas.create_text(
                *bounds.center,
                text="NO OBJECTS",
                fill=self.MUTED,
                font=self._font(9, bold=True),
            )
            return True
        left_count = metadata.get("left_count", metadata.get("left"))
        right_count = metadata.get("right_count", metadata.get("right"))
        if left_count is not None and right_count is not None:
            try:
                left_total = max(0, min(10, int(left_count)))
                right_total = max(0, min(10, int(right_count)))
            except (TypeError, ValueError):
                left_total = right_total = 0
            if left_total or right_total:
                self._draw_count_group(
                    Rect(bounds.left, bounds.top, bounds.center[0] - 4, bounds.bottom),
                    left_total,
                    self.CORAL,
                )
                self._draw_count_group(
                    Rect(bounds.center[0] + 4, bounds.top, bounds.right, bounds.bottom),
                    right_total,
                    self.BLUE,
                )
                self.canvas.create_line(
                    bounds.center[0],
                    bounds.top + 4,
                    bounds.center[0],
                    bounds.bottom - 4,
                    fill=self.MUTED,
                    width=2,
                )
                return True
        sequence = metadata.get("sequence")
        if isinstance(sequence, Sequence) and not isinstance(sequence, str) and sequence:
            entries = tuple(sequence)[:8]
            spacing = max(25, bounds.width // max(1, len(entries)))
            for index, entry in enumerate(entries):
                x_value = bounds.left + spacing // 2 + index * spacing
                if entry is None:
                    self.canvas.create_rectangle(
                        x_value - 10,
                        bounds.center[1] - 10,
                        x_value + 10,
                        bounds.center[1] + 10,
                        fill=self.WHITE,
                        outline=self.CORAL,
                        width=2,
                    )
                elif isinstance(entry, (int, float, str)):
                    self.canvas.create_text(
                        x_value,
                        bounds.center[1],
                        text=str(entry),
                        fill=self.INK,
                        font=self._font(11, bold=True),
                    )
            return True
        if not art:
            return False
        self._draw_token_icon(bounds, art)
        del choice_label
        return True

    def _draw_count_group(self, bounds: Rect, count: int, color: str) -> None:
        assert self.canvas is not None
        columns = min(5, max(1, count))
        rows = max(1, (count + columns - 1) // columns)
        radius = max(3, min(9, bounds.width // (columns * 3), bounds.height // (rows * 3)))
        for index in range(count):
            row, column = divmod(index, columns)
            x_value = bounds.left + (column + 1) * bounds.width // (columns + 1)
            y_value = bounds.top + (row + 1) * bounds.height // (rows + 1)
            self.canvas.create_oval(
                x_value - radius,
                y_value - radius,
                x_value + radius,
                y_value + radius,
                fill=color,
                outline=self.INK,
                width=1,
            )

    def _draw_token_icon(self, bounds: Rect, token: str) -> None:
        """Render any local picture token with stable, lightweight geometry."""
        assert self.canvas is not None
        center_x = bounds.center[0]
        center_y = bounds.center[1] - 10
        size = max(16, min(40, bounds.width // 4, bounds.height // 3))
        palette = (self.SKY, self.YELLOW, "#9AD18B", "#E9A2B0", "#BCA7E8")
        color = palette[sum(ord(character) for character in token) % len(palette)]
        if "red" in token:
            color = self.CORAL
        elif "blue" in token:
            color = self.SKY
        elif "green" in token:
            color = "#8FD08A"
        elif "yellow" in token:
            color = self.YELLOW
        elif "purple" in token:
            color = "#BCA7E8"
        if any(word in token for word in ("circle", "sphere", "round", "ball")):
            self.canvas.create_oval(center_x - size, center_y - size, center_x + size, center_y + size, fill=color, outline=self.INK, width=2)
        elif any(word in token for word in ("square", "cube", "block", "tile")):
            self.canvas.create_rectangle(center_x - size, center_y - size, center_x + size, center_y + size, fill=color, outline=self.INK, width=2)
            if "cube" in token:
                self.canvas.create_line(center_x - size, center_y - size, center_x - size // 2, center_y - size - 9, center_x + size, center_y - size, fill=self.INK, width=2)
        elif any(word in token for word in ("triangle", "cone", "hat")):
            points = (center_x, center_y - size, center_x + size, center_y + size, center_x - size, center_y + size)
            self.canvas.create_polygon(*points, fill=color, outline=self.INK, width=2)
        elif "star" in token:
            self.canvas.create_polygon(center_x, center_y - size, center_x + size, center_y + size, center_x - size, center_y + size, fill=color, outline=self.INK, width=2)
        elif any(word in token for word in ("book", "page", "cover", "spine", "title")):
            self.canvas.create_rectangle(center_x - size, center_y - size, center_x, center_y + size, fill=self.YELLOW, outline=self.INK, width=2)
            self.canvas.create_rectangle(center_x, center_y - size, center_x + size, center_y + size, fill=self.SKY, outline=self.INK, width=2)
        elif any(word in token for word in ("sun", "day")):
            self.canvas.create_oval(center_x - size, center_y - size, center_x + size, center_y + size, fill=self.YELLOW, outline=self.CORAL, width=3)
        elif any(word in token for word in ("cloud", "rain", "snow", "weather")):
            self.canvas.create_oval(center_x - size, center_y - size // 2, center_x + size, center_y + size // 2, fill=self.SKY, outline=self.BLUE, width=2)
            if "rain" in token:
                for offset in (-size // 2, 0, size // 2):
                    self.canvas.create_line(center_x + offset, center_y + size // 2 + 4, center_x + offset - 4, center_y + size, fill=self.BLUE, width=2)
        elif any(word in token for word in ("plant", "seed", "sprout", "leaf", "flower", "garden", "tree")):
            self.canvas.create_line(center_x, center_y + size, center_x, center_y - size, fill=self.GREEN, width=5)
            self.canvas.create_oval(center_x - size, center_y - size, center_x, center_y, fill="#8CCB73", outline=self.GREEN)
            self.canvas.create_oval(center_x, center_y - size // 2, center_x + size, center_y + size // 2, fill="#8CCB73", outline=self.GREEN)
        elif any(word in token for word in ("fish", "bird", "dog", "cat", "frog", "rabbit", "tiger", "bear", "ant", "animal")):
            self.canvas.create_oval(center_x - size, center_y - size // 2, center_x + size // 2, center_y + size // 2, fill=color, outline=self.INK, width=2)
            self.canvas.create_oval(center_x + size // 3, center_y - size // 3, center_x + size, center_y + size // 3, fill=color, outline=self.INK, width=2)
            self.canvas.create_oval(center_x + size * 2 // 3, center_y - 3, center_x + size * 2 // 3 + 5, center_y + 2, fill=self.INK, outline="")
        elif any(word in token for word in ("child", "friend", "adult", "person", "body", "hand", "feel")):
            self.canvas.create_oval(center_x - 10, center_y - size, center_x + 10, center_y - size + 20, fill=color, outline=self.INK, width=2)
            self.canvas.create_line(center_x, center_y - size + 20, center_x, center_y + size // 2, fill=self.INK, width=4)
            self.canvas.create_line(center_x, center_y, center_x - size, center_y + size // 3, fill=self.INK, width=3)
            self.canvas.create_line(center_x, center_y, center_x + size, center_y + size // 3, fill=self.INK, width=3)
        else:
            # Every authored picture token still receives an original scene.
            self.canvas.create_rectangle(bounds.left + 5, bounds.top + 5, bounds.right - 5, bounds.bottom - 28, fill="#E2F4FB", outline="#85B5C6", width=2)
            self.canvas.create_oval(center_x - size // 2, center_y - size // 2, center_x + size // 2, center_y + size // 2, fill=color, outline=self.INK, width=2)
            self.canvas.create_line(bounds.left + 8, bounds.bottom - 32, bounds.right - 8, bounds.bottom - 32, fill=self.GREEN, width=3)

    def _choose_answer(self, choice_id: str) -> None:
        controller = self._question_controller
        if controller is None or self._input_locked:
            return
        result = controller.choose(choice_id)
        if not result.accepted:
            return
        if result.submit_immediately:
            self._submit_current()
        else:
            self._show_lesson()

    def _submit_current(self) -> None:
        controller = self._question_controller
        question = self._question
        if controller is None or question is None or self._input_locked:
            return
        if not controller.submit_ready:
            self._status = "Choose an answer before you submit."
            self._show_lesson()
            return
        self._input_locked = True
        controller.locked = True
        attempt = self._question_attempts.get(question.question_id, 0) + 1
        self._question_attempts[question.question_id] = attempt
        try:
            result = self._engine_submit(controller.response(), attempt)
            evaluation_value, new_session, next_question, attempt_record = self._unpack_submission(result)
            if new_session is not None:
                self._session = new_session
            self._pending_question = next_question
            evaluation = evaluation_snapshot(evaluation_value, question, attempt)
            self._pending_evaluation = evaluation
            self._progress_saved = self._persist_answer(attempt_record)
            self._feedback_retry = evaluation.try_again
            self._show_feedback()
        except Exception:
            self._input_locked = False
            controller.locked = False
            self._show_error("That answer could not be checked. Your session is still here.", self._show_lesson)

    def _engine_submit(self, response: Any, attempt: int) -> Any:
        method = getattr(self.engine, "submit", None)
        if callable(method):
            elapsed = max(0.0, min(86_400.0, time.monotonic() - self._question_started_at))
            return self._invoke(
                method,
                self._session,
                response,
                elapsed_seconds=elapsed,
            )
        evaluate = getattr(self.engine, "evaluate", None)
        if callable(evaluate):
            return self._invoke(evaluate, self._question, response, attempt_number=attempt)
        raise RuntimeError("Learning engine has no answer evaluator")

    def _unpack_submission(self, result: Any) -> tuple[Any, Any, Any, Any]:
        evaluation = _field(result, "evaluation", "result", default=None)
        session = _field(result, "session", "updated_session", default=None)
        question = _field(result, "next_question", "question", default=None)
        attempt = _field(result, "attempt", "attempt_record", default=None)
        if isinstance(result, tuple):
            for item in result:
                if _field(item, "correct", "is_correct", default=None) is not None:
                    evaluation = item
                elif _field(item, "profile_id", default=None) is not None and _field(item, "session_id", "plan_id", default=None) is not None:
                    session = item
                elif _field(item, "interaction", "choices", default=None) is not None:
                    question = item
        if evaluation is None:
            evaluation = result
        return evaluation, session, question, attempt

    def _persist_session(self) -> bool:
        method = getattr(self.store, "save_session", None)
        if not callable(method) or self._session is None:
            return True
        try:
            self._invoke(method, self._session)
            return True
        except Exception:
            return False

    def _persist_answer(self, attempt_record: Any) -> bool:
        transition = getattr(self.store, "record_transition", None)
        if attempt_record is not None and self._session is not None and callable(transition):
            try:
                self._invoke(transition, attempt_record, self._session)
                return True
            except Exception:
                return False
        saved = True
        if attempt_record is not None:
            method = getattr(self.store, "append_attempt", None)
            if callable(method):
                try:
                    self._invoke(method, attempt_record)
                except Exception:
                    saved = False
        if not self._persist_session():
            saved = False
        return saved

    def _show_feedback(self) -> None:
        evaluation = self._pending_evaluation
        if evaluation is None:
            return
        self.screen = LearningScreen.FEEDBACK
        self._feedback_ready = False
        self._clear()
        self._header("NICE TRY" if not evaluation.correct else "GREAT WORK")
        assert self.canvas is not None
        color = self.YELLOW if self._feedback_retry else self.GREEN
        self.canvas.create_oval(298, 95, 502, 299, fill=color, outline=self.NAVY, width=5)
        self.canvas.create_text(400, 162, text="TRY\nAGAIN" if self._feedback_retry else "YOU\nGOT IT", fill=self.NAVY if self._feedback_retry else self.WHITE, font=self._font(25, bold=True), justify=tk.CENTER)
        message = evaluation.feedback
        if not self._progress_saved:
            message += "\nProgress was not saved. Please tell a teacher."
        self.canvas.create_text(400, 335, text=message, fill=self.INK, width=650, font=self._font(16, bold=True), justify=tk.CENTER)
        button_label = "TRY AGAIN" if self._feedback_retry else "CONTINUE"
        self._button(
            Rect(260, 396, 540, 466),
            button_label,
            self._retry_question if self._feedback_retry else self._advance_question,
            color=self.TEAL if self._feedback_retry else self.GREEN,
            enabled=self._feedback_ready,
            font_size=16,
        )

        def ready() -> None:
            if self.closed or self.screen is not LearningScreen.FEEDBACK:
                return
            self._feedback_ready = True
            self._input_locked = False
            self._show_feedback_ready()

        if not self._speak(message, ready):
            ready()

    def _show_feedback_ready(self) -> None:
        evaluation = self._pending_evaluation
        if evaluation is None:
            return
        self.screen = LearningScreen.FEEDBACK
        self._clear()
        self._header("NICE TRY" if not evaluation.correct else "GREAT WORK")
        assert self.canvas is not None
        color = self.YELLOW if self._feedback_retry else self.GREEN
        self.canvas.create_oval(298, 95, 502, 299, fill=color, outline=self.NAVY, width=5)
        self.canvas.create_text(400, 190, text="TRY AGAIN" if self._feedback_retry else "YOU GOT IT", fill=self.NAVY if self._feedback_retry else self.WHITE, font=self._font(23, bold=True))
        message = evaluation.feedback
        if not self._progress_saved:
            message += "\nProgress was not saved. Please tell a teacher."
        self.canvas.create_text(400, 335, text=message, fill=self.INK, width=650, font=self._font(16, bold=True), justify=tk.CENTER)
        self._button(Rect(260, 396, 540, 466), "TRY AGAIN" if self._feedback_retry else "CONTINUE", self._retry_question if self._feedback_retry else self._advance_question, color=self.TEAL if self._feedback_retry else self.GREEN, font_size=16)

    def _retry_question(self) -> None:
        controller = self._question_controller
        if controller is not None:
            controller.reset_for_retry()
        self._input_locked = False
        self._status = "Notice what is different, then choose again."
        self._show_lesson()

    def _advance_question(self) -> None:
        self._session_index += 1
        if self._pending_evaluation is not None and self._pending_evaluation.complete:
            self._show_complete()
            return
        raw_question = self._pending_question
        if raw_question is None:
            try:
                raw_question = self._engine_current_question()
            except Exception:
                raw_question = None
        if raw_question is not None and self._question is not None:
            candidate = question_snapshot(raw_question)
            if candidate.question_id == self._question.question_id:
                advance = getattr(self.engine, "advance", None)
                if callable(advance):
                    try:
                        advanced = self._invoke(advance, self._session)
                        if advanced is not None:
                            self._session = advanced
                        raw_question = self._engine_current_question()
                    except Exception:
                        raw_question = None
        if raw_question is None or self._session_is_complete():
            self._show_complete()
        else:
            self._set_question(raw_question)

    def _session_is_complete(self) -> bool:
        status = _identifier(_field(self._session, "status", default="")).lower()
        return bool(_field(self._session, "complete", "completed", default=False)) or status in {"complete", "completed", "finished"}

    def _show_complete(self) -> None:
        self.screen = LearningScreen.COMPLETE
        self._clear()
        self._header("SESSION COMPLETE")
        assert self.canvas is not None
        for index in range(3):
            x_value = 305 + index * 95
            self.canvas.create_polygon(x_value, 120, x_value + 14, 155, x_value + 51, 158, x_value + 22, 181, x_value + 31, 218, x_value, 197, x_value - 31, 218, x_value - 22, 181, x_value - 51, 158, x_value - 14, 155, fill=self.YELLOW, outline=self.CORAL, width=2)
        self.canvas.create_text(400, 278, text="You practiced, learned, and kept going!", fill=self.INK, font=self._font(20, bold=True))
        self._button(Rect(105, 365, 375, 455), "MORE LEARNING", self._show_plans, color=self.BLUE, font_size=15)
        self._button(Rect(425, 365, 695, 455), "HOME", self._show_home, color=self.GREEN, font_size=17)
        self._speak("Session complete. You practiced, learned, and kept going!", None)

    def _replay_question(self) -> None:
        question = self._question
        if question is None or not self.replay_enabled:
            return
        self._speak(question.spoken_prompt, None)

    def _speak(self, text: str, on_complete: Callable[[], None] | None) -> bool:
        if not self.replay_enabled or not str(text).strip():
            return False
        self._face_speaking = True

        def complete() -> None:
            if self.closed:
                return
            self._face_speaking = False
            if on_complete is not None:
                on_complete()

        try:
            accepted = bool(self.announce(str(text).strip(), complete if on_complete is not None else complete))
        except Exception:
            accepted = False
        if not accepted:
            self._face_speaking = False
            self._speech_failed = True
            if (
                getattr(self, "screen", None) is LearningScreen.LESSON
                and getattr(self, "canvas", None) is not None
            ):
                self._show_lesson()
        return accepted

    def _show_teacher_pin(self) -> None:
        self.screen = LearningScreen.TEACHER_PIN
        self._pin.clear()
        self._pin_error = False
        self._draw_teacher_pin()

    def _draw_teacher_pin(self) -> None:
        self._clear()
        self._header("TEACHER ACCESS")
        assert self.canvas is not None
        self.canvas.create_text(244, 113, text="Enter the 4-digit teacher PIN", fill=self.INK, font=self._font(17, bold=True))
        for index in range(self._pin.length):
            x_value = 126 + index * 78
            filled = index < len(self._pin._entered)
            self.canvas.create_oval(x_value, 148, x_value + 36, 184, fill=self.RED if self._pin_error else (self.TEAL if filled else self.WHITE), outline=self.RED if self._pin_error else self.NAVY, width=3)
        if self._pin_error:
            self.canvas.create_text(244, 210, text="That PIN did not match. Try again.", fill=self.RED, font=self._font(11, bold=True))
        for index, digit in enumerate("123456789"):
            row, column = divmod(index, 3)
            left = 470 + column * 94
            top = 91 + row * 82
            self._button(Rect(left, top, left + 78, top + 68), digit, lambda value=digit: self._pin_digit(value), color=self.NAVY, font_size=20)
        self._button(Rect(470, 337, 548, 405), "CLEAR", self._pin_clear, color=self.RED, font_size=9)
        self._button(Rect(564, 337, 642, 405), "0", lambda: self._pin_digit("0"), color=self.NAVY, font_size=20)
        self._button(Rect(658, 337, 736, 405), "BACK", self._pin_backspace, color=self.BLUE, font_size=9)

    def _pin_digit(self, digit: str) -> None:
        self._pin_error = False
        if not self._pin.push(digit):
            return
        if not self._pin.complete:
            self._draw_teacher_pin()
            return
        value = self._pin.consume()
        verifier = getattr(self.config, "verify_teacher_pin", None)
        try:
            if callable(verifier):
                valid = bool(verifier(value))
            elif isinstance(self.config, Mapping):
                valid = str(self.config.get("teacher_pin", "")) == value
            else:
                valid = False
        except Exception:
            valid = False
        if valid:
            self._show_teacher_home()
        else:
            self._pin_error = True
            self._draw_teacher_pin()

    def _pin_clear(self) -> None:
        self._pin.clear()
        self._pin_error = False
        self._draw_teacher_pin()

    def _pin_backspace(self) -> None:
        self._pin.backspace()
        self._pin_error = False
        self._draw_teacher_pin()

    def _show_teacher_home(self) -> None:
        self.screen = LearningScreen.TEACHER_HOME
        self._clear()
        self._header("TEACHER AREA")
        assert self.canvas is not None
        self.canvas.create_text(400, 96, text="Profiles, plans, and progress stay on this kiosk.", fill=self.MUTED, font=self._font(11, bold=True))
        buttons = (
            (Rect(70, 135, 370, 255), "LEARNER PROFILES", self._show_teacher_profiles, self.TEAL),
            (Rect(430, 135, 730, 255), "LEARNING PLANS", self._teacher_plans_entry, self.BLUE),
            (Rect(70, 285, 370, 405), "PROGRESS REPORTS", self._teacher_stats_entry, self.YELLOW),
            (Rect(430, 285, 730, 405), "EXIT TEACHER AREA", self._show_home, self.NAVY),
        )
        for bounds, label, callback, color in buttons:
            self._button(bounds, label, callback, color=color, font_size=15)

    def _show_teacher_profiles(self) -> None:
        self._load_profiles()
        self.screen = LearningScreen.TEACHER_PROFILES
        self._clear()
        self._header("LEARNER PROFILES")
        assert self.canvas is not None
        profiles = self._teacher_pages.current(self._profiles)
        for index, profile in enumerate(profiles):
            top = 90 + index * 91
            self._button(Rect(72, top, 590, top + 72), profile.display_name, lambda selected=profile: self._show_teacher_profile(selected), color=self.TEAL, font_size=16)
        self._button(Rect(616, 100, 774, 180), "NEW\nLEARNER", self._new_profile, color=self.GREEN, font_size=12)
        self._button(Rect(616, 205, 774, 285), "BACK", self._show_teacher_home, color=self.NAVY, font_size=13)
        if self._teacher_pages.page_count > 1:
            self._page_buttons(self._teacher_pages, self._show_teacher_profiles)
        self._draw_notice(self._data_error, danger=True)

    def _show_teacher_profile(self, profile: ProfileSnapshot) -> None:
        self._selected_profile = profile
        self._load_plans()
        self.screen = LearningScreen.TEACHER_PROFILE
        self._clear()
        self._header("LEARNER PROFILE")
        assert self.canvas is not None
        self.canvas.create_text(400, 102, text=profile.display_name, fill=self.INK, font=self._font(25, bold=True))
        actions = (
            (Rect(68, 145, 282, 230), "RENAME", self._rename_profile, self.BLUE),
            (Rect(293, 145, 507, 230), "PLANS", self._show_teacher_plans, self.TEAL),
            (Rect(518, 145, 732, 230), "REPORT", self._show_profile_stats, self.YELLOW),
            (Rect(68, 260, 282, 345), "RESET PROGRESS", self._confirm_reset_profile, self.CORAL),
            (Rect(293, 260, 507, 345), "ARCHIVE", self._confirm_archive_profile, self.RED),
            (Rect(518, 260, 732, 345), "BACK", self._show_teacher_profiles, self.NAVY),
        )
        for bounds, label, callback, color in actions:
            self._button(bounds, label, callback, color=color, font_size=12)

    def _new_profile(self) -> None:
        self._begin_text_entry("NEW LEARNER NAME", "create_profile", "", LearningScreen.TEACHER_PROFILES)

    def _rename_profile(self) -> None:
        profile = self._selected_profile
        if profile is not None:
            self._begin_text_entry("RENAME LEARNER", "rename_profile", profile.display_name, LearningScreen.TEACHER_PROFILE)

    def _begin_text_entry(self, title: str, purpose: str, value: str, return_screen: LearningScreen) -> None:
        self._status = title
        self._text_purpose = purpose
        self._text_entry = TextEntry(value=value)
        self._text_return = return_screen
        self._draw_text_entry()

    def _draw_text_entry(self) -> None:
        self.screen = LearningScreen.TEXT_ENTRY
        self._clear()
        self._header(self._status or "ENTER A NAME")
        assert self.canvas is not None
        self.canvas.create_rectangle(78, 79, 722, 137, fill=self.WHITE, outline=self.TEAL, width=3)
        self.canvas.create_text(400, 108, text=self._text_entry.value or " ", fill=self.INK, width=620, font=self._font(20, bold=True))
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        columns = 9
        for index, letter in enumerate(letters):
            row, column = divmod(index, columns)
            left = 42 + column * 81
            top = 152 + row * 66
            self._button(Rect(left, top, left + 70, top + 56), letter, lambda value=letter: self._text_key(value), color=self.BLUE, font_size=15)
        self._button(Rect(42, 354, 188, 416), "CANCEL", self._return_from_text, color=self.NAVY, font_size=11)
        self._button(Rect(199, 354, 405, 416), "SPACE", lambda: self._text_key(" "), color=self.TEAL, font_size=11)
        self._button(Rect(416, 354, 562, 416), "BACK", self._text_backspace, color=self.CORAL, font_size=11)
        self._button(Rect(573, 354, 758, 416), "SAVE", self._save_text_entry, color=self.GREEN, enabled=bool(self._text_entry.cleaned), font_size=12)

    def _text_key(self, value: str) -> None:
        self._text_entry.push(value)
        self._draw_text_entry()

    def _text_backspace(self) -> None:
        self._text_entry.backspace()
        self._draw_text_entry()

    def _return_from_text(self) -> None:
        callbacks = {
            LearningScreen.TEACHER_PROFILES: self._show_teacher_profiles,
            LearningScreen.TEACHER_PROFILE: lambda: self._show_teacher_profile(self._selected_profile) if self._selected_profile else self._show_teacher_profiles(),
            LearningScreen.TEACHER_PLANS: self._show_teacher_plans,
        }
        callbacks.get(self._text_return, self._show_teacher_home)()

    def _save_text_entry(self) -> None:
        name = self._text_entry.cleaned
        if not name:
            return
        try:
            if self._text_purpose == "create_profile":
                self.store.create_profile(name)
                self._show_teacher_profiles()
            elif self._text_purpose == "rename_profile" and self._selected_profile is not None:
                value = self.store.rename_profile(self._selected_profile.profile_id, name)
                self._selected_profile = profile_snapshot(value) if value is not None else ProfileSnapshot(self._selected_profile.profile_id, name, False, self._selected_profile.raw)
                self._load_profiles()
                self._show_teacher_profile(self._selected_profile)
            elif self._text_purpose == "create_plan":
                self._plan_draft_name = name
                self._plan_draft_lessons = []
                self._plan_draft_question_count = self.default_question_count
                self._plan_draft_repetitions = 1
                self._plan_draft_mastery_gate = False
                self._editing_plan_id = None
                self._lesson_domain_filter = "all"
                self._lesson_family_filter = "all"
                self._lesson_pages.page_index = 0
                self._show_lesson_selector()
        except Exception:
            self._show_error("That change could not be saved.", self._return_from_text)

    def _confirm_archive_profile(self) -> None:
        profile = self._selected_profile
        if profile is None:
            return
        self._ask_confirmation(
            "ARCHIVE LEARNER?",
            f"Archive {profile.display_name}? Their records are kept locally.",
            "ARCHIVE",
            self._archive_profile,
            lambda: self._show_teacher_profile(profile),
        )

    def _archive_profile(self) -> None:
        profile = self._selected_profile
        if profile is None:
            return
        try:
            self._invoke(self.store.archive_profile, profile.profile_id, confirmed=True, confirm=True)
            self._selected_profile = None
            self._show_teacher_profiles()
        except Exception:
            self._show_error("The learner could not be archived.", self._show_teacher_profiles)

    def _confirm_reset_profile(self) -> None:
        profile = self._selected_profile
        if profile is None:
            return
        self._ask_confirmation(
            "RESET PROGRESS?",
            f"Reset all saved learning progress for {profile.display_name}? This cannot be undone.",
            "RESET",
            lambda: self._reset_progress(profile.profile_id),
            lambda: self._show_teacher_profile(profile),
        )

    def _reset_progress(self, profile_id: str, plan_id: str | None = None) -> None:
        try:
            self._invoke(self.store.reset_progress, profile_id, plan_id=plan_id, confirmed=True, confirm=True)
            if plan_id and self._selected_plan:
                self._show_teacher_plan(self._selected_plan)
            elif self._selected_profile:
                self._show_teacher_profile(self._selected_profile)
            else:
                self._show_teacher_home()
        except Exception:
            self._show_error("Progress could not be reset.", self._show_teacher_home)

    def _teacher_plans_entry(self) -> None:
        if self._selected_profile is not None:
            self._load_plans()
            self._show_teacher_plans()
        else:
            self._show_teacher_profiles()

    def _show_teacher_plans(self) -> None:
        profile = self._selected_profile
        if profile is None:
            self._show_teacher_profiles()
            return
        self._load_plans()
        self.screen = LearningScreen.TEACHER_PLANS
        self._clear()
        self._header(f"PLANS FOR {profile.display_name.upper()}")
        for index, plan in enumerate(self._teacher_pages.current(self._plans)):
            top = 88 + index * 94
            state = "ON" if plan.enabled else "OFF"
            self._button(Rect(55, top, 590, top + 75), f"{plan.name}   {len(plan.lesson_ids)} LESSONS   {state}", lambda selected=plan: self._show_teacher_plan(selected), color=self.TEAL if plan.enabled else self.DISABLED, font_size=13)
        self._button(Rect(614, 98, 776, 178), "NEW PLAN", self._new_plan, color=self.GREEN, font_size=12)
        self._button(Rect(614, 200, 776, 280), "BACK", lambda: self._show_teacher_profile(profile), color=self.NAVY, font_size=12)
        if self._teacher_pages.page_count > 1:
            self._page_buttons(self._teacher_pages, self._show_teacher_plans)

    def _new_plan(self) -> None:
        self._begin_text_entry("NEW PLAN NAME", "create_plan", "", LearningScreen.TEACHER_PLANS)

    def _show_teacher_plan(self, plan: PlanSnapshot) -> None:
        self._selected_plan = plan
        self.screen = LearningScreen.TEACHER_PLAN
        self._clear()
        self._header("PLAN SETTINGS")
        assert self.canvas is not None
        self.canvas.create_text(400, 96, text=plan.name, fill=self.INK, font=self._font(23, bold=True))
        self.canvas.create_text(
            400,
            126,
            text=(
                f"{len(plan.lesson_ids)} lessons  |  "
                f"{plan.question_count} questions  |  "
                f"{plan.repetitions} practice round{'s' if plan.repetitions != 1 else ''}  |  "
                f"Mastery {'ON' if plan.mastery_gate else 'OFF'}"
            ),
            fill=self.MUTED,
            font=self._font(9, bold=True),
        )
        actions = (
            (Rect(45, 157, 225, 232), "EDIT & REORDER", self._edit_plan, self.BLUE),
            (Rect(235, 157, 415, 232), "DUPLICATE", self._duplicate_plan, self.TEAL),
            (Rect(425, 157, 605, 232), "TURN OFF" if plan.enabled else "TURN ON", self._toggle_plan, self.YELLOW),
            (Rect(615, 157, 785, 232), "ARCHIVE", self._confirm_archive_plan, self.RED),
            (Rect(95, 269, 305, 348), "REPORT", self._show_plan_stats, self.YELLOW),
            (Rect(320, 269, 530, 348), "RESET PROGRESS", self._confirm_reset_plan, self.CORAL),
            (Rect(545, 269, 755, 348), "BACK", self._show_teacher_plans, self.NAVY),
        )
        for bounds, label, callback, color in actions:
            self._button(bounds, label, callback, color=color, font_size=10)

    def _edit_plan(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        self._editing_plan_id = plan.plan_id
        self._plan_draft_name = plan.name
        self._plan_draft_lessons = list(plan.lesson_ids)
        self._plan_draft_question_count = plan.question_count
        self._plan_draft_repetitions = plan.repetitions
        self._plan_draft_mastery_gate = plan.mastery_gate
        self._lesson_pages.page_index = 0
        self._show_plan_editor()

    def _show_plan_editor(self) -> None:
        self.screen = LearningScreen.TEACHER_PLAN_EDIT
        self._clear()
        self._header("ORDER LESSONS")
        assert self.canvas is not None
        self.canvas.create_text(195, 90, text=self._plan_draft_name, fill=self.INK, width=260, font=self._font(15, bold=True))
        self._button(
            Rect(365, 70, 421, 116),
            "-",
            lambda: self._adjust_plan_questions(-1),
            color=self.BLUE,
            enabled=self._plan_draft_question_count > 3,
            font_size=18,
        )
        self.canvas.create_text(
            467,
            84,
            text=str(self._plan_draft_question_count),
            fill=self.INK,
            font=self._font(15, bold=True),
        )
        self.canvas.create_text(
            467,
            105,
            text="QUESTIONS",
            fill=self.MUTED,
            font=self._font(7, bold=True),
        )
        self._button(
            Rect(513, 70, 569, 116),
            "+",
            lambda: self._adjust_plan_questions(1),
            color=self.BLUE,
            enabled=self._plan_draft_question_count < 20,
            font_size=18,
        )
        self._button(
            Rect(584, 70, 630, 116),
            "-",
            lambda: self._adjust_plan_repetitions(-1),
            color=self.TEAL,
            enabled=self._plan_draft_repetitions > 1,
            font_size=16,
        )
        self.canvas.create_text(
            665,
            84,
            text=str(self._plan_draft_repetitions),
            fill=self.INK,
            font=self._font(15, bold=True),
        )
        self.canvas.create_text(
            665,
            105,
            text="ROUNDS",
            fill=self.MUTED,
            font=self._font(7, bold=True),
        )
        self._button(
            Rect(700, 70, 746, 116),
            "+",
            lambda: self._adjust_plan_repetitions(1),
            color=self.TEAL,
            enabled=self._plan_draft_repetitions < 10,
            font_size=16,
        )
        self._button(
            Rect(750, 70, 792, 116),
            "GATE\nON" if self._plan_draft_mastery_gate else "GATE\nOFF",
            self._toggle_draft_mastery,
            color=self.GREEN if self._plan_draft_mastery_gate else self.DISABLED,
            font_size=6,
        )
        lesson_by_id = {lesson.lesson_id: lesson for lesson in self._lessons}
        self._lesson_pages.set_count(len(self._plan_draft_lessons))
        visible = self._lesson_pages.current(self._plan_draft_lessons)
        start = self._lesson_pages.page_index * self._lesson_pages.page_size
        for row, lesson_id in enumerate(visible):
            index = start + row
            lesson = lesson_by_id.get(lesson_id)
            title = lesson.title if lesson else lesson_id
            top = 126 + row * 64
            assert self.canvas is not None
            self.canvas.create_rectangle(44, top, 610, top + 55, fill=self.WHITE, outline="#9ABBC7", width=2)
            self.canvas.create_text(60, top + 27, anchor="w", text=f"{index + 1}. {title}", fill=self.INK, width=430, font=self._font(10, bold=True))
            self._button(Rect(620, top, 690, top + 55), "UP", lambda item=index: self._move_lesson(item, -1), color=self.BLUE, enabled=index > 0, font_size=8)
            self._button(Rect(700, top, 770, top + 55), "DOWN", lambda item=index: self._move_lesson(item, 1), color=self.BLUE, enabled=index < len(self._plan_draft_lessons) - 1, font_size=7)
        self._button(Rect(44, 400, 232, 466), "CHOOSE LESSONS", self._show_lesson_selector, color=self.TEAL, font_size=10)
        self._button(Rect(306, 400, 494, 466), "SAVE ORDER", self._save_plan_lessons, color=self.GREEN, enabled=bool(self._plan_draft_lessons), font_size=10)
        self._button(Rect(568, 400, 756, 466), "CANCEL", lambda: self._show_teacher_plan(self._selected_plan) if self._selected_plan else self._show_teacher_plans(), color=self.NAVY, font_size=11)

    def _adjust_plan_questions(self, offset: int) -> None:
        self._plan_draft_question_count = max(
            3,
            min(20, self._plan_draft_question_count + int(offset)),
        )
        self._show_plan_editor()

    def _toggle_draft_mastery(self) -> None:
        self._plan_draft_mastery_gate = not self._plan_draft_mastery_gate
        self._show_plan_editor()

    def _adjust_plan_repetitions(self, offset: int) -> None:
        self._plan_draft_repetitions = max(
            1,
            min(10, self._plan_draft_repetitions + int(offset)),
        )
        self._show_plan_editor()

    def _move_lesson(self, index: int, offset: int) -> None:
        self._plan_draft_lessons[:] = reorder_item(self._plan_draft_lessons, index, offset)
        destination = max(0, min(len(self._plan_draft_lessons) - 1, index + offset))
        self._lesson_pages.page_index = destination // self._lesson_pages.page_size
        self._show_plan_editor()

    def _show_lesson_selector(self) -> None:
        self.screen = LearningScreen.TEACHER_LESSONS
        self._clear()
        self._header("CHOOSE LESSONS")
        assert self.canvas is not None
        domains = ("all", *lesson_filter_domains(self._lessons))
        if self._lesson_domain_filter not in domains:
            self._lesson_domain_filter = "all"
        families = (
            "all",
            *lesson_filter_families(self._lessons, self._lesson_domain_filter),
        )
        if self._lesson_family_filter not in families:
            self._lesson_family_filter = "all"
        filtered = filter_lessons(
            self._lessons,
            domain=self._lesson_domain_filter,
            family=self._lesson_family_filter,
        )
        self._lesson_pages.set_count(len(filtered))
        self._button(
            Rect(48, 72, 232, 116),
            f"DOMAIN: {self._lesson_domain_filter.upper()}",
            self._cycle_lesson_domain,
            color=self.NAVY,
            font_size=8,
        )
        self._button(
            Rect(244, 72, 476, 116),
            f"FAMILY: {self._lesson_family_filter.replace('_', ' ').upper()}",
            self._cycle_lesson_family,
            color=self.NAVY,
            font_size=8,
        )
        self._button(
            Rect(488, 72, 752, 116),
            f"ADD THESE {len(filtered)}",
            lambda: self._bulk_add_lessons(filtered),
            color=self.GREEN,
            enabled=bool(filtered),
            font_size=8,
        )
        visible = self._lesson_pages.current(filtered)
        for index, lesson in enumerate(visible):
            top = 124 + index * 64
            selected = lesson.lesson_id in self._plan_draft_lessons
            label = f"{'ADDED' if selected else 'ADD'}  |  {lesson.domain}: {lesson.title}"
            self._button(Rect(54, top, 746, top + 52), label, lambda item=lesson: self._toggle_lesson(item), color=self.GREEN if selected else self.BLUE, font_size=9)
        self._button(Rect(260, 400, 540, 466), "DONE", self._finish_lesson_selection, color=self.TEAL, font_size=14)
        if self._lesson_pages.page_count > 1:
            self._button(Rect(12, 400, 96, 466), "PREV", lambda: self._turn_page(self._lesson_pages, -1, self._show_lesson_selector), color=self.NAVY, enabled=self._lesson_pages.page_index > 0, font_size=9)
            self._button(Rect(704, 400, 788, 466), "NEXT", lambda: self._turn_page(self._lesson_pages, 1, self._show_lesson_selector), color=self.NAVY, enabled=self._lesson_pages.page_index < self._lesson_pages.page_count - 1, font_size=9)

    def _cycle_lesson_domain(self) -> None:
        values = ("all", *lesson_filter_domains(self._lessons))
        index = values.index(self._lesson_domain_filter)
        self._lesson_domain_filter = values[(index + 1) % len(values)]
        self._lesson_family_filter = "all"
        self._lesson_pages.page_index = 0
        self._show_lesson_selector()

    def _cycle_lesson_family(self) -> None:
        values = (
            "all",
            *lesson_filter_families(self._lessons, self._lesson_domain_filter),
        )
        index = values.index(self._lesson_family_filter)
        self._lesson_family_filter = values[(index + 1) % len(values)]
        self._lesson_pages.page_index = 0
        self._show_lesson_selector()

    def _bulk_add_lessons(self, lessons: Iterable[LessonSnapshot]) -> None:
        proposed = tuple(lessons)
        missing = bulk_missing_prerequisites(
            proposed,
            self._plan_draft_lessons,
        )
        lesson_ids = tuple(lesson.lesson_id for lesson in proposed)
        if missing:
            titles = {item.lesson_id: item.title for item in self._lessons}
            summary = ", ".join(titles.get(item, item) for item in missing[:3])
            self._ask_confirmation(
                "FOUNDATION WARNING",
                f"This group recommends first: {summary}. Add the group anyway?",
                "ADD ANYWAY",
                lambda: self._complete_bulk_add(lesson_ids),
                self._show_lesson_selector,
            )
            return
        self._complete_bulk_add(lesson_ids)

    def _complete_bulk_add(self, lesson_ids: Iterable[str]) -> None:
        for lesson_id in lesson_ids:
            if lesson_id not in self._plan_draft_lessons:
                self._plan_draft_lessons.append(lesson_id)
        self._show_lesson_selector()

    def _toggle_lesson(self, lesson: LessonSnapshot) -> None:
        if lesson.lesson_id in self._plan_draft_lessons:
            self._plan_draft_lessons.remove(lesson.lesson_id)
            self._show_lesson_selector()
            return
        missing = missing_prerequisites(lesson.lesson_id, self._plan_draft_lessons, self._lessons)
        if missing:
            titles = {item.lesson_id: item.title for item in self._lessons}
            summary = ", ".join(titles.get(item, item) for item in missing[:3])
            self._ask_confirmation(
                "FOUNDATION WARNING",
                f"Recommended first: {summary}. Add this lesson anyway?",
                "ADD ANYWAY",
                lambda: self._add_lesson(lesson.lesson_id),
                self._show_lesson_selector,
            )
        else:
            self._add_lesson(lesson.lesson_id)

    def _add_lesson(self, lesson_id: str) -> None:
        if lesson_id not in self._plan_draft_lessons:
            self._plan_draft_lessons.append(lesson_id)
        self._show_lesson_selector()

    def _finish_lesson_selection(self) -> None:
        if self._editing_plan_id is None:
            self._save_new_plan()
        else:
            self._show_plan_editor()

    def _save_new_plan(self) -> None:
        profile = self._selected_profile
        if profile is None or not self._plan_draft_lessons:
            self._show_error("Choose at least one lesson for this plan.", self._show_lesson_selector)
            return
        try:
            self._invoke(
                self.store.create_plan,
                profile.profile_id,
                self._plan_draft_name,
                tuple(self._plan_draft_lessons),
                question_count=self._plan_draft_question_count,
                questions_per_session=self._plan_draft_question_count,
                session_size=self._plan_draft_question_count,
                repetitions=self._plan_draft_repetitions,
                mastery_gate=self._plan_draft_mastery_gate,
            )
            self._load_plans()
            self._show_teacher_plans()
        except Exception:
            self._show_error("The learning plan could not be created.", self._show_lesson_selector)

    def _save_plan_lessons(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        try:
            updated = self.store.reorder_plan_lessons(plan.plan_id, tuple(self._plan_draft_lessons))
            if (
                self._plan_draft_question_count != plan.question_count
                or self._plan_draft_repetitions != plan.repetitions
                or self._plan_draft_mastery_gate != plan.mastery_gate
            ):
                raw = updated if updated is not None else plan.raw
                if is_dataclass(raw):
                    field_names = getattr(raw, "__dataclass_fields__", {})
                    changes: dict[str, Any] = {
                        "repetitions": self._plan_draft_repetitions,
                        "mastery_gate": self._plan_draft_mastery_gate,
                    }
                    if "questions_per_session" in field_names:
                        changes["questions_per_session"] = self._plan_draft_question_count
                    elif "question_count" in field_names:
                        changes["question_count"] = self._plan_draft_question_count
                    raw = replace(raw, **changes)
                elif isinstance(raw, Mapping):
                    count_key = (
                        "questions_per_session"
                        if "questions_per_session" in raw
                        else "question_count"
                    )
                    raw = {
                        **raw,
                        count_key: self._plan_draft_question_count,
                        "repetitions": self._plan_draft_repetitions,
                        "mastery_gate": self._plan_draft_mastery_gate,
                    }
                updated = self.store.update_plan(raw)
            self._load_plans()
            selected = next((item for item in self._plans if item.plan_id == plan.plan_id), None)
            if selected is None and updated is not None:
                selected = plan_snapshot(updated, default_questions=self.default_question_count)
            self._show_teacher_plan(selected or plan)
        except Exception:
            self._show_error("The lesson order could not be saved.", self._show_plan_editor)

    def _duplicate_plan(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        try:
            self._invoke(self.store.duplicate_plan, plan.plan_id, name=f"{plan.name} Copy")
            self._load_plans()
            self._show_teacher_plans()
        except Exception:
            self._show_error("The plan could not be duplicated.", lambda: self._show_teacher_plan(plan))

    def _toggle_plan(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        try:
            method = getattr(self.store, "set_plan_enabled", None)
            if callable(method):
                updated = self._invoke(method, plan.plan_id, not plan.enabled)
            else:
                raw = plan.raw
                if is_dataclass(raw):
                    raw = replace(raw, enabled=not plan.enabled)
                elif isinstance(raw, Mapping):
                    raw = {**raw, "enabled": not plan.enabled}
                else:
                    raise TypeError("Plan records cannot be updated")
                updated = self.store.update_plan(raw)
            selected = (
                plan_snapshot(updated, default_questions=self.default_question_count)
                if updated is not None
                else PlanSnapshot(
                    plan_id=plan.plan_id,
                    profile_id=plan.profile_id,
                    name=plan.name,
                    lesson_ids=plan.lesson_ids,
                    enabled=not plan.enabled,
                    question_count=plan.question_count,
                    repetitions=plan.repetitions,
                    mastery_gate=plan.mastery_gate,
                    archived=plan.archived,
                    raw=plan.raw,
                )
            )
            self._load_plans()
            self._show_teacher_plan(selected)
        except Exception:
            self._show_error("The plan setting could not be changed.", lambda: self._show_teacher_plan(plan))

    def _confirm_archive_plan(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        self._ask_confirmation("ARCHIVE PLAN?", f"Archive {plan.name}? Learning history is kept.", "ARCHIVE", self._archive_plan, lambda: self._show_teacher_plan(plan))

    def _archive_plan(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        try:
            self._invoke(self.store.archive_plan, plan.plan_id, confirmed=True, confirm=True)
            self._selected_plan = None
            self._load_plans()
            self._show_teacher_plans()
        except Exception:
            self._show_error("The plan could not be archived.", self._show_teacher_plans)

    def _confirm_reset_plan(self) -> None:
        plan = self._selected_plan
        profile = self._selected_profile
        if plan is None or profile is None:
            return
        self._ask_confirmation("RESET THIS PLAN?", f"Reset only the saved progress for {plan.name}?", "RESET PLAN", lambda: self._reset_progress(profile.profile_id, plan.plan_id), lambda: self._show_teacher_plan(plan))

    def _teacher_stats_entry(self) -> None:
        if self._selected_profile is not None:
            self._show_profile_stats()
        else:
            self._show_teacher_profiles()

    def _show_profile_stats(self) -> None:
        profile = self._selected_profile
        if profile is None:
            self._show_teacher_profiles()
            return
        method = getattr(self.store, "profile_stats", None)
        try:
            self._stats = method(profile.profile_id) if callable(method) else {}
        except Exception:
            self._show_error("The progress report could not be read.", lambda: self._show_teacher_profile(profile))
            return
        self.previous_screen = LearningScreen.TEACHER_PROFILE
        self._mastery_pages.page_index = 0
        self._draw_stats(f"PROGRESS: {profile.display_name.upper()}")

    def _show_plan_stats(self) -> None:
        plan = self._selected_plan
        if plan is None:
            return
        method = getattr(self.store, "plan_stats", None)
        try:
            self._stats = method(plan.plan_id) if callable(method) else {}
        except Exception:
            self._show_error("The plan report could not be read.", lambda: self._show_teacher_plan(plan))
            return
        self.previous_screen = LearningScreen.TEACHER_PLAN
        self._mastery_pages.page_index = 0
        self._draw_stats(f"REPORT: {plan.name.upper()}")

    def _draw_stats(self, title: str) -> None:
        self.screen = LearningScreen.TEACHER_STATS
        self._clear()
        self._header(title)
        assert self.canvas is not None
        stats = self._stats or {}
        metrics = teacher_report_metrics(stats)
        for index, (label, value) in enumerate(metrics):
            if index < 4:
                row, column = divmod(index, 4)
                left = 24 + column * 194
                top = 82 + row * 82
                width = 178
            else:
                row, column = divmod(index - 4, 3)
                left = 35 + column * 252
                top = 174 + row * 82
                width = 226
            self.canvas.create_rectangle(left, top, left + width, top + 70, fill=self.WHITE, outline="#91B7C7", width=3)
            self.canvas.create_text(left + width // 2, top + 19, text=label, fill=self.MUTED, font=self._font(8, bold=True))
            self.canvas.create_text(left + width // 2, top + 48, text=value, fill=self.INK, font=self._font(18, bold=True))
        mastery = _field(stats, "mastery", "skills", "domains", default=()) or ()
        if isinstance(mastery, Mapping):
            mastery = tuple(mastery.items())
        mastery = tuple(mastery)
        self._mastery_pages.set_count(len(mastery))
        page_label = (
            f"  {self._mastery_pages.page_index + 1}/{self._mastery_pages.page_count}"
            if self._mastery_pages.page_count > 1
            else ""
        )
        self.canvas.create_text(400, 267, text=f"SKILL STATUS{page_label}", fill=self.INK, font=self._font(12, bold=True))
        for index, item in enumerate(self._mastery_pages.current(mastery)):
            if isinstance(item, tuple) and len(item) == 2:
                label, value = item
            else:
                label = _field(item, "skill", "domain", "name", default="Skill")
                value = _field(item, "status", "mastery", default="not started")
            self.canvas.create_text(160, 294 + index * 28, anchor="w", text=str(label), fill=self.INK, width=290, font=self._font(10, bold=True))
            self.canvas.create_text(640, 294 + index * 28, anchor="e", text=str(value).replace("_", " ").upper(), fill=self.TEAL, width=250, font=self._font(10, bold=True))
        self._button(Rect(290, 410, 510, 468), "BACK", self._return_from_stats, color=self.NAVY, font_size=12)
        if self._mastery_pages.page_count > 1:
            self._button(
                Rect(75, 410, 245, 468),
                "PREV",
                lambda: self._turn_page(
                    self._mastery_pages,
                    -1,
                    lambda: self._draw_stats(title),
                ),
                color=self.NAVY,
                enabled=self._mastery_pages.page_index > 0,
                font_size=10,
            )
            self._button(
                Rect(555, 410, 725, 468),
                "NEXT",
                lambda: self._turn_page(
                    self._mastery_pages,
                    1,
                    lambda: self._draw_stats(title),
                ),
                color=self.NAVY,
                enabled=self._mastery_pages.page_index < self._mastery_pages.page_count - 1,
                font_size=10,
            )

    def _return_from_stats(self) -> None:
        if self.previous_screen is LearningScreen.TEACHER_PLAN and self._selected_plan:
            self._show_teacher_plan(self._selected_plan)
        elif self._selected_profile:
            self._show_teacher_profile(self._selected_profile)
        else:
            self._show_teacher_home()

    def _ask_confirmation(
        self,
        title: str,
        message: str,
        confirm_label: str,
        confirm: Callable[[], None],
        cancel: Callable[[], None],
    ) -> None:
        self._confirmation = PendingConfirmation(title, message, confirm_label, confirm, cancel)
        self.screen = LearningScreen.CONFIRM
        self._clear()
        self._header(title)
        assert self.canvas is not None
        self.canvas.create_rectangle(100, 108, 700, 344, fill=self.WHITE, outline=self.CORAL, width=4)
        self.canvas.create_text(400, 200, text=message, fill=self.INK, width=520, font=self._font(17, bold=True), justify=tk.CENTER)
        self._button(Rect(110, 375, 375, 457), "CANCEL", cancel, color=self.NAVY, font_size=14)
        self._button(Rect(425, 375, 690, 457), confirm_label, confirm, color=self.RED, font_size=14)

    def _show_error(self, message: str, return_callback: Callable[[], None]) -> None:
        self.screen = LearningScreen.ERROR
        self._clear()
        self._header("LEARNING NEEDS A MOMENT")
        assert self.canvas is not None
        self._draw_empty_character(400, 210)
        self.canvas.create_text(400, 319, text=message, fill=self.RED, width=620, font=self._font(16, bold=True), justify=tk.CENTER)
        self._button(Rect(270, 381, 530, 459), "GO BACK", return_callback, color=self.NAVY, font_size=15)

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> str | None:
        if self.closed:
            return None
        after_id: str | None = None

        def run() -> None:
            if after_id is not None:
                self._after_ids.discard(after_id)
            if not self.closed:
                callback()

        after_id = self.root.after(delay_ms, run)
        self._after_ids.add(after_id)
        return after_id

    def _refresh_face(self) -> None:
        if self.closed or self.canvas is None:
            return
        if self._face_after_id is not None:
            self._after_ids.discard(self._face_after_id)
        try:
            self.canvas.lift()
        except tk.TclError:
            pass
        if self._face_item is not None:
            try:
                face = self.face_provider()
                if face is not None:
                    resized = face.convert("RGB").resize(
                        (108, 48),
                        Image.Resampling.LANCZOS,
                    )
                    self._face_image = ImageTk.PhotoImage(resized)
                    self.canvas.itemconfigure(self._face_item, image=self._face_image)
                    for item in self._fallback_items:
                        self.canvas.itemconfigure(item, state=tk.HIDDEN)
            except Exception:
                pass
        self._face_after_id = self.root.after(FACE_REFRESH_MS, self._refresh_face)
        self._after_ids.add(self._face_after_id)

    def _handle_press(self, event: tk.Event) -> str:
        if not self._input_locked:
            self.touch.press((int(event.x), int(event.y)))
        return "break"

    def _handle_motion(self, event: tk.Event) -> str:
        del event
        return "break"

    def _handle_release(self, event: tk.Event) -> str:
        if self._input_locked:
            self.touch.cancel()
            return "break"
        point = self.touch.release((int(event.x), int(event.y)))
        if point is None:
            return "break"
        key = hit_test(self._regions, point)
        if key is not None:
            callback = self._callbacks.get(key)
            if callback is not None:
                callback()
        return "break"

    def _dispose(self, *, notify: bool) -> None:
        if self.closed:
            return
        self.closed = True
        pin = getattr(self, "_pin", None)
        if pin is not None:
            pin.clear()
        try:
            self.cancel_announcements()
        except Exception:
            pass
        for after_id in tuple(self._after_ids):
            try:
                self.root.after_cancel(after_id)
            except (tk.TclError, ValueError):
                pass
        self._after_ids.clear()
        self._face_after_id = None
        canvas = self.canvas
        self.canvas = None
        if canvas is not None:
            try:
                canvas.destroy()
            except tk.TclError:
                pass
        if notify:
            self.on_close()

    def close(self) -> None:
        """Cancel every Learning-owned callback/speech and reveal the same menu."""
        self._dispose(notify=True)


__all__ = [
    "ChoiceSnapshot",
    "EvaluationSnapshot",
    "HitRegion",
    "InteractionController",
    "LearningApp",
    "LearningScreen",
    "LessonSnapshot",
    "MAX_QUESTION_ATTEMPTS",
    "PageCursor",
    "PinEntry",
    "PlanSnapshot",
    "Point",
    "ProfileSnapshot",
    "QuestionSnapshot",
    "Rect",
    "SelectionResult",
    "TextEntry",
    "TouchTracker",
    "WINDOW_HEIGHT",
    "WINDOW_WIDTH",
    "bulk_missing_prerequisites",
    "choice_snapshot",
    "contrast_ratio",
    "evaluation_snapshot",
    "filter_lessons",
    "format_percent",
    "hit_test",
    "lesson_family",
    "lesson_filter_domains",
    "lesson_filter_families",
    "lesson_snapshot",
    "missing_prerequisites",
    "plan_snapshot",
    "profile_snapshot",
    "question_snapshot",
    "reorder_item",
    "safe_choice_text_color",
    "teacher_report_metrics",
]
