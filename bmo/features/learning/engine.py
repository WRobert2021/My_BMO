"""Deterministic question generation, grading, and progress calculations.

The engine is intentionally independent of Tk and persistence.  Callers inject
their own :class:`random.Random`, clock, and optional ID factory in tests.  The
module never touches global random state.

Scoring formula
---------------
Each distinct question is one piece of evidence.  First-try accuracy is the
fraction answered correctly on attempt one; eventual accuracy is the fraction
answered correctly before reveal.  The percentage grade is
``100 * (0.60 * first_try_accuracy + 0.40 * eventual_accuracy)``.  Completion
is reported separately.  A skill is mastered only with the configured minimum
recent evidence, eventual accuracy at the threshold, and first-try accuracy at
least ``max(0.50, threshold - 0.20)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import random
from typing import Any
from uuid import uuid4

from .curriculum import (
    CURRICULUM,
    READABLE_FONTS,
    READABLE_GLYPH_COLORS,
    Catalog,
)
from .models import (
    AttemptRecord,
    Choice,
    ContentItem,
    Evaluation,
    InteractionKind,
    LearningDataError,
    LearningPlan,
    LearningSession,
    MasteryStatus,
    PlanReport,
    Question,
    SessionTransition,
    SkillMastery,
)


MAX_QUESTION_ATTEMPTS = 2
DEFAULT_RECENT_EVIDENCE = 20
_NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)
_PATTERN_SYMBOLS = (
    ("red circle", "red-circle"),
    ("blue square", "blue-square"),
    ("green triangle", "green-triangle"),
    ("yellow star", "yellow-star"),
    ("purple diamond", "purple-diamond"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_id() -> str:
    return uuid4().hex


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _sample_excluding(
    rng: random.Random,
    values: Iterable[Any],
    excluded: set[Any],
    count: int,
) -> list[Any]:
    pool = list(dict.fromkeys(value for value in values if value not in excluded))
    if len(pool) < count:
        raise LearningDataError(
            f"content bank has {len(pool)} usable distractors; {count} required"
        )
    return rng.sample(pool, count)


class LearningEngine:
    """Generate questions and apply immutable, explainable transitions."""

    def __init__(
        self,
        catalog: Catalog = CURRICULUM,
        *,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _default_id,
        max_attempts: int = MAX_QUESTION_ATTEMPTS,
    ) -> None:
        if not isinstance(catalog, Catalog):
            raise TypeError("catalog must be a Catalog")
        if rng is not None and not isinstance(rng, random.Random):
            raise TypeError("rng must be random.Random")
        if not callable(clock) or not callable(id_factory):
            raise TypeError("clock and id_factory must be callable")
        if not isinstance(max_attempts, int) or not 2 <= max_attempts <= 4:
            raise ValueError("max_attempts must be between 2 and 4")
        self.catalog = catalog
        self.rng = rng or random.Random()
        self._clock = clock
        self._id_factory = id_factory
        self.max_attempts = max_attempts
        self._question_counter = 0

    def _new_id(self, prefix: str) -> str:
        value = str(self._id_factory()).strip()
        safe = "".join(character for character in value if character.isalnum() or character in "_.-@")
        if not safe:
            raise LearningDataError("id_factory returned no safe identifier characters")
        return f"{prefix}-{safe[:120]}"

    def _question_id(self, lesson_id: str) -> str:
        self._question_counter += 1
        return f"{lesson_id}:v1:{self._question_counter:06d}"

    def generate_question(self, lesson_id: str) -> Question:
        """Generate one complete question using only this engine's RNG."""

        lesson = self.catalog.get(lesson_id)
        generator = getattr(self, f"_generate_{lesson.generator}", None)
        if generator is None:
            raise LearningDataError(f"no generator for {lesson.generator}")
        question = generator(lesson)
        if question.lesson_id != lesson.lesson_id:
            raise LearningDataError("question generator returned the wrong lesson id")
        return question

    def _make_choices(
        self,
        payloads: Sequence[tuple[str, str, Mapping[str, Any]]],
        *,
        shuffle: bool = True,
    ) -> tuple[tuple[Choice, ...], tuple[str, ...]]:
        """Create choices from ``(label, spoken, metadata)`` payloads.

        A truthy ``correct`` metadata value marks a correct ID.  Payload order
        is shuffled before positional IDs are assigned, eliminating a stable
        correct-button position while keeping IDs unique.
        """

        values = list(payloads)
        if shuffle:
            self.rng.shuffle(values)
        choices: list[Choice] = []
        correct: list[str] = []
        for index, (label, spoken, metadata) in enumerate(values):
            choice_id = f"c{index}"
            frozen = dict(metadata)
            is_correct = bool(frozen.pop("correct", False))
            choices.append(Choice(choice_id, label, spoken, frozen))
            if is_correct:
                correct.append(choice_id)
        return tuple(choices), tuple(correct)

    def _question(
        self,
        lesson: Any,
        *,
        prompt: str,
        spoken_prompt: str | None,
        choices: tuple[Choice, ...],
        correct: tuple[str, ...],
        hidden: bool | None = None,
        requires_submit: bool | None = None,
        example: str = "",
        explanation: str = "",
        hint: str = "",
        metadata: Mapping[str, Any] | None = None,
        interaction: InteractionKind | None = None,
    ) -> Question:
        effective_interaction = interaction or lesson.interaction
        # Hidden spoken prompts still have tappable answers.  Visibility and
        # answer mechanics are separate so a renderer does not mistake these
        # for passive listen-only cards.
        if effective_interaction is InteractionKind.LISTEN_HIDDEN:
            effective_interaction = InteractionKind.SINGLE_CHOICE
        return Question(
            question_id=self._question_id(lesson.lesson_id),
            lesson_id=lesson.lesson_id,
            domain=lesson.domain,
            # Domain evidence is recorded alongside the narrower skill tags so
            # teacher reports can show both domain and per-skill mastery from
            # the same rebuildable attempt history.
            skills=(f"domain.{lesson.domain}", *lesson.skills),
            interaction=effective_interaction,
            prompt=prompt,
            spoken_prompt=spoken_prompt or prompt,
            choices=choices,
            correct_answers=correct,
            hidden_prompt=bool(lesson.setting("hidden", False) if hidden is None else hidden),
            requires_submit=(
                len(correct) > 1
                or lesson.interaction
                in {
                    InteractionKind.MULTI_SELECT,
                    InteractionKind.CATEGORY_SORT,
                    InteractionKind.MATCHING_PAIRS,
                    InteractionKind.ORDERED_SEQUENCE,
                }
                if requires_submit is None
                else requires_submit
            ),
            example=example,
            explanation=explanation,
            hint=hint,
            metadata=metadata or {},
        )

    def _bank(self, lesson: Any) -> tuple[ContentItem, ...]:
        return tuple(
            item
            for bank_name in lesson.bank_refs
            for item in self.catalog.bank(bank_name)
        )

    def _target_value(self, lesson: Any, items: Sequence[ContentItem]) -> str:
        explicit = lesson.setting("target")
        if explicit is not None:
            return str(explicit)
        target_pool = lesson.setting("target_pool")
        if target_pool:
            return str(self.rng.choice(tuple(target_pool)))
        return self.rng.choice(tuple(item.label for item in items))

    def _letter_payload(self, glyph: str, correct: bool) -> tuple[str, str, Mapping[str, Any]]:
        return (
            glyph,
            glyph,
            {
                "correct": correct,
                "font": self.rng.choice(READABLE_FONTS),
                "color": self.rng.choice(READABLE_GLYPH_COLORS),
                "glyph": glyph,
            },
        )

    def _generate_letter_single(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        target = self._target_value(lesson, items)
        preferred = tuple(lesson.setting("distractor_pool", ()))
        pool = tuple(dict.fromkeys((*preferred, *(item.label for item in items))))
        distractors = _sample_excluding(self.rng, pool, {target}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [self._letter_payload(target, True)]
            + [self._letter_payload(value, False) for value in distractors]
        )
        hidden = bool(lesson.setting("hidden", False))
        if hidden:
            prompt = lesson.prompt_templates[0]
            spoken = f"Choose the letter {target}."
        else:
            prompt = lesson.prompt_templates[0].format(target=target)
            spoken = prompt
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=hidden,
            example="" if hidden else target,
            explanation=f"This is the letter {target}.",
            hint=f"Look for the same shape as {target}." if not hidden else "Listen to the letter name again.",
            metadata={"target": target, "example_color": "#000000", "example_font": READABLE_FONTS[0]},
        )

    def _generate_letter_multi(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        target = self._target_value(lesson, items)
        target_count = self.rng.randint(lesson.minimum_correct, lesson.maximum_correct)
        preferred = tuple(lesson.setting("distractor_pool", ()))
        pool = tuple(dict.fromkeys((*preferred, *(item.label for item in items))))
        distractors = _sample_excluding(
            self.rng, pool, {target}, lesson.choice_count - target_count
        )
        payloads = [self._letter_payload(target, True) for _ in range(target_count)]
        payloads.extend(self._letter_payload(value, False) for value in distractors)
        choices, correct = self._make_choices(payloads)
        hidden = bool(lesson.setting("hidden", False))
        visible = lesson.prompt_templates[0]
        case = str(lesson.setting("case", "")).strip().lower()
        case_words = f"{case}case " if case in {"upper", "lower"} else ""
        spoken = f"Find every choice showing the {case_words}letter {target}."
        if not hidden:
            visible = f"Find all {case_words}letter {target} choices."
        return self._question(
            lesson,
            prompt=visible,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=hidden,
            requires_submit=True,
            example="" if hidden else target,
            explanation=f"Every selected {target} has the same letter shape.",
            hint="Check each shape one at a time before you tap Submit.",
            metadata={"target": target, "target_count": target_count, "example_color": "#000000", "example_font": READABLE_FONTS[0]},
            interaction=InteractionKind.MULTI_SELECT,
        )

    def _generate_alphabet_grid(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        target = self._target_value(lesson, items)
        payloads = [
            (item.label, item.spoken, {"correct": item.label == target, "glyph": item.label, "font": READABLE_FONTS[0], "color": "#124559"})
            for item in items
        ]
        choices, correct = self._make_choices(payloads, shuffle=False)
        prompt = lesson.prompt_templates[0].format(target=target)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"You found {target} in the alphabet.",
            hint="Follow the alphabet row and compare each letter shape.",
            metadata={"target": target, "alphabet_ordered": True},
        )

    def _generate_case_match(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        target = self._target_value(lesson, items)
        source = target.upper() if lesson.setting("source_case") == "upper" else target.lower()
        pool = tuple(lesson.setting("target_pool", ())) or tuple(item.label for item in items)
        distractors = _sample_excluding(self.rng, pool, {target}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [self._letter_payload(target, True)]
            + [self._letter_payload(value, False) for value in distractors]
        )
        prompt = lesson.prompt_templates[0].format(example=source)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            example=source,
            explanation=f"{source} and {target} are the same letter in different cases.",
            hint="Say the example letter name, then find that name in the other case.",
            metadata={"target": target, "source": source, "example_color": "#000000"},
        )

    def _generate_case_multi(self, lesson: Any) -> Question:
        target_case = lesson.setting("target_case")
        target_count = self.rng.randint(lesson.minimum_correct, lesson.maximum_correct)
        alphabet = tuple("abcdefghijklmnopqrstuvwxyz")
        selected = self.rng.sample(alphabet, lesson.choice_count)
        flags = [True] * target_count + [False] * (lesson.choice_count - target_count)
        self.rng.shuffle(flags)
        payloads = []
        for letter, is_target in zip(selected, flags):
            use_lower = is_target if target_case == "lower" else not is_target
            glyph = letter if use_lower else letter.upper()
            payloads.append(self._letter_payload(glyph, is_target))
        choices, correct = self._make_choices(payloads)
        prompt = lesson.prompt_templates[0]
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            requires_submit=True,
            explanation=f"The selected letters are all {target_case}case.",
            hint=f"Look at each letter and decide whether it is {target_case}case.",
            metadata={"target_case": target_case, "target_count": target_count},
            interaction=InteractionKind.MULTI_SELECT,
        )

    def _generate_same_pair(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        target = self.rng.choice(items)
        distractors = _sample_excluding(
            self.rng, items, {target}, lesson.choice_count - 2
        )
        payloads = [
            (target.label, target.spoken, {"correct": True, "picture": target.attribute("picture", ""), "speakable": True}),
            (target.label, target.spoken, {"correct": True, "picture": target.attribute("picture", ""), "speakable": True}),
        ]
        payloads.extend(
            (item.label, item.spoken, {"correct": False, "speakable": True})
            for item in distractors
        )
        choices, correct = self._make_choices(payloads)
        return self._question(
            lesson,
            prompt=lesson.prompt_templates[0],
            spoken_prompt=lesson.prompt_templates[0],
            choices=choices,
            correct=correct,
            requires_submit=True,
            explanation=f"Both choices say {target.label}; every letter is in the same order.",
            hint="Compare the words from the first letter to the last.",
            metadata={"target": target.label},
        )

    def _generate_scenario_choice(self, lesson: Any) -> Question:
        scenario = self.rng.choice(self._bank(lesson))
        distractors = tuple(scenario.attribute("distractors", ()))
        options = (scenario.label, *distractors[: lesson.choice_count - 1])
        if len(set(options)) != lesson.choice_count:
            raise LearningDataError(f"scenario {scenario.key} has ambiguous choices")
        choices, correct = self._make_choices(
            [
                (
                    label,
                    label,
                    {
                        "correct": index == 0,
                        "picture": scenario.attribute("picture", "") if index == 0 else "",
                    },
                )
                for index, label in enumerate(options)
            ]
        )
        prompt = str(scenario.attribute("prompt", lesson.prompt_templates[0]))
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=str(scenario.attribute("explanation", f"{scenario.label} fits best.")),
            hint="Look at every detail, then choose the answer that fits the question.",
            metadata={"scenario": scenario.key, "picture": scenario.attribute("picture", "")},
        )

    def _generate_word_in_sentence(self, lesson: Any) -> Question:
        items = tuple(item for item in self._bank(lesson) if len(item.label) <= 5)
        target = self.rng.choice(items)
        distractors = _sample_excluding(self.rng, items, {target}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [(target.label, target.spoken, {"correct": True})]
            + [(item.label, item.spoken, {"correct": False}) for item in distractors]
        )
        sentence = f"The word {target.label} is here."
        prompt = f'Find the word "{target.label}" in the sentence below.'
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=f"Find the word {target.spoken} in this sentence. {sentence}",
            choices=choices,
            correct=correct,
            example=sentence,
            explanation=f"The word {target.label} has the same letters in the same order.",
            hint=f"Look for the first letter of {target.label}, then check the rest.",
            metadata={"target": target.label, "sentence": sentence},
        )

    def _grouped(self, items: Sequence[ContentItem], field: str = "group") -> dict[str, list[ContentItem]]:
        groups: dict[str, list[ContentItem]] = defaultdict(list)
        for item in items:
            value = item.group if field == "group" else str(item.attribute(field, ""))
            if value:
                groups[value].append(item)
        return groups

    def _generate_rhyme_one(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        groups = self._grouped(items)
        group = self.rng.choice(tuple(name for name, values in groups.items() if len(values) >= 2))
        target, answer = self.rng.sample(groups[group], 2)
        distractor_pool = [item for item in items if item.group != group]
        distractors = self.rng.sample(distractor_pool, lesson.choice_count - 1)
        picture_choices = bool(lesson.setting("picture_choices", False))
        choices, correct = self._make_choices(
            [(answer.label, answer.spoken, {"correct": True, "picture": answer.attribute("picture", "") if picture_choices else ""})]
            + [(item.label, item.spoken, {"correct": False, "picture": item.attribute("picture", "") if picture_choices else ""}) for item in distractors]
        )
        prompt = lesson.prompt_templates[0].format(target=target.label)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"{target.label} and {answer.label} share the ending {group}.",
            hint="Say the ending of each word slowly and listen for a match.",
            metadata={"target": target.label, "rhyme": group},
        )

    def _generate_rhyme_two(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        groups = self._grouped(items)
        group = self.rng.choice(tuple(name for name, values in groups.items() if len(values) >= 2))
        answers = self.rng.sample(groups[group], 2)
        distractor_groups = [name for name in groups if name != group]
        chosen_groups = self.rng.sample(distractor_groups, lesson.choice_count - 2)
        distractors = [self.rng.choice(groups[name]) for name in chosen_groups]
        choices, correct = self._make_choices(
            [(item.label, item.spoken, {"correct": True}) for item in answers]
            + [(item.label, item.spoken, {"correct": False}) for item in distractors]
        )
        return self._question(
            lesson,
            prompt=lesson.prompt_templates[0],
            spoken_prompt=lesson.prompt_templates[0],
            choices=choices,
            correct=correct,
            requires_submit=True,
            explanation=f"{answers[0].label} and {answers[1].label} share the ending {group}.",
            hint="Say each word and compare its ending sound.",
            metadata={"rhyme": group},
        )

    def _generate_blend(self, lesson: Any) -> Question:
        field = str(lesson.setting("blend_field", "phonemes"))
        items = self._bank(lesson)
        if field == "syllables":
            candidates = tuple(item for item in items if "-" in str(item.attribute("syllables", "")))
        else:
            candidates = tuple(item for item in items if item.attribute("phonemes", ""))
        target = self.rng.choice(candidates)
        if field == "order":
            sounds = tuple(str(target.attribute("phonemes")).split("-"))
            original = [(f"sound-{index}", sound) for index, sound in enumerate(sounds)]
            shuffled = list(original)
            self.rng.shuffle(shuffled)
            choices = tuple(
                Choice(choice_id, sound, sound, {"sound": sound})
                for choice_id, sound in shuffled
            )
            correct = tuple(choice_id for choice_id, _ in original)
            prompt = lesson.prompt_templates[0].format(target=target.label)
            return self._question(
                lesson,
                prompt=prompt,
                spoken_prompt=prompt,
                choices=choices,
                correct=correct,
                requires_submit=True,
                explanation=f"In order, the sounds blend into {target.label}.",
                hint="Listen to the word slowly from beginning to end.",
                metadata={"target": target.label},
            )
        distractors = _sample_excluding(self.rng, items, {target}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [(target.label, target.spoken, {"correct": True, "picture": target.attribute("picture", "")})]
            + [(item.label, item.spoken, {"correct": False, "picture": item.attribute("picture", "")}) for item in distractors]
        )
        if field == "onset_rime":
            blend = f"{target.attribute('onset')} ... {target.attribute('rime')}"
        else:
            blend = str(target.attribute(field, target.label)).replace("-", " ... ")
        visible = lesson.prompt_templates[0]
        spoken = f"Listen and blend: {blend}. Which word does that make?"
        return self._question(
            lesson,
            prompt=visible,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=bool(lesson.setting("hidden", False)),
            explanation=f"Those parts blend together to make {target.label}.",
            hint="Say the parts closer together each time.",
            metadata={"target": target.label, "blend": blend},
        )

    def _generate_initial_sound(self, lesson: Any) -> Question:
        items = tuple(item for item in self._bank(lesson) if item.attribute("initial", ""))
        target = self.rng.choice(items)
        initial = str(target.attribute("initial"))
        if lesson.setting("choose_word", False):
            distractors = self.rng.sample(
                [item for item in items if item.attribute("initial") != initial],
                lesson.choice_count - 1,
            )
            choices, correct = self._make_choices(
                [(target.label, target.spoken, {"correct": True, "picture": target.attribute("picture", "")})]
                + [(item.label, item.spoken, {"correct": False, "picture": item.attribute("picture", "")}) for item in distractors]
            )
            prompt = lesson.prompt_templates[0].format(sound=initial)
            spoken = prompt
        else:
            sounds = tuple("bcdfghjklmnprstvw")
            distractors = _sample_excluding(self.rng, sounds, {initial}, lesson.choice_count - 1)
            choices, correct = self._make_choices(
                [(initial, initial, {"correct": True})]
                + [(sound, sound, {"correct": False}) for sound in distractors]
            )
            prompt = lesson.prompt_templates[0]
            spoken = f"Listen to {target.label}. Which sound comes first?"
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=bool(lesson.setting("hidden", False)),
            explanation=f"{target.label} begins with the {initial} sound.",
            hint=f"Stretch the beginning of {target.label} and listen to its first sound.",
            metadata={"target": target.label, "sound": initial},
        )

    def _generate_sound_compare(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        field = str(lesson.setting("sound_field", "initial"))
        groups = self._grouped(items, field)
        group = self.rng.choice(tuple(name for name, values in groups.items() if len(values) >= 2))
        paired = bool(lesson.setting("paired", lesson.interaction is InteractionKind.MULTI_SELECT))
        if paired:
            answers = self.rng.sample(groups[group], 2)
            other_groups = self.rng.sample([name for name in groups if name != group], lesson.choice_count - 2)
            distractors = [self.rng.choice(groups[name]) for name in other_groups]
            prompt = lesson.prompt_templates[0]
        else:
            target, answer = self.rng.sample(groups[group], 2)
            answers = [answer]
            distractors = self.rng.sample([item for item in items if item.attribute(field) != group], lesson.choice_count - 1)
            prompt = lesson.prompt_templates[0].format(target=target.label)
        choices, correct = self._make_choices(
            [(item.label, item.spoken, {"correct": True, "picture": item.attribute("picture", "")}) for item in answers]
            + [(item.label, item.spoken, {"correct": False, "picture": item.attribute("picture", "")}) for item in distractors]
        )
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            requires_submit=paired,
            explanation=f"The matching words share the {group} sound at the {field}.",
            hint=f"Say each word slowly and listen to its {field} sound.",
            metadata={"sound": group, "sound_field": field},
        )

    def _generate_sound_letter(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        pool = tuple(lesson.setting("target_pool", ())) or tuple(item.label for item in items)
        target_label = self.rng.choice(pool)
        target = next(item for item in items if item.label == target_label)
        distractors = _sample_excluding(self.rng, pool, {target_label}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [self._letter_payload(target_label, True)]
            + [self._letter_payload(value, False) for value in distractors]
        )
        sound = str(target.attribute("sound", f"{target_label} sound"))
        example = str(target.attribute("example", target_label))
        visible = lesson.prompt_templates[0]
        spoken = f"Listen for the {sound}, like the start of {example}. Which letter matches?"
        return self._question(
            lesson,
            prompt=visible,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=True,
            explanation=f"{target_label} matches the {sound}, as in {example}.",
            hint=f"Listen again to the beginning of {example}.",
            metadata={"target": target_label, "sound": sound, "example_word": example},
        )

    def _generate_vowel_word(self, lesson: Any) -> Question:
        vowel = str(lesson.setting("vowel"))
        items = tuple(item for item in self._bank(lesson) if item.attribute("vowel", ""))
        answers = tuple(item for item in items if item.attribute("vowel") == vowel)
        target = self.rng.choice(answers)
        distractors = self.rng.sample(
            [item for item in items if item.attribute("vowel") != vowel],
            lesson.choice_count - 1,
        )
        choices, correct = self._make_choices(
            [(target.label, target.spoken, {"correct": True, "picture": target.attribute("picture", "")})]
            + [(item.label, item.spoken, {"correct": False, "picture": item.attribute("picture", "")}) for item in distractors]
        )
        prompt = lesson.prompt_templates[0]
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"{target.label} has the short {vowel} sound in the middle.",
            hint=f"Say each word slowly and listen for short {vowel}.",
            metadata={"vowel": vowel, "target": target.label},
        )

    def _generate_picture_word(self, lesson: Any) -> Question:
        vowel = str(lesson.setting("vowel"))
        case = str(lesson.setting("word_case", "lower"))
        direction = str(lesson.setting("direction", "word"))
        items = tuple(item for item in self._bank(lesson) if item.attribute("vowel") == vowel)
        target = self.rng.choice(items)
        other_items = tuple(item for item in self._bank(lesson) if item != target)
        distractors = self.rng.sample(other_items, lesson.choice_count - 1)

        def label(item: ContentItem) -> str:
            if direction == "picture":
                return f"picture: {item.attribute('picture', item.label)}"
            return item.label.upper() if case == "upper" else item.label.lower()

        choices, correct = self._make_choices(
            [(label(target), target.spoken, {"correct": True, "picture": target.attribute("picture", "")})]
            + [(label(item), item.spoken, {"correct": False, "picture": item.attribute("picture", "")}) for item in distractors]
        )
        prompt = lesson.prompt_templates[0]
        metadata: dict[str, Any] = {"target": target.label, "vowel": vowel, "word_case": case, "direction": direction}
        if direction == "word":
            metadata["prompt_picture"] = target.attribute("picture", target.label)
            spoken = f"Look at the picture. {prompt}"
        else:
            metadata["prompt_word"] = target.label.upper() if case == "upper" else target.label.lower()
            spoken = f"The word is {target.label}. {prompt}"
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            explanation=f"The picture and the word {target.label} match, and {target.label} has short {vowel}.",
            hint="Name each picture or read each word slowly, then compare.",
            metadata=metadata,
        )

    def _generate_sight_word(self, lesson: Any) -> Question:
        allowed = tuple(lesson.setting("words", ()))
        items = tuple(item for item in self._bank(lesson) if item.label in allowed)
        if len(items) < lesson.choice_count:
            raise LearningDataError(f"sight lesson {lesson.lesson_id} has too few unique words")
        target = self.rng.choice(items)
        distractors = _sample_excluding(self.rng, items, {target}, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [(target.label, target.spoken, {"correct": True})]
            + [(item.label, item.spoken, {"correct": False}) for item in distractors]
        )
        visible = lesson.prompt_templates[0]
        spoken = f"Listen: {target.label}. Choose the word {target.label}."
        return self._question(
            lesson,
            prompt=visible,
            spoken_prompt=spoken,
            choices=choices,
            correct=correct,
            hidden=True,
            explanation=f"The letters in {target.label} match the word you heard.",
            hint="Replay the word, then compare the first and last letters.",
            metadata={"target": target.label},
        )

    def _generate_category_sort(self, lesson: Any) -> Question:
        items = self._bank(lesson)
        groups = self._grouped(items)
        group_count = int(lesson.setting("group_count", 2))
        selected_groups = self.rng.sample(tuple(groups), group_count)
        per_group = lesson.choice_count // group_count
        selected: list[ContentItem] = []
        for group in selected_groups:
            selected.extend(self.rng.sample(groups[group], per_group))
        self.rng.shuffle(selected)
        choices: list[Choice] = []
        correct: list[str] = []
        for index, item in enumerate(selected):
            choice_id = f"c{index}"
            choices.append(
                Choice(choice_id, item.label, item.spoken, {"picture": item.attribute("picture", ""), "categories": selected_groups})
            )
            correct.append(f"{choice_id}={item.group}")
        return self._question(
            lesson,
            prompt=lesson.prompt_templates[0],
            spoken_prompt=lesson.prompt_templates[0],
            choices=tuple(choices),
            correct=tuple(correct),
            requires_submit=True,
            explanation="Each object belongs with other objects of the same kind.",
            hint="Name the object, then ask what kind of thing it is.",
            metadata={"categories": selected_groups},
        )

    def _generate_ordered_sequence(self, lesson: Any) -> Question:
        groups = self._grouped(self._bank(lesson))
        candidates = tuple(values for values in groups.values() if len(values) >= lesson.choice_count)
        if not candidates:
            raise LearningDataError(f"lesson {lesson.lesson_id} has no complete sequence")
        ordered = sorted(self.rng.choice(candidates), key=lambda item: int(item.attribute("order", 0)))[: lesson.choice_count]
        original = [(f"step-{index}", item) for index, item in enumerate(ordered)]
        shuffled = list(original)
        self.rng.shuffle(shuffled)
        choices = tuple(
            Choice(choice_id, item.label, item.spoken, {"picture": item.attribute("picture", "")})
            for choice_id, item in shuffled
        )
        correct = tuple(choice_id for choice_id, _ in original)
        return self._question(
            lesson,
            prompt=lesson.prompt_templates[0],
            spoken_prompt=lesson.prompt_templates[0],
            choices=choices,
            correct=correct,
            requires_submit=True,
            explanation="That order shows the steps from first to last.",
            hint="Find what must happen first, then follow one step at a time.",
            metadata={"sequence_group": ordered[0].group},
        )

    def _number_choices(self, target: int, count: int, *, words: bool = False) -> tuple[tuple[Choice, ...], tuple[str, ...]]:
        candidates = [number for number in range(0, 21) if number != target]
        near = sorted(candidates, key=lambda number: (abs(number - target), number))[: max(6, count + 2)]
        distractors = self.rng.sample(near, count - 1)

        def label(number: int) -> str:
            return _NUMBER_WORDS[number] if words else str(number)

        return self._make_choices(
            [(label(target), label(target), {"correct": True, "number": target})]
            + [(label(number), label(number), {"correct": False, "number": number}) for number in distractors]
        )

    def _generate_number_choice(self, lesson: Any) -> Question:
        minimum = int(lesson.setting("number_min", 0))
        maximum = int(lesson.setting("number_max", 10))
        target = self.rng.randint(minimum, maximum)
        words = lesson.lesson_id.startswith("literacy.") or bool(lesson.setting("show_word_target", True)) and bool(lesson.setting("mixed_forms", False))
        choices, correct = self._number_choices(target, lesson.choice_count, words=words)
        if lesson.setting("mixed_forms", False):
            prompt = f"Which number word matches {target} dots?"
        else:
            prompt = lesson.prompt_templates[0].format(target=target)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"{_NUMBER_WORDS[target]} means {target}.",
            hint="Count slowly or say the number names in order.",
            metadata={"target": target, "choice_form": "word" if words else "numeral"},
        )

    def _generate_count(self, lesson: Any) -> Question:
        minimum = int(lesson.setting("number_min", 0))
        maximum = int(lesson.setting("number_max", 10))
        target = self.rng.randint(minimum, maximum)
        choices, correct = self._number_choices(target, lesson.choice_count)
        object_name = self.rng.choice(("dots", "blocks", "apples", "stars"))
        prompt = lesson.prompt_templates[0]
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"There are {target} {object_name}; touching each once gives the total.",
            hint="Point to each object once and say the next number.",
            metadata={"count": target, "object": object_name},
        )

    def _generate_compare_count(self, lesson: Any) -> Question:
        maximum = int(lesson.setting("number_max", 10))
        comparison = self.rng.choice(("more", "fewer", "same"))
        if comparison == "same":
            left = right = self.rng.randint(1, maximum)
            answer = "same"
        else:
            left, right = self.rng.sample(range(0, maximum + 1), 2)
            if comparison == "more":
                answer = "left group" if left > right else "right group"
            else:
                answer = "left group" if left < right else "right group"
        payloads = [
            (label, label, {"correct": label == answer})
            for label in ("left group", "right group", "same", "count again")
        ]
        choices, correct = self._make_choices(payloads)
        prompt = lesson.prompt_templates[0].format(comparison=comparison)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"The left group has {left} and the right group has {right}, so {answer} is correct.",
            hint="Count each group once, then compare the totals.",
            metadata={"left_count": left, "right_count": right, "comparison": comparison},
        )

    def _generate_missing_number(self, lesson: Any) -> Question:
        minimum = int(lesson.setting("number_min", 0))
        maximum = int(lesson.setting("number_max", 10))
        mode = str(lesson.setting("mode", "missing"))
        if mode == "before_after":
            target = self.rng.randint(minimum + 1, maximum - 1)
            position = self.rng.choice(("before", "after"))
            answer = target - 1 if position == "before" else target + 1
            prompt = lesson.prompt_templates[0].format(position=position, target=target)
            sequence = ()
        else:
            start = self.rng.randint(minimum, maximum - 3)
            sequence_values = (start, start + 1, start + 2, start + 3)
            missing_index = self.rng.choice((1, 2))
            answer = sequence_values[missing_index]
            sequence = tuple(None if index == missing_index else value for index, value in enumerate(sequence_values))
            prompt = lesson.prompt_templates[0]
        choices, correct = self._number_choices(answer, lesson.choice_count)
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"Counting in order shows that {answer} fits there.",
            hint="Say the number sequence slowly from the beginning.",
            metadata={"answer": answer, "sequence": sequence, "mode": mode},
        )

    def _generate_operation(self, lesson: Any) -> Question:
        operation = str(lesson.setting("operation", "add"))
        maximum = int(lesson.setting("number_max", 5))
        if operation in {"add", "compose"}:
            answer = self.rng.randint(1, maximum)
            left = self.rng.randint(0, answer)
            right = answer - left
            symbol = "+"
        else:
            left = self.rng.randint(1, maximum)
            right = self.rng.randint(0, left)
            answer = left - right
            symbol = "-"
        choices, correct = self._number_choices(answer, lesson.choice_count)
        prompt = lesson.prompt_templates[0]
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"{left} {symbol} {right} makes {answer}.",
            hint="Use the picture objects: join them or move some away one at a time.",
            metadata={"left": left, "right": right, "operation": operation, "answer": answer},
        )

    def _generate_pattern(self, lesson: Any) -> Question:
        pattern = str(lesson.setting("pattern", "AB"))
        distinct = len(set(pattern))
        selected = self.rng.sample(_PATTERN_SYMBOLS, distinct)
        symbol_by_letter = {letter: selected[index] for index, letter in enumerate(dict.fromkeys(pattern))}
        repeated = (pattern * 3)[: len(pattern) * 2 + 1]
        sequence = tuple(symbol_by_letter[letter][0] for letter in repeated)
        next_letter = pattern[len(repeated) % len(pattern)]
        answer_label, answer_token = symbol_by_letter[next_letter]
        distractor_symbols = [symbol for symbol in _PATTERN_SYMBOLS if symbol[1] != answer_token]
        distractors = self.rng.sample(distractor_symbols, lesson.choice_count - 1)
        choices, correct = self._make_choices(
            [(answer_label, answer_label, {"correct": True, "picture": answer_token})]
            + [(label, label, {"correct": False, "picture": token}) for label, token in distractors]
        )
        prompt = lesson.prompt_templates[0]
        return self._question(
            lesson,
            prompt=prompt,
            spoken_prompt=prompt,
            choices=choices,
            correct=correct,
            explanation=f"The {pattern} core repeats, so {answer_label} comes next.",
            hint="Find the smallest part that repeats, then say it again.",
            metadata={"pattern_type": pattern, "sequence": sequence},
        )

    def _normalize_response(
        self,
        question: Question,
        response: str | Choice | Sequence[str | Choice] | Mapping[str, str],
    ) -> tuple[str, ...]:
        choice_ids = {choice.id for choice in question.choices}
        label_to_ids: dict[str, list[str]] = defaultdict(list)
        for choice in question.choices:
            label_to_ids[choice.label.casefold()].append(choice.id)

        def normalize_one(value: str | Choice) -> str:
            raw = value.id if isinstance(value, Choice) else str(value).strip()
            if raw in choice_ids:
                return raw
            matching = label_to_ids.get(raw.casefold(), ())
            if len(matching) == 1:
                return matching[0]
            return "invalid"

        if isinstance(response, Mapping):
            return tuple(
                sorted(f"{normalize_one(choice_id)}={str(category).strip()}" for choice_id, category in response.items())
            )
        if isinstance(response, (str, Choice)):
            return (normalize_one(response),)
        if not isinstance(response, Sequence):
            raise TypeError("response must be a choice id, sequence, or category mapping")
        return tuple(normalize_one(value) for value in response)

    def evaluate(
        self,
        question: Question,
        response: str | Choice | Sequence[str | Choice] | Mapping[str, str],
        *,
        attempt_number: int = 1,
        scaffold_used: bool = False,
    ) -> Evaluation:
        """Check one response and return retry/reveal guidance."""

        if not isinstance(question, Question):
            raise TypeError("question must be a Question")
        if not isinstance(attempt_number, int) or attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        normalized = self._normalize_response(question, response)
        if question.interaction is InteractionKind.ORDERED_SEQUENCE:
            correct = normalized == question.correct_answers
        elif question.requires_submit or len(question.correct_answers) > 1:
            correct = set(normalized) == set(question.correct_answers) and len(normalized) == len(set(normalized))
        else:
            correct = len(normalized) == 1 and normalized[0] == question.correct_answers[0]
        reveal = not correct and attempt_number >= self.max_attempts
        retry = not correct and not reveal
        answer_labels = self._answer_labels(question)
        if correct:
            feedback = f"Yes! {question.explanation or 'That answer fits.'}"
        elif retry:
            feedback = f"Almost. {question.hint or 'Look carefully at each choice.'} Try once more."
        else:
            shown = ", then ".join(answer_labels) if question.interaction is InteractionKind.ORDERED_SEQUENCE else ", ".join(answer_labels)
            feedback = f"Let's learn it together. The answer is {shown}. {question.explanation}"
        return Evaluation(
            correct=correct,
            normalized_response=normalized,
            attempt_number=attempt_number,
            feedback=feedback,
            try_again=retry,
            reveal_answer=reveal,
            revealed_answers=question.correct_answers if reveal else (),
            scaffold_used=scaffold_used,
        )

    @staticmethod
    def _answer_labels(question: Question) -> tuple[str, ...]:
        labels: list[str] = []
        for token in question.correct_answers:
            choice_id, separator, category = token.partition("=")
            choice = question.choice(choice_id)
            label = choice.label if choice is not None else choice_id
            labels.append(f"{label} goes in {category}" if separator else label)
        return tuple(labels)

    def start_session(
        self,
        profile_id: str,
        plan_id: str | LearningPlan | None = None,
        *,
        lesson_ids: Sequence[str] | None = None,
        plan: LearningPlan | None = None,
        question_count: int | None = None,
        repetitions: int | None = None,
    ) -> LearningSession:
        """Create an immutable resumable session.

        Passing only ``profile_id`` is supported for a kiosk quick-start and
        uses the first curriculum activity.  A teacher plan preserves its
        ordered lesson sequence and cycles through it without random
        reordering.  ``repetitions`` generates that many fresh, consecutive
        questions for one lesson before advancing to the next lesson.
        """

        if isinstance(plan_id, LearningPlan):
            if plan is not None:
                raise ValueError("pass a plan only once")
            plan = plan_id
            plan_id = plan.plan_id
        if plan is not None:
            if profile_id != plan.profile_id:
                raise ValueError("plan belongs to a different learner profile")
            plan_id = plan.plan_id
            lesson_ids = plan.lesson_ids
            if question_count is None:
                question_count = plan.questions_per_session
            if repetitions is None:
                repetitions = plan.repetitions
        selected = tuple(lesson_ids or (self.catalog.lessons[0].lesson_id,))
        for lesson_id in selected:
            self.catalog.get(lesson_id)
        count = question_count if question_count is not None else min(8, max(3, len(selected)))
        if not isinstance(count, int) or not 1 <= count <= 20:
            raise ValueError("question_count must be between 1 and 20")
        repeat_count = 1 if repetitions is None else repetitions
        if (
            isinstance(repeat_count, bool)
            or not isinstance(repeat_count, int)
            or not 1 <= repeat_count <= 10
        ):
            raise ValueError("repetitions must be between 1 and 10")
        lesson_cycle = tuple(
            lesson_id
            for lesson_id in selected
            for _ in range(repeat_count)
        )
        scheduled = tuple(
            lesson_cycle[index % len(lesson_cycle)] for index in range(count)
        )
        # Generate rather than copy each scheduled question: repeated lesson
        # blocks therefore consume fresh RNG state and receive unique IDs.
        questions = tuple(self.generate_question(lesson_id) for lesson_id in scheduled)
        now = _iso(self._clock())
        return LearningSession(
            session_id=self._new_id("session"),
            profile_id=profile_id,
            plan_id=str(plan_id) if plan_id is not None else None,
            questions=questions,
            question_index=0,
            current_attempt=0,
            scaffolded=False,
            attempts=(),
            started_at=now,
            updated_at=now,
        )

    @staticmethod
    def current_question(session: LearningSession) -> Question | None:
        if not isinstance(session, LearningSession):
            raise TypeError("session must be a LearningSession")
        return session.current_question

    @staticmethod
    def replay(session: LearningSession) -> str:
        """Return replay text; no attempt or score is created or changed."""

        question = session.current_question
        return question.spoken_prompt if question is not None else "This learning session is complete."

    def record_replay(self, session: LearningSession) -> LearningSession:
        """Optionally persist replay count while leaving attempts unchanged."""

        return replace(
            session,
            replay_count=session.replay_count + 1,
            updated_at=_iso(self._clock()),
        )

    def submit(
        self,
        session: LearningSession,
        response: str | Choice | Sequence[str | Choice] | Mapping[str, str],
        *,
        elapsed_seconds: float = 0.0,
    ) -> SessionTransition:
        """Apply one answer, retry at most once, then advance or reveal."""

        if not isinstance(session, LearningSession):
            raise TypeError("session must be a LearningSession")
        question = session.current_question
        if question is None:
            raise LearningDataError("cannot answer a completed session")
        attempt_number = session.current_attempt + 1
        evaluation = self.evaluate(
            question,
            response,
            attempt_number=attempt_number,
            scaffold_used=session.scaffolded,
        )
        timestamp = _iso(self._clock())
        attempt = AttemptRecord(
            attempt_id=self._new_id("attempt"),
            session_id=session.session_id,
            profile_id=session.profile_id,
            plan_id=session.plan_id,
            lesson_id=question.lesson_id,
            skills=question.skills,
            question_id=question.question_id,
            correct_answers=question.correct_answers,
            response=evaluation.normalized_response,
            correct=evaluation.correct,
            attempt_number=attempt_number,
            scaffolded=session.scaffolded,
            hint_used=session.scaffolded,
            revealed=evaluation.reveal_answer,
            elapsed_seconds=elapsed_seconds,
            timestamp=timestamp,
            generation_version=question.generation_version,
        )
        if evaluation.try_again:
            updated = replace(
                session,
                current_attempt=attempt_number,
                scaffolded=True,
                attempts=session.attempts + (attempt,),
                updated_at=timestamp,
            )
        else:
            updated = replace(
                session,
                question_index=session.question_index + 1,
                current_attempt=0,
                scaffolded=False,
                attempts=session.attempts + (attempt,),
                updated_at=timestamp,
            )
        return SessionTransition(updated, evaluation, attempt, updated.current_question)

    def eligible_lesson_ids(
        self,
        plan: LearningPlan,
        attempts: Iterable[AttemptRecord],
        *,
        mastery_threshold: float = 0.8,
        minimum_evidence: int = 5,
    ) -> tuple[str, ...]:
        """Apply a plan's optional sequential mastery gate."""

        for lesson_id in plan.lesson_ids:
            self.catalog.get(lesson_id)
        if not plan.mastery_gate:
            return plan.lesson_ids
        eligible: list[str] = []
        all_attempts = tuple(attempts)
        for lesson_id in plan.lesson_ids:
            eligible.append(lesson_id)
            mastery = summarize_mastery(
                (attempt for attempt in all_attempts if attempt.lesson_id == lesson_id),
                skill=lesson_id,
                mastery_threshold=mastery_threshold,
                minimum_evidence=minimum_evidence,
            )
            if mastery.status is not MasteryStatus.MASTERED:
                break
        return tuple(eligible)


