"""Tests for the UI-independent matching-game rules."""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from bmo.matching_game import (
    BmoMemoryPlayer,
    CHARACTER_FILES,
    MatchingGameHistory,
    MatchingGameModel,
    SCORE_HISTORY_PATH,
    is_matching_game_start_request,
)
from bmo.matching_game_core import SCORE_HISTORY_PATH as CORE_SCORE_HISTORY_PATH


class MatchingGameModelTests(unittest.TestCase):
    def test_score_history_uses_plugin_data_directory(self) -> None:
        expected = (
            Path(__file__).resolve().parents[1]
            / "bmo"
            / "data"
            / "matching_game"
            / "matching_game_scores.json"
        )
        self.assertEqual(SCORE_HISTORY_PATH, expected)
        self.assertEqual(CORE_SCORE_HISTORY_PATH, expected)

    def make_game(self) -> MatchingGameModel:
        return MatchingGameModel(
            characters=("Chase", "Skye"),
            rng=random.Random(7),
        )

    def test_reset_creates_two_of_every_character(self) -> None:
        game = self.make_game()
        self.assertEqual(len(game.cards), 4)
        self.assertEqual(
            sorted(card.character for card in game.cards),
            ["Chase", "Chase", "Skye", "Skye"],
        )

    def test_matching_pair_is_kept_face_up(self) -> None:
        game = self.make_game()
        first = game.cards[0]
        match = next(
            card for card in game.cards[1:]
            if card.character == first.character
        )
        self.assertEqual(game.reveal(first.card_id), "first")
        self.assertEqual(game.reveal(match.card_id), "match")
        self.assertEqual(game.moves, 1)
        self.assertEqual(game.matched, {first.card_id, match.card_id})
        self.assertEqual(game.face_up, [])
        self.assertEqual(game.scores["human"], 1)

    def test_miss_can_be_hidden(self) -> None:
        game = self.make_game()
        first = game.cards[0]
        other = next(
            card for card in game.cards[1:]
            if card.character != first.character
        )
        self.assertEqual(game.reveal(first.card_id), "first")
        self.assertEqual(game.reveal(other.card_id), "miss")
        self.assertEqual(
            game.hide_unmatched(),
            (first.card_id, other.card_id),
        )
        self.assertEqual(game.face_up, [])
        self.assertEqual(game.current_player, "bmo")

    def test_game_finishes_after_every_pair(self) -> None:
        game = self.make_game()
        for character in game.characters:
            pair = [
                card.card_id for card in game.cards
                if card.character == character
            ]
            game.reveal(pair[0])
            game.reveal(pair[1])
        self.assertTrue(game.complete)
        self.assertIsNotNone(game.finished_at)

    def test_bmo_uses_a_remembered_pair(self) -> None:
        game = self.make_game()
        bmo = BmoMemoryPlayer(
            random.Random(4),
            recall_probability=1.0,
        )
        pair = [
            card.card_id
            for card in game.cards
            if card.character == game.characters[0]
        ]
        for card_id in pair:
            bmo.observe(card_id, game.cards[card_id].character)
        first = bmo.choose_first(game)
        second = bmo.choose_second(game, first)
        self.assertEqual({first, second}, set(pair))

    def test_bmo_can_forget_a_pair_it_has_seen(self) -> None:
        class AlwaysLapseRandom:
            @staticmethod
            def random() -> float:
                return 1.0

            @staticmethod
            def choice(values):
                return values[0]

        game = MatchingGameModel(
            characters=("Chase", "Skye", "Rubble"),
            rng=random.Random(0),
        )
        bmo = BmoMemoryPlayer(
            AlwaysLapseRandom(),
            recall_probability=0.72,
        )
        for card in game.cards:
            bmo.observe(card.card_id, card.character)

        first = bmo.choose_first(game)
        second = bmo.choose_second(game, first)
        self.assertNotEqual(
            game.cards[first].character,
            game.cards[second].character,
        )

    def test_spoken_launch_phrases_are_recognized(self) -> None:
        requests = (
            "Let's play the matching game",
            "Start a memory game",
            "Launch the Paw Patrol game",
            "Pup pairs!",
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(is_matching_game_start_request(request))

    def test_normal_game_discussion_does_not_launch(self) -> None:
        self.assertFalse(
            is_matching_game_start_request("Matching games help your memory")
        )

    def test_all_supplied_images_are_available_at_maximum_difficulty(self) -> None:
        self.assertEqual(len(CHARACTER_FILES), 14)
        self.assertIn("Paw Patrol - Ryder.png", CHARACTER_FILES)
        for shield_number in range(6):
            self.assertIn(
                f"Paw Patrol - Shield {shield_number}.png",
                CHARACTER_FILES,
            )

    def test_history_remembers_scores_without_changing_difficulty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "scores.json"
            history = MatchingGameHistory(path=path)
            next_pairs = history.record_game(
                pairs=6,
                human_score=4,
                bmo_score=2,
                moves=14,
                seconds=42,
            )
            self.assertEqual(next_pairs, 6)

            reloaded = MatchingGameHistory(path=path)
            self.assertEqual(reloaded.pair_count, 6)
            self.assertEqual(reloaded.games[-1]["winner"], "YOU")
            self.assertEqual(reloaded.games[-1]["human"], 4)
            self.assertEqual(reloaded.games[-1]["bmo"], 2)

    def test_manual_difficulty_is_clamped_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            history = MatchingGameHistory(path=path)
            self.assertEqual(history.set_pair_count(100), 14)
            self.assertEqual(
                MatchingGameHistory(path=path).pair_count,
                14,
            )


if __name__ == "__main__":
    unittest.main()
