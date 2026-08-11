"""Indexed, dataset-backed Twenty Questions game.

The base catalog is deliberately kept outside the Python package.  It is
loaded lazily, validated as a complete JSONL file, and never written to.  A
small JSONL overlay stores only answers learned after the player confirms or
reveals the target object.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OBJECT_NAME_KEY = "What object is it?"
BASE_DATA_PATH = PROJECT_ROOT / "data" / "20_questions" / "data.jsonl"
LEARNED_DATA_PATH = PROJECT_ROOT / "data" / "20_questions" / "learned.jsonl"
# These aliases make the paths easy to discover for callers and tests.
DATA_PATH = BASE_DATA_PATH
LEARNED_PATH = LEARNED_DATA_PATH

PLAYER_ANSWERS = ("yes", "no", "sometimes", "unknown")
DATASET_ANSWERS = frozenset({"yes", "no", "sometimes", "often"})
LEARNED_ANSWERS = frozenset((*DATASET_ANSWERS, "unknown"))
DISPLAY_ANSWERS = {
    "yes": "Yes",
    "no": "No",
    "sometimes": "Sometimes",
    "often": "Often",
    "unknown": "Unknown",
}
INTRODUCTION = (
    "Think of something and I’ll try to guess it. Answer yes, no, "
    "sometimes, or I don’t know."
)
ANSWER_PROMPT = "Please answer yes, no, sometimes, or I don't know."
REVEAL_PROMPT = "You stumped me. What were you thinking of?"
LLM_GUESS_REQUEST = "__TWENTY_QUESTIONS_LLM_GUESS_REQUEST__"
BONUS_INTRODUCTION = (
    "You win! You made it through 20 questions. Let's play a bonus round."
)


class TwentyQuestionsDataError(ValueError):
    """A base or learned catalog failed validation."""


class LearningPersistenceError(OSError):
    """The learned overlay could not be atomically persisted."""


def canonical_object_name(name: str) -> str:
    """Normalize an object name for case-insensitive overlay matching."""
    return " ".join(str(name).strip().split()).casefold()


def clean_display_name(name: str) -> str:
    """Collapse whitespace while retaining the speaker's display spelling."""
    return " ".join(str(name).strip().split())


def normalize_dataset_answer(value: object, *, learned: bool = False) -> str:
    """Normalize one dataset value and reject labels outside its contract."""
    if not isinstance(value, str):
        raise TwentyQuestionsDataError("answer values must be strings")
    normalized = " ".join(value.strip().casefold().split())
    allowed = LEARNED_ANSWERS if learned else DATASET_ANSWERS
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise TwentyQuestionsDataError(
            f"answer label must be one of {allowed_text}"
        )
    return normalized


@dataclass(frozen=True)
class DatasetRow:
    """One normalized wide row, aligned to a catalog's question ordering."""

    name: str
    answers: tuple[str, ...]

    def answer_for(self, question_index: int) -> str:
        return self.answers[question_index]


@dataclass(frozen=True)
class DatasetCatalog:
    """Immutable effective catalog used by a game and its index."""

    question_keys: tuple[str, ...]
    rows: tuple[DatasetRow, ...]
    base_rows: tuple[DatasetRow, ...] = ()
    learned_rows: tuple[DatasetRow, ...] = ()
    learning_enabled: bool = True

    @property
    def object_count(self) -> int:
        return len(self.rows)

    @property
    def question_count(self) -> int:
        return len(self.question_keys)

    @property
    def questions(self) -> tuple[str, ...]:
        """Readable alias for the ordered question-key tuple."""
        return self.question_keys

    @property
    def object_names(self) -> tuple[str, ...]:
        return tuple(row.name for row in self.rows)

    def row_by_name(self, name: str) -> DatasetRow | None:
        wanted = canonical_object_name(name)
        return next(
            (row for row in self.rows if canonical_object_name(row.name) == wanted),
            None,
        )


# A more explicit name is useful to integrations without making the internal
# effective/base distinction part of the mode contract.
BaseCatalog = DatasetCatalog


@dataclass(frozen=True)
class LearningOutcome:
    """Result of one confirmed/revealed target learning operation."""

    changed: bool
    persisted: bool
    learning_enabled: bool
    error: str | None = None


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently losing a value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TwentyQuestionsDataError("duplicate JSON key")
        result[key] = value
    return result


