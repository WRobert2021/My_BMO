"""Structural and regression tests for Bayesian Twenty Questions."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from bmo.twenty_questions import (
    Entity,
    Fact,
    LEARNED_ENTITIES_FILE,
    QUESTION_BY_KEY,
    Question,
    TwentyQuestionsGame,
)


MANHOLE_ANSWERS = {
    "manufactured": "yes",
    "inside_home": "no",
    "physical": "yes",
    "vehicle": "no",
    "handheld": "no",
    "nature": "no",
    "entertainment": "no",
    "practical_task": "no",
    "abstract": "no",
    "edible": "no",
    "larger_person": "no",
    "wheels": "no",
    "electric": "no",
    "before_1900": "yes",
    "alive": "no",
    "kitchen": "no",
    "sports": "no",
}

TV_ANSWERS = {
    "physical": "yes",
    "manufactured": "yes",
    "inside_home": "yes",
    "normally_indoors": "yes",
    "electric": "yes",
    "screen": "yes",
    "entertainment": "yes",
    "handheld": "no",
    "sound": "yes",
    "moving_images": "yes",
    "vehicle": "no",
    "alive": "no",
    "abstract": "no",
}


class TwentyQuestionsTests(unittest.TestCase):
    def make_game(self, *, debug: bool = False) -> TwentyQuestionsGame:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return TwentyQuestionsGame(
            Path(temp_dir.name) / "learned.json",
            debug=debug,
        )

    def test_missing_trait_is_unknown_not_false(self) -> None:
        item = Entity("test:x", "x", "object", .5)
        likelihoods = item.likelihoods("electric")
        self.assertEqual(likelihoods["yes"], likelihoods["no"])
        self.assertFalse(item.fact("electric").known)

    def test_explicit_false_trait_favors_no(self) -> None:
        item = Entity(
            "test:x",
            "x",
            "object",
            .5,
            {"electric": Fact.no()},
        )
        likelihoods = item.likelihoods("electric")
        self.assertGreater(likelihoods["no"], likelihoods["yes"])

    def test_provisional_candidates_replay_complete_history(self) -> None:
        game = self.make_game()
        game.start()
        game.observe("physical", "yes")
        game.observe("manufactured", "yes")
        added = game.add_provisional_candidates(
            [
                {
                    "name": "matching object",
                    "entity_type": "object",
                    "traits": {
                        "physical": "yes",
                        "manufactured": "yes",
                    },
                },
                {
                    "name": "contradicted object",
                    "entity_type": "object",
                    "traits": {
                        "physical": "no",
                        "manufactured": "no",
                    },
                },
            ]
        )
        self.assertEqual(added, 2)
        probabilities = game.probabilities()
        self.assertGreater(
            probabilities["provisional:matching_object"],
            probabilities["provisional:contradicted_object"],
        )

    def test_rejected_guesses_cannot_return_through_expansion(self) -> None:
        game = self.make_game()
        game.start()
        game.current_question = None
        game.current_guess = game.entities["object:chair"]
        game.accept_answer("no")
        self.assertEqual(
            game.add_provisional_candidates(
                [
                    {
                        "name": "a chair",
                        "entity_type": "furniture",
                        "traits": {},
                    }
                ]
            ),
            0,
        )

    def test_inapplicable_question_is_not_eligible(self) -> None:
        item = game_entity = Entity(
            "concept:x",
            "idea",
            "abstract",
            .5,
            {"physical": Fact.no()},
        )
        circular = QUESTION_BY_KEY["circular"]
        self.assertFalse(
            TwentyQuestionsGame._question_applies(circular, game_entity)
        )

    def test_semantic_duplicate_group_is_not_selected(self) -> None:
        game = self.make_game()
        game.start()
        game.asked_groups.add("origin_period")
        probabilities = game.probabilities()
        selected = game._best_question(probabilities)
        if selected:
            self.assertNotEqual(
                selected[0].semantic_group,
                "origin_period",
            )

    def test_low_coverage_question_is_rejected(self) -> None:
        game = self.make_game()
        low_coverage = Question(
            "rare_fact",
            "Is it rare?",
            "test",
            min_coverage=.8,
        )
        coverage = sum(
            probability
            for entity_id, probability in game.probabilities().items()
            if game.entities.get(entity_id)
            and game.entities[entity_id].fact(low_coverage.key).known
        )
        self.assertEqual(coverage, 0)

    def test_strongly_contradicted_entity_is_not_guessed(self) -> None:
        game = self.make_game()
        game.start()
        game.observe("manufactured", "yes")
        game.observe("nature", "no")
        for entity_id in game.log_scores:
            game.log_scores[entity_id] = -20
        game.log_scores["element:oxygen"] = 0
        game._normalize_scores()
        game.next_move()
        self.assertNotEqual(
            getattr(game.current_guess, "entity_id", None),
            "element:oxygen",
        )

    def test_empty_expansion_is_visible_in_debug_output(self) -> None:
        game = self.make_game(debug=True)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            game.start()
            added = game.add_provisional_candidates([])
        self.assertEqual(added, 0)
        self.assertIn("returned=0", stream.getvalue())

    def test_learned_entity_merges_observations(self) -> None:
        game = self.make_game()
        for answer in ("yes", "no"):
            game.start()
            game.observe("electric", answer)
            game.reveal_and_learn("A Toaster")
        payload = json.loads(game.learned_path.read_text(encoding="utf-8"))
        record = payload["entities"][0]
        self.assertEqual(record["name"], "toaster")
        self.assertIn("A Toaster", record["aliases"])
        self.assertEqual(
            record["observations"]["electric"]["yes"],
            1,
        )
        self.assertEqual(
            record["observations"]["electric"]["no"],
            1,
        )

    def test_default_persistence_path_is_cwd_independent(self) -> None:
        self.assertTrue(LEARNED_ENTITIES_FILE.is_absolute())
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                game = TwentyQuestionsGame()
                self.assertEqual(game.learned_path, LEARNED_ENTITIES_FILE)
            finally:
                os.chdir(old_cwd)

    def test_answer_parser_accepts_bullets_and_filler(self) -> None:
        self.assertEqual(TwentyQuestionsGame.parse_answer("- Yes."), "yes")
        self.assertEqual(TwentyQuestionsGame.parse_answer("• No."), "no")
        self.assertEqual(TwentyQuestionsGame.parse_answer("Oh. No."), "no")
        self.assertIsNone(TwentyQuestionsGame.parse_answer("not yes"))

    def test_manhole_cover_regression_ranks_correct_entity(self) -> None:
        game = self.make_game()
        game.start()
        for key, answer in MANHOLE_ANSWERS.items():
            game.observe(key, answer)
        ranking = game.ranking(10)
        self.assertEqual(ranking[0][0], "manhole cover")
        top_names = {name for name, _, _ in ranking[:5]}
        self.assertNotIn("chair", top_names)
        self.assertNotIn("oxygen", top_names)
        self.assertNotIn("war", top_names)
        move = game.next_move()
        self.assertEqual(
            game.current_guess.entity_id,
            "infrastructure:manhole_cover",
        )
        self.assertLessEqual(game.question_count, 20)
        self.assertIn("manhole cover", move)

    def test_manhole_cover_survives_subjective_maybe_answer(self) -> None:
        game = self.make_game()
        game.start()
        answers = dict(MANHOLE_ANSWERS)
        answers["practical_task"] = "maybe"
        for key, answer in answers.items():
            game.observe(key, answer)
        self.assertEqual(game.ranking(1)[0][0], "manhole cover")

    def test_television_beats_phone(self) -> None:
        game = self.make_game()
        game.start()
        for key, answer in TV_ANSWERS.items():
            game.observe(key, answer)
        names = [name for name, _, _ in game.ranking(3)]
        self.assertEqual(names[0], "television")
        self.assertLess(names.index("television"), names.index("smartphone"))
        game.next_move()
        self.assertEqual(game.current_guess.entity_id, "device:television")

    def test_television_survives_one_inaccurate_answer(self) -> None:
        game = self.make_game()
        game.start()
        answers = dict(TV_ANSWERS)
        answers["sound"] = "no"
        for key, answer in answers.items():
            game.observe(key, answer)
        names = [name for name, _, _ in game.ranking(5)]
        self.assertIn("television", names)


if __name__ == "__main__":
    unittest.main()
