"""Bayesian, applicability-aware Twenty Questions engine."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ANSWER_FLOOR = 0.005
MODULE_DATA_DIR = Path(__file__).resolve().parent / "data"
LEARNED_ENTITIES_FILE = MODULE_DATA_DIR / "twenty_questions_learned.json"
LEGACY_LEARNED_ENTITIES_FILE = (
    Path(__file__).resolve().parent.parent
    / "twenty_questions_learned.json"
)
ANSWERS = ("yes", "no", "maybe", "unknown")


@dataclass(frozen=True)
class Fact:
    """Known yes/no, variable, probabilistic, or explicitly unknown evidence."""

    state: str
    yes_probability: float | None = None

    @classmethod
    def yes(cls) -> Fact:
        return cls("yes")

    @classmethod
    def no(cls) -> Fact:
        return cls("no")

    @classmethod
    def variable(cls) -> Fact:
        return cls("variable")

    @classmethod
    def unknown(cls) -> Fact:
        return cls("unknown")

    @classmethod
    def probabilistic(cls, probability: float) -> Fact:
        return cls("probabilistic", min(max(float(probability), .02), .98))

    @property
    def known(self) -> bool:
        return self.state != "unknown"

    def likelihoods(self) -> dict[str, float]:
        if self.state == "yes":
            return {"yes": .93, "no": .025, "maybe": .035, "unknown": .01}
        if self.state == "no":
            return {"yes": .025, "no": .93, "maybe": .035, "unknown": .01}
        if self.state == "variable":
            return {"yes": .22, "no": .22, "maybe": .52, "unknown": .04}
        if self.state == "probabilistic":
            yes = self.yes_probability if self.yes_probability is not None else .5
            return {
                "yes": yes * .90,
                "no": (1 - yes) * .90,
                "maybe": .07,
                "unknown": .03,
            }
        # Unknown facts must not favor either yes or no.
        return {"yes": .25, "no": .25, "maybe": .25, "unknown": .25}


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    category: str
    applicable_types: frozenset[str] = frozenset()
    prerequisites: tuple[str, ...] = ()
    excluded_traits: tuple[str, ...] = ()
    min_coverage: float = .42
    ambiguity: float = 0.0
    difficulty: float = 0.0
    semantic_group: str | None = None


@dataclass
class Entity:
    entity_id: str
    name: str
    entity_type: str
    popularity: float
    facts: dict[str, Fact] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)
    observations: dict[str, dict[str, int]] = field(default_factory=dict)
    source_confidence: float = .8

    def fact(self, key: str) -> Fact:
        return self.facts.get(key, Fact.unknown())

    def likelihoods(self, key: str) -> dict[str, float]:
        return self.fact(key).likelihoods()


def question(
    key: str,
    text: str,
    category: str,
    *,
    types: Iterable[str] = (),
    requires: Iterable[str] = (),
    excludes: Iterable[str] = (),
    coverage: float = .42,
    ambiguity: float = 0.0,
    difficulty: float = 0.0,
    group: str | None = None,
) -> Question:
    return Question(
        key,
        text,
        category,
        frozenset(types),
        tuple(requires),
        tuple(excludes),
        coverage,
        ambiguity,
        difficulty,
        group,
    )


PHYSICAL_TYPES = {
    "animal", "plant", "food", "drink", "device", "vehicle", "furniture",
    "tool", "object", "clothing", "instrument", "place", "building",
    "person", "substance", "chemical_element", "natural_phenomenon",
    "infrastructure",
}
MEDIA_TYPES = {"media", "game", "fictional_character", "franchise"}


QUESTIONS = (
    question("physical", "Is it a physical thing?", "ontology", coverage=.65),
    question("alive", "Is it alive?", "ontology", types=PHYSICAL_TYPES),
    question("fictional", "Does it exist primarily in fiction?", "ontology"),
    question("person", "Is it a person or character?", "ontology"),
    question("place", "Is it a place?", "ontology"),
    question("building", "Is it a building?", "ontology", requires=("physical",)),
    question("manufactured", "Is it made or significantly modified by people?", "ontology", types=PHYSICAL_TYPES),
    question("abstract", "Is it an abstract idea or concept?", "ontology"),
    question("animal", "Is it an animal?", "ontology", types=PHYSICAL_TYPES, requires=("alive",)),
    question("plant", "Is it a plant?", "ontology", types=PHYSICAL_TYPES, requires=("alive",)),
    question("substance", "Is it a material or substance?", "ontology"),
    question("event", "Is it an event?", "ontology"),
    question("organization", "Is it an organization?", "ontology"),
    question("normally_indoors", "Is it normally located indoors?", "location", types=PHYSICAL_TYPES),
    question("inside_home", "Is it commonly found inside a home?", "location", types=PHYSICAL_TYPES),
    question("outdoors", "Is it normally outdoors?", "location", types=PHYSICAL_TYPES),
    question("public_place", "Is it commonly found in a public place?", "location", requires=("physical",)),
    question("road_sidewalk", "Is it commonly found in a road or sidewalk?", "location", types={"infrastructure", "object", "vehicle"}, requires=("outdoors",)),
    question("underground", "Is part of it normally underground?", "location", types={"infrastructure", "building", "object"}, requires=("physical",)),
    question("water", "Is it strongly associated with water?", "location"),
    question("kitchen", "Is it commonly associated with a kitchen?", "household", types=PHYSICAL_TYPES),
    question("bathroom", "Is it commonly associated with a bathroom?", "household", types=PHYSICAL_TYPES),
    question("bedroom", "Is it commonly associated with a bedroom?", "household", types=PHYSICAL_TYPES),
    question("metal", "Is it primarily made of metal?", "material", types=PHYSICAL_TYPES),
    question("wood", "Is it primarily made of wood?", "material", types=PHYSICAL_TYPES),
    question("plastic", "Is it primarily made of plastic?", "material", types=PHYSICAL_TYPES),
    question("glass", "Is glass a major material in it?", "material", types=PHYSICAL_TYPES),
    question("fabric", "Is it primarily made of fabric?", "material", types=PHYSICAL_TYPES),
    question("circular", "Is a typical example usually circular?", "shape", types=PHYSICAL_TYPES, ambiguity=.03),
    question("flat", "Is it mostly flat?", "shape", types=PHYSICAL_TYPES, ambiguity=.03),
    question("hollow", "Is it normally hollow?", "shape", types=PHYSICAL_TYPES, ambiguity=.04),
    question("handheld", "Can a typical example be held in one hand?", "size", types=PHYSICAL_TYPES, ambiguity=.04),
    question("larger_person", "Is a typical example larger than a person?", "size", types=PHYSICAL_TYPES, ambiguity=.05),
    question("heavy", "Would a typical example be difficult for one person to lift?", "size", types=PHYSICAL_TYPES, ambiguity=.05),
    question("edible", "Can people normally eat or drink it?", "function", types=PHYSICAL_TYPES),
    question("practical_task", "Is its main purpose a practical task?", "function"),
    question("entertainment", "Is entertainment its primary purpose?", "function"),
    question("sports", "Is it strongly associated with sports or exercise?", "function"),
    question("wearable", "Is it normally worn on the body?", "function", types=PHYSICAL_TYPES),
    question("covers_opening", "Is it designed to cover an opening?", "function", types={"infrastructure", "object", "building"}),
    question("provides_access", "Is it designed to provide access to something?", "function", types={"infrastructure", "building", "object"}),
    question("travel_over", "Can people or vehicles normally travel over it?", "function", types={"infrastructure", "object", "place"}),
    question("fixed_installation", "Is it normally installed in a fixed location?", "installation", types=PHYSICAL_TYPES),
    question("public_infrastructure", "Is it part of public infrastructure?", "infrastructure", types={"infrastructure", "building", "place", "object"}),
    question("city_utility", "Is it normally maintained by a city or utility?", "infrastructure", types={"infrastructure", "building", "place"}),
    question("electric", "Does it normally use electricity?", "technology", types=PHYSICAL_TYPES),
    question("screen", "Does it normally have an electronic screen?", "technology", types={"device", "vehicle", "object"}),
    question("internet", "Does it commonly connect to the internet?", "technology", types={"device", "vehicle"}),
    question("sound", "Is producing sound central to what it does?", "technology", ambiguity=.03),
    question("vehicle", "Is it primarily used for transportation?", "transportation"),
    question("wheels", "Does a typical example have wheels?", "transportation", types=PHYSICAL_TYPES),
    question("flies", "Can it normally fly?", "transportation", types=PHYSICAL_TYPES),
    question("media", "Is it a form of media?", "media"),
    question("moving_images", "Does it primarily display moving images?", "media", types=MEDIA_TYPES | {"device"}),
    question("interactive", "Is it primarily interactive?", "games", types=MEDIA_TYPES),
    question("competitive", "Is it normally competitive?", "games", types={"game", "sport"}),
    question("playable", "Is it something people play?", "games"),
    question("character", "Is it a fictional character?", "fiction", types=MEDIA_TYPES),
    question("animation", "Is it strongly associated with animation?", "fiction", types=MEDIA_TYPES),
    question("comic_origin", "Did it originate in comic books?", "fiction", types=MEDIA_TYPES),
    question("real_person", "Is it a real individual person?", "people"),
    question("famous", "Is it widely famous?", "people", ambiguity=.07),
    question("country", "Is it a country?", "places", types={"place"}),
    question("city", "Is it a city?", "places", types={"place"}),
    question("historical", "Is it primarily historical?", "events"),
    question("chemical_element", "Is it a chemical element?", "substances"),
    question("gas_room_temp", "Is it normally a gas at room temperature?", "substances", types={"chemical_element", "substance"}),
    question("emotion", "Is it an emotion?", "abstract"),
    question("scientific", "Is it a scientific concept?", "abstract"),
    question("nature", "Does it occur naturally?", "nature"),
    question("weather", "Is it a weather phenomenon?", "nature"),
    question("before_1900", "Did it exist before the year 1900?", "time", ambiguity=.02),
    question("after_2000", "Did it originate after the year 2000?", "time", ambiguity=.02, group="origin_period"),
    question("american_origin", "Did it originate in the United States?", "culture", ambiguity=.05),
    question("japanese_origin", "Did it originate in Japan?", "culture", ambiguity=.05, group="cultural_origin"),
)

QUESTION_BY_KEY = {item.key: item for item in QUESTIONS}


def facts(*, yes: Iterable[str] = (), no: Iterable[str] = (), maybe: Iterable[str] = ()) -> dict[str, Fact]:
    result = {key: Fact.no() for key in no}
    result.update({key: Fact.yes() for key in yes})
    result.update({key: Fact.variable() for key in maybe})
    return result


def entity(
    entity_id: str,
    name: str,
    entity_type: str,
    popularity: float,
    *,
    yes: Iterable[str] = (),
    no: Iterable[str] = (),
    maybe: Iterable[str] = (),
    aliases: Iterable[str] = (),
) -> Entity:
    return Entity(
        entity_id,
        name,
        entity_type,
        popularity,
        facts(yes=yes, no=no, maybe=maybe),
        set(aliases),
    )


BASE_NO_PHYSICAL = ("alive", "abstract", "fictional", "edible", "vehicle")
BASE_MANUFACTURED = ("physical", "manufactured")
INFRA_YES = ("physical", "manufactured", "outdoors", "public_place", "fixed_installation", "public_infrastructure", "city_utility")
INFRA_NO = ("alive", "abstract", "fictional", "edible", "inside_home", "normally_indoors", "entertainment", "vehicle", "wearable", "electric")


SEED_ENTITIES = (
    entity("animal:cat", "cat", "animal", 1.0, yes=("physical", "alive", "animal", "nature", "inside_home"), no=("manufactured", "abstract", "vehicle", "edible", "larger_person")),
    entity("animal:dog", "dog", "animal", 1.0, yes=("physical", "alive", "animal", "nature", "inside_home"), no=("manufactured", "abstract", "vehicle", "edible")),
    entity("plant:tree", "tree", "plant", .75, yes=("physical", "alive", "plant", "nature", "outdoors", "larger_person", "before_1900"), no=("manufactured", "abstract", "inside_home", "vehicle")),
    entity("food:pizza", "pizza", "food", .9, yes=BASE_MANUFACTURED + ("edible", "kitchen", "handheld"), no=BASE_NO_PHYSICAL + ("electric", "outdoors", "larger_person")),
    entity("device:phone", "smartphone", "device", 1.0, yes=BASE_MANUFACTURED + ("electric", "screen", "internet", "handheld", "inside_home", "practical_task"), no=BASE_NO_PHYSICAL + ("larger_person", "wheels", "nature", "before_1900")),
    entity("device:television", "television", "device", .9, yes=BASE_MANUFACTURED + ("electric", "screen", "sound", "moving_images", "entertainment", "normally_indoors", "inside_home"), no=BASE_NO_PHYSICAL + ("handheld", "vehicle", "wheels", "nature"), maybe=("larger_person",)),
    entity("device:monitor", "computer monitor", "device", .55, yes=BASE_MANUFACTURED + ("electric", "screen", "normally_indoors", "inside_home", "practical_task"), no=BASE_NO_PHYSICAL + ("sound", "moving_images", "vehicle", "nature")),
    entity("vehicle:car", "car", "vehicle", 1.0, yes=BASE_MANUFACTURED + ("vehicle", "wheels", "larger_person", "metal", "outdoors", "practical_task"), no=BASE_NO_PHYSICAL + ("handheld", "inside_home", "nature")),
    entity("object:chair", "chair", "furniture", .75, yes=BASE_MANUFACTURED + ("inside_home", "normally_indoors", "practical_task"), no=BASE_NO_PHYSICAL + ("electric", "wheels", "nature", "outdoors", "metal")),
    entity("object:hammer", "hammer", "tool", .55, yes=BASE_MANUFACTURED + ("handheld", "metal", "practical_task"), no=BASE_NO_PHYSICAL + ("electric", "wheels", "edible", "larger_person")),
    entity("object:book", "book", "media", .8, yes=BASE_MANUFACTURED + ("handheld", "inside_home", "media", "entertainment", "before_1900"), no=BASE_NO_PHYSICAL + ("electric", "screen", "wheels", "nature")),
    entity("place:mountain", "mountain", "place", .6, yes=("physical", "place", "outdoors", "larger_person", "nature", "before_1900"), no=("manufactured", "alive", "abstract", "inside_home", "electric", "vehicle")),
    entity("person:human", "real person", "person", .7, yes=("physical", "alive", "animal", "person", "real_person", "nature"), no=("manufactured", "abstract", "fictional", "vehicle")),
    entity("character:batman", "Batman character", "fictional_character", .85, yes=("fictional", "person", "character", "entertainment", "comic_origin", "before_1900"), no=("physical", "alive", "real_person", "place")),
    entity("character:mario", "Mario character", "fictional_character", .9, yes=("fictional", "person", "character", "entertainment", "interactive", "japanese_origin"), no=("physical", "alive", "real_person", "place", "before_1900")),
    entity("media:movie", "movie", "media", .7, yes=("abstract", "manufactured", "entertainment", "media", "moving_images", "sound"), no=("physical", "alive", "vehicle", "edible")),
    entity("media:video_game", "video game", "game", .8, yes=("abstract", "manufactured", "entertainment", "media", "interactive", "playable", "electric", "screen", "sound"), no=("physical", "alive", "before_1900")),
    entity("game:chess", "chess", "game", .7, yes=("abstract", "manufactured", "entertainment", "interactive", "competitive", "playable", "before_1900"), no=("physical", "alive", "electric", "screen")),
    entity("concept:love", "love", "emotion", .7, yes=("abstract", "emotion", "before_1900"), no=("physical", "alive", "manufactured", "place", "electric")),
    entity("concept:gravity", "gravity", "scientific_concept", .55, yes=("abstract", "scientific", "nature", "before_1900"), no=("physical", "alive", "manufactured", "person", "place")),
    entity("event:war", "war", "historical_event", .4, yes=("abstract", "event", "historical", "manufactured", "before_1900"), no=("physical", "alive", "edible", "place", "nature")),
    entity("substance:water", "water", "substance", .9, yes=("physical", "substance", "water", "nature", "edible", "before_1900"), no=("manufactured", "alive", "abstract", "vehicle", "electric")),
    entity("element:oxygen", "oxygen", "chemical_element", .6, yes=("physical", "substance", "chemical_element", "gas_room_temp", "nature", "before_1900"), no=("manufactured", "alive", "abstract", "edible", "vehicle")),
    entity("phenomenon:rain", "rain", "natural_phenomenon", .75, yes=("physical", "water", "nature", "weather", "before_1900"), no=("manufactured", "alive", "abstract", "electric", "vehicle")),
    entity("infrastructure:manhole_cover", "manhole cover", "infrastructure", .52, yes=INFRA_YES + ("road_sidewalk", "metal", "circular", "flat", "heavy", "covers_opening", "provides_access", "travel_over", "underground", "before_1900"), no=INFRA_NO + ("handheld", "larger_person", "wheels", "nature", "kitchen", "sports", "practical_task"), aliases=("a manhole cover",)),
    entity("infrastructure:street_sign", "street sign", "infrastructure", .5, yes=INFRA_YES + ("road_sidewalk", "metal", "provides_access", "before_1900"), no=INFRA_NO + ("circular", "covers_opening", "travel_over", "underground", "handheld", "larger_person")),
    entity("infrastructure:fire_hydrant", "fire hydrant", "infrastructure", .48, yes=INFRA_YES + ("road_sidewalk", "metal", "water", "provides_access", "underground", "before_1900"), no=INFRA_NO + ("circular", "covers_opening", "travel_over", "handheld", "larger_person")),
    entity("infrastructure:utility_pole", "utility pole", "infrastructure", .43, yes=INFRA_YES + ("road_sidewalk", "wood", "larger_person", "electric", "before_1900"), no=INFRA_NO + ("circular", "covers_opening", "travel_over", "handheld")),
    entity("infrastructure:traffic_barrier", "traffic barrier", "infrastructure", .35, yes=INFRA_YES + ("road_sidewalk", "travel_over"), no=INFRA_NO + ("circular", "covers_opening", "underground", "electric")),
    entity("infrastructure:drain_cover", "drain cover", "infrastructure", .4, yes=INFRA_YES + ("road_sidewalk", "metal", "flat", "covers_opening", "travel_over", "underground"), no=INFRA_NO + ("electric", "wheels", "larger_person")),
    entity("object:outdoor_bench", "outdoor bench", "furniture", .42, yes=BASE_MANUFACTURED + ("outdoors", "public_place", "fixed_installation", "practical_task", "before_1900"), no=BASE_NO_PHYSICAL + ("inside_home", "electric", "wheels", "covers_opening")),
    entity("infrastructure:mailbox", "mailbox", "infrastructure", .48, yes=INFRA_YES + ("road_sidewalk", "metal", "provides_access"), no=INFRA_NO + ("circular", "travel_over", "underground", "larger_person")),
)


@dataclass(frozen=True)
class Turn:
    question_key: str
    question: str
    answer: str
    was_guess: bool = False
    guessed_entity_id: str | None = None


@dataclass(frozen=True)
class Compatibility:
    average_likelihood: float
    coverage: float
    contradictions: int
    posterior: float
    margin: float = 0.0


class TwentyQuestionsGame:
    """Maintain belief, select questions, learn losses, and enforce the budget."""

    MAX_QUESTIONS = 20

    def __init__(
        self,
        learned_path: Path | None = None,
        *,
        debug: bool = False,
    ) -> None:
        self.learned_path = learned_path or LEARNED_ENTITIES_FILE
        self.debug = debug
        self.entities: dict[str, Entity] = {}
        self.log_scores: dict[str, float] = {}
        self.active = False
        self.awaiting_reveal = False
        self.question_count = 0
        self.history: list[Turn] = []
        self.asked_keys: set[str] = set()
        self.asked_groups: set[str] = set()
        self.rejected: set[str] = set()
        self.rejected_names: set[str] = set()
        self.current_question: Question | None = None
        self.current_guess: Entity | None = None
        self.last_question_score = 0.0
        self.last_question_coverage = 0.0
        self.expansion_requests = 0
        self.priority_categories: set[str] = set()

    @staticmethod
    def is_start_request(text: str) -> bool:
        normalized = " ".join(text.lower().strip().rstrip("?.!").split())
        return bool(
            re.search(
                r"\b(?:play|start|let'?s play)\b.*\b(?:20|twenty)\s+questions\b",
                normalized,
            )
            or normalized in {"20 questions", "twenty questions"}
        )

    @staticmethod
    def parse_answer(text: str) -> str | None:
        normalized = text.lower().strip()
        normalized = re.sub(r"^[\s\-\u2013\u2014*•]+", "", normalized)
        normalized = re.sub(r"^(?:oh|well|um|uh|okay|ok)[,.\s]+", "", normalized)
        normalized = re.sub(r"^[^\w']+|[^\w']+$", "", normalized)
        normalized = " ".join(normalized.split())
        groups = {
            "yes": {"yes", "yep", "yeah", "correct", "it is", "sure"},
            "no": {"no", "nope", "nah", "incorrect", "it isn't", "it is not"},
            "maybe": {"maybe", "sometimes", "probably", "possibly", "sort of", "kind of", "it depends"},
            "unknown": {"i don't know", "i dont know", "don't know", "dont know", "not sure", "unknown"},
            "quit": {"stop", "quit", "end game", "cancel"},
        }
        return next((answer for answer, words in groups.items() if normalized in words), None)

    def start(self) -> str:
        self.entities = {
            item.entity_id: copy.deepcopy(item) for item in SEED_ENTITIES
        }
        names = {
            self._canonical_name(item.name): item
            for item in self.entities.values()
        }
        for learned in self._load_learned():
            existing = names.get(self._canonical_name(learned.name))
            if existing is None:
                self.entities[learned.entity_id] = learned
                names[self._canonical_name(learned.name)] = learned
                continue
            existing.aliases.update(learned.aliases)
            existing.aliases.add(learned.name)
            for key, fact in learned.facts.items():
                existing.facts.setdefault(key, fact)
            for key, counts in learned.observations.items():
                current = existing.observations.setdefault(
                    key,
                    {answer: 0 for answer in ANSWERS},
                )
                for answer, count in counts.items():
                    current[answer] = current.get(answer, 0) + count
        total_prior = sum(max(item.popularity, .01) for item in self.entities.values())
        self.log_scores = {
            entity_id: math.log(max(item.popularity, .01) / total_prior)
            for entity_id, item in self.entities.items()
        }
        self.active = True
        self.awaiting_reveal = False
        self.question_count = 0
        self.history = []
        self.asked_keys = set()
        self.asked_groups = set()
        self.rejected = set()
        self.rejected_names = set()
        self.current_question = None
        self.current_guess = None
        self.expansion_requests = 0
        persisted = self._read_persistence()
        raw_confusions = persisted.get("confusions", {})
        if not isinstance(raw_confusions, dict):
            raw_confusions = {}
        self.priority_categories = {
            str(category)
            for confusion in raw_confusions.values()
            if isinstance(confusion, dict)
            for category in confusion.get("priority_categories", [])
        }
        intro = (
            "Okay! Think of anything, but don't tell me what it is. "
            "Answer yes, no, maybe, or I don't know. "
        )
        return intro + self.next_move()

    def accept_answer(self, text: str) -> str | None:
        answer = self.parse_answer(text)
        if answer is None:
            return "Please answer yes, no, maybe, or I don't know."
        if answer == "quit":
            self.active = False
            return "Okay, game over!"

        if self.current_guess is not None:
            guess = self.current_guess
            self.history.append(
                Turn(
                    f"guess:{guess.entity_id}",
                    self._guess_text(guess),
                    answer,
                    True,
                    guess.entity_id,
                )
            )
            if answer == "yes":
                self.active = False
                return f"Yes! I got it in {self.question_count} questions!"
            if answer == "no":
                self.rejected.add(guess.entity_id)
                self.rejected_names.add(self._canonical_name(guess.name))
                self.log_scores[guess.entity_id] = float("-inf")
                self._normalize_scores()
        elif self.current_question is not None:
            item = self.current_question
            self.history.append(Turn(item.key, item.text, answer))
            self.asked_keys.add(item.key)
            self.asked_groups.add(item.semantic_group or item.key)
            self._apply_answer(item, answer)

        self.current_guess = None
        self.current_question = None
        self._debug_turn(answer)
        if self.question_count >= self.MAX_QUESTIONS:
            self.awaiting_reveal = True
            return "You stumped me. What were you thinking of?"
        return None

    def next_move(self) -> str:
        probabilities = self.probabilities()
        ranking = sorted(probabilities, key=probabilities.get, reverse=True)
        top_id = ranking[0]
        top = self.compatibility(top_id, probabilities)
        top_margin = probabilities[top_id] - (
            probabilities[ranking[1]] if len(ranking) > 1 else 0.0
        )
        turns_remaining = self.MAX_QUESTIONS - self.question_count
        contradiction_tolerable = (
            top.contradictions == 0
            or (
                top.contradictions == 1
                and top.coverage >= .75
                and top.average_likelihood >= .48
            )
        )
        should_guess = (
            contradiction_tolerable
            and top.coverage >= .50
            and top.average_likelihood >= .56
            and (
                (top.posterior >= .78 and top_margin >= .18)
                or (
                    turns_remaining <= 3
                    and top.posterior >= .52
                    and top_margin >= .12
                )
            )
        )
        if should_guess:
            item = self.entities[top_id]
            self.current_guess = item
            self.current_question = None
            self.question_count += 1
            self._debug(f"Selected credible guess: {item.name} {top}")
            return self._numbered(self._guess_text(item))

        selected = self._best_question(probabilities)
        if selected is None:
            self.awaiting_reveal = True
            return "I don't have a credible candidate yet. What were you thinking of?"
        item, score, coverage = selected
        self.current_question = item
        self.current_guess = None
        self.last_question_score = score
        self.last_question_coverage = coverage
        self.question_count += 1
        self._debug(
            f"Selected question {item.key}: IG score={score:.4f}, "
            f"coverage={coverage:.3f}"
        )
        return self._numbered(item.text)

    def add_provisional_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> int:
        """Validate candidates, replay full history, then normalize once."""
        self.expansion_requests += 1
        existing_names = {
            self._canonical_name(item.name) for item in self.entities.values()
        }
        accepted: list[Entity] = []
        rejected_reasons: list[str] = []
        for raw in candidates[:50]:
            if not isinstance(raw, dict):
                rejected_reasons.append("candidate was not an object")
                continue
            display_name = " ".join(str(raw.get("name") or "").split())
            canonical = self._canonical_name(display_name)
            if not canonical:
                rejected_reasons.append("candidate had no usable name")
                continue
            if canonical in existing_names:
                rejected_reasons.append(f"{display_name}: duplicate")
                continue
            if canonical in self.rejected_names:
                rejected_reasons.append(f"{display_name}: previously rejected")
                continue
            entity_id = (
                "provisional:"
                + re.sub(r"[^a-z0-9]+", "_", canonical).strip("_")
            )
            raw_traits = raw.get("traits")
            if not isinstance(raw_traits, dict):
                rejected_reasons.append(f"{display_name}: traits were missing")
                continue
            parsed_facts: dict[str, Fact] = {}
            for key, value in raw_traits.items():
                if str(key) not in QUESTION_BY_KEY:
                    continue
                parsed = self._parse_fact(value)
                if parsed is not None:
                    parsed_facts[str(key)] = parsed
            asked_descriptive = {
                turn.question_key for turn in self.history if not turn.was_guess
            }
            missing_asked = asked_descriptive - parsed_facts.keys()
            if missing_asked:
                rejected_reasons.append(
                    f"{display_name}: missing asked traits "
                    f"{sorted(missing_asked)}"
                )
                continue
            accepted.append(
                Entity(
                    entity_id,
                    canonical,
                    str(raw.get("entity_type") or "provisional")[:48],
                    .20,
                    parsed_facts,
                    {display_name} if display_name != canonical else set(),
                    source_confidence=.55,
                )
            )
            existing_names.add(canonical)

        for item in accepted:
            self.entities[item.entity_id] = item
        if accepted:
            # Recompute the whole pool so old and new candidates share the
            # same prior/evidence scale.
            self._recompute_scores()
        self._debug(
            f"Expansion request {self.expansion_requests}: returned="
            f"{len(candidates)}, accepted={len(accepted)}, "
            f"rejected={len(rejected_reasons)}"
        )
        if self.debug:
            for reason in rejected_reasons:
                self._debug(f"Expansion rejection: {reason}")
        return len(accepted)

    def compatibility(
        self,
        entity_id: str,
        probabilities: dict[str, float] | None = None,
    ) -> Compatibility:
        item = self.entities[entity_id]
        likelihoods: list[float] = []
        contradictions = 0
        descriptive = [turn for turn in self.history if not turn.was_guess]
        for turn in descriptive:
            fact = item.fact(turn.question_key)
            if not fact.known or turn.answer == "unknown":
                continue
            likelihood = item.likelihoods(turn.question_key)[turn.answer]
            likelihoods.append(likelihood)
            if likelihood < .08:
                contradictions += 1
        coverage = len(likelihoods) / max(
            sum(turn.answer != "unknown" for turn in descriptive),
            1,
        )
        average = (
            math.exp(sum(math.log(max(value, ANSWER_FLOOR)) for value in likelihoods) / len(likelihoods))
            if likelihoods
            else .25
        )
        current = probabilities or self.probabilities()
        return Compatibility(
            average,
            coverage,
            contradictions,
            current.get(entity_id, 0.0),
        )

    def structured_history(self) -> list[dict[str, Any]]:
        return [
            {
                "question_key": turn.question_key,
                "question": turn.question,
                "answer": turn.answer,
                "was_guess": turn.was_guess,
            }
            for turn in self.history
        ]

    def history_text(self) -> str:
        return "\n".join(
            f"{index}. [{turn.question_key}] {turn.question} "
            f"Answer: {turn.answer}."
            for index, turn in enumerate(self.history, start=1)
        )

    def expansion_exclusions(self) -> list[str]:
        return sorted(
            {item.name for item in self.entities.values()}
            | self.rejected_names
        )

    def reveal_and_learn(self, answer_name: str) -> str:
        alias = " ".join(answer_name.strip().rstrip("?.!").split())
        canonical = self._canonical_name(alias)
        if not canonical:
            return "I didn't catch the answer. What was it?"
        entity_id = (
            "learned:"
            + re.sub(r"[^a-z0-9]+", "_", canonical).strip("_")
        )
        records = {item.entity_id: item for item in self._load_learned()}
        learned = records.get(
            entity_id,
            Entity(
                entity_id,
                canonical,
                self._infer_learned_type(),
                .30,
                {},
                set(),
                {},
                .45,
            ),
        )
        if alias.casefold() != canonical:
            learned.aliases.add(alias)
        for turn in self.history:
            if turn.was_guess or turn.answer == "unknown":
                continue
            counts = learned.observations.setdefault(
                turn.question_key,
                {answer: 0 for answer in ANSWERS},
            )
            counts[turn.answer] = counts.get(turn.answer, 0) + 1
            learned.facts[turn.question_key] = self._fact_from_counts(counts)
        for key, fact in self._inferred_type_facts(
            learned.entity_type
        ).items():
            learned.facts.setdefault(key, fact)
        learned.popularity = min(learned.popularity + .03, 1.0)
        records[entity_id] = learned
        rejected_names = [
            turn.question.removeprefix("Are you thinking of ").rstrip("?")
            for turn in self.history
            if turn.was_guess and turn.answer == "no"
        ]
        previous_payload = self._read_persistence()
        confusions = (
            dict(previous_payload.get("confusions", {}))
            if isinstance(previous_payload, dict)
            else {}
        )
        confusions[canonical] = {
            "wrong_guesses": sorted(
                set(
                    confusions.get(canonical, {}).get(
                        "wrong_guesses",
                        [],
                    )
                )
                | set(rejected_names)
            ),
            "priority_categories": [
                "infrastructure",
                "location",
                "material",
                "installation",
                "function",
            ],
        }
        payload = {
            "version": 2,
            "entities": [self._entity_to_json(item) for item in records.values()],
            "confusions": confusions,
        }
        try:
            self._atomic_save(payload)
        except OSError as exc:
            print(f"[20 QUESTIONS] Could not save learned answer: {exc}", flush=True)
        self.active = False
        self.awaiting_reveal = False
        return f"Thanks! I'll remember that you were thinking of {canonical}."

    def probabilities(self) -> dict[str, float]:
        finite = [
            score for score in self.log_scores.values() if math.isfinite(score)
        ]
        if not finite:
            count = max(len(self.log_scores), 1)
            return {
                entity_id: 1 / count for entity_id in self.log_scores
            }
        maximum = max(finite)
        weights = {
            entity_id: (
                math.exp(score - maximum) if math.isfinite(score) else 0.0
            )
            for entity_id, score in self.log_scores.items()
        }
        total = sum(weights.values()) or 1.0
        return {
            entity_id: weight / total
            for entity_id, weight in weights.items()
        }

    def ranking(self, limit: int = 10) -> list[tuple[str, float, Compatibility]]:
        probabilities = self.probabilities()
        ordered = sorted(
            probabilities,
            key=probabilities.get,
            reverse=True,
        )[:limit]
        return [
            (
                self.entities[entity_id].name,
                probabilities[entity_id],
                self.compatibility(entity_id, probabilities),
            )
            for entity_id in ordered
        ]

    def observe(self, key: str, answer: str) -> None:
        """Apply a structured observation for regression simulations."""
        item = QUESTION_BY_KEY[key]
        self.history.append(Turn(item.key, item.text, answer))
        self.asked_keys.add(item.key)
        self.asked_groups.add(item.semantic_group or item.key)
        self._apply_answer(item, answer)
        self.question_count += 1

    def _apply_answer(self, item: Question, answer: str) -> None:
        if answer == "unknown":
            return
        for entity_id, candidate in self.entities.items():
            likelihood = candidate.likelihoods(item.key)[answer]
            self.log_scores[entity_id] += math.log(
                max(likelihood, ANSWER_FLOOR)
            )
        self._normalize_scores()

    def _best_question(
        self,
        probabilities: dict[str, float],
    ) -> tuple[Question, float, float] | None:
        current_entropy = self._entropy(probabilities.values())
        top_ids = sorted(
            probabilities,
            key=probabilities.get,
            reverse=True,
        )[:6]
        best: tuple[Question, float, float] | None = None
        for item in QUESTIONS:
            group = item.semantic_group or item.key
            if item.key in self.asked_keys or group in self.asked_groups:
                continue
            applicable_mass = 0.0
            known_mass = 0.0
            for entity_id, probability in probabilities.items():
                candidate = self.entities[entity_id]
                if not self._question_applies(item, candidate):
                    continue
                applicable_mass += probability
                if candidate.fact(item.key).known:
                    known_mass += probability
            if applicable_mass < .35:
                continue
            coverage = known_mass / applicable_mass
            if coverage < item.min_coverage:
                continue

            answer_mass = {answer: 0.0 for answer in ANSWERS}
            for entity_id, probability in probabilities.items():
                candidate = self.entities[entity_id]
                distribution = candidate.likelihoods(item.key)
                for answer, likelihood in distribution.items():
                    answer_mass[answer] += probability * likelihood
            expected_entropy = 0.0
            for answer, mass in answer_mass.items():
                if mass <= 0:
                    continue
                posterior = [
                    probability
                    * self.entities[entity_id].likelihoods(item.key)[answer]
                    / mass
                    for entity_id, probability in probabilities.items()
                ]
                expected_entropy += mass * self._entropy(posterior)
            information_gain = current_entropy - expected_entropy
            differing = {
                self.entities[entity_id].fact(item.key).state
                for entity_id in top_ids
                if self.entities[entity_id].fact(item.key).known
            }
            confusion_bonus = .10 if "yes" in differing and "no" in differing else 0.0
            domain_relevance = min(known_mass, .8) * .05
            learned_confusion_bonus = (
                .06 if item.category in self.priority_categories else 0.0
            )
            score = (
                information_gain
                + confusion_bonus
                + domain_relevance
                + learned_confusion_bonus
                - item.ambiguity
                - item.difficulty
            )
            if best is None or score > best[1]:
                best = (item, score, coverage)
        return best

    @staticmethod
    def _question_applies(item: Question, candidate: Entity) -> bool:
        if item.applicable_types and candidate.entity_type not in item.applicable_types:
            return False
        for key in item.prerequisites:
            fact = candidate.fact(key)
            if not fact.known or fact.likelihoods()["yes"] < .55:
                return False
        for key in item.excluded_traits:
            if candidate.fact(key).likelihoods()["yes"] > .70:
                return False
        return True

    def _normalize_scores(self) -> None:
        probabilities = self.probabilities()
        self.log_scores = {
            entity_id: (
                math.log(probability)
                if probability > 0
                else float("-inf")
            )
            for entity_id, probability in probabilities.items()
        }

    def _recompute_scores(self) -> None:
        total_prior = sum(
            max(item.popularity, .01)
            for item in self.entities.values()
            if item.entity_id not in self.rejected
        ) or 1.0
        scores: dict[str, float] = {}
        for entity_id, item in self.entities.items():
            if entity_id in self.rejected:
                scores[entity_id] = float("-inf")
                continue
            score = math.log(max(item.popularity, .01) / total_prior)
            for turn in self.history:
                if turn.was_guess or turn.answer == "unknown":
                    continue
                likelihood = item.likelihoods(turn.question_key)[turn.answer]
                score += math.log(max(likelihood, ANSWER_FLOOR))
            scores[entity_id] = score
        self.log_scores = scores
        self._normalize_scores()

    def _load_learned(self) -> list[Entity]:
        source_path = self.learned_path
        if (
            not source_path.exists()
            and source_path == LEARNED_ENTITIES_FILE
            and LEGACY_LEARNED_ENTITIES_FILE.exists()
        ):
            source_path = LEGACY_LEARNED_ENTITIES_FILE
        if not source_path.exists():
            return []
        try:
            payload = json.loads(
                source_path.read_text(encoding="utf-8")
            )
            raw_entities = (
                payload.get("entities", [])
                if isinstance(payload, dict)
                else payload
            )
            return [
                self._entity_from_json(raw)
                for raw in raw_entities
                if isinstance(raw, dict)
            ]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return []

    def _read_persistence(self) -> dict[str, Any]:
        if not self.learned_path.exists():
            return {}
        try:
            payload = json.loads(
                self.learned_path.read_text(encoding="utf-8")
            )
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _atomic_save(self, payload: dict[str, Any]) -> None:
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.learned_path.with_suffix(
            f"{self.learned_path.suffix}.tmp"
        )
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(self.learned_path)

    @staticmethod
    def _parse_fact(value: Any) -> Fact | None:
        if isinstance(value, str):
            state = value.lower().strip()
            if state == "yes":
                return Fact.yes()
            if state == "no":
                return Fact.no()
            if state in {"maybe", "variable"}:
                return Fact.variable()
            if state == "unknown":
                return Fact.unknown()
            return None
        if isinstance(value, (int, float)):
            return Fact.probabilistic(float(value))
        if isinstance(value, dict):
            state = str(value.get("state") or "").lower()
            probability = value.get("yes_probability")
            if state == "probabilistic" and probability is not None:
                return Fact.probabilistic(float(probability))
            return TwentyQuestionsGame._parse_fact(state)
        return None

    @staticmethod
    def _fact_from_counts(counts: dict[str, int]) -> Fact:
        yes = counts.get("yes", 0)
        no = counts.get("no", 0)
        maybe = counts.get("maybe", 0)
        total = yes + no + maybe
        if total == 0:
            return Fact.unknown()
        if maybe / total >= .4:
            return Fact.variable()
        # Beta prior prevents one observation from becoming absolute truth.
        return Fact.probabilistic((yes + 1.0) / (yes + no + 2.0))

    @staticmethod
    def _entity_to_json(item: Entity) -> dict[str, Any]:
        return {
            "entity_id": item.entity_id,
            "name": item.name,
            "entity_type": item.entity_type,
            "popularity": item.popularity,
            "aliases": sorted(item.aliases),
            "facts": {
                key: {
                    "state": fact.state,
                    "yes_probability": fact.yes_probability,
                }
                for key, fact in item.facts.items()
            },
            "observations": item.observations,
            "source_confidence": item.source_confidence,
        }

    @classmethod
    def _entity_from_json(cls, raw: dict[str, Any]) -> Entity:
        raw_facts = raw.get("facts", raw.get("traits", {}))
        legacy_keys = {
            "indoors": "inside_home",
            "tool": "practical_task",
            "old": "before_1900",
            "food_related": "kitchen",
        }
        parsed = {
            legacy_keys.get(str(key), str(key)): fact
            for key, value in (
                raw_facts.items() if isinstance(raw_facts, dict) else ()
            )
            if (fact := cls._parse_fact(value)) is not None
        }
        name = cls._canonical_name(str(raw["name"]))
        entity_id = str(raw["entity_id"])
        if entity_id.startswith("learned:"):
            entity_id = (
                "learned:"
                + re.sub(r"[^a-z0-9]+", "_", name).strip("_")
            )
        return Entity(
            entity_id,
            name,
            str(raw.get("entity_type") or "learned"),
            float(raw.get("popularity") or .25),
            parsed,
            {str(alias) for alias in raw.get("aliases", [])},
            {
                str(key): {
                    str(answer): int(count)
                    for answer, count in counts.items()
                }
                for key, counts in raw.get("observations", {}).items()
                if isinstance(counts, dict)
            },
            float(raw.get("source_confidence") or .45),
        )

    def _infer_learned_type(self) -> str:
        answers = {
            turn.question_key: turn.answer
            for turn in self.history
            if not turn.was_guess
        }
        if answers.get("public_infrastructure") == "yes":
            return "infrastructure"
        if answers.get("animal") == "yes":
            return "animal"
        if answers.get("place") == "yes":
            return "place"
        if answers.get("fictional") == "yes":
            return "fictional_character"
        if answers.get("abstract") == "yes":
            return "abstract"
        if answers.get("electric") == "yes":
            return "device"
        return "object"

    @staticmethod
    def _inferred_type_facts(entity_type: str) -> dict[str, Fact]:
        if entity_type == "infrastructure":
            return facts(
                yes=(
                    "physical",
                    "manufactured",
                    "outdoors",
                    "fixed_installation",
                    "public_infrastructure",
                ),
                no=("alive", "abstract", "inside_home"),
            )
        if entity_type == "device":
            return facts(
                yes=("physical", "manufactured", "electric"),
                no=("alive", "abstract", "nature"),
            )
        if entity_type == "animal":
            return facts(
                yes=("physical", "alive", "animal", "nature"),
                no=("manufactured", "abstract"),
            )
        return {}

    @staticmethod
    def _canonical_name(name: str) -> str:
        normalized = " ".join(name.casefold().strip().split())
        normalized = re.sub(r"^(?:a|an|the)\s+", "", normalized)
        return normalized

    @staticmethod
    def _entropy(probabilities: Iterable[float]) -> float:
        return -sum(
            probability * math.log2(probability)
            for probability in probabilities
            if probability > 0
        )

    def _numbered(self, text: str) -> str:
        prefix = (
            "Question one"
            if self.question_count == 1
            else f"Question {self.question_count}"
        )
        return f"{prefix}. {text}"

    @staticmethod
    def _guess_text(item: Entity) -> str:
        return f"Are you thinking of {item.name}?"

    def _debug_turn(self, answer: str) -> None:
        if not self.debug:
            return
        self._debug(f"Parsed answer: {answer}")
        ranking = self.ranking(10)
        margin = (
            ranking[0][1] - ranking[1][1]
            if len(ranking) > 1
            else ranking[0][1]
        )
        self._debug(f"Top-candidate posterior margin: {margin:.4f}")
        for name, posterior, fit in ranking:
            self._debug(
                f"Candidate {name}: posterior={posterior:.4f}, "
                f"compatibility={fit.average_likelihood:.4f}, "
                f"coverage={fit.coverage:.3f}, "
                f"contradictions={fit.contradictions}"
            )

    def _debug(self, message: str) -> None:
        if self.debug:
            print(f"[20 QUESTIONS DEBUG] {message}", flush=True)