class TwentyQuestionsDatasetLoader:
    """Validate the base JSONL catalog and manage its learned overlay."""

    def __init__(
        self,
        base_path: Path | str = BASE_DATA_PATH,
        learned_path: Path | str = LEARNED_DATA_PATH,
        *,
        reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.base_path = Path(base_path)
        self.learned_path = Path(learned_path)
        if self.base_path.resolve() == self.learned_path.resolve():
            raise TwentyQuestionsDataError(
                "base and learned paths must be different files"
            )
        self.reporter = reporter or (lambda message: print(message, flush=True))
        self._base_catalog: DatasetCatalog | None = None
        self._learned_rows: dict[str, DatasetRow] | None = None
        self._learning_enabled = True
        self.diagnostics: list[str] = []

    @property
    def base_catalog(self) -> DatasetCatalog | None:
        return self._base_catalog

    @property
    def learning_enabled(self) -> bool:
        return self._learning_enabled

    def load_base(self) -> DatasetCatalog:
        """Load and validate the immutable base catalog once per loader."""
        if self._base_catalog is not None:
            return self._base_catalog
        path = self.base_path
        if not path.exists():
            raise TwentyQuestionsDataError(
                f"base dataset is unavailable: {path.name} is missing"
            )
        if not path.is_file():
            raise TwentyQuestionsDataError(
                f"base dataset is unavailable: {path.name} is not a file"
            )

        rows: list[DatasetRow] = []
        question_keys: tuple[str, ...] | None = None
        seen_names: set[str] = set()
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    if not raw_line.strip():
                        continue
                    raw = self._parse_line(raw_line, line_number, "base")
                    if OBJECT_NAME_KEY not in raw:
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} is missing the object-name field"
                        )
                    raw_name = raw[OBJECT_NAME_KEY]
                    if not isinstance(raw_name, str):
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} object name must be a string"
                        )
                    name = clean_display_name(raw_name)
                    canonical = canonical_object_name(name)
                    if not canonical:
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} has an empty object name"
                        )
                    if canonical in seen_names:
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} duplicates an object name"
                        )

                    row_questions = tuple(
                        key for key in raw if key != OBJECT_NAME_KEY
                    )
                    if question_keys is None:
                        if not row_questions:
                            raise TwentyQuestionsDataError(
                                f"base row {line_number} has no questions"
                            )
                        question_keys = row_questions
                    elif set(row_questions) != set(question_keys):
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} has a mismatched question set"
                        )

                    try:
                        answers = tuple(
                            normalize_dataset_answer(raw[key])
                            for key in question_keys
                        )
                    except TwentyQuestionsDataError as exc:
                        raise TwentyQuestionsDataError(
                            f"base row {line_number} has an invalid answer"
                        ) from exc
                    seen_names.add(canonical)
                    rows.append(DatasetRow(name, answers))
        except (OSError, UnicodeError) as exc:
            raise TwentyQuestionsDataError(
                f"base dataset could not be read: {type(exc).__name__}"
            ) from exc

        if not rows or question_keys is None:
            raise TwentyQuestionsDataError("base dataset contains no rows")
        self._base_catalog = DatasetCatalog(
            question_keys=question_keys,
            rows=tuple(rows),
        )
        return self._base_catalog

    def load(self) -> DatasetCatalog:
        """Return the base catalog with a validated learned overlay applied."""
        base = self.load_base()
        learned = self._load_learned(base.question_keys)
        learned_by_name = dict(learned)
        effective: list[DatasetRow] = []
        base_names: set[str] = set()
        for base_row in base.rows:
            canonical = canonical_object_name(base_row.name)
            base_names.add(canonical)
            learned_row = learned_by_name.get(canonical)
            if learned_row is None:
                effective.append(base_row)
                continue
            answers = tuple(
                self._effective_answer(base_answer, learned_answer)
                for base_answer, learned_answer in zip(
                    base_row.answers,
                    learned_row.answers,
                    strict=True,
                )
            )
            effective.append(DatasetRow(base_row.name, answers))

        for canonical, learned_row in learned.items():
            if canonical not in base_names:
                effective.append(learned_row)

        return DatasetCatalog(
            question_keys=base.question_keys,
            rows=tuple(effective),
            base_rows=base.rows,
            learned_rows=tuple(learned.values()),
            learning_enabled=self._learning_enabled,
        )

    load_catalog = load

    def learn(
        self,
        target_name: str,
        observations: Iterable[tuple[str, str]],
    ) -> LearningOutcome:
        """Merge confirmed observations and atomically persist if changed."""
        base = self.load_base()
        if not self._learning_enabled:
            return LearningOutcome(False, False, False, "learning is disabled")
        if self._learned_rows is None:
            self._load_learned(base.question_keys)
        assert self._learned_rows is not None

        display_name = clean_display_name(target_name)
        canonical = canonical_object_name(display_name)
        if not canonical:
            return LearningOutcome(False, False, True, "target name is empty")

        current = dict(self._learned_rows)
        existing = current.get(canonical)
        base_row = next(
            (
                row
                for row in base.rows
                if canonical_object_name(row.name) == canonical
            ),
            None,
        )
        if existing is None:
            if base_row is not None:
                # Do not create an all-Unknown overlay for a base object unless
                # an observation below actually changes something.
                candidate = None
            else:
                candidate = DatasetRow(
                    display_name,
                    tuple("unknown" for _ in base.question_keys),
                )
        else:
            candidate = DatasetRow(existing.name, existing.answers)

        changed = False
        for question_key, raw_answer in observations:
            answer = normalize_player_answer(raw_answer)
            if answer not in {"yes", "no", "sometimes"}:
                continue
            try:
                question_index = base.question_keys.index(question_key)
            except ValueError:
                continue

            base_answer = (
                base_row.answers[question_index]
                if base_row is not None
                else "unknown"
            )
            learned_answer = (
                candidate.answers[question_index]
                if candidate is not None
                else "unknown"
            )
            # A hard answer is authoritative.  A wildcard or Unknown may be
            # refined, but a single contradictory game cannot rewrite a hard
            # base or learned answer.
            if learned_answer in {"yes", "no", "sometimes"}:
                continue
            if base_answer in {"yes", "no", "sometimes"} and learned_answer != "unknown":
                continue
            if base_answer in {"yes", "no", "sometimes"} and existing is None:
                # There is no useful overlay to write when the observation
                # agrees with a known base answer.
                continue
            if candidate is None:
                candidate = DatasetRow(
                    base_row.name if base_row is not None else display_name,
                    tuple("unknown" for _ in base.question_keys),
                )
            if candidate.answers[question_index] != answer:
                values = list(candidate.answers)
                values[question_index] = answer
                candidate = DatasetRow(candidate.name, tuple(values))
                changed = True

        if candidate is not None and base_row is None and existing is None:
            changed = True
        if not changed:
            return LearningOutcome(False, False, True)

        assert candidate is not None
        current[canonical] = candidate
        try:
            self._atomic_write(current, base.question_keys)
        except (OSError, ValueError) as exc:
            diagnostic = (
                f"learned data could not be saved: {type(exc).__name__}"
            )
            self._diagnose(diagnostic)
            return LearningOutcome(True, False, True, diagnostic)
        self._learned_rows = current
        return LearningOutcome(True, True, True)

    def _load_learned(self, question_keys: tuple[str, ...]) -> dict[str, DatasetRow]:
        if self._learned_rows is not None:
            return self._learned_rows
        self._learned_rows = {}
        path = self.learned_path
        if not path.exists():
            return self._learned_rows
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    if not raw_line.strip():
                        continue
                    raw = self._parse_line(raw_line, line_number, "learned")
                    if OBJECT_NAME_KEY not in raw:
                        raise TwentyQuestionsDataError(
                            f"learned row {line_number} is missing the object-name field"
                        )
                    if set(raw) != {OBJECT_NAME_KEY, *question_keys}:
                        raise TwentyQuestionsDataError(
                            f"learned row {line_number} has a mismatched question set"
                        )
                    raw_name = raw[OBJECT_NAME_KEY]
                    if not isinstance(raw_name, str):
                        raise TwentyQuestionsDataError(
                            f"learned row {line_number} object name must be a string"
                        )
                    name = clean_display_name(raw_name)
                    canonical = canonical_object_name(name)
                    if not canonical:
                        raise TwentyQuestionsDataError(
                            f"learned row {line_number} has an empty object name"
                        )
                    try:
                        row = DatasetRow(
                            name,
                            tuple(
                                normalize_dataset_answer(raw[key], learned=True)
                                for key in question_keys
                            ),
                        )
                    except TwentyQuestionsDataError as exc:
                        raise TwentyQuestionsDataError(
                            f"learned row {line_number} has an invalid answer"
                        ) from exc
                    existing = self._learned_rows.get(canonical)
                    self._learned_rows[canonical] = (
                        row if existing is None else self._merge_rows(existing, row)
                    )
        except (
            OSError,
            UnicodeError,
            TwentyQuestionsDataError,
            json.JSONDecodeError,
        ) as exc:
            self._learning_enabled = False
            self._learned_rows = {}
            self._diagnose(
                f"learned data ignored for this session: {type(exc).__name__}"
            )
        return self._learned_rows

    @staticmethod
    def _merge_rows(first: DatasetRow, second: DatasetRow) -> DatasetRow:
        values = list(first.answers)
        for index, incoming in enumerate(second.answers):
            current = values[index]
            if current in {"yes", "no", "sometimes"}:
                continue
            if incoming in {"yes", "no", "sometimes"}:
                values[index] = incoming
            elif current == "unknown" and incoming == "often":
                values[index] = incoming
        return DatasetRow(first.name, tuple(values))

    @staticmethod
    def _effective_answer(base_answer: str, learned_answer: str) -> str:
        if base_answer in {"yes", "no", "sometimes"}:
            return base_answer
        if learned_answer in {"yes", "no", "sometimes"}:
            return learned_answer
        return base_answer

    @staticmethod
    def _parse_line(raw_line: str, line_number: int, kind: str) -> dict[str, Any]:
        try:
            value = json.loads(raw_line, object_pairs_hook=_json_object_pairs)
        except (json.JSONDecodeError, TwentyQuestionsDataError) as exc:
            raise TwentyQuestionsDataError(
                f"{kind} row {line_number} is not valid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise TwentyQuestionsDataError(
                f"{kind} row {line_number} must be a JSON object"
            )
        return value

    def _atomic_write(
        self,
        rows: Mapping[str, DatasetRow],
        question_keys: tuple[str, ...],
    ) -> None:
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.learned_path.parent,
                prefix=f".{self.learned_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                for row in rows.values():
                    payload = {OBJECT_NAME_KEY: row.name}
                    payload.update(
                        {
                            key: DISPLAY_ANSWERS[row.answers[index]]
                            for index, key in enumerate(question_keys)
                        }
                    )
                    handle.write(
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.learned_path)
            temp_name = None
        finally:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink()
                except OSError:
                    pass

    def _diagnose(self, message: str) -> None:
        self.diagnostics.append(message)
        self.reporter(f"[20 QUESTIONS] {message}")


