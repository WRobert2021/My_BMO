"""Toolkit-neutral selection state for Learning presentations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        return {str(key): item for key, item in value}
    except (TypeError, ValueError):
        return {}


def _interaction(value: Any) -> str:
    raw = getattr(value, "value", value)
    name = str(raw or "single_choice").strip().lower().replace("-", "_")
    return {
        "category_sort": "category_sorting",
        "scene_choice": "scene_prediction",
        "listen_hidden": "single_choice",
    }.get(name, name)


@dataclass(frozen=True)
class ChoiceSnapshot:
    choice_id: str
    label: str


@dataclass(frozen=True)
class QuestionSnapshot:
    interaction: str
    choices: tuple[ChoiceSnapshot, ...]
    requires_submit: bool
    categories: tuple[str, ...]


@dataclass(frozen=True)
class SelectionResult:
    accepted: bool
    submit_ready: bool
    submit_immediately: bool
    response: Any = None


def question_snapshot(question: Any) -> QuestionSnapshot:
    interaction = _interaction(getattr(question, "interaction", "single_choice"))
    metadata = _mapping(getattr(question, "metadata", ()))
    categories = tuple(
        str(
            item.get("id", item.get("value", item.get("label", "")))
            if isinstance(item, Mapping)
            else item
        ).strip()
        for item in metadata.get("categories", ())
    )
    categories = tuple(item for item in categories if item)
    return QuestionSnapshot(
        interaction=interaction,
        choices=tuple(
            ChoiceSnapshot(str(choice.id), str(choice.label))
            for choice in getattr(question, "choices", ())
        ),
        requires_submit=bool(getattr(question, "requires_submit", False)),
        categories=categories,
    )


class InteractionController:
    """Generic response builder for all data-driven interaction kinds."""

    SUBMIT_KINDS = frozenset(
        {"multi_select", "matching_pairs", "ordered_sequence", "category_sorting"}
    )

    def __init__(self, question: QuestionSnapshot) -> None:
        self.question = question
        self.choice_ids = tuple(
            str(getattr(choice, "choice_id", getattr(choice, "id", "")))
            for choice in question.choices
        )
        self.selected: list[str] = []
        self.assignments: dict[str, str] = {}
        categories = getattr(question, "categories", None)
        if categories is None:
            categories = _mapping(getattr(question, "metadata", ())).get("categories", ())
        self.categories = tuple(
            str(
                item.get("id", item.get("value", item.get("label", "")))
                if isinstance(item, Mapping)
                else item
            ).strip()
            for item in categories
        )
        self.categories = tuple(item for item in self.categories if item)
        self.locked = False

    @property
    def needs_submit(self) -> bool:
        return self.question.requires_submit or self.question.interaction in self.SUBMIT_KINDS

    @property
    def submit_ready(self) -> bool:
        if self.question.interaction == "category_sorting":
            return bool(self.choice_ids) and all(item in self.assignments for item in self.choice_ids)
        if self.question.interaction == "ordered_sequence":
            return bool(self.choice_ids) and len(self.selected) == len(self.choice_ids)
        if self.question.interaction == "listen_only":
            return True
        return bool(self.selected)

    def choose(self, choice_id: str) -> SelectionResult:
        value = str(choice_id)
        if self.locked or value not in self.choice_ids:
            return SelectionResult(False, self.submit_ready, False)
        kind = self.question.interaction
        if kind == "category_sorting":
            if not self.categories:
                return SelectionResult(False, False, False)
            previous = self.assignments.get(value)
            index = -1 if previous not in self.categories else self.categories.index(previous)
            self.assignments[value] = self.categories[(index + 1) % len(self.categories)]
        elif kind == "ordered_sequence":
            if value in self.selected:
                del self.selected[self.selected.index(value) :]
            else:
                self.selected.append(value)
        elif kind in {"multi_select", "matching_pairs"}:
            self.selected.remove(value) if value in self.selected else self.selected.append(value)
        else:
            self.selected[:] = [value]
        response = self.response()
        return SelectionResult(
            True,
            self.submit_ready,
            self.submit_ready and not self.needs_submit,
            response,
        )

    def response(self) -> Any:
        if self.question.interaction == "category_sorting":
            return dict(self.assignments)
        if self.question.interaction in {"multi_select", "matching_pairs", "ordered_sequence"}:
            return tuple(self.selected)
        if self.question.interaction == "listen_only":
            return ()
        return self.selected[0] if self.selected else None

    def reset_for_retry(self) -> None:
        self.selected.clear()
        self.assignments.clear()
        self.locked = False


__all__ = [
    "ChoiceSnapshot",
    "InteractionController",
    "QuestionSnapshot",
    "SelectionResult",
    "question_snapshot",
]