def _question_evidence(attempts: Iterable[AttemptRecord]) -> list[list[AttemptRecord]]:
    grouped: dict[tuple[str, str], list[AttemptRecord]] = {}
    for attempt in attempts:
        key = (attempt.session_id, attempt.question_id)
        grouped.setdefault(key, []).append(attempt)
    # Timestamp order makes "recent" evidence independent of JSON/load order;
    # Python's stable sort preserves input order for identical timestamps.
    ordered = sorted(grouped.values(), key=lambda group: max(item.timestamp for item in group))
    return [sorted(group, key=lambda item: item.attempt_number) for group in ordered]


def _rates(attempts: Sequence[AttemptRecord]) -> tuple[int, float, float, float, float]:
    evidence = _question_evidence(attempts)
    if not evidence:
        return 0, 0.0, 0.0, 0.0, 0.0
    first = sum(bool(group[0].correct and group[0].attempt_number == 1) for group in evidence) / len(evidence)
    eventual = sum(any(item.correct for item in group) for group in evidence) / len(evidence)
    grade = 0.60 * first + 0.40 * eventual
    recent = evidence[-min(5, len(evidence)) :]
    trend = sum(any(item.correct for item in group) for group in recent) / len(recent)
    return len(evidence), first, eventual, grade, trend


