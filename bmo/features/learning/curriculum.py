"""Locally authored, validated Pre-K curriculum for BMO Learning.

Lesson definitions are intentionally data, not UI branches.  Adding a lesson
means adding a bank (when needed) and one :class:`LessonDefinition`; the engine
selects a reusable generator from the definition.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import string
from types import MappingProxyType
from typing import Iterable, Mapping

from .models import (
    ContentItem,
    InteractionKind,
    LearningDataError,
    LessonDefinition,
)


LETTERS = tuple(string.ascii_uppercase)
LETTER_REVIEW_BLOCKS = (
    "A-D",
    "E-H",
    "A-D",
    "I-L",
    "M-P",
    "I-P",
    "Q-U",
    "V-Z",
    "Q-V",
    "A-Z",
)
CONFUSED_LETTER_GROUPS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        # Straight, readable sans-serif fonts are required for these groups.
        "bdpq": ("b", "d", "p", "q"),
        "mnuw": ("m", "n", "u", "w"),
        "ceo": ("c", "e", "o"),
        "ijlt": ("i", "j", "l", "t"),
    }
)
CASE_MATCH_GROUPS = (
    ("c", "k", "o", "p", "s", "u", "v", "w", "x", "z"),
    ("f", "i", "j", "l", "m", "t", "y"),
    ("a", "b", "d", "e", "g", "h", "n", "q", "r"),
)
UPPER_SOUND_GROUPS = (
    ("B", "D", "J", "K", "P", "T", "V", "Z"),
    ("F", "L", "M", "N", "R", "S"),
    ("C", "G", "H", "W"),
)
SIGHT_WORD_SETS: Mapping[int, tuple[str, ...]] = MappingProxyType(
    {
        1: ("a", "in", "run", "the", "you"),
        2: ("and", "had", "is", "let", "to"),
        3: ("at", "for", "I", "one", "said"),
        4: ("can", "it", "not", "up", "yes"),
        5: ("an", "do", "jump", "look", "make"),
        6: ("down", "go", "out", "so", "two"),
        7: ("find", "my", "no", "red", "see"),
        8: ("come", "funny", "little", "me", "sit"),
        9: ("big", "help", "play", "three", "yellow"),
        10: ("away", "blue", "here", "us", "where"),
    }
)

READABLE_FONTS = (
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
    "Noto Sans",
)
READABLE_GLYPH_COLORS = (
    "#124559",
    "#7A1F3D",
    "#22543D",
    "#633C8A",
    "#813B13",
    "#1D4E89",
)

KNOWN_GENERATORS = frozenset(
    {
        "letter_single",
        "letter_multi",
        "alphabet_grid",
        "case_match",
        "case_multi",
        "same_pair",
        "scenario_choice",
        "word_in_sentence",
        "rhyme_one",
        "rhyme_two",
        "blend",
        "initial_sound",
        "sound_compare",
        "sound_letter",
        "vowel_word",
        "picture_word",
        "sight_word",
        "category_sort",
        "ordered_sequence",
        "number_choice",
        "count",
        "compare_count",
        "missing_number",
        "operation",
        "pattern",
    }
)


@dataclass(frozen=True)
class Catalog:
    """Immutable lesson catalog and referenced local content banks."""

    lessons: tuple[LessonDefinition, ...]
    banks: Mapping[str, tuple[ContentItem, ...]]
    _by_id: Mapping[str, LessonDefinition] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        lessons = tuple(self.lessons)
        frozen_banks = MappingProxyType(
            {str(name): tuple(items) for name, items in self.banks.items()}
        )
        object.__setattr__(self, "lessons", lessons)
        object.__setattr__(self, "banks", frozen_banks)
        object.__setattr__(
            self,
            "_by_id",
            MappingProxyType({lesson.lesson_id: lesson for lesson in lessons}),
        )

    def get(self, lesson_id: str) -> LessonDefinition:
        try:
            return self._by_id[lesson_id]
        except KeyError as exc:
            raise KeyError(f"unknown Learning lesson: {lesson_id}") from exc

    def bank(self, name: str) -> tuple[ContentItem, ...]:
        try:
            return self.banks[name]
        except KeyError as exc:
            raise KeyError(f"unknown Learning content bank: {name}") from exc

    def for_domain(self, domain: str) -> tuple[LessonDefinition, ...]:
        return tuple(lesson for lesson in self.lessons if lesson.domain == domain)

    @property
    def lesson_ids(self) -> tuple[str, ...]:
        return tuple(lesson.lesson_id for lesson in self.lessons)


def _item(
    key: str,
    label: str,
    *,
    spoken: str = "",
    group: str = "",
    **attributes: object,
) -> ContentItem:
    return ContentItem(key, label, spoken, group, attributes)


_LETTER_SOUNDS = {
    "B": ("b sound", "ball"),
    "C": ("hard c sound", "cat"),
    "D": ("d sound", "dog"),
    "F": ("f sound", "fish"),
    "G": ("hard g sound", "goat"),
    "H": ("h sound", "hat"),
    "J": ("j sound", "jam"),
    "K": ("k sound", "kite"),
    "L": ("l sound", "leaf"),
    "M": ("m sound", "moon"),
    "N": ("n sound", "nest"),
    "P": ("p sound", "pig"),
    "R": ("r sound", "rain"),
    "S": ("s sound", "sun"),
    "T": ("t sound", "top"),
    "V": ("v sound", "van"),
    "W": ("w sound", "web"),
    "Z": ("z sound", "zip"),
}


def _alphabet(case: str) -> tuple[ContentItem, ...]:
    values = LETTERS if case == "upper" else tuple(letter.lower() for letter in LETTERS)
    return tuple(
        _item(
            f"letter-{case}-{letter.lower()}",
            letter,
            spoken=f"{letter.upper()}, as in {_LETTER_SOUNDS.get(letter.upper(), ('', letter))[1]}",
            group=case,
            sound=_LETTER_SOUNDS.get(letter.upper(), (f"{letter} sound", letter))[0],
            example=_LETTER_SOUNDS.get(letter.upper(), ("", letter))[1],
        )
        for letter in values
    )


_PHONICS_WORD_DATA = (
    ("cat", "at", "c", "t", "c-a-t", "c", "at", "cat"),
    ("hat", "at", "h", "t", "h-a-t", "h", "at", "hat"),
    ("map", "ap", "m", "p", "m-a-p", "m", "ap", "map"),
    ("cap", "ap", "c", "p", "c-a-p", "c", "ap", "cap"),
    ("bed", "ed", "b", "d", "b-e-d", "b", "ed", "bed"),
    ("red", "ed", "r", "d", "r-e-d", "r", "ed", "red"),
    ("hen", "en", "h", "n", "h-e-n", "h", "en", "hen"),
    ("pen", "en", "p", "n", "p-e-n", "p", "en", "pen"),
    ("pig", "ig", "p", "g", "p-i-g", "p", "ig", "pig"),
    ("wig", "ig", "w", "g", "w-i-g", "w", "ig", "wig"),
    ("sit", "it", "s", "t", "s-i-t", "s", "it", "sit"),
    ("kit", "it", "k", "t", "k-i-t", "k", "it", "kit"),
    ("dog", "og", "d", "g", "d-o-g", "d", "og", "dog"),
    ("log", "og", "l", "g", "l-o-g", "l", "og", "log"),
    ("fox", "ox", "f", "x", "f-o-x", "f", "ox", "fox"),
    ("box", "ox", "b", "x", "b-o-x", "b", "ox", "box"),
    ("sun", "un", "s", "n", "s-u-n", "s", "un", "sun"),
    ("fun", "un", "f", "n", "f-u-n", "f", "un", "fun"),
    ("bug", "ug", "b", "g", "b-u-g", "b", "ug", "bug"),
    ("mug", "ug", "m", "g", "m-u-g", "m", "ug", "mug"),
)


def _phonics_words() -> tuple[ContentItem, ...]:
    items: list[ContentItem] = []
    for word, rhyme, initial, final, phonemes, onset, rime, picture in _PHONICS_WORD_DATA:
        vowel = word[1]
        syllables = word if len(word) <= 3 else f"{word[:-2]}-{word[-2:]}"
        items.append(
            _item(
                f"word-{word}",
                word,
                group=rhyme,
                rhyme=rhyme,
                initial=initial,
                final=final,
                phonemes=phonemes,
                onset=onset,
                rime=rime,
                vowel=vowel,
                syllables=syllables,
                picture=picture,
            )
        )
    items.extend(
        (
            _item("word-rabbit", "rabbit", group="rabbit", syllables="rab-bit", initial="r", final="t", picture="rabbit"),
            _item("word-tiger", "tiger", group="tiger", syllables="ti-ger", initial="t", final="r", picture="tiger"),
            _item("word-sunset", "sunset", group="sunset", syllables="sun-set", initial="s", final="t", picture="sunset"),
            _item("word-picnic", "picnic", group="picnic", syllables="pic-nic", initial="p", final="c", picture="picnic"),
            _item("word-robin", "robin", group="robin", syllables="rob-in", initial="r", final="n", picture="robin"),
        )
    )
    return tuple(items)


def _scenario(
    key: str,
    prompt: str,
    answer: str,
    *distractors: str,
    explanation: str,
    picture: str = "",
) -> ContentItem:
    return _item(
        key,
        answer,
        prompt=prompt,
        answer=answer,
        distractors=tuple(distractors),
        explanation=explanation,
        picture=picture,
    )


def _scenario_banks() -> dict[str, tuple[ContentItem, ...]]:
    return {
        "sentences.spacing": (
            _scenario("spacing-1", "Which sentence has good spaces?", "We see a red bird.", "Wesee a red bird.", "We seeared bird.", "We  see  a red bird.", explanation="Spaces separate each word."),
            _scenario("spacing-2", "Which sentence has good spaces?", "The cat can nap.", "Thecat can nap.", "The catcannap.", "The  cat cannap.", explanation="Each spoken word gets its own space."),
            _scenario("spacing-3", "Which sentence has good spaces?", "I like my blue hat.", "Ilike my blue hat.", "I like mybluehat.", "I  likemy blue hat.", explanation="The words are separated clearly."),
        ),
        "reading.book_parts": (
            _scenario("book-cover", "Tap the front cover.", "front cover", "back cover", "spine", "title page", explanation="The front cover is the first outside face of a book.", picture="book-front"),
            _scenario("book-spine", "What holds the pages together along the side?", "spine", "title", "illustration", "page number", explanation="The spine joins and protects the pages.", picture="book-spine"),
            _scenario("book-title", "Which feature tells the book's name?", "title", "author", "page number", "back cover", explanation="The title is the book's name.", picture="book-title"),
            _scenario("book-author", "Who writes the words in a book?", "author", "illustrator", "reader", "character", explanation="An author writes the book's words.", picture="book-author"),
            _scenario("book-illustrator", "Who creates the pictures in a book?", "illustrator", "author", "reader", "character", explanation="An illustrator creates the pictures.", picture="book-picture"),
        ),
        "reading.reality": (
            _scenario("real-garden", "Which could happen in real life?", "A child waters a garden.", "A flower sings a song.", "A cloud wears boots.", "A spoon drives a bus.", explanation="People really can water plants.", picture="garden"),
            _scenario("real-dog", "Which could happen in real life?", "A dog chases a ball.", "A dog reads the newspaper aloud.", "A dog turns into a rainbow.", "A dog flies to the moon alone.", explanation="Dogs really can run after balls.", picture="dog-ball"),
            _scenario("real-rain", "Which could happen in real life?", "Rain makes a puddle.", "Rain turns shoes into fish.", "Rain asks for lunch.", "Rain builds a castle by itself.", explanation="Rainwater can collect in puddles.", picture="rain-puddle"),
            _scenario("real-bus", "Which could happen in real life?", "A bus stops for riders.", "A bus grows wings and becomes a bird.", "A bus eats a sandwich.", "A bus sleeps under a blanket.", explanation="Buses really stop so people can get on and off.", picture="bus-stop"),
        ),
        "reading.feelings": (
            _scenario("feel-proud", "Mia finishes a tall block tower. How might Mia feel?", "proud", "sleepy", "worried", "lonely", explanation="Finishing something you worked on can feel proud.", picture="tower-finished"),
            _scenario("feel-sad", "A child's ice pop falls on the ground. How might the child feel?", "sad", "excited", "calm", "silly", explanation="Losing a treat can make someone feel sad.", picture="dropped-pop"),
            _scenario("feel-worried", "Sam cannot see their grown-up in a busy store. How might Sam feel?", "worried", "proud", "sleepy", "playful", explanation="Not seeing a trusted adult can feel worrying; Sam should ask a store worker for help.", picture="busy-store"),
            _scenario("feel-excited", "Friends arrive for a picnic. How might the waiting child feel?", "excited", "angry", "lonely", "tired", explanation="Seeing friends for a fun activity can feel exciting.", picture="picnic-friends"),
        ),
        "reading.next": (
            _scenario("next-seed", "A child puts a seed in soil and waters it. What may happen next?", "A small sprout may grow.", "The seed becomes a shoe.", "The soil flies away.", "The pot starts singing.", explanation="With water, light, and time, a seed may sprout.", picture="watered-seed"),
            _scenario("next-coat", "Kai sees rain outside and puts on a raincoat. What may happen next?", "Kai goes outside more prepared for rain.", "The raincoat becomes a boat.", "The sky moves indoors.", "Kai plants the coat.", explanation="A raincoat helps keep a person drier outside.", picture="raincoat"),
            _scenario("next-blocks", "A tower leans far to one side. What may happen next?", "The blocks may tumble down.", "The blocks turn into soup.", "The tower swims away.", "The floor disappears.", explanation="A leaning tower can lose balance and fall.", picture="leaning-tower"),
            _scenario("next-hands", "Jo puts soap and water on dirty hands. What happens next?", "Jo rubs and rinses the hands.", "Jo puts the soap in a pocket.", "The sink becomes a kite.", "Jo waters a book.", explanation="Rubbing, rinsing, and drying are the next handwashing steps.", picture="hand-wash"),
        ),
        "vocabulary.color_words": (
            _scenario("color-red", "Which word names this red color?", "red", "blue", "green", "yellow", explanation="R E D spells red.", picture="red-swatch"),
            _scenario("color-blue", "Which word names this blue color?", "blue", "orange", "pink", "brown", explanation="B L U E spells blue.", picture="blue-swatch"),
            _scenario("color-green", "Which word names this green color?", "green", "purple", "black", "white", explanation="G R E E N spells green.", picture="green-swatch"),
            _scenario("color-yellow", "Which word names this yellow color?", "yellow", "gray", "red", "blue", explanation="Y E L L O W spells yellow.", picture="yellow-swatch"),
            _scenario("color-orange", "Which word names this orange color?", "orange", "green", "purple", "black", explanation="O R A N G E spells orange.", picture="orange-swatch"),
            _scenario("color-purple", "Which word names this purple color?", "purple", "yellow", "brown", "white", explanation="P U R P L E spells purple.", picture="purple-swatch"),
        ),
        "vocabulary.nouns": (
            _scenario("noun-one-cat", "The picture has one cat. Which word fits?", "cat", "cats", "catting", "catted", explanation="One animal uses the singular word cat.", picture="one-cat"),
            _scenario("noun-two-cats", "The picture has two cats. Which word fits?", "cats", "cat", "catting", "catted", explanation="More than one cat uses the plural word cats.", picture="two-cats"),
            _scenario("noun-one-cup", "The picture has one cup. Which word fits?", "cup", "cups", "cupping", "cupped", explanation="One object uses the singular word cup.", picture="one-cup"),
            _scenario("noun-three-cups", "The picture has three cups. Which word fits?", "cups", "cup", "cupping", "cupped", explanation="More than one cup uses the plural word cups.", picture="three-cups"),
        ),
        "vocabulary.verbs": (
            _scenario("verb-hop", "Which picture shows hop?", "a child hopping", "a child sleeping", "a child reading", "a child washing", explanation="Hop means to jump lightly, often on one foot.", picture="hop"),
            _scenario("verb-pour", "Which picture shows pour?", "water moving from a pitcher into a cup", "a closed book", "shoes by a door", "a sleeping cat", explanation="Pour means to make liquid flow from one container to another.", picture="pour"),
            _scenario("verb-stretch", "Which picture shows stretch?", "a child reaching arms high", "a child sitting still", "a ball under a chair", "two blocks touching", explanation="Stretch means to extend part of your body.", picture="stretch"),
            _scenario("verb-build", "Which picture shows build?", "hands making a block tower", "feet beside a puddle", "a spoon in a bowl", "a bird on a branch", explanation="Build means to put parts together to make something.", picture="build"),
        ),
        "vocabulary.adjectives": (
            _scenario("adj-tall", "Which tree is taller?", "the tall tree", "the short tree", "both are the same height", "neither tree", explanation="Taller means having more height.", picture="trees-height"),
            _scenario("adj-small", "Which ball is smaller?", "the small ball", "the large ball", "both are the same size", "neither ball", explanation="Smaller means taking up less space.", picture="balls-size"),
            _scenario("adj-full", "Which cup is fuller?", "the cup with more water", "the empty cup", "the shorter spoon", "the blue napkin", explanation="Fuller means containing more.", picture="cups-full"),
            _scenario("adj-long", "Which ribbon is longer?", "the long ribbon", "the short ribbon", "both are circles", "neither ribbon", explanation="Longer means reaching farther from end to end.", picture="ribbons-length"),
        ),
        "vocabulary.inside_outside": (
            _scenario("inside-box", "Where is the ball?", "inside the box", "outside the box", "above the box", "beside the box", explanation="Inside means within the box's edges.", picture="ball-in-box"),
            _scenario("outside-basket", "Where is the apple?", "outside the basket", "inside the basket", "below the basket", "on the basket", explanation="Outside means not within the basket.", picture="apple-out-basket"),
            _scenario("inside-tent", "Where is the child?", "inside the tent", "outside the tent", "above the tent", "under the ground", explanation="The tent surrounds the child, so the child is inside.", picture="child-in-tent"),
        ),
        "vocabulary.above_below": (
            _scenario("above-cloud", "The bird is over the cloud. Where is the bird?", "above the cloud", "below the cloud", "inside the cloud", "beside the cloud", explanation="Above means higher than something.", picture="bird-above-cloud"),
            _scenario("below-table", "The ball is under the table. Where is the ball?", "below the table", "above the table", "inside the table", "on the table", explanation="Below means lower than something.", picture="ball-under-table"),
            _scenario("above-shelf", "The clock is higher than the shelf. Where is it?", "above the shelf", "below the shelf", "inside the shelf", "behind the shelf", explanation="The clock is above because it is higher.", picture="clock-above-shelf"),
        ),
        "vocabulary.next_to": (
            _scenario("beside-chair", "The backpack is beside the chair. Where is it?", "next to the chair", "inside the chair", "above the chair", "far from the chair", explanation="Beside and next to both mean at the side of something.", picture="bag-chair"),
            _scenario("next-cup", "The spoon is next to the cup. Which word also fits?", "beside", "above", "inside", "far", explanation="Beside means the same as next to.", picture="spoon-cup"),
            _scenario("next-friends", "Two friends stand side by side. Where are they?", "beside each other", "inside each other", "above each other", "far apart", explanation="Side by side means beside or next to.", picture="friends-beside"),
        ),
        "vocabulary.antonyms": (
            _scenario("opposite-hot", "Which picture means the opposite of hot?", "cold", "warm", "bright", "loud", explanation="Cold is the opposite of hot.", picture="hot-cold"),
            _scenario("opposite-open", "Which word means the opposite of open?", "closed", "wide", "tall", "fast", explanation="Closed is the opposite of open.", picture="door-closed"),
            _scenario("opposite-fast", "Which word means the opposite of fast?", "slow", "large", "up", "full", explanation="Slow is the opposite of fast.", picture="fast-slow"),
            _scenario("opposite-up", "Which word means the opposite of up?", "down", "over", "near", "out", explanation="Down is the opposite of up.", picture="up-down"),
        ),
        "vocabulary.odd_one": (
            _scenario("odd-fruit", "Which one does not belong with the fruits?", "sock", "apple", "pear", "banana", explanation="A sock is clothing; the others are fruits.", picture="fruit-and-sock"),
            _scenario("odd-animals", "Which one does not belong with the animals?", "chair", "dog", "fish", "bird", explanation="A chair is furniture; the others are animals.", picture="animals-chair"),
            _scenario("odd-tools", "Which one does not belong with things used for drawing?", "spoon", "crayon", "pencil", "marker", explanation="A spoon is used for eating; the others can draw.", picture="drawing-spoon"),
            _scenario("odd-weather", "Which one does not belong with kinds of weather?", "sandwich", "rain", "snow", "wind", explanation="A sandwich is food; the others are weather.", picture="weather-food"),
        ),
    }


def _readiness_scenario_banks() -> dict[str, tuple[ContentItem, ...]]:
    return {
        "readiness.body": (
            _scenario("body-elbow", "Which body part bends in the middle of your arm?", "elbow", "ankle", "chin", "ear", explanation="Your elbow helps your arm bend.", picture="body-elbow"),
            _scenario("body-knee", "Which body part bends in the middle of your leg?", "knee", "wrist", "nose", "shoulder", explanation="Your knee helps your leg bend.", picture="body-knee"),
            _scenario("body-wrist", "Which body part joins your hand to your arm?", "wrist", "knee", "neck", "heel", explanation="Your wrist is between your hand and forearm.", picture="body-wrist"),
            _scenario("body-shoulder", "Which body part joins your arm near your chest?", "shoulder", "ankle", "forehead", "toe", explanation="Your shoulder connects your arm to your upper body.", picture="body-shoulder"),
        ),
        "readiness.senses": (
            _scenario("sense-see", "Which sense helps you notice colors?", "sight", "hearing", "taste", "smell", explanation="We use our eyes and sense of sight to notice colors.", picture="color-sight"),
            _scenario("sense-hear", "Which sense helps you notice a bell ringing?", "hearing", "touch", "taste", "smell", explanation="We use our ears and hearing to notice sounds.", picture="bell"),
            _scenario("sense-smell", "Which sense helps you notice a flower's scent?", "smell", "sight", "hearing", "touch", explanation="We use our nose and sense of smell for scents.", picture="flower-smell"),
            _scenario("sense-touch", "Which sense helps you notice a soft blanket?", "touch", "taste", "hearing", "smell", explanation="Our skin and sense of touch notice textures.", picture="soft-blanket"),
            _scenario("sense-taste", "Which sense helps you notice a lemon is sour?", "taste", "sight", "hearing", "touch", explanation="Our tongue and sense of taste notice flavors.", picture="lemon"),
        ),
        "readiness.habitats": (
            _scenario("habitat-fish", "Where does a fish usually live?", "in water", "in a nest", "under a bed", "in a treehouse", explanation="Fish have bodies suited to living in water.", picture="fish-water"),
            _scenario("habitat-bird", "Where might a robin build a nest?", "in a tree", "underwater", "inside a toaster", "in a bathtub", explanation="Many robins build nests on tree branches.", picture="bird-tree"),
            _scenario("habitat-frog", "Where can a frog often live?", "near a pond", "on the moon", "in a freezer", "inside a book", explanation="Many frogs live where land and fresh water meet.", picture="frog-pond"),
            _scenario("habitat-polar", "Which home suits a polar bear?", "a cold Arctic habitat", "a warm coral reef", "a tiny bird nest", "a kitchen cupboard", explanation="Polar bears are suited to cold Arctic habitats.", picture="polar-habitat"),
        ),
        "readiness.day_night": (
            _scenario("day-sun", "When is the sun usually bright in the sky?", "daytime", "nighttime", "only winter", "only when raining", explanation="Our part of Earth faces the sun during daytime.", picture="day-sun"),
            _scenario("night-stars", "When are stars often easier to see?", "nighttime", "bright midday", "only summer", "only during rain", explanation="A darker night sky makes many stars easier to see.", picture="night-stars"),
            _scenario("night-sleep", "Which is a common nighttime routine?", "putting on pajamas", "eating every meal", "wearing a raincoat indoors", "watering a book", explanation="Many people put on pajamas before sleep.", picture="pajamas"),
        ),
        "readiness.weather": (
            _scenario("weather-rain", "Which picture shows rainy weather?", "drops falling from clouds", "a clear sky with no clouds", "leaves still on the ground", "a lamp indoors", explanation="Rain is water falling from clouds.", picture="rain"),
            _scenario("weather-wind", "Which clue can show windy weather?", "a flag waving strongly", "a closed drawer", "a still cup", "a book on a shelf", explanation="Moving air can make flags wave.", picture="wind-flag"),
            _scenario("weather-snow", "Which picture shows snowy weather?", "snowflakes falling", "sunlight on dry sand", "a fan indoors", "a full bathtub", explanation="Snow is frozen precipitation that can fall from clouds.", picture="snow"),
            _scenario("weather-cloud", "Which picture shows cloudy weather?", "many clouds covering the sky", "a shoe by a door", "a plate on a table", "a fish in water", explanation="Cloudy weather has many clouds in the sky.", picture="cloudy"),
        ),
        "readiness.seasons": (
            _scenario("season-change", "What is true about seasons?", "They change through the year.", "Winter always makes snow everywhere.", "Summer is always rainy.", "Every place has identical seasons.", explanation="Seasons change daylight and typical weather, but places experience them differently.", picture="four-seasons"),
            _scenario("season-fall", "Which change is common in fall in many places?", "Some leaves change color.", "Every lake freezes solid.", "The sun never rises.", "All flowers disappear everywhere.", explanation="Some trees change leaf color in fall, though places differ.", picture="fall-leaves"),
            _scenario("season-spring", "Which event is common in spring in many places?", "Many plants begin new growth.", "Snow must fall every day.", "Night lasts all day everywhere.", "All animals sleep.", explanation="Warmer temperatures and more daylight help many plants grow, though climates differ.", picture="spring-growth"),
        ),
        "readiness.living": (
            _scenario("living-tree", "Which one is living?", "tree", "rock", "spoon", "wagon", explanation="A tree grows and needs water and energy.", picture="tree-rock"),
            _scenario("living-bird", "Which one is living?", "bird", "chair", "cup", "ball", explanation="A bird grows, needs food, and responds to its world.", picture="bird-chair"),
            _scenario("nonliving-rock", "Which one is nonliving?", "rock", "flower", "ant", "dog", explanation="A rock does not grow or need food.", picture="rock-living"),
            _scenario("nonliving-toy", "Which one is nonliving?", "toy truck", "tree", "fish", "mushroom", explanation="A toy truck does not grow or need water or food.", picture="truck-living"),
        ),
        "readiness.healthy": (
            _scenario("healthy-hands", "What helps wash germs from hands?", "soap and water", "a dry crayon", "a toy block", "a sock", explanation="Washing with soap and water helps remove germs.", picture="wash-hands"),
            _scenario("healthy-teeth", "What helps care for teeth?", "brushing with a toothbrush", "covering them with a hat", "tapping them with a spoon", "never drinking water", explanation="Gentle brushing helps clean teeth.", picture="brush-teeth"),
            _scenario("healthy-sleep", "Which routine helps the body rest?", "a calm bedtime routine", "staying awake all night", "skipping every meal", "shouting at bedtime", explanation="A calm, regular bedtime helps the body get needed rest.", picture="bedtime"),
            _scenario("healthy-food", "Which is a helpful snack choice?", "fruit and water", "only candy all day", "a toy block", "soap", explanation="Foods such as fruit and water can help fuel and hydrate the body.", picture="fruit-water"),
        ),
        "readiness.safety": (
            _scenario("safe-lost", "What should you do if you cannot find your grown-up in a store?", "Ask a store worker or another trusted adult for help.", "Leave the store alone.", "Hide where nobody can see you.", "Follow a stranger outside.", explanation="Stay in the public place and ask an identifiable worker or trusted adult for help.", picture="store-help"),
            _scenario("safe-medicine", "You find medicine without a grown-up. What should you do?", "Do not touch it and tell a trusted adult.", "Taste it.", "Share it with a friend.", "Hide it in a pocket.", explanation="Only take medicine when a trusted adult responsible for you gives it correctly.", picture="medicine-adult"),
            _scenario("safe-road", "Before crossing a street with a grown-up, what should you do?", "Stop and look with the grown-up.", "Run ahead alone.", "Close your eyes.", "Play in the road.", explanation="Stay with the trusted adult and check that crossing is safe.", picture="street-cross"),
            _scenario("safe-emergency", "If something feels unsafe, who can help?", "a trusted adult nearby", "this kiosk by itself", "a toy", "a picture in a book", explanation="Tell a trusted adult nearby. This kiosk cannot provide emergency help.", picture="trusted-adult"),
        ),
        "readiness.feelings": (
            _scenario("calm-breathe", "You feel upset. Which calm choice could help?", "Take slow breaths and ask for help.", "Hit someone.", "Break a toy.", "Run away alone.", explanation="Slow breathing and support from a trusted adult can help your body settle.", picture="slow-breath"),
            _scenario("calm-space", "The room feels too busy. What could you do?", "Ask a trusted adult for a quiet space.", "Push everyone.", "Hide outside alone.", "Throw things.", explanation="Asking for a quieter space is a safe way to care for yourself.", picture="quiet-space"),
            _scenario("calm-name", "What can help when a feeling is very big?", "Name the feeling and tell a trusted adult.", "Pretend nobody can help.", "Yell at a friend.", "Leave alone without telling anyone.", explanation="Naming a feeling and asking for support can make it easier to handle.", picture="name-feeling"),
        ),
        "readiness.social": (
            _scenario("turn-game", "Two children want the same game piece. What is a fair choice?", "Take turns.", "Grab it and keep it.", "Hide all the pieces.", "End the game for everyone.", explanation="Taking turns lets both children participate.", picture="taking-turns"),
            _scenario("help-zip", "Your zipper is stuck. What can you do?", "Ask a trusted adult for help.", "Pull until it breaks.", "Throw the coat.", "Walk outside without telling anyone.", explanation="It is okay to ask a trusted adult for help with a hard task.", picture="zipper-help"),
            _scenario("social-wait", "A friend is speaking. What can you do?", "Listen, then take your turn.", "Talk over the friend.", "Grab the friend's toy.", "Walk away with no words.", explanation="Listening and waiting helps both people share ideas.", picture="listen-turn"),
        ),
        "readiness.directions": (
            _scenario("direction-one", "Tap the blue circle.", "blue circle", "red square", "green triangle", "yellow star", explanation="You followed the one-step direction.", picture="shape-grid"),
            _scenario("direction-two", "First choose the cup, then choose the spoon.", "cup then spoon", "spoon then cup", "cup then plate", "plate then spoon", explanation="The direction names the cup first and spoon second.", picture="table-items"),
            _scenario("direction-color", "Touch the small red block, then the large blue block.", "small red then large blue", "large blue then small red", "small blue then large red", "large red then small blue", explanation="Following both size and color completes the two steps.", picture="blocks-directions"),
        ),
    }


def _build_banks() -> dict[str, tuple[ContentItem, ...]]:
    banks: dict[str, tuple[ContentItem, ...]] = {
        "alphabet.upper": _alphabet("upper"),
        "alphabet.lower": _alphabet("lower"),
        "words.phonics": _phonics_words(),
        "words.sight": tuple(
            _item(f"sight-{index}-{position}", word, group=f"set-{index}")
            for index, words in SIGHT_WORD_SETS.items()
            for position, word in enumerate(words, 1)
        ),
        "words.number": tuple(
            _item(f"number-word-{number}", word, group="number", number=number)
            for number, word in enumerate(
                ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
            )
        ),
        "categories.objects": (
            _item("category-apple", "apple", group="fruit", picture="apple"),
            _item("category-banana", "banana", group="fruit", picture="banana"),
            _item("category-pear", "pear", group="fruit", picture="pear"),
            _item("category-carrot", "carrot", group="vegetable", picture="carrot"),
            _item("category-pea", "pea", group="vegetable", picture="pea"),
            _item("category-broccoli", "broccoli", group="vegetable", picture="broccoli"),
            _item("category-shirt", "shirt", group="clothing", picture="shirt"),
            _item("category-sock", "sock", group="clothing", picture="sock"),
            _item("category-hat", "hat", group="clothing", picture="hat"),
            _item("category-dog", "dog", group="animal", picture="dog"),
            _item("category-fish", "fish", group="animal", picture="fish"),
            _item("category-bird", "bird", group="animal", picture="bird"),
        ),
        "sequences.plant": (
            _item("plant-seed", "seed in soil", group="plant", order=1, picture="seed"),
            _item("plant-sprout", "small sprout", group="plant", order=2, picture="sprout"),
            _item("plant-leaves", "plant with leaves", group="plant", order=3, picture="leaves"),
            _item("plant-flower", "flowering plant", group="plant", order=4, picture="flower"),
        ),
        "sequences.daily": (
            _item("daily-hands-wet", "wet hands", group="wash", order=1, picture="hands-wet"),
            _item("daily-hands-soap", "add soap", group="wash", order=2, picture="hands-soap"),
            _item("daily-hands-rub", "rub hands", group="wash", order=3, picture="hands-rub"),
            _item("daily-hands-rinse", "rinse and dry", group="wash", order=4, picture="hands-rinse"),
            _item("daily-coat", "put on coat", group="outside", order=1, picture="coat"),
            _item("daily-shoes", "put on shoes", group="outside", order=2, picture="shoes"),
            _item("daily-door", "go to the door with an adult", group="outside", order=3, picture="door"),
        ),
    }
    banks.update(_scenario_banks())
    banks.update(_readiness_scenario_banks())
    return banks


def _lesson(
    lesson_id: str,
    title: str,
    skill: str,
    generator: str,
    bank: str,
    *,
    domain: str = "literacy",
    interaction: InteractionKind = InteractionKind.SINGLE_CHOICE,
    prerequisites: tuple[str, ...] = (),
    prompt: str = "Choose the best answer.",
    difficulty: int = 1,
    choices: int = 4,
    minimum_correct: int = 1,
    maximum_correct: int = 1,
    **settings: object,
) -> LessonDefinition:
    return LessonDefinition(
        lesson_id=lesson_id,
        domain=domain,
        title=title,
        skills=(skill,),
        prerequisites=prerequisites,
        prompt_templates=(prompt,),
        interaction=interaction,
        generator=generator,
        bank_refs=(bank,),
        difficulty=difficulty,
        choice_count=choices,
        minimum_correct=minimum_correct,
        maximum_correct=maximum_correct,
        settings=settings,
    )


def _range_letters(label: str) -> tuple[str, ...]:
    start, end = label.split("-")
    return LETTERS[LETTERS.index(start) : LETTERS.index(end) + 1]


def _literacy_lessons() -> list[LessonDefinition]:
    lessons: list[LessonDefinition] = []
    for letter in LETTERS:
        lower = letter.lower()
        upper_single = f"literacy.letter.upper.{lower}.single"
        lower_single = f"literacy.letter.lower.{lower}.single"
        lessons.extend(
            (
                _lesson(upper_single, f"Meet uppercase {letter}", "letter.upper", "letter_single", "alphabet.upper", prompt="This is the uppercase letter {target}. Find the letter {target}.", target=letter, case="upper"),
                _lesson(f"literacy.letter.upper.{lower}.multi", f"Find all uppercase {letter}s", "letter.upper", "letter_multi", "alphabet.upper", interaction=InteractionKind.MULTI_SELECT, prerequisites=(upper_single,), prompt="Find all of the uppercase {target}s.", choices=5, minimum_correct=1, maximum_correct=3, target=letter, case="upper"),
                _lesson(lower_single, f"Meet lowercase {lower}", "letter.lower", "letter_single", "alphabet.lower", prompt="This is the lowercase letter {target}. Find the letter {target}.", target=lower, case="lower"),
                _lesson(f"literacy.letter.lower.{lower}.multi", f"Find all lowercase {lower}s", "letter.lower", "letter_multi", "alphabet.lower", interaction=InteractionKind.MULTI_SELECT, prerequisites=(lower_single,), prompt="Find all of the lowercase {target}s.", choices=5, minimum_correct=1, maximum_correct=3, target=lower, case="lower"),
            )
        )

    seen_blocks: dict[str, int] = {}
    for position, block in enumerate(LETTER_REVIEW_BLOCKS, 1):
        slug = block.lower().replace("-", "")
        seen_blocks[slug] = seen_blocks.get(slug, 0) + 1
        occurrence = seen_blocks[slug]
        lesson_id = f"literacy.letter_review.{slug}.{occurrence}"
        letters = _range_letters(block)
        lessons.append(
            _lesson(
                lesson_id,
                f"Letter review {block}",
                "letter.review",
                "letter_multi",
                "alphabet.upper",
                interaction=InteractionKind.LISTEN_HIDDEN,
                prerequisites=tuple(f"literacy.letter.upper.{letter.lower()}.single" for letter in letters),
                prompt="Tap Speak to hear the question.",
                choices=5,
                minimum_correct=1,
                maximum_correct=3,
                target_pool=letters,
                case="upper",
                hidden=True,
                review_block=block,
                source_order=position,
            )
        )

    all_upper = tuple(f"literacy.letter.upper.{letter.lower()}.single" for letter in LETTERS)
    all_lower = tuple(f"literacy.letter.lower.{letter.lower()}.single" for letter in LETTERS)
    lessons.extend(
        (
            _lesson("literacy.identify.alphabet.lower", "Find a lowercase letter in the alphabet", "letter.identify", "alphabet_grid", "alphabet.lower", interaction=InteractionKind.ALPHABET_GRID, prerequisites=all_lower, prompt="Find the lowercase letter {target}.", choices=26, case="lower"),
            _lesson("literacy.identify.alphabet.upper", "Find an uppercase letter in the alphabet", "letter.identify", "alphabet_grid", "alphabet.upper", interaction=InteractionKind.ALPHABET_GRID, prerequisites=all_upper, prompt="Find the uppercase letter {target}.", choices=26, case="upper"),
            _lesson("literacy.identify.heard", "Choose the letter you hear", "letter.listening", "letter_single", "alphabet.upper", interaction=InteractionKind.LISTEN_HIDDEN, prerequisites=all_upper, prompt="Tap Speak to hear the letter, then choose it.", target_pool=LETTERS, hidden=True, case="upper"),
        )
    )
    for group_name, group in CONFUSED_LETTER_GROUPS.items():
        lessons.extend(
            (
                _lesson(f"literacy.confused.{group_name}.single", f"Tell apart {', '.join(group)}", "letter.confused", "letter_single", "alphabet.lower", prerequisites=tuple(f"literacy.letter.lower.{letter}.single" for letter in group), prompt="Find the letter {target}.", target_pool=group, distractor_pool=group, case="lower", safe_font_only=True),
                _lesson(f"literacy.confused.{group_name}.multi", f"Find all confused letters: {', '.join(group)}", "letter.confused", "letter_multi", "alphabet.lower", interaction=InteractionKind.MULTI_SELECT, prerequisites=(f"literacy.confused.{group_name}.single",), prompt="Find all of the {target}s.", choices=5, minimum_correct=1, maximum_correct=3, target_pool=group, distractor_pool=group, case="lower", safe_font_only=True),
            )
        )

    for direction in ("lower", "upper"):
        target_case = "lower" if direction == "lower" else "upper"
        source_case = "upper" if direction == "lower" else "lower"
        bank = f"alphabet.{target_case}"
        for index, group in enumerate(CASE_MATCH_GROUPS, 1):
            normalized = group if target_case == "lower" else tuple(letter.upper() for letter in group)
            lessons.append(
                _lesson(
                    f"literacy.case_match.{direction}.group{index}",
                    f"Choose the matching {target_case}case letter, group {index}",
                    "letter.case_match",
                    "case_match",
                    bank,
                    prerequisites=all_lower + all_upper,
                    prompt=f"Choose the {target_case}case letter that matches {{example}}.",
                    target_pool=normalized,
                    target_case=target_case,
                    source_case=source_case,
                )
            )
        lessons.append(
            _lesson(
                f"literacy.case_match.find_all_{direction}",
                f"Find all the {target_case}case letters",
                "letter.case_match",
                "case_multi",
                bank,
                interaction=InteractionKind.MULTI_SELECT,
                prerequisites=all_lower + all_upper,
                prompt=f"Find all the {target_case}case letters.",
                choices=5,
                minimum_correct=1,
                maximum_correct=4,
                target_case=target_case,
            )
        )

    # Word recognition, phonological awareness, phonics, and short vowels.
    lessons.extend(
        (
            _lesson("literacy.words.same", "Choose the two words that are the same", "word.match", "same_pair", "words.phonics", interaction=InteractionKind.MULTI_SELECT, prompt="Choose the two words that are the same.", choices=5, minimum_correct=2, maximum_correct=2),
            _lesson("literacy.words.spacing", "Choose the sentence spaced correctly", "sentence.spacing", "scenario_choice", "sentences.spacing", prompt="Which sentence has good spaces?"),
            _lesson("literacy.words.find_in_sentence", "Find a word in a sentence", "word.in_sentence", "word_in_sentence", "words.phonics", prompt="Find {target} in the sentence."),
            _lesson("literacy.rhyme.one", "Which word has the same ending?", "rhyme.one", "rhyme_one", "words.phonics", prompt="Which word has the same ending as {target}?"),
            _lesson("literacy.rhyme.two", "Which two words have the same ending?", "rhyme.pair", "rhyme_two", "words.phonics", interaction=InteractionKind.MULTI_SELECT, prompt="Which two words have the same ending?", choices=5, minimum_correct=2, maximum_correct=2),
            _lesson("literacy.rhyme.picture", "Choose the picture that rhymes", "rhyme.picture", "rhyme_one", "words.phonics", interaction=InteractionKind.PICTURE_CHOICE, prompt="Choose the picture that rhymes with {target}.", picture_choices=True),
            _lesson("literacy.syllables.blend", "Blend syllables to make a word", "syllable.blend", "blend", "words.phonics", interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak, blend the word parts, then choose the word.", blend_field="syllables", hidden=True),
            _lesson("literacy.phoneme.onset_rime", "Blend onset and rime", "phoneme.onset_rime", "blend", "words.phonics", interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak, blend the beginning and ending, then choose the word.", blend_field="onset_rime", hidden=True),
            _lesson("literacy.phoneme.blend", "Blend each sound in a word", "phoneme.blend", "blend", "words.phonics", interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak, blend each sound, then choose the word.", blend_field="phonemes", hidden=True),
            _lesson("literacy.phoneme.initial", "Identify the first sound", "phoneme.initial", "initial_sound", "words.phonics", interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak, then choose the first sound.", hidden=True),
            _lesson("literacy.phoneme.order", "Put the sounds in order", "phoneme.sequence", "blend", "words.phonics", interaction=InteractionKind.ORDERED_SEQUENCE, prompt="Put the sounds in order to make {target}.", choices=3, minimum_correct=3, maximum_correct=3, blend_field="order"),
            _lesson("literacy.sound.beginning_pair", "Which two words start with the same sound?", "sound.beginning", "sound_compare", "words.phonics", interaction=InteractionKind.MULTI_SELECT, prompt="Which two words start with the same sound?", choices=5, minimum_correct=2, maximum_correct=2, sound_field="initial"),
            _lesson("literacy.sound.ending_one", "Which word ends with the same sound?", "sound.ending", "sound_compare", "words.phonics", prompt="Which word ends with the same sound as {target}?", sound_field="final", paired=False),
            _lesson("literacy.sound.ending_pair", "Which two words end with the same sound?", "sound.ending", "sound_compare", "words.phonics", interaction=InteractionKind.MULTI_SELECT, prompt="Which two words end with the same sound?", choices=5, minimum_correct=2, maximum_correct=2, sound_field="final", paired=True),
        )
    )
    for case, groups in (("upper", UPPER_SOUND_GROUPS), ("lower", tuple(tuple(letter.lower() for letter in group) for group in UPPER_SOUND_GROUPS))):
        bank = f"alphabet.{case}"
        for index, group in enumerate(groups, 1):
            lessons.append(
                _lesson(f"literacy.letter_sound.{case}.group{index}", f"{case.title()}case consonant sounds, group {index}", f"letter_sound.{case}", "sound_letter", bank, interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak to hear the sound, then choose its letter.", target_pool=group, hidden=True, case=case)
            )
        lessons.append(
            _lesson(f"literacy.letter_sound.{case}.review", f"{case.title()}case consonant sound review", f"letter_sound.{case}", "sound_letter", bank, interaction=InteractionKind.LISTEN_HIDDEN, prerequisites=tuple(f"literacy.letter_sound.{case}.group{index}" for index in range(1, 4)), prompt="Tap Speak to hear the sound, then choose its letter.", target_pool=tuple(letter for group in groups for letter in group), hidden=True, case=case)
        )
    lessons.insert(
        next(index for index, item in enumerate(lessons) if item.lesson_id == "literacy.letter_sound.lower.group1"),
        _lesson("literacy.letter_sound.lower.word", "Find the word that begins with a sound", "letter_sound.lower", "initial_sound", "words.phonics", interaction=InteractionKind.PICTURE_CHOICE, prompt="Which word begins with the {sound} sound?", choose_word=True),
    )
    for vowel in "aeiou":
        lessons.append(
            _lesson(f"literacy.vowel.short_{vowel}.identify", f"Find the short {vowel} word", f"vowel.short_{vowel}", "vowel_word", "words.phonics", prompt=f"Find the short {vowel} word.", vowel=vowel)
        )
        direction = "word" if vowel in "ai" else "picture"
        for case in ("upper", "lower"):
            prompt = (
                f"Choose the short {vowel} word that matches the picture."
                if direction == "word"
                else f"Choose the picture that matches the short {vowel} word."
            )
            lessons.append(
                _lesson(f"literacy.vowel.short_{vowel}.picture_match.{case}", f"Short {vowel} picture and word match: {case}case", f"vowel.short_{vowel}", "picture_word", "words.phonics", interaction=InteractionKind.PICTURE_CHOICE, prerequisites=(f"literacy.vowel.short_{vowel}.identify",), prompt=prompt, vowel=vowel, word_case=case, direction=direction)
            )

    lessons.append(_lesson("literacy.sight.same", "Choose the two sight words that are the same", "sight.match", "same_pair", "words.sight", interaction=InteractionKind.MULTI_SELECT, prompt="Choose the two sight words that are the same.", choices=5, minimum_correct=2, maximum_correct=2))
    for set_number, words in SIGHT_WORD_SETS.items():
        lessons.append(
            _lesson(f"literacy.sight.set{set_number}", f"Read sight words set {set_number}", "sight.read", "sight_word", "words.sight", interaction=InteractionKind.LISTEN_HIDDEN, prompt="Tap Speak to hear the word, then choose it.", words=words, set_number=set_number, hidden=True)
        )
    for slug, set_numbers in (("1_3", (1, 2, 3)), ("4_6", (4, 5, 6)), ("7_10", (7, 8, 9, 10)), ("1_10", tuple(range(1, 11)))):
        words = tuple(word for number in set_numbers for word in SIGHT_WORD_SETS[number])
        lessons.append(
            _lesson(f"literacy.sight.review.{slug}", f"Sight word review sets {slug.replace('_', '–')}", "sight.review", "sight_word", "words.sight", interaction=InteractionKind.LISTEN_HIDDEN, prerequisites=tuple(f"literacy.sight.set{number}" for number in set_numbers), prompt="Tap Speak to hear the word, then choose it.", words=words, review_sets=set_numbers, hidden=True)
        )

    scenario_lessons = (
        ("literacy.reading.book_parts", "Book parts and features", "reading.book_parts", "reading.book_parts", InteractionKind.PICTURE_CHOICE),
        ("literacy.reading.reality", "Reality and fiction", "reading.reality", "reading.reality", InteractionKind.SCENE_CHOICE),
        ("literacy.reading.feeling", "Infer a feeling", "reading.inference", "reading.feelings", InteractionKind.SCENE_CHOICE),
        ("literacy.reading.next", "What happens next?", "reading.sequence", "reading.next", InteractionKind.SCENE_CHOICE),
        ("literacy.vocabulary.colors", "Use color words", "vocabulary.colors", "vocabulary.color_words", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.nouns", "Singular and plural nouns", "vocabulary.nouns", "vocabulary.nouns", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.verbs", "Action verbs", "vocabulary.verbs", "vocabulary.verbs", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.adjectives", "Compare with adjectives", "vocabulary.adjectives", "vocabulary.adjectives", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.location.inside_outside", "Inside and outside", "vocabulary.location", "vocabulary.inside_outside", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.location.above_below", "Above and below", "vocabulary.location", "vocabulary.above_below", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.location.next_to", "Next to and beside", "vocabulary.location", "vocabulary.next_to", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.antonyms", "Match antonyms", "vocabulary.antonyms", "vocabulary.antonyms", InteractionKind.PICTURE_CHOICE),
        ("literacy.vocabulary.odd_one_out", "Find the object that does not belong", "vocabulary.categories", "vocabulary.odd_one", InteractionKind.PICTURE_CHOICE),
    )
    for lesson_id, title, skill, bank, interaction in scenario_lessons:
        lessons.append(_lesson(lesson_id, title, skill, "scenario_choice", bank, interaction=interaction))
    for start, end, slug in ((1, 5, "1_5"), (6, 10, "6_10"), (1, 10, "1_10")):
        lessons.append(_lesson(f"literacy.vocabulary.number_words.{slug}", f"Use number words {start} to {end}", "vocabulary.number_words", "number_choice", "words.number", prompt="Choose the number word for {target}.", number_min=start, number_max=end, show_word_target=False))
    lessons.append(_lesson("literacy.vocabulary.categories", "Sort objects into categories", "vocabulary.categories", "category_sort", "categories.objects", interaction=InteractionKind.CATEGORY_SORT, prompt="Sort each object into its group.", choices=6, minimum_correct=6, maximum_correct=6, group_count=2))
    return lessons


def _math_lessons() -> list[LessonDefinition]:
    definitions = (
        ("math.number.0_10", "Recognize numbers 0 to 10", "math.number", "number_choice", "words.number", "Choose the number {target}.", {"number_min": 0, "number_max": 10}),
        ("math.number.11_20", "Recognize numbers 11 to 20", "math.number", "number_choice", "words.number", "Choose the number {target}.", {"number_min": 11, "number_max": 20}),
        ("math.count.0_10", "Count objects to 10", "math.count", "count", "words.number", "Count each object once. How many are there?", {"number_min": 0, "number_max": 10}),
        ("math.count.11_20", "Count objects to 20", "math.count", "count", "words.number", "Count each object once. How many are there?", {"number_min": 11, "number_max": 20}),
        ("math.match.number_forms", "Match numerals, quantities, and number words", "math.number_forms", "number_choice", "words.number", "Match the number form.", {"number_min": 1, "number_max": 10, "mixed_forms": True}),
        ("math.compare.more_fewer_same", "More, fewer, and same", "math.compare", "compare_count", "words.number", "Which group has {comparison}?", {"number_min": 0, "number_max": 10}),
        ("math.sequence.before_after", "Before and after", "math.sequence", "missing_number", "words.number", "Which number comes {position} {target}?", {"number_min": 0, "number_max": 10, "mode": "before_after"}),
        ("math.sequence.missing", "Missing number", "math.sequence", "missing_number", "words.number", "Which number is missing?", {"number_min": 0, "number_max": 10, "mode": "missing"}),
        ("math.operation.compose", "Make a number within 5", "math.compose", "operation", "words.number", "How many altogether?", {"operation": "compose", "number_max": 5}),
        ("math.operation.add", "Picture addition within 5", "math.add", "operation", "words.number", "How many altogether?", {"operation": "add", "number_max": 5}),
        ("math.operation.subtract", "Picture subtraction within 5", "math.subtract", "operation", "words.number", "How many are left?", {"operation": "subtract", "number_max": 5}),
        ("math.pattern.ab", "Continue an AB pattern", "math.pattern", "pattern", "words.number", "What comes next in the AB pattern?", {"pattern": "AB"}),
        ("math.pattern.aab", "Continue an AAB pattern", "math.pattern", "pattern", "words.number", "What comes next in the AAB pattern?", {"pattern": "AAB"}),
        ("math.pattern.abb", "Continue an ABB pattern", "math.pattern", "pattern", "words.number", "What comes next in the ABB pattern?", {"pattern": "ABB"}),
        ("math.pattern.abc", "Continue an ABC pattern", "math.pattern", "pattern", "words.number", "What comes next in the ABC pattern?", {"pattern": "ABC"}),
    )
    lessons = [
        _lesson(lesson_id, title, skill, generator, bank, domain="math", prompt=prompt, **settings)
        for lesson_id, title, skill, generator, bank, prompt, settings in definitions
    ]
    scenarios = {
        "math.shapes.2d": (
            _scenario("shape-circle", "Which shape is round with no corners?", "circle", "square", "triangle", "rectangle", explanation="A circle is round and has no corners.", picture="shape-circle"),
            _scenario("shape-triangle", "Which shape has three straight sides?", "triangle", "circle", "square", "oval", explanation="A triangle has three straight sides and three corners.", picture="shape-triangle"),
            _scenario("shape-square", "Which shape has four equal straight sides?", "square", "circle", "triangle", "oval", explanation="A square has four equal sides and four corners.", picture="shape-square"),
            _scenario("shape-rectangle", "Which shape has four corners and two long sides?", "rectangle", "circle", "triangle", "oval", explanation="A rectangle has four corners and opposite sides match.", picture="shape-rectangle"),
        ),
        "math.shapes.solid": (
            _scenario("solid-sphere", "Which solid shape is like a ball?", "sphere", "cube", "cone", "cylinder", explanation="A sphere is round in every direction like a ball.", picture="solid-sphere"),
            _scenario("solid-cube", "Which solid shape is like a block with square faces?", "cube", "sphere", "cone", "cylinder", explanation="A cube has six square faces.", picture="solid-cube"),
            _scenario("solid-cone", "Which solid shape is like a party hat?", "cone", "cube", "sphere", "cylinder", explanation="A cone has a circular base and one point.", picture="solid-cone"),
            _scenario("solid-cylinder", "Which solid shape is like a can?", "cylinder", "cube", "sphere", "cone", explanation="A cylinder has two circular ends and one curved side.", picture="solid-cylinder"),
        ),
        "math.attributes.one": (
            _scenario("attr-red", "Which item is red?", "red button", "blue button", "green button", "yellow button", explanation="The red button matches the color rule.", picture="buttons-color"),
            _scenario("attr-small", "Which item is small?", "small block", "large block", "tall tower", "long ribbon", explanation="The small block matches the size rule.", picture="blocks-size"),
            _scenario("attr-round", "Which item is round?", "round plate", "square tile", "triangle flag", "rectangle book", explanation="The plate has the round attribute.", picture="objects-shape"),
        ),
        "math.colors": (
            _scenario("math-color-blue", "Which block is blue?", "blue block", "red block", "green block", "yellow block", explanation="The blue block matches the named color.", picture="blocks-color"),
            _scenario("math-color-yellow", "Which circle is yellow?", "yellow circle", "purple circle", "orange circle", "blue circle", explanation="The yellow circle matches the named color.", picture="circles-color"),
            _scenario("math-color-green", "Which ribbon is green?", "green ribbon", "red ribbon", "blue ribbon", "orange ribbon", explanation="The green ribbon matches the named color.", picture="ribbons-color"),
            _scenario("math-color-purple", "Which button is purple?", "purple button", "yellow button", "green button", "red button", explanation="The purple button matches the named color.", picture="buttons-color"),
        ),
        "math.same_different": (
            _scenario("same-shapes", "Which two shapes are the same?", "two matching red circles", "a circle and square", "a large and small triangle", "a blue and yellow block", explanation="The two circles match in shape, size, and color.", picture="same-shapes"),
            _scenario("different-size", "Which block is different from the others?", "the one small block", "the three large blocks", "all four together", "none of the blocks", explanation="The small block has a different size from the other three.", picture="different-size"),
            _scenario("same-pattern", "Which pair is exactly the same?", "two blue striped socks", "a blue sock and red sock", "a striped sock and plain sock", "a large sock and small sock", explanation="The matching pair has the same color, pattern, and size.", picture="same-socks"),
            _scenario("different-shape", "Which tile is different from the round tiles?", "the square tile", "a round tile", "all the round tiles", "none of the tiles", explanation="The square has a different shape from the circles.", picture="different-tile"),
        ),
        "math.attributes.two": (
            _scenario("attr-small-blue", "Which item is both small and blue?", "small blue block", "large blue block", "small red block", "large red block", explanation="It matches both the size and color rules.", picture="blocks-two-attributes"),
            _scenario("attr-big-round", "Which item is both large and round?", "large circle", "small circle", "large square", "small square", explanation="It matches both size and shape.", picture="shapes-two-attributes"),
            _scenario("attr-long-green", "Which item is both long and green?", "long green ribbon", "short green ribbon", "long yellow ribbon", "short yellow ribbon", explanation="It matches both length and color.", picture="ribbons-two-attributes"),
        ),
        "math.ordinal": (
            _scenario("ordinal-first", "Which animal is first in line?", "the first animal", "the second animal", "the fourth animal", "the fifth animal", explanation="First means at the beginning of the line.", picture="animal-line-first"),
            _scenario("ordinal-second", "Which animal is second in line?", "the second animal", "the first animal", "the fourth animal", "the fifth animal", explanation="Second is position number two, just after first.", picture="animal-line-second"),
            _scenario("ordinal-third", "Which animal is third in line?", "the third animal", "the first animal", "the fourth animal", "the fifth animal", explanation="Third comes after first and second.", picture="animal-line-third"),
            _scenario("ordinal-fourth", "Which animal is fourth in line?", "the fourth animal", "the first animal", "the second animal", "the fifth animal", explanation="Fourth is position number four, after third.", picture="animal-line-fourth"),
            _scenario("ordinal-fifth", "Which animal is fifth in line?", "the fifth animal", "the second animal", "the third animal", "the fourth animal", explanation="Fifth is position number five.", picture="animal-line-fifth"),
            _scenario("ordinal-last", "Which animal is last in line?", "the last animal", "the first animal", "the second animal", "the middle animal", explanation="Last means at the end of the line.", picture="animal-line-last"),
        ),
        "math.spatial": (
            _scenario("spatial-under", "Where is the cat if it is under the table?", "below the table", "above the table", "inside the table", "far from the table", explanation="Under and below both mean lower than.", picture="cat-under-table"),
            _scenario("spatial-between", "Where is the red block if it has one block on each side?", "between the blocks", "above the blocks", "inside a block", "far away", explanation="Between means in the middle of two things.", picture="block-between"),
            _scenario("spatial-near", "Which ball is near the box?", "the ball close to the box", "the ball far from the box", "the ball above the cloud", "the hidden ball", explanation="Near means close by.", picture="near-far"),
        ),
        "math.measure": (
            _scenario("measure-length", "Which ribbon is longer?", "the ribbon reaching farther", "the shorter ribbon", "the fuller cup", "the heavier bag", explanation="Length tells how far something reaches end to end.", picture="compare-ribbons"),
            _scenario("measure-height", "Which tower is taller?", "the tower reaching higher", "the shorter tower", "the lighter bag", "the empty cup", explanation="Height tells how high something reaches.", picture="compare-towers"),
            _scenario("measure-weight", "Which might feel heavier?", "a full basket of books", "one feather", "an empty paper bag", "one leaf", explanation="The basket of books has more weight than the light objects.", picture="compare-weight"),
            _scenario("measure-capacity", "Which container can hold more water?", "the large bucket", "the tiny cup", "the flat card", "the small spoon", explanation="Capacity tells how much a container can hold.", picture="compare-capacity"),
        ),
    }
    # Banks are populated by build_catalog after this helper returns.
    for bank, items in scenarios.items():
        _EXTRA_BANKS[bank] = items
    for lesson_id, title, skill, bank in (
        ("math.shapes.2d", "Common flat shapes", "math.shapes", "math.shapes.2d"),
        ("math.shapes.solid", "Simple solid shapes", "math.shapes", "math.shapes.solid"),
        ("math.attributes.one", "Sort and compare one attribute", "math.attributes", "math.attributes.one"),
        ("math.colors", "Recognize and compare colors", "math.colors", "math.colors"),
        ("math.same_different", "Same and different", "math.attributes", "math.same_different"),
        ("math.attributes.two", "Sort using two attributes", "math.attributes", "math.attributes.two"),
        ("math.ordinal", "First, last, and positions through fifth", "math.ordinal", "math.ordinal"),
        ("math.spatial", "Simple spatial words", "math.spatial", "math.spatial"),
        ("math.measure", "Compare length, height, weight, and capacity", "math.measure", "math.measure"),
    ):
        lessons.append(_lesson(lesson_id, title, skill, "scenario_choice", bank, domain="math", interaction=InteractionKind.PICTURE_CHOICE))
    return lessons


_EXTRA_BANKS: dict[str, tuple[ContentItem, ...]] = {}


def _readiness_lessons() -> list[LessonDefinition]:
    scenario_specs = (
        ("readiness.body_parts", "Body parts", "readiness.body", "readiness.body"),
        ("readiness.five_senses", "The five senses", "readiness.senses", "readiness.senses"),
        ("readiness.animals_habitats", "Animals and habitats", "readiness.habitats", "readiness.habitats"),
        ("readiness.day_night", "Day and night", "readiness.earth", "readiness.day_night"),
        ("readiness.weather", "Common weather", "readiness.weather", "readiness.weather"),
        ("readiness.seasons", "Seasons vary by place", "readiness.seasons", "readiness.seasons"),
        ("readiness.living_nonliving", "Living and nonliving", "readiness.science", "readiness.living"),
        ("readiness.healthy_routines", "Healthy routines", "readiness.health", "readiness.healthy"),
        ("readiness.safety_choices", "Safe choices and trusted adults", "readiness.safety", "readiness.safety"),
        ("readiness.feeling_recognition", "Recognize common feelings", "readiness.feelings", "reading.feelings"),
        ("readiness.calming", "Feelings and calming strategies", "readiness.feelings", "readiness.feelings"),
        ("readiness.social", "Turn-taking and asking for help", "readiness.social", "readiness.social"),
        ("readiness.directions", "One- and two-step directions", "readiness.directions", "readiness.directions"),
    )
    lessons = [
        _lesson(lesson_id, title, skill, "scenario_choice", bank, domain="readiness", interaction=InteractionKind.SCENE_CHOICE)
        for lesson_id, title, skill, bank in scenario_specs
    ]
    lessons.extend(
        (
            _lesson("readiness.plant_growth", "Put plant growth in order", "readiness.plants", "ordered_sequence", "sequences.plant", domain="readiness", interaction=InteractionKind.ORDERED_SEQUENCE, prompt="Put the plant pictures in order.", choices=4, minimum_correct=4, maximum_correct=4),
            _lesson("readiness.visual_sequence", "Put everyday steps in order", "readiness.sequence", "ordered_sequence", "sequences.daily", domain="readiness", interaction=InteractionKind.ORDERED_SEQUENCE, prompt="Put the pictures in order.", choices=4, minimum_correct=3, maximum_correct=4),
            _lesson("readiness.classification", "Classify familiar objects", "readiness.classification", "category_sort", "categories.objects", domain="readiness", interaction=InteractionKind.CATEGORY_SORT, prompt="Sort each object into its group.", choices=6, minimum_correct=6, maximum_correct=6, group_count=2),
        )
    )
    return lessons


def prerequisite_warnings(
    catalog: Catalog,
    lesson_ids: Iterable[str],
) -> tuple[tuple[str, str], ...]:
    """Return ``(lesson, missing prerequisite)`` pairs in plan order."""

    selected: set[str] = set()
    warnings: list[tuple[str, str]] = []
    for lesson_id in lesson_ids:
        lesson = catalog.get(lesson_id)
        warnings.extend(
            (lesson_id, prerequisite)
            for prerequisite in lesson.prerequisites
            if prerequisite not in selected
        )
        selected.add(lesson_id)
    return tuple(warnings)


def validate_catalog(catalog: Catalog) -> Catalog:
    """Validate identifiers, banks, generator feasibility, and DAG ordering."""

    if not isinstance(catalog, Catalog):
        raise TypeError("catalog must be a Catalog")
    ids = tuple(lesson.lesson_id for lesson in catalog.lessons)
    if len(ids) != len(set(ids)):
        duplicates = sorted(
            lesson_id
            for lesson_id, count in Counter(ids).items()
            if count > 1
        )
        raise LearningDataError("duplicate lesson id(s): " + ", ".join(duplicates))
    if len(catalog._by_id) != len(catalog.lessons):
        raise LearningDataError("catalog lesson index lost duplicate ids")
    for name, bank in catalog.banks.items():
        if not name or not bank:
            raise LearningDataError(f"content bank {name!r} cannot be empty")
        keys = tuple(item.key for item in bank)
        if len(keys) != len(set(keys)):
            raise LearningDataError(f"content bank {name} has duplicate item keys")
        if any(not isinstance(item, ContentItem) for item in bank):
            raise LearningDataError(f"content bank {name} contains an invalid item")
    for lesson in catalog.lessons:
        if lesson.generator not in KNOWN_GENERATORS:
            raise LearningDataError(
                f"lesson {lesson.lesson_id} uses unknown generator {lesson.generator}"
            )
        for prerequisite in lesson.prerequisites:
            if prerequisite not in catalog._by_id:
                raise LearningDataError(
                    f"lesson {lesson.lesson_id} has missing prerequisite {prerequisite}"
                )
            if prerequisite == lesson.lesson_id:
                raise LearningDataError(f"lesson {lesson.lesson_id} depends on itself")
        for bank_name in lesson.bank_refs:
            if bank_name not in catalog.banks:
                raise LearningDataError(
                    f"lesson {lesson.lesson_id} has missing bank {bank_name}"
                )
        available = sum(len(catalog.bank(name)) for name in lesson.bank_refs)
        if lesson.generator not in {"letter_multi", "case_multi", "scenario_choice", "number_choice", "count", "compare_count", "missing_number", "operation", "pattern"} and available < lesson.choice_count:
            raise LearningDataError(
                f"lesson {lesson.lesson_id} cannot generate {lesson.choice_count} choices"
            )
        if lesson.generator == "scenario_choice":
            for item in catalog.bank(lesson.bank_refs[0]):
                distractors = item.attribute("distractors", ())
                if len(set((item.label, *distractors))) < lesson.choice_count:
                    raise LearningDataError(
                        f"scenario {item.key} cannot generate unique choices"
                    )
        if lesson.generator in {"rhyme_one", "rhyme_two"}:
            groups: dict[str, int] = {}
            for item in catalog.bank(lesson.bank_refs[0]):
                groups[item.group] = groups.get(item.group, 0) + 1
            if max(groups.values(), default=0) < 2:
                raise LearningDataError(f"lesson {lesson.lesson_id} needs a rhyme pair")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lesson_id: str) -> None:
        if lesson_id in visiting:
            raise LearningDataError(f"curriculum prerequisite cycle includes {lesson_id}")
        if lesson_id in visited:
            return
        visiting.add(lesson_id)
        for prerequisite in catalog.get(lesson_id).prerequisites:
            visit(prerequisite)
        visiting.remove(lesson_id)
        visited.add(lesson_id)

    for lesson_id in ids:
        visit(lesson_id)
    return catalog


def build_catalog() -> Catalog:
    """Build and validate the complete offline Pre-K curriculum."""

    _EXTRA_BANKS.clear()
    lessons = _literacy_lessons()
    lessons.extend(_math_lessons())
    lessons.extend(_readiness_lessons())
    banks = _build_banks()
    banks.update(_EXTRA_BANKS)
    return validate_catalog(Catalog(tuple(lessons), banks))


CURRICULUM = build_catalog()
MANDATORY_LITERACY_LESSON_IDS = tuple(
    lesson.lesson_id for lesson in CURRICULUM.lessons if lesson.domain == "literacy"
)


def get_catalog() -> Catalog:
    """Return the immutable process-wide curriculum."""

    return CURRICULUM


__all__ = [
    "CASE_MATCH_GROUPS",
    "CONFUSED_LETTER_GROUPS",
    "CURRICULUM",
    "Catalog",
    "KNOWN_GENERATORS",
    "LETTER_REVIEW_BLOCKS",
    "LETTERS",
    "MANDATORY_LITERACY_LESSON_IDS",
    "READABLE_FONTS",
    "READABLE_GLYPH_COLORS",
    "SIGHT_WORD_SETS",
    "UPPER_SOUND_GROUPS",
    "build_catalog",
    "get_catalog",
    "prerequisite_warnings",
    "validate_catalog",
]
