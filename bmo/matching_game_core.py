"""Toolkit-neutral state and persistence for the matching game."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAW_PATROL_DIR = PROJECT_ROOT / "graphics" / "Paw Patrol"
CARD_BACK_PATH = PROJECT_ROOT / "graphics" / "card_backs" / "card_back.png"
SCORE_HISTORY_PATH = PROJECT_ROOT / "matching_game_scores.json"
CHARACTER_FILES = (
    "Paw Patrol - Chase.png",
    "Paw Patrol - Marshall.png",
    "Paw Patrol - Skye.png",
    "Paw Patrol - Rubble.png",
    "Paw Patrol - Rocky.png",
    "Paw Patrol - Zuma.png",
    "Paw Patrol - Everest.png",
    "Paw Patrol - Ryder.png",
    "Paw Patrol - Shield 0.png",
    "Paw Patrol - Shield 1.png",
    "Paw Patrol - Shield 2.png",
    "Paw Patrol - Shield 3.png",
    "Paw Patrol - Shield 4.png",
    "Paw Patrol - Shield 5.png",
)
DEFAULT_PAIR_COUNT = 6
MIN_PAIR_COUNT = 4


@dataclass(frozen=True)
class Card:
    card_id: int
    character: str


class MatchingGameHistory:
    """Persist selected difficulty and a bounded list of results."""

    def __init__(
        self,
        path: Path | None = SCORE_HISTORY_PATH,
        maximum_pairs: int = len(CHARACTER_FILES),
    ) -> None:
        self.path = path
        self.maximum_pairs = maximum_pairs
        self.pair_count = min(DEFAULT_PAIR_COUNT, maximum_pairs)
        self.games: list[dict[str, int | str]] = []
        self.load()

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("games", []), list):
                raise ValueError("invalid matching-game history")
            self.pair_count = self._clamp(int(data.get("pair_count", self.pair_count)))
            self.games = [item for item in data.get("games", []) if isinstance(item, dict)][-50:]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"[MATCHING GAME] Score history ignored: {exc}", flush=True)

    def set_pair_count(self, pair_count: int) -> int:
        self.pair_count = self._clamp(pair_count)
        self.save()
        return self.pair_count

    def record_game(
        self,
        *,
        pairs: int,
        human_score: int,
        bmo_score: int,
        moves: int,
        seconds: int,
    ) -> int:
        winner = "YOU" if human_score > bmo_score else "BMO" if bmo_score > human_score else "TIE"
        self.games.append(
            {
                "played_at": datetime.now().isoformat(timespec="seconds"),
                "pairs": pairs,
                "human": human_score,
                "bmo": bmo_score,
                "winner": winner,
                "moves": moves,
                "seconds": seconds,
            }
        )
        self.games = self.games[-50:]
        self.pair_count = self._clamp(pairs)
        self.save()
        return self.pair_count

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.write_text(
                json.dumps({"pair_count": self.pair_count, "games": self.games}, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[MATCHING GAME] Could not save scores: {exc}", flush=True)

    def _clamp(self, pair_count: int) -> int:
        return min(max(pair_count, min(MIN_PAIR_COUNT, self.maximum_pairs)), self.maximum_pairs)


class MatchingGameModel:
    """UI-independent matching-game state."""

    def __init__(
        self,
        characters: tuple[str, ...] = CHARACTER_FILES,
        rng: random.Random | None = None,
    ) -> None:
        if len(characters) < 2:
            raise ValueError("The game needs at least two character pairs.")
        self.characters = characters
        self.rng = rng or random.Random()
        self.reset()

    def reset(self) -> None:
        characters = list(self.characters) * 2
        self.rng.shuffle(characters)
        self.cards = [Card(index, character) for index, character in enumerate(characters)]
        self.face_up: list[int] = []
        self.matched: set[int] = set()
        self.current_player = "human"
        self.scores = {"human": 0, "bmo": 0}
        self.moves = 0
        self.started_at: float | None = None
        self.finished_at: float | None = None

    def set_characters(self, characters: tuple[str, ...]) -> None:
        if len(characters) < 2:
            raise ValueError("The game needs at least two character pairs.")
        self.characters = characters
        self.reset()

    @property
    def complete(self) -> bool:
        return len(self.matched) == len(self.cards)

    @property
    def elapsed_seconds(self) -> int:
        if self.started_at is None:
            return 0
        return max(0, int((self.finished_at or time.monotonic()) - self.started_at))

    def reveal(self, card_id: int) -> str:
        if (
            self.complete
            or not 0 <= card_id < len(self.cards)
            or card_id in self.matched
            or card_id in self.face_up
            or len(self.face_up) >= 2
        ):
            return "ignored"
        if self.started_at is None:
            self.started_at = time.monotonic()
        self.face_up.append(card_id)
        if len(self.face_up) == 1:
            return "first"
        self.moves += 1
        first, second = self.face_up
        if self.cards[first].character == self.cards[second].character:
            self.matched.update((first, second))
            self.scores[self.current_player] += 1
            self.face_up = []
            if self.complete:
                self.finished_at = time.monotonic()
            return "match"
        return "miss"

    def hide_unmatched(self) -> tuple[int, int] | tuple[()]:
        if len(self.face_up) != 2:
            return ()
        hidden = (self.face_up[0], self.face_up[1])
        self.face_up = []
        self.current_player = "bmo" if self.current_player == "human" else "human"
        return hidden


class BmoMemoryPlayer:
    """Choose cards using only faces BMO has seen."""

    def __init__(
        self,
        rng: random.Random | None = None,
        recall_probability: float = 0.72,
    ) -> None:
        if not 0.0 <= recall_probability <= 1.0:
            raise ValueError("recall_probability must be between 0 and 1")
        self.rng = rng or random.Random()
        self.recall_probability = recall_probability
        self.memory: dict[int, str] = {}

    def reset(self) -> None:
        self.memory.clear()

    def observe(self, card_id: int, character: str) -> None:
        self.memory[card_id] = character

    def forget_matched(self, matched: set[int]) -> None:
        for card_id in matched:
            self.memory.pop(card_id, None)

    def choose_first(self, game: MatchingGameModel) -> int:
        available = self._available(game)
        known: dict[str, list[int]] = {}
        for card_id in available:
            character = self.memory.get(card_id)
            if character:
                known.setdefault(character, []).append(card_id)
        pairs = [card_ids for card_ids in known.values() if len(card_ids) >= 2]
        if pairs and self._recalls():
            return self.rng.choice(self.rng.choice(pairs))
        unseen = [card_id for card_id in available if card_id not in self.memory]
        return self.rng.choice(unseen or available)

    def choose_second(self, game: MatchingGameModel, first_id: int) -> int:
        available = [card_id for card_id in self._available(game) if card_id != first_id]
        known_match = [
            card_id
            for card_id in available
            if self.memory.get(card_id) == self.memory.get(first_id)
        ]
        if known_match and self._recalls():
            return self.rng.choice(known_match)
        unseen = [card_id for card_id in available if card_id not in self.memory]
        return self.rng.choice(unseen or available)

    def _recalls(self) -> bool:
        return self.rng.random() < self.recall_probability

    @staticmethod
    def _available(game: MatchingGameModel) -> list[int]:
        return [card.card_id for card in game.cards if card.card_id not in game.matched]


__all__ = [
    "BmoMemoryPlayer",
    "CARD_BACK_PATH",
    "CHARACTER_FILES",
    "Card",
    "DEFAULT_PAIR_COUNT",
    "MatchingGameHistory",
    "MatchingGameModel",
    "MIN_PAIR_COUNT",
    "PAW_PATROL_DIR",
    "SCORE_HISTORY_PATH",
]