def summarize_mastery(
    attempts: Iterable[AttemptRecord],
    *,
    skill: str,
    mastery_threshold: float = 0.8,
    minimum_evidence: int = 5,
    recent_evidence_limit: int = DEFAULT_RECENT_EVIDENCE,
) -> SkillMastery:
    """Summarize recent evidence for one skill with no one-question mastery."""

    if not 0.5 <= mastery_threshold <= 1.0:
        raise ValueError("mastery_threshold must be between 0.5 and 1.0")
    if not isinstance(minimum_evidence, int) or minimum_evidence < 2:
        raise ValueError("minimum_evidence must be at least 2")
    if not isinstance(recent_evidence_limit, int) or recent_evidence_limit < minimum_evidence:
        raise ValueError("recent_evidence_limit must cover minimum_evidence")
    relevant = tuple(
        attempt
        for attempt in attempts
        if skill == attempt.lesson_id or skill in attempt.skills
    )
    evidence_groups = _question_evidence(relevant)[-recent_evidence_limit:]
    recent_attempts = tuple(item for group in evidence_groups for item in group)
    evidence_count, first, eventual, grade, trend = _rates(recent_attempts)
    if evidence_count == 0:
        status = MasteryStatus.NOT_STARTED
    elif evidence_count < minimum_evidence:
        status = MasteryStatus.IN_PROGRESS
    elif (
        eventual + 1e-12 >= mastery_threshold
        and first + 1e-12 >= max(0.50, mastery_threshold - 0.20)
    ):
        status = MasteryStatus.MASTERED
    else:
        status = MasteryStatus.NEEDS_PRACTICE
    return SkillMastery(
        skill=skill,
        status=status,
        evidence_count=evidence_count,
        attempt_count=len(recent_attempts),
        first_try_accuracy=round(first, 4),
        eventual_accuracy=round(eventual, 4),
        percentage_grade=round(grade * 100.0, 1),
        recent_trend=round(trend, 4),
        practiced_seconds=round(sum(item.elapsed_seconds for item in recent_attempts), 2),
    )