# Friendly functional entry points for callers that do not need a loader
# object.  Game instances use the object form so base data remains cached.
def load_dataset(
    base_path: Path | str = BASE_DATA_PATH,
    learned_path: Path | str = LEARNED_DATA_PATH,
) -> DatasetCatalog:
    return TwentyQuestionsDatasetLoader(base_path, learned_path).load()


@dataclass(frozen=True)
class QuestionMasks:
    yes: int
    no: int
    sometimes: int
    often: int
    unknown: int

    @property
    def wildcard(self) -> int:
        return self.often | self.unknown


@dataclass(frozen=True)
class CandidateIndex:
    """Compact inverted bitset index for an effective catalog."""

    question_keys: tuple[str, ...]
    masks: tuple[QuestionMasks, ...]
    all_candidates: int
    candidate_count: int

    @classmethod
    def build(cls, catalog: DatasetCatalog) -> CandidateIndex:
        question_masks: list[QuestionMasks] = []
        for question_index in range(catalog.question_count):
            values = {
                answer: 0 for answer in ("yes", "no", "sometimes", "often", "unknown")
            }
            for row_index, row in enumerate(catalog.rows):
                value = row.answer_for(question_index)
                values[value] |= 1 << row_index
            question_masks.append(QuestionMasks(**values))
        all_candidates = (1 << catalog.object_count) - 1
        return cls(
            catalog.question_keys,
            tuple(question_masks),
            all_candidates,
            catalog.object_count,
        )

    def branch_masks(self, question_index: int, pool: int) -> dict[str, int]:
        masks = self.masks[question_index]
        wildcard = masks.wildcard
        return {
            "yes": pool & (masks.yes | wildcard),
            "no": pool & (masks.no | wildcard),
            "sometimes": pool & (masks.sometimes | wildcard),
        }

    @property
    def question_masks(self) -> tuple[QuestionMasks, ...]:
        return self.masks


