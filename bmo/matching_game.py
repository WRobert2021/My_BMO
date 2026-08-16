"""Touch-friendly Paw Patrol matching game for the Raspberry Pi display."""

from __future__ import annotations

import json
import random
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

from bmo.matching_game_text import is_matching_game_start_request
from bmo.ui.compact_face import CompactFace


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

WINDOW_SIZE = (800, 480)
DEFAULT_PAIR_COUNT = 6
MIN_PAIR_COUNT = 4
BOARD_BOUNDS = (154, 72, 628, 448)
CARD_GAP = 6
FLIP_STEPS = (0.70, 0.38, 0.12, 0.38, 0.70, 1.0)


@dataclass(frozen=True)
class Card:
    """One card in a shuffled deck."""

    card_id: int
    character: str


class MatchingGameHistory:
    """Persist the selected difficulty and a bounded list of game results."""

    def __init__(
        self,
        path: Path = SCORE_HISTORY_PATH,
        maximum_pairs: int = len(CHARACTER_FILES),
    ) -> None:
        self.path = path
        self.maximum_pairs = maximum_pairs
        self.pair_count = min(DEFAULT_PAIR_COUNT, maximum_pairs)
        self.games: list[dict[str, int | str]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("history root must be an object")
            pair_count = int(data.get("pair_count", self.pair_count))
            games = data.get("games", [])
            if not isinstance(games, list):
                raise ValueError("games must be a list")
            self.pair_count = self._clamp(pair_count)
            self.games = [
                game for game in games
                if isinstance(game, dict)
            ][-50:]
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
        if human_score > bmo_score:
            winner = "YOU"
        elif bmo_score > human_score:
            winner = "BMO"
        else:
            winner = "TIE"
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
        # Difficulty is controlled by the player. Completing a game records
        # the result without silently changing the next board size.
        self.pair_count = self._clamp(pairs)
        self.save()
        return self.pair_count

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(
                    {
                        "pair_count": self.pair_count,
                        "games": self.games,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[MATCHING GAME] Could not save scores: {exc}", flush=True)

    def _clamp(self, pair_count: int) -> int:
        minimum = min(MIN_PAIR_COUNT, self.maximum_pairs)
        return min(max(pair_count, minimum), self.maximum_pairs)


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
        self.cards: list[Card] = []
        self.face_up: list[int] = []
        self.matched: set[int] = set()
        self.current_player = "human"
        self.scores = {"human": 0, "bmo": 0}
        self.moves = 0
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.reset()

    def reset(self) -> None:
        characters = list(self.characters) * 2
        self.rng.shuffle(characters)
        self.cards = [
            Card(card_id=index, character=character)
            for index, character in enumerate(characters)
        ]
        self.face_up = []
        self.matched = set()
        self.current_player = "human"
        self.scores = {"human": 0, "bmo": 0}
        self.moves = 0
        self.started_at = None
        self.finished_at = None

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
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0, int(end - self.started_at))

    def reveal(self, card_id: int) -> str:
        """Reveal a card and return ignored, first, match, or miss."""
        if self.complete or card_id in self.matched or card_id in self.face_up:
            return "ignored"
        if len(self.face_up) >= 2:
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
        self.current_player = (
            "bmo" if self.current_player == "human" else "human"
        )
        return hidden


class BmoMemoryPlayer:
    """Choose cards using only faces that BMO has already seen."""

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
        known_by_character: dict[str, list[int]] = {}
        for card_id in available:
            character = self.memory.get(card_id)
            if character:
                known_by_character.setdefault(character, []).append(card_id)
        pairs = [
            card_ids
            for card_ids in known_by_character.values()
            if len(card_ids) >= 2
        ]
        if pairs and self._recalls():
            return self.rng.choice(self.rng.choice(pairs))

        unseen = [card_id for card_id in available if card_id not in self.memory]
        return self.rng.choice(unseen or available)

    def choose_second(self, game: MatchingGameModel, first_id: int) -> int:
        available = [
            card_id
            for card_id in self._available(game)
            if card_id != first_id
        ]
        character = self.memory.get(first_id)
        known_match = [
            card_id
            for card_id in available
            if self.memory.get(card_id) == character
        ]
        if known_match and self._recalls():
            return self.rng.choice(known_match)

        unseen = [card_id for card_id in available if card_id not in self.memory]
        return self.rng.choice(unseen or available)

    def _recalls(self) -> bool:
        """Sometimes lapse so a fully revealed board is not solved perfectly."""
        return self.rng.random() < self.recall_probability

    @staticmethod
    def _available(game: MatchingGameModel) -> list[int]:
        return [
            card.card_id
            for card in game.cards
            if card.card_id not in game.matched
        ]


class MatchingGameApp:
    """Draw and coordinate the matching game on a Tk canvas."""

    BACKGROUND = "#e7f7ff"
    NAVY = "#102a5e"
    BLUE = "#1578d3"
    FRONT = "#f3cf31"
    WHITE = "#ffffff"
    MUTED = "#58708c"

    def __init__(
        self,
        root: tk.Tk,
        *,
        embedded: bool = False,
        on_close: Callable[[], None] | None = None,
        announce: Callable[[str], None] | None = None,
        face_provider: Callable[[], Image.Image | None] | None = None,
        on_player_change: Callable[[str], None] | None = None,
        history: MatchingGameHistory | None = None,
    ) -> None:
        self.root = root
        self.embedded = embedded
        self.on_close = on_close
        self.announce = announce
        self.on_player_change = on_player_change
        self.history = history or MatchingGameHistory()
        self.pair_count = self.history.pair_count
        self.model = MatchingGameModel(
            CHARACTER_FILES[: self.pair_count]
        )
        self.bmo = BmoMemoryPlayer()
        self.canvas = tk.Canvas(
            root,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        if embedded:
            self.canvas.place(x=0, y=0, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1])
        else:
            self.canvas.pack(fill=tk.BOTH, expand=True)
        self.card_images: dict[str, ImageTk.PhotoImage] = {}
        self.back_image: ImageTk.PhotoImage | None = None
        self.source_art: dict[str, Image.Image] = {}
        self.back_source: Image.Image | None = None
        self.card_size = (106, 116)
        self.grid_columns = 4
        self.board_origin = (154, 72)
        self.card_items: dict[int, int] = {}
        self.animating = False
        self.pending_after_ids: set[str] = set()
        self.tick_after_id: str | None = None
        self.win_items: list[int] = []
        self.game_recorded = False

        self._configure_window()
        self._load_source_images()
        self._draw_static_ui()
        self.compact_face = CompactFace(
            root,
            self.canvas,
            face_provider=face_provider,
        )
        self.new_game()
        self._tick()

    def _configure_window(self) -> None:
        if self.embedded:
            return
        self.root.title("Pup Pairs")
        self.root.geometry(f"{WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}")
        self.root.resizable(False, False)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", self._exit_fullscreen)
        self.root.bind("<Key-r>", lambda _event: self.new_game())
        self.root.bind("<Key-R>", lambda _event: self.new_game())

    def _exit_fullscreen(self, _event: tk.Event | None = None) -> None:
        self.root.attributes("-fullscreen", False)

    @staticmethod
    def _rounded_card(color: str, card_size: tuple[int, int]) -> Image.Image:
        scale = 3
        width, height = card_size
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (2 * scale, 2 * scale, (width - 2) * scale, (height - 2) * scale),
            radius=12 * scale,
            fill=color,
            outline="#ffffff",
            width=3 * scale,
        )
        return image.resize(card_size, Image.Resampling.LANCZOS)

    @staticmethod
    def _crop_subject(image: Image.Image) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha_box = rgba.getchannel("A").getbbox()
        if alpha_box:
            return rgba.crop(alpha_box)
        return rgba

    def _load_source_images(self) -> None:
        if not CARD_BACK_PATH.exists():
            raise FileNotFoundError(f"Missing card back: {CARD_BACK_PATH}")

        self.back_source = Image.open(CARD_BACK_PATH).convert("RGBA")
        for filename in CHARACTER_FILES:
            source_path = PAW_PATROL_DIR / filename
            if not source_path.exists():
                raise FileNotFoundError(f"Missing character art: {source_path}")
            self.source_art[filename] = self._crop_subject(
                Image.open(source_path)
            )

    def _build_card_images(self) -> None:
        width, height = self.card_size
        if self.back_source is None:
            raise RuntimeError("Card back image has not been loaded.")
        back = self.back_source.copy()
        back.thumbnail((width - 6, height - 6), Image.Resampling.LANCZOS)
        back_plate = self._rounded_card(self.WHITE, self.card_size)
        back_plate.alpha_composite(
            back,
            ((width - back.width) // 2, (height - back.height) // 2),
        )
        self.back_image = ImageTk.PhotoImage(back_plate)

        self.card_images.clear()
        for filename in self.model.characters:
            subject = self.source_art[filename].copy()
            subject.thumbnail(
                (width - 10, height - 10),
                Image.Resampling.LANCZOS,
            )
            face = self._rounded_card(self.FRONT, self.card_size)
            face.alpha_composite(
                subject,
                (
                    (width - subject.width) // 2,
                    (height - subject.height) // 2,
                ),
            )
            self.card_images[filename] = ImageTk.PhotoImage(face)

    def _draw_static_ui(self) -> None:
        self.canvas.create_rectangle(0, 0, 800, 62, fill=self.NAVY, outline="")
        self.canvas.create_text(
            24,
            30,
            anchor="w",
            text="PUP PAIRS",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self._draw_button(552, 10, 668, 51, "EXIT GAME", self.close)
        self.canvas.create_text(
            714,
            207,
            text="PREVIOUS GAMES",
            fill=self.MUTED,
            font=("Arial", 9, "bold"),
        )
        self.history_items = [
            self.canvas.create_text(
                714,
                232 + index * 27,
                text="—",
                fill=self.NAVY,
                font=("Arial", 9, "bold"),
            )
            for index in range(5)
        ]
        self.canvas.create_text(
            76,
            79,
            text="YOUR PAIRS",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.human_score_item = self.canvas.create_text(
            76,
            106,
            text="0",
            fill=self.BLUE,
            font=("Arial Rounded MT Bold", 27, "bold"),
        )
        self.canvas.create_text(
            76,
            142,
            text="BMO'S PAIRS",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.bmo_score_item = self.canvas.create_text(
            76,
            169,
            text="0",
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 27, "bold"),
        )
        self.canvas.create_text(
            76,
            207,
            text="MOVES",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.moves_item = self.canvas.create_text(
            76,
            233,
            text="0",
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.canvas.create_text(
            76,
            269,
            text="TIME",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self.time_item = self.canvas.create_text(
            76,
            295,
            text="0:00",
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 22, "bold"),
        )
        self.canvas.create_text(
            76,
            332,
            text="NUMBER OF PAIRS",
            fill=self.MUTED,
            font=("Arial", 10, "bold"),
        )
        self._draw_button(
            18,
            347,
            55,
            384,
            "−",
            lambda: self.change_difficulty(-1),
        )
        self.difficulty_item = self.canvas.create_text(
            76,
            365,
            text="6",
            fill=self.NAVY,
            font=("Arial Rounded MT Bold", 16, "bold"),
        )
        self._draw_button(
            97,
            347,
            134,
            384,
            "+",
            lambda: self.change_difficulty(1),
        )
        self._draw_button(18, 402, 135, 443, "NEW GAME", self.new_game)
        self.status_item = self.canvas.create_text(
            548,
            462,
            text="Pick a card to start!",
            fill=self.MUTED,
            font=("Arial", 12, "bold"),
        )

    def _draw_button(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        label: str,
        command: Callable[[], None],
    ) -> None:
        tag = f"button-{label.lower().replace(' ', '-')}"
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=self.BLUE,
            outline="",
            tags=(tag,),
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=label,
            fill=self.WHITE,
            font=("Arial", 11, "bold"),
            tags=(tag,),
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event: command())

    def _cancel_pending(self) -> None:
        for after_id in tuple(self.pending_after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.pending_after_ids.clear()

    def _after(self, delay: int, callback: Callable[[], None]) -> None:
        after_id = ""

        def run() -> None:
            self.pending_after_ids.discard(after_id)
            callback()

        after_id = self.root.after(delay, run)
        self.pending_after_ids.add(after_id)

    def new_game(self) -> None:
        self._cancel_pending()
        self.animating = False
        self.game_recorded = False
        self.model.set_characters(
            CHARACTER_FILES[: self.pair_count]
        )
        self.bmo.reset()
        for item in self.card_items.values():
            self.canvas.delete(item)
        for item in self.win_items:
            self.canvas.delete(item)
        self.card_items.clear()
        self.win_items.clear()
        self._configure_board()
        self._build_card_images()

        for card in self.model.cards:
            row, column = divmod(card.card_id, self.grid_columns)
            x = self.board_origin[0] + column * (
                self.card_size[0] + CARD_GAP
            )
            y = self.board_origin[1] + row * (
                self.card_size[1] + CARD_GAP
            )
            item = self.canvas.create_image(
                x,
                y,
                anchor=tk.NW,
                image=self.back_image,
                tags=(f"card-{card.card_id}", "card"),
            )
            self.card_items[card.card_id] = item
            self.canvas.tag_bind(
                f"card-{card.card_id}",
                "<Button-1>",
                lambda _event, card_id=card.card_id: self.choose_card(card_id),
            )
        self.canvas.tag_raise(self.status_item)
        self._update_stats("Your turn — pick a card!")
        self._update_history()
        if self.on_player_change:
            self.on_player_change("human")

    def change_difficulty(self, amount: int) -> None:
        new_count = min(
            max(self.pair_count + amount, MIN_PAIR_COUNT),
            len(CHARACTER_FILES),
        )
        if new_count == self.pair_count:
            return
        self.pair_count = self.history.set_pair_count(new_count)
        self.new_game()

    def _configure_board(self) -> None:
        total_cards = self.pair_count * 2
        if total_cards <= 12:
            columns = 4
        elif total_cards <= 20:
            columns = 5
        elif total_cards <= 24:
            columns = 6
        else:
            columns = 7
        rows = (total_cards + columns - 1) // columns
        left, top, right, bottom = BOARD_BOUNDS
        available_width = right - left - CARD_GAP * (columns - 1)
        available_height = bottom - top - CARD_GAP * (rows - 1)
        self.grid_columns = columns
        self.card_size = (
            available_width // columns,
            available_height // rows,
        )
        board_width = columns * self.card_size[0] + CARD_GAP * (columns - 1)
        board_height = rows * self.card_size[1] + CARD_GAP * (rows - 1)
        self.board_origin = (
            left + (right - left - board_width) // 2,
            top + (bottom - top - board_height) // 2,
        )

    def choose_card(self, card_id: int) -> None:
        if self.animating or self.model.current_player != "human":
            return
        self._reveal_card(card_id)

    def _reveal_card(self, card_id: int) -> None:
        result = self.model.reveal(card_id)
        if result == "ignored":
            return
        card = self.model.cards[card_id]
        self.bmo.observe(card_id, card.character)

        self.animating = True
        self._animate_flip(
            card_id,
            show_front=True,
            on_complete=lambda: self._after_reveal(result),
        )

    def _animate_flip(
        self,
        card_id: int,
        show_front: bool,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        item = self.card_items[card_id]
        card = self.model.cards[card_id]
        full_image = (
            self.card_images[card.character] if show_front else self.back_image
        )
        source = ImageTk.getimage(full_image).convert("RGBA")

        def step(index: int) -> None:
            scale = FLIP_STEPS[index]
            card_width, card_height = self.card_size
            width = max(2, int(card_width * scale))
            frame = source.resize(
                (width, card_height),
                Image.Resampling.LANCZOS,
            )
            frame_image = ImageTk.PhotoImage(frame)
            self.canvas.itemconfigure(item, image=frame_image)
            self.canvas.coords(
                item,
                self._card_x(card_id) + (card_width - width) // 2,
                self._card_y(card_id),
            )
            self.canvas.image_refs = getattr(self.canvas, "image_refs", {})
            self.canvas.image_refs[card_id] = frame_image
            if index + 1 < len(FLIP_STEPS):
                self._after(28, lambda: step(index + 1))
            else:
                self.canvas.itemconfigure(item, image=full_image)
                self.canvas.coords(item, self._card_x(card_id), self._card_y(card_id))
                if on_complete:
                    on_complete()

        step(0)

    def _card_x(self, card_id: int) -> int:
        return self.board_origin[0] + (card_id % self.grid_columns) * (
            self.card_size[0] + CARD_GAP
        )

    def _card_y(self, card_id: int) -> int:
        return self.board_origin[1] + (card_id // self.grid_columns) * (
            self.card_size[1] + CARD_GAP
        )

    def _after_reveal(self, result: str) -> None:
        self.animating = False
        if result == "first":
            if self.model.current_player == "human":
                self._update_stats("Now find its match!")
            else:
                self._update_stats("BMO is remembering...")
                self._after(450, self._bmo_choose_second)
            return
        if result == "match":
            player = self.model.current_player
            self.bmo.forget_matched(self.model.matched)
            status = (
                "Great match! Go again."
                if player == "human"
                else "BMO found a pair and goes again!"
            )
            self._update_stats(status)
            if self.model.complete:
                self._after(450, self._show_win)
            elif player == "bmo":
                self._after(750, self._bmo_take_turn)
            return

        player = self.model.current_player
        status = (
            "No match. BMO's turn!"
            if player == "human"
            else "No match. Your turn next!"
        )
        self._update_stats(status)
        self.animating = True
        self._after(650, self._hide_miss)

    def _hide_miss(self) -> None:
        hidden = self.model.hide_unmatched()
        if not hidden:
            self.animating = False
            return

        first, second = hidden
        remaining = 2

        def finished() -> None:
            nonlocal remaining
            remaining -= 1
            if remaining == 0:
                self.animating = False
                if self.model.current_player == "bmo":
                    self._update_stats("BMO's turn...")
                    if self.on_player_change:
                        self.on_player_change("bmo")
                    self._after(550, self._bmo_take_turn)
                else:
                    self._update_stats("Your turn — pick a card!")
                    if self.on_player_change:
                        self.on_player_change("human")

        self._animate_flip(first, show_front=False, on_complete=finished)
        self._animate_flip(second, show_front=False, on_complete=finished)

    def _bmo_take_turn(self) -> None:
        if self.model.complete or self.model.current_player != "bmo":
            return
        self._update_stats("BMO is choosing...")
        self._reveal_card(self.bmo.choose_first(self.model))

    def _bmo_choose_second(self) -> None:
        if len(self.model.face_up) != 1:
            return
        first_id = self.model.face_up[0]
        self._reveal_card(self.bmo.choose_second(self.model, first_id))

    def _update_stats(self, status: str | None = None) -> None:
        self.canvas.itemconfigure(
            self.human_score_item,
            text=str(self.model.scores["human"]),
        )
        self.canvas.itemconfigure(
            self.bmo_score_item,
            text=str(self.model.scores["bmo"]),
        )
        self.canvas.itemconfigure(self.moves_item, text=str(self.model.moves))
        self.canvas.itemconfigure(
            self.difficulty_item,
            text=str(self.pair_count),
        )
        if status is not None:
            self.canvas.itemconfigure(self.status_item, text=status)

    def _update_history(self) -> None:
        recent_games = list(reversed(self.history.games[-5:]))
        for index, item in enumerate(self.history_items):
            if index >= len(recent_games):
                text = "—"
            else:
                game = recent_games[index]
                text = (
                    f"{game.get('pairs', '?')}P  "
                    f"{game.get('human', '?')}–{game.get('bmo', '?')}  "
                    f"{game.get('winner', '?')}"
                )
            self.canvas.itemconfigure(item, text=text)

    def _tick(self) -> None:
        seconds = self.model.elapsed_seconds
        self.canvas.itemconfigure(
            self.time_item,
            text=f"{seconds // 60}:{seconds % 60:02d}",
        )
        self.tick_after_id = self.root.after(250, self._tick)

    def _show_win(self) -> None:
        self.animating = True
        human_score = self.model.scores["human"]
        bmo_score = self.model.scores["bmo"]
        completed_pairs = self.pair_count
        if not self.game_recorded:
            self.pair_count = self.history.record_game(
                pairs=completed_pairs,
                human_score=human_score,
                bmo_score=bmo_score,
                moves=self.model.moves,
                seconds=self.model.elapsed_seconds,
            )
            self.game_recorded = True
            self._update_history()
            self._update_stats()
        if human_score > bmo_score:
            headline = "YOU WIN!"
            spoken = "You win! Great matching!"
        elif bmo_score > human_score:
            headline = "BMO WINS!"
            spoken = "I win! That was fun. Let's play again!"
        else:
            headline = "IT'S A TIE!"
            spoken = "It's a tie! Great game!"
        if self.announce:
            if self.on_player_change:
                self.on_player_change("speaking")
            self.announce(spoken)
        self.win_items = [
            self.canvas.create_rectangle(
                177,
                130,
                625,
                382,
                fill=self.NAVY,
                outline=self.WHITE,
                width=4,
            ),
            self.canvas.create_text(
                401,
                181,
                text=headline,
                fill=self.FRONT,
                font=("Arial Rounded MT Bold", 31, "bold"),
            ),
            self.canvas.create_text(
                401,
                231,
                text=f"You {human_score}  •  BMO {bmo_score}",
                fill=self.WHITE,
                font=("Arial", 17, "bold"),
            ),
            self.canvas.create_text(
                401,
                278,
                text=(
                    f"{self.model.moves} moves  •  "
                    f"{self.model.elapsed_seconds // 60}:"
                    f"{self.model.elapsed_seconds % 60:02d}  •  "
                    f"{completed_pairs} pairs"
                ),
                fill="#bde7ff",
                font=("Arial", 15, "bold"),
            ),
        ]
        tag = "play-again"
        self.win_items.extend(
            [
                self.canvas.create_rectangle(
                    310,
                    315,
                    492,
                    361,
                    fill=self.BLUE,
                    outline="",
                    tags=(tag,),
                ),
                self.canvas.create_text(
                    401,
                    338,
                    text="PLAY AGAIN",
                    fill=self.WHITE,
                    font=("Arial", 12, "bold"),
                    tags=(tag,),
                ),
            ]
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event: self.new_game())

    def close(self) -> None:
        self._cancel_pending()
        if self.tick_after_id:
            try:
                self.root.after_cancel(self.tick_after_id)
            except tk.TclError:
                pass
            self.tick_after_id = None
        self.compact_face.destroy()
        if self.embedded:
            self.canvas.destroy()
        else:
            self.root.destroy()
        if self.on_close:
            self.on_close()


def main() -> None:
    root = tk.Tk()
    MatchingGameApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