def summarize_plan(
    plan: LearningPlan,
    attempts: Iterable[AttemptRecord],
    *,
    mastery_threshold: float = 0.8,
    minimum_evidence: int = 5,
    recent_evidence_limit: int = DEFAULT_RECENT_EVIDENCE,
) -> PlanReport:
    """Return plan grade, completion, trend, time, and per-skill mastery."""

    plan_attempts = tuple(
        attempt
        for attempt in attempts
        if attempt.profile_id == plan.profile_id
        and (attempt.plan_id == plan.plan_id or attempt.plan_id is None)
        and attempt.lesson_id in plan.lesson_ids
    )
    lesson_mastery = tuple(
        summarize_mastery(
            (attempt for attempt in plan_attempts if attempt.lesson_id == lesson_id),
            skill=lesson_id,
            mastery_threshold=mastery_threshold,
            minimum_evidence=minimum_evidence,
            recent_evidence_limit=recent_evidence_limit,
        )
        for lesson_id in plan.lesson_ids
    )
    started = sum(item.status is not MasteryStatus.NOT_STARTED for item in lesson_mastery)
    mastered = sum(item.status is MasteryStatus.MASTERED for item in lesson_mastery)
    evidence_count, first, eventual, grade, trend = _rates(plan_attempts)
    accuracy = (
        sum(attempt.correct for attempt in plan_attempts) / len(plan_attempts)
        if plan_attempts
        else 0.0
    )
    if mastered == len(plan.lesson_ids):
        status = MasteryStatus.MASTERED
    elif started == 0:
        status = MasteryStatus.NOT_STARTED
    elif any(item.status is MasteryStatus.NEEDS_PRACTICE for item in lesson_mastery):
        status = MasteryStatus.NEEDS_PRACTICE
    else:
        status = MasteryStatus.IN_PROGRESS
    # Per-skill summaries are useful in addition to lesson completion.
    skill_ids = tuple(dict.fromkeys(skill for attempt in plan_attempts for skill in attempt.skills))
    skill_mastery = tuple(
        summarize_mastery(
            plan_attempts,
            skill=skill,
            mastery_threshold=mastery_threshold,
            minimum_evidence=minimum_evidence,
            recent_evidence_limit=recent_evidence_limit,
        )
        for skill in skill_ids
    )
    return PlanReport(
        plan_id=plan.plan_id,
        status=status,
        total_lessons=len(plan.lesson_ids),
        started_lessons=started,
        mastered_lessons=mastered,
        completion_percent=round(100.0 * mastered / len(plan.lesson_ids), 1),
        percentage_grade=round(100.0 * grade, 1),
        accuracy=round(accuracy, 4),
        first_try_accuracy=round(first, 4),
        eventual_accuracy=round(eventual, 4),
        attempt_count=len(plan_attempts),
        evidence_count=evidence_count,
        recent_trend=round(trend, 4),
        practiced_seconds=round(sum(attempt.elapsed_seconds for attempt in plan_attempts), 2),
        skills=skill_mastery,
    )


summarize_progress = summarize_plan


__all__ = [
    "DEFAULT_RECENT_EVIDENCE",
    "MAX_QUESTION_ATTEMPTS",
    "LearningEngine",
    "summarize_mastery",
    "summarize_plan",
    "summarize_progress",
]