def normalize_player_answer(text: object) -> str | None:
    """Normalize natural speech to a player answer or quit command."""
    if not isinstance(text, str):
        return None
    normalized = text.casefold().replace("’", "'")
    normalized = re.sub(r"^[\s\-\u2013\u2014*•]+", "", normalized)
    normalized = re.sub(r"^(?:oh|well|um|uh|okay|ok)[,.\s]+", "", normalized)
    normalized = re.sub(r"^[^\w']+|[^\w']+$", "", normalized)
    normalized = " ".join(normalized.split())
    aliases = {
        "yes": {"yes", "yep", "yeah", "correct", "it is", "sure"},
        "no": {"no", "nope", "nah", "incorrect", "it isn't", "it is not", "it isnt"},
        "sometimes": {
            "sometimes", "maybe", "probably", "possibly", "often", "usually",
            "sort of", "kind of", "it depends",
        },
        "unknown": {
            "i don't know", "i dont know", "don't know", "dont know", "not sure",
            "unsure", "unknown",
        },
        "quit": {"stop", "quit", "cancel", "end game"},
    }
    for answer, words in aliases.items():
        if normalized in words:
            return answer
    return None


# Short compatibility alias for tests and integrations.
normalize_answer = normalize_player_answer


@dataclass(frozen=True)
class Turn:
    question_key: str
    question: str
    answer: str
    was_guess: bool = False
    guessed_object: str | None = None
    usable_for_learning: bool = True


class TwentyQuestionsGame:
    """Adaptive balanced elimination over the effective dataset catalog."""

    MAX_INFORMATIVE_DECISIONS = 20
    MAX_TOTAL_PROMPTS = 30
    BONUS_QUESTION_COUNT = 4
    # Retain the old public name for callers that used the game limit.
    MAX_QUESTIONS = MAX_INFORMATIVE_DECISIONS

    def __init__(
        self,
        learned_path: Path | str | None = None,
        *,
        base_path: Path | str = BASE_DATA_PATH,
        debug: bool = False,
        informative_question_limit: object = MAX_INFORMATIVE_DECISIONS,
        total_prompt_limit: object = MAX_TOTAL_PROMPTS,
        loader: TwentyQuestionsDatasetLoader | None = None,
    ) -> None:
        effective_learned_path = learned_path or LEARNED_DATA_PATH
        self.loader = loader or TwentyQuestionsDatasetLoader(
            base_path,
            effective_learned_path,
        )
        self.base_path = self.loader.base_path
        self.learned_path = self.loader.learned_path
        self.debug = bool(debug)
        self.informative_question_limit = self._positive_limit(
            informative_question_limit,
            self.MAX_INFORMATIVE_DECISIONS,
        )
        self.total_prompt_limit = self._positive_limit(
            total_prompt_limit,
            self.MAX_TOTAL_PROMPTS,
        )
        self.catalog: DatasetCatalog | None = None
        self.index: CandidateIndex | None = None
        self.active = False
        self.awaiting_reveal = False
        self.current_question: str | None = None
        self.current_guess: DatasetRow | None = None
        self.current_llm_guess: str | None = None
        self.history: list[Turn] = []
        self.asked_keys: set[str] = set()
        self._asked_partitions: set[tuple[int, int, int]] = set()
        self.rejected_names: set[str] = set()
        self.candidate_pool = 0
        self.informative_decisions = 0
        self.total_prompt_count = 0
        self.bonus_active = False
        self.bonus_question_count = 0
        self._normal_llm_attempted = False
        self._bonus_llm_attempted = False
        self._bonus_guess_attempted = False
        self._llm_guess_requested = False
        self._attempted_names: set[str] = set()
        self.last_diagnostic: str | None = None
        self._pending_notice: str | None = None

    @property
    def learning_enabled(self) -> bool:
        return self.loader.learning_enabled

    @property
    def question_count(self) -> int:
        """Compatibility view of the total numbered question prompts."""
        return self.total_prompt_count

    @property
    def informative_question_count(self) -> int:
        return self.informative_decisions

    @property
    def candidate_count(self) -> int:
        return self.candidate_pool.bit_count()

    @property
    def candidate_names(self) -> tuple[str, ...]:
        if self.catalog is None:
            return ()
        return tuple(
            row.name
            for index, row in enumerate(self.catalog.rows)
            if self.candidate_pool & (1 << index)
        )

    @property
    def guess_name(self) -> str | None:
        """Return the display name of either a dataset or LLM guess."""
        if self.current_guess is not None:
            return self.current_guess.name
        return self.current_llm_guess

    @property
    def needs_llm_guess(self) -> bool:
        """Whether the mode should ask the local model for a fallback guess."""
        return self._llm_guess_requested

    def structured_history(self) -> list[dict[str, object]]:
        """Return compact history suitable for a fallback model prompt."""
        return [
            {
                "question": turn.question,
                "answer": turn.answer,
                "was_guess": turn.was_guess,
                "guessed_object": turn.guessed_object,
            }
            for turn in self.history
        ]

    @staticmethod
    def is_start_request(text: str) -> bool:
        normalized = " ".join(str(text).casefold().strip().rstrip("?.!").split())
        return bool(
            normalized in {"20 questions", "twenty questions"}
            or re.search(
                r"\b(?:play|start)\b.*\b(?:20|twenty)\s+questions\b",
                normalized,
            )
            or re.search(
                r"\blet'?s\s+play\b.*\b(?:20|twenty)\s+questions\b",
                normalized,
            )
        )

    parse_answer = staticmethod(normalize_player_answer)

    def start(self) -> str:
        """Lazily load the catalog and begin a new game."""
        self._reset_runtime()
        try:
            self.catalog = self.loader.load()
        except TwentyQuestionsDataError as exc:
            self.last_diagnostic = str(exc)
            self._diagnose(str(exc))
            self.active = False
            raise
        self.index = CandidateIndex.build(self.catalog)
        self.candidate_pool = self.index.all_candidates
        self.active = True
        self.awaiting_reveal = False
        self._debug(
            f"Loaded {self.catalog.object_count} objects and "
            f"{self.catalog.question_count} questions."
        )
        return f"{INTRODUCTION} {self.next_move()}"

    def accept_answer(self, text: str) -> str | None:
        """Accept a response to the current question or guess."""
        answer = normalize_player_answer(text)
        if answer is None:
            if self.guess_name is not None:
                return "For a guess, please answer yes, no, or I don't know."
            return ANSWER_PROMPT
        if answer == "quit":
            self.active = False
            self.awaiting_reveal = False
            return "Okay, game over!"
        if not self.active:
            return None
        if self.awaiting_reveal:
            return REVEAL_PROMPT
        if self.guess_name is not None:
            return self._accept_guess(answer)
        if self.current_question is None or self.catalog is None:
            return REVEAL_PROMPT

        question_key = self.current_question
        question_index = self.catalog.question_keys.index(question_key)
        before_pool = self.candidate_pool
        self.asked_keys.add(question_key)
        branches = self.index.branch_masks(question_index, before_pool)  # type: ignore[union-attr]
        usable = answer != "unknown"
        if answer == "unknown":
            after_pool = before_pool
        else:
            after_pool = branches[answer]
        self.history.append(
            Turn(
                question_key,
                question_key,
                answer,
                usable_for_learning=(
                    usable and not (after_pool == 0 and before_pool != 0)
                ),
            )
        )
        self.current_question = None
        self._asked_partitions.add(
            (
                branches["yes"],
                branches["no"],
                branches["sometimes"],
            )
        )
        if answer in {"yes", "no", "sometimes"}:
            if after_pool == 0 and before_pool != 0:
                self.candidate_pool = before_pool
                self._pending_notice = (
                    "That answer conflicts with the remaining candidates, "
                    "so I’ll skip that question."
                )
            else:
                self.candidate_pool = after_pool
                self.informative_decisions += 1
        self._debug(f"Answer {answer}; candidates={self.candidate_count}")
        if self._hard_limit_reached():
            self.awaiting_reveal = True
            return self._reveal_prompt()
        return None

    def next_move(self) -> str:
        """Select a guess/question, fallback guess, or bonus-round move."""
        if not self.active:
            return ""
        if self._hard_limit_reached():
            self.awaiting_reveal = True
            return self._reveal_prompt()

        if not self.bonus_active and self.total_prompt_count >= self.informative_question_limit:
            self._begin_bonus_round()

        if self.bonus_active and self.bonus_question_count >= self.BONUS_QUESTION_COUNT:
            if not self._bonus_guess_attempted:
                row = self._next_candidate_guess()
                if row is not None:
                    self._bonus_guess_attempted = True
                    self.current_guess = row
                    self.current_llm_guess = None
                    self.current_question = None
                    return self._guess_text(row.name)
            if self.candidate_count == 0 and not self._bonus_llm_attempted:
                self._llm_guess_requested = True
                return LLM_GUESS_REQUEST
            self.awaiting_reveal = True
            return self._reveal_prompt()

        if self.candidate_count == 1 and not self.bonus_active:
            row = self._next_candidate_guess()
            if row is not None:
                self.current_guess = row
                self.current_llm_guess = None
                self.current_question = None
                return self._guess_text(row.name)

        if (
            not self.bonus_active
            and self.total_prompt_count == self.informative_question_limit - 1
            and self.candidate_count == 0
            and not self._normal_llm_attempted
        ):
            self._llm_guess_requested = True
            return LLM_GUESS_REQUEST

        selected = self._best_question()
        if selected is None:
            selected = self._fallback_question()
        if selected is None:
            if self.bonus_active:
                self.bonus_question_count = self.BONUS_QUESTION_COUNT
                return self.next_move()
            self.awaiting_reveal = True
            return self._reveal_prompt()
        question_key, branches = selected
        self.current_question = question_key
        self.current_guess = None
        self.current_llm_guess = None
        self.total_prompt_count += 1
        if self.bonus_active:
            self.bonus_question_count += 1
        if branches is not None:
            self._asked_partitions.add(branches)
        question_text = question_key
        prefix = f"Question {self.total_prompt_count}."
        notice = self._pending_notice
        self._pending_notice = None
        return " ".join(part for part in (notice, prefix, question_text) if part)

    def offer_llm_guess(self, name: str) -> str | None:
        """Install a validated model guess as the current guess prompt."""
        display_name = clean_display_name(name)
        canonical_name = canonical_object_name(display_name)
        if (
            not canonical_name
            or canonical_name in self._attempted_names
            or canonical_name in self.rejected_names
        ):
            self.llm_guess_failed()
            return None
        self._llm_guess_requested = False
        if self.bonus_active:
            self._bonus_llm_attempted = True
            self._bonus_guess_attempted = True
        else:
            self._normal_llm_attempted = True
        self._attempted_names.add(canonical_name)
        self.current_llm_guess = display_name
        self.current_guess = None
        self.current_question = None
        return self._guess_text(display_name)

    def llm_guess_failed(self) -> None:
        """Mark a fallback attempt as used so the game can keep asking."""
        self._llm_guess_requested = False
        if self.bonus_active:
            self._bonus_llm_attempted = True
        else:
            self._normal_llm_attempted = True

    def reveal_and_learn(self, answer_name: str) -> str:
        """Finish after a reveal and merge the replayable game history."""
        if normalize_player_answer(answer_name) == "quit":
            self.active = False
            self.awaiting_reveal = False
            return "Okay, game over!"
        display_name = clean_display_name(answer_name.rstrip("?.!"))
        if not canonical_object_name(display_name):
            return "I didn't catch the object name. What were you thinking of?"
        outcome = self.loader.learn(
            display_name,
            (
                (turn.question_key, turn.answer)
                for turn in self.history
                if not turn.was_guess and turn.usable_for_learning
            ),
        )
        response = self._learning_response(display_name, outcome)
        self.active = False
        self.awaiting_reveal = False
        self.current_question = None
        self.current_guess = None
        self.current_llm_guess = None
        return response

    def close(self) -> None:
        """End the game and clear all per-game state; safe to call repeatedly."""
        self.active = False
        self.awaiting_reveal = False
        self.current_question = None
        self.current_guess = None
        self.current_llm_guess = None
        self.history.clear()
        self.asked_keys.clear()
        self._asked_partitions.clear()
        self.rejected_names.clear()
        self.candidate_pool = 0
        self.informative_decisions = 0
        self.total_prompt_count = 0
        self.bonus_active = False
        self.bonus_question_count = 0
        self._normal_llm_attempted = False
        self._bonus_llm_attempted = False
        self._bonus_guess_attempted = False
        self._llm_guess_requested = False
        self._attempted_names.clear()
        self._pending_notice = None
        self.catalog = None
        self.index = None

    def select_question(self) -> str | None:
        """Return the best unasked question without speaking or numbering it."""
        selected = self._best_question()
        return selected[0] if selected else None

    def filter_candidates(self, answer: str) -> int:
        """Apply a canonical answer to the current question for test clients."""
        if self.current_question is None:
            return self.candidate_pool
        self.accept_answer(answer)
        return self.candidate_pool

    def _accept_guess(self, answer: str) -> str | None:
        guess = self.guess_name
        assert guess is not None
        if answer == "sometimes":
            return "For a guess, please answer yes, no, or I don't know."
        canonical_guess = canonical_object_name(guess)
        self.history.append(
            Turn(
                f"guess:{canonical_guess}",
                self._guess_text(guess),
                answer,
                was_guess=True,
                guessed_object=guess,
                usable_for_learning=False,
            )
        )
        self._attempted_names.add(canonical_guess)
        dataset_guess = self.current_guess
        self.current_guess = None
        self.current_llm_guess = None
        if answer == "yes":
            outcome = self.loader.learn(
                guess,
                (
                    (turn.question_key, turn.answer)
                    for turn in self.history
                    if not turn.was_guess and turn.usable_for_learning
                ),
            )
            self.active = False
            return f"Yes! I got it. {self._learning_response('', outcome)}"
        if answer == "no":
            self.rejected_names.add(canonical_guess)
            if dataset_guess is not None and self.catalog is not None:
                for index, row in enumerate(self.catalog.rows):
                    if row is dataset_guess:
                        self.candidate_pool &= ~(1 << index)
                        break
            if self.candidate_count == 0:
                self._pending_notice = None
        else:
            self._pending_notice = "Okay, I’ll keep trying."
        return None

    def _best_question(self) -> tuple[str, tuple[int, int, int]] | None:
        if self.catalog is None or self.index is None or self.candidate_count < 2:
            return None
        pool = self.candidate_pool
        candidate_count = self.candidate_count
        choices: list[tuple[tuple[int, int, int, int, int, str], str, tuple[int, int, int]]] = []
        for index, question_key in enumerate(self.catalog.question_keys):
            if question_key in self.asked_keys:
                continue
            branches = self.index.branch_masks(index, pool)
            signature = (branches["yes"], branches["no"], branches["sometimes"])
            if signature in self._asked_partitions:
                continue
            branch_sizes = tuple(mask.bit_count() for mask in signature)
            largest_branch = max(branch_sizes)
            if largest_branch >= candidate_count:
                continue
            masks = self.index.masks[index]
            wildcard_count = (pool & masks.wildcard).bit_count()
            definite_coverage = candidate_count - wildcard_count
            yes_no_balance = abs(branch_sizes[0] - branch_sizes[1])
            # Lexicographic ordering makes each requested preference explicit:
            # worst-case elimination, wildcard penalty, yes/no balance, high
            # definite coverage, then stable text ordering.
            score = (
                largest_branch,
                wildcard_count,
                yes_no_balance,
                -definite_coverage,
                len(question_key),
                question_key.casefold(),
            )
            choices.append((score, question_key, signature))
        if not choices:
            return None
        _score, question_key, signature = min(choices, key=lambda item: item[0])
        return question_key, signature

    def _fallback_question(self) -> tuple[str, tuple[int, int, int]] | None:
        """Return a deterministic question when elimination cannot continue."""
        if self.catalog is None or self.index is None or not self.catalog.question_keys:
            return None
        available = [
            question
            for question in self.catalog.question_keys
            if question not in self.asked_keys
        ]
        if available:
            question_key = available[0]
        else:
            question_key = self.catalog.question_keys[
                self.total_prompt_count % len(self.catalog.question_keys)
            ]
        question_index = self.catalog.question_keys.index(question_key)
        branches = self.index.branch_masks(question_index, self.candidate_pool)
        return (
            question_key,
            (branches["yes"], branches["no"], branches["sometimes"]),
        )

    def _hard_limit_reached(self) -> bool:
        return self.total_prompt_count >= self.total_prompt_limit

    def _begin_bonus_round(self) -> None:
        if self.bonus_active:
            return
        self.bonus_active = True
        self.bonus_question_count = 0
        self._pending_notice = BONUS_INTRODUCTION

    def _next_candidate_guess(self) -> DatasetRow | None:
        if self.catalog is None:
            return None
        for index, row in enumerate(self.catalog.rows):
            if (
                self.candidate_pool & (1 << index)
                and canonical_object_name(row.name) not in self._attempted_names
            ):
                return row
        return None

    def _only_candidate(self) -> DatasetRow | None:
        if self.catalog is None or self.candidate_count != 1:
            return None
        for index, row in enumerate(self.catalog.rows):
            if self.candidate_pool & (1 << index):
                return row
        return None

    def _reveal_prompt(self) -> str:
        notice = self._pending_notice
        self._pending_notice = None
        return " ".join(part for part in (notice, REVEAL_PROMPT) if part)

    @staticmethod
    def _guess_text(name: str) -> str:
        return f"My guess is {name}. Am I right?"

    @staticmethod
    def _learning_response(display_name: str, outcome: LearningOutcome) -> str:
        if outcome.error and not outcome.persisted:
            if outcome.learning_enabled:
                return "I couldn't save that learning right now."
            return "Learning is disabled for this game."
        if outcome.changed and outcome.persisted:
            if display_name:
                return f"Thanks! I'll remember that you were thinking of {display_name}."
            return "Thanks! I'll remember that."
        if display_name:
            return f"Thanks! I was thinking of {display_name}."
        return "Thanks! I was thinking of that."

    def _reset_runtime(self) -> None:
        self.active = False
        self.awaiting_reveal = False
        self.current_question = None
        self.current_guess = None
        self.history = []
        self.asked_keys = set()
        self._asked_partitions = set()
        self.rejected_names = set()
        self.candidate_pool = 0
        self.informative_decisions = 0
        self.total_prompt_count = 0
        self.bonus_active = False
        self.bonus_question_count = 0
        self._normal_llm_attempted = False
        self._bonus_llm_attempted = False
        self._bonus_guess_attempted = False
        self._llm_guess_requested = False
        self._attempted_names = set()
        self._pending_notice = None

    @staticmethod
    def _positive_limit(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(parsed, 1)

    def _diagnose(self, message: str) -> None:
        print(f"[20 QUESTIONS] {message}", flush=True)

    def _debug(self, message: str) -> None:
        if self.debug:
            print(f"[20 QUESTIONS DEBUG] {message}", flush=True)


__all__ = [
    "ANSWER_PROMPT",
    "BASE_DATA_PATH",
    "BONUS_INTRODUCTION",
    "BaseCatalog",
    "CandidateIndex",
    "DatasetCatalog",
    "DatasetRow",
    "INTRODUCTION",
    "LEARNED_DATA_PATH",
    "LLM_GUESS_REQUEST",
    "LearningOutcome",
    "LearningPersistenceError",
    "OBJECT_NAME_KEY",
    "PLAYER_ANSWERS",
    "QuestionMasks",
    "REVEAL_PROMPT",
    "TwentyQuestionsDataError",
    "TwentyQuestionsDatasetLoader",
    "TwentyQuestionsGame",
    "Turn",
    "canonical_object_name",
    "clean_display_name",
    "load_dataset",
    "normalize_answer",
    "normalize_dataset_answer",
    "normalize_player_answer",
]
