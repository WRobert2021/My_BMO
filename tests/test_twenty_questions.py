"""Synthetic-catalog tests for the indexed Twenty Questions engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bmo.twenty_questions import (
    ANSWER_PROMPT,
    OBJECT_NAME_KEY,
    CandidateIndex,
    TwentyQuestionsHistory,
    LLM_GUESS_REQUEST,
    TwentyQuestionsDataError,
    TwentyQuestionsDatasetLoader,
    TwentyQuestionsGame,
    normalize_player_answer,
)


QUESTIONS = (
    "Is it warm?",
    "Is it round?",
    "Is it useful?",
    "Is it found indoors?",
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def base_rows() -> list[dict[str, object]]:
    return [
        {
            OBJECT_NAME_KEY: "Alpha",
            QUESTIONS[0]: "Yes",
            QUESTIONS[1]: "Yes",
            QUESTIONS[2]: "No",
            QUESTIONS[3]: "No",
        },
        {
            OBJECT_NAME_KEY: "Beta",
            QUESTIONS[0]: "No",
            QUESTIONS[1]: "No",
            QUESTIONS[2]: "Yes",
            QUESTIONS[3]: "Yes",
        },
        {
            OBJECT_NAME_KEY: "Gamma",
            QUESTIONS[0]: "Yes",
            QUESTIONS[1]: "Yes",
            QUESTIONS[2]: "Yes",
            QUESTIONS[3]: "No",
        },
        {
            OBJECT_NAME_KEY: "Delta",
            QUESTIONS[0]: "No",
            QUESTIONS[1]: "Often",
            QUESTIONS[2]: "Sometimes",
            QUESTIONS[3]: "Yes",
        },
    ]


class DatasetLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.base = root / "data.jsonl"
        self.learned = root / "learned.jsonl"
        write_jsonl(self.base, base_rows())

    def test_valid_wide_jsonl_and_stable_question_order(self) -> None:
        catalog = TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()
        self.assertEqual(catalog.question_keys, QUESTIONS)
        self.assertEqual(catalog.object_names, ("Alpha", "Beta", "Gamma", "Delta"))
        self.assertEqual(catalog.rows[0].answers, ("yes", "yes", "no", "no"))

    def test_case_insensitive_answer_normalization(self) -> None:
        rows = base_rows()
        rows[0][QUESTIONS[0]] = " yEs "
        rows[0][QUESTIONS[1]] = "oFtEn"
        write_jsonl(self.base, rows)
        catalog = TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()
        self.assertEqual(catalog.rows[0].answers[:2], ("yes", "often"))

    def test_duplicate_object_detection(self) -> None:
        rows = base_rows()
        rows[-1][OBJECT_NAME_KEY] = " alpha "
        write_jsonl(self.base, rows)
        with self.assertRaisesRegex(TwentyQuestionsDataError, "duplicates"):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

    def test_missing_or_empty_object_name_is_rejected(self) -> None:
        rows = base_rows()
        rows[0].pop(OBJECT_NAME_KEY)
        write_jsonl(self.base, rows)
        with self.assertRaises(TwentyQuestionsDataError):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

        rows = base_rows()
        rows[0][OBJECT_NAME_KEY] = " \t "
        write_jsonl(self.base, rows)
        with self.assertRaisesRegex(TwentyQuestionsDataError, "empty"):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

    def test_mismatched_questions_and_invalid_answer_are_rejected(self) -> None:
        rows = base_rows()
        rows[1].pop(QUESTIONS[-1])
        rows[1]["A different question"] = "Yes"
        write_jsonl(self.base, rows)
        with self.assertRaisesRegex(TwentyQuestionsDataError, "mismatched"):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

        rows = base_rows()
        rows[0][QUESTIONS[0]] = "Maybe"
        write_jsonl(self.base, rows)
        with self.assertRaises(TwentyQuestionsDataError):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

    def test_missing_file_and_malformed_json_are_rejected(self) -> None:
        missing = self.base.with_name("missing.jsonl")
        with self.assertRaisesRegex(TwentyQuestionsDataError, "unavailable"):
            TwentyQuestionsDatasetLoader(missing, self.learned).load_base()
        self.base.write_text("not json\n", encoding="utf-8")
        with self.assertRaisesRegex(TwentyQuestionsDataError, "valid JSON"):
            TwentyQuestionsDatasetLoader(self.base, self.learned).load_base()

    def test_missing_learned_file_is_an_empty_overlay(self) -> None:
        catalog = TwentyQuestionsDatasetLoader(self.base, self.learned).load()
        self.assertTrue(catalog.learning_enabled)
        self.assertEqual(len(catalog.learned_rows), 0)

    def test_malformed_learned_file_disables_only_learning(self) -> None:
        self.learned.write_text("{not json}\n", encoding="utf-8")
        loader = TwentyQuestionsDatasetLoader(self.base, self.learned)
        catalog = loader.load()
        self.assertFalse(catalog.learning_enabled)
        self.assertEqual(catalog.object_count, 4)
        self.assertFalse(loader.learn("new object", ((QUESTIONS[0], "yes"),)).learning_enabled)
        self.assertIn("ignored", loader.diagnostics[0])

    def test_learned_overlay_uses_unknown_and_merges_case_insensitively(self) -> None:
        write_jsonl(
            self.learned,
            [
                {
                    OBJECT_NAME_KEY: "  aLPHa ",
                    **{question: "Unknown" for question in QUESTIONS},
                },
                {
                    OBJECT_NAME_KEY: "NEW THING",
                    QUESTIONS[0]: "Yes",
                    QUESTIONS[1]: "Unknown",
                    QUESTIONS[2]: "Often",
                    QUESTIONS[3]: "No",
                },
            ],
        )
        catalog = TwentyQuestionsDatasetLoader(self.base, self.learned).load()
        self.assertEqual(catalog.object_names[-1], "NEW THING")
        self.assertEqual(catalog.rows[0].answers, ("yes", "yes", "no", "no"))
        self.assertEqual(catalog.rows[-1].answers[1], "unknown")


class ThingHistoryTests(unittest.TestCase):
    def test_history_rejects_duplicate_json_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(
                '{"things":["first"],"things":["second"]}',
                encoding="utf-8",
            )

            history = TwentyQuestionsHistory(path)

        self.assertEqual(history.snapshot(), ())

    def test_history_keeps_the_five_newest_targets_across_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            history = TwentyQuestionsHistory(path)
            for name in ("one", "two", "three", "four", "five", "six"):
                history.record(name)

            self.assertEqual(
                history.snapshot(),
                ("six", "five", "four", "three", "two"),
            )
            self.assertEqual(
                TwentyQuestionsHistory(path).snapshot(),
                history.snapshot(),
            )

    def test_history_save_uses_atomic_replace_and_cleans_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            history = TwentyQuestionsHistory(path)
            with patch("bmo.twenty_questions.os.replace", wraps=os.replace) as replace:
                history.record("strawberry")

            replace.assert_called_once()
            self.assertEqual(
                list(Path(temp_dir).glob(".history.json.*.tmp")),
                [],
            )


class IndexedGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.base = root / "data.jsonl"
        self.learned = root / "learned.jsonl"
        write_jsonl(self.base, base_rows())

    def make_game(self, **kwargs: object) -> TwentyQuestionsGame:
        return TwentyQuestionsGame(
            learned_path=self.learned,
            base_path=self.base,
            **kwargs,
        )

    def test_index_has_integer_masks_and_best_question_is_deterministic(self) -> None:
        game = self.make_game()
        game.start()
        self.assertIsInstance(game.index, CandidateIndex)
        self.assertEqual(game.index.candidate_count, 4)
        self.assertEqual(game.current_question, QUESTIONS[0])
        self.assertEqual(game.select_question(), QUESTIONS[3])

    def test_yes_no_and_sometimes_filter_with_often_as_wildcard(self) -> None:
        for answer, expected in (
            ("yes", {"Alpha", "Gamma", "Delta"}),
            ("no", {"Beta", "Delta"}),
            ("sometimes", {"Delta"}),
        ):
            with self.subTest(answer=answer):
                game = self.make_game()
                game.start()
                game.accept_answer("unknown")
                game.current_question = QUESTIONS[1]
                game.accept_answer(answer)
                self.assertEqual(set(game.candidate_names), expected)

    def test_unknown_retires_question_without_narrowing_or_reusing_number(self) -> None:
        game = self.make_game()
        game.start()
        first = game.current_question
        self.assertEqual(game.total_prompt_count, 1)
        game.accept_answer("I don’t know")
        response = game.next_move()
        self.assertNotEqual(game.current_question, first)
        self.assertEqual(game.total_prompt_count, 2)
        self.assertIn("Question 2.", response)
        self.assertEqual(game.informative_decisions, 0)
        self.assertEqual(game.candidate_count, 4)

    def test_conflicting_zero_candidate_answer_restores_pool_and_retires_question(self) -> None:
        game = self.make_game()
        game.start()
        game.accept_answer("yes")
        game.next_move()
        question = game.current_question
        pool_before = game.candidate_pool
        # The selected second question has no sometimes branch in this pool.
        game.accept_answer("sometimes")
        self.assertEqual(game.candidate_pool, pool_before)
        self.assertIn(question, game.asked_keys)
        self.assertEqual(game.informative_decisions, 1)
        self.assertTrue(game.active)

    def test_one_candidate_triggers_guess_and_wrong_guess_is_removed(self) -> None:
        game = self.make_game()
        game.start()
        game.accept_answer("yes")
        game.next_move()
        game.accept_answer("yes")
        game.next_move()
        self.assertEqual(game.candidate_count, 1)
        self.assertIsNotNone(game.current_guess)
        guessed = game.current_guess.name
        game.accept_answer("no")
        self.assertNotIn(guessed, game.candidate_names)
        self.assertNotIn(guessed.casefold(), {name.casefold() for name in game.candidate_names})

    def test_guess_does_not_consume_informative_budget_and_sometimes_is_rejected(self) -> None:
        game = self.make_game()
        game.start()
        game.accept_answer("yes")
        game.next_move()
        game.accept_answer("yes")
        game.next_move()
        decisions = game.informative_decisions
        response = game.accept_answer("maybe")
        self.assertIn("yes, no, or I don't know", response or "")
        self.assertEqual(game.informative_decisions, decisions)

    def test_wrong_guess_keeps_questioning_until_the_normal_limit(self) -> None:
        game = self.make_game()
        game.start()
        game.current_question = None
        game.candidate_pool = 1
        self.assertIn("My guess is", game.next_move())
        game.accept_answer("no")

        response = game.next_move()

        self.assertIsNotNone(game.current_question)
        self.assertEqual(game.total_prompt_count, 2)
        self.assertIn("Question 2.", response)

    def test_empty_pool_at_question_nineteen_requests_llm_then_reaches_twenty(self) -> None:
        game = self.make_game()
        game.start()
        for _ in range(18):
            game.accept_answer("unknown")
            game.next_move()
        game.candidate_pool = 0
        game.accept_answer("unknown")

        self.assertEqual(game.next_move(), LLM_GUESS_REQUEST)
        self.assertTrue(game.needs_llm_guess)
        self.assertIn("My guess is", game.offer_llm_guess("A mystery object") or "")
        game.accept_answer("no")
        self.assertEqual(game.history[-1].guessed_object, "A mystery object")
        response = game.next_move()

        self.assertEqual(game.total_prompt_count, 20)
        self.assertIn("Question 20.", response)

    def test_twenty_questions_are_followed_by_four_bonus_questions_and_a_guess(self) -> None:
        game = self.make_game()
        game.start()
        for _ in range(19):
            game.accept_answer("unknown")
            game.next_move()
        game.accept_answer("unknown")
        response = game.next_move()

        self.assertEqual(response, LLM_GUESS_REQUEST)
        self.assertFalse(game.bonus_active)
        game.offer_llm_guess("normal final object")
        game.accept_answer("no")
        response = game.next_move()
        self.assertTrue(game.bonus_active)
        self.assertEqual(game.bonus_question_count, 1)
        self.assertIn("bonus", response.casefold())
        for _ in range(3):
            game.accept_answer("unknown")
            response = game.next_move()
        game.accept_answer("unknown")
        response = game.next_move()

        self.assertEqual(game.total_prompt_count, 24)
        self.assertEqual(game.bonus_question_count, 4)
        self.assertEqual(response, LLM_GUESS_REQUEST)
        self.assertIn("My guess is", game.offer_llm_guess("bonus final object") or "")

    def test_limits_and_cancel(self) -> None:
        invalid_limits = self.make_game(
            informative_question_limit=float("inf"),
            total_prompt_limit=True,
        )
        self.assertEqual(invalid_limits.informative_question_limit, 20)
        self.assertEqual(invalid_limits.total_prompt_limit, 30)

        game = self.make_game(informative_question_limit=1)
        game.start()
        game.accept_answer("yes")
        response = game.next_move()
        self.assertEqual(response, LLM_GUESS_REQUEST)
        game.offer_llm_guess("short round object")
        game.accept_answer("no")
        response = game.next_move()
        self.assertFalse(game.awaiting_reveal)
        self.assertTrue(game.bonus_active)
        self.assertIn("bonus", response.casefold())

        game = self.make_game(total_prompt_limit=1)
        game.start()
        game.accept_answer("unknown")
        self.assertTrue(game.awaiting_reveal)

        game = self.make_game()
        game.start()
        self.assertEqual(game.accept_answer("cancel"), "Okay, game over!")
        self.assertFalse(game.active)

    def test_close_is_idempotent_and_clears_game_state(self) -> None:
        game = self.make_game()
        game.start()
        game.close()
        game.close()
        self.assertFalse(game.active)
        self.assertIsNone(game.current_question)
        self.assertIsNone(game.current_guess)
        self.assertEqual(game.history, [])
        self.assertEqual(game.candidate_names, ())


class LearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.base = root / "data.jsonl"
        self.learned = root / "learned.jsonl"
        write_jsonl(self.base, base_rows())

    def make_game(self) -> TwentyQuestionsGame:
        return TwentyQuestionsGame(learned_path=self.learned, base_path=self.base)

    def reveal_after_second_question(self, target: str, answer: str) -> str:
        game = self.make_game()
        game.start()
        self.assertEqual(game.current_question, QUESTIONS[0])
        game.accept_answer("unknown")
        game.current_question = QUESTIONS[1]
        game.accept_answer(answer)
        return game.reveal_and_learn(target)

    def read_learned(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.learned.read_text(encoding="utf-8").splitlines()]

    def test_base_bytes_never_change_and_often_becomes_learned_yes_or_no(self) -> None:
        before = hashlib.sha256(self.base.read_bytes()).digest()
        self.reveal_after_second_question("Delta", "yes")
        self.assertEqual(hashlib.sha256(self.base.read_bytes()).digest(), before)
        self.assertEqual(self.read_learned()[0][QUESTIONS[1]], "Yes")

        self.learned.unlink()
        self.reveal_after_second_question("Delta", "no")
        self.assertEqual(self.read_learned()[0][QUESTIONS[1]], "No")

    def test_often_is_not_updated_before_target_is_known(self) -> None:
        game = self.make_game()
        game.start()
        game.accept_answer("unknown")
        game.current_question = QUESTIONS[1]
        game.accept_answer("yes")
        self.assertFalse(self.learned.exists())

    def test_unknown_overlay_is_filled_and_hard_values_are_not_overwritten(self) -> None:
        write_jsonl(
            self.learned,
            [
                {
                    OBJECT_NAME_KEY: "Delta",
                    QUESTIONS[0]: "Unknown",
                    QUESTIONS[1]: "Unknown",
                    QUESTIONS[2]: "Unknown",
                    QUESTIONS[3]: "Unknown",
                },
                {
                    OBJECT_NAME_KEY: "Alpha",
                    QUESTIONS[0]: "No",
                    QUESTIONS[1]: "Unknown",
                    QUESTIONS[2]: "Unknown",
                    QUESTIONS[3]: "Unknown",
                },
            ],
        )
        self.reveal_after_second_question("Delta", "sometimes")
        rows = {row[OBJECT_NAME_KEY]: row for row in self.read_learned()}
        self.assertEqual(rows["Delta"][QUESTIONS[1]], "Sometimes")
        game = self.make_game()
        game.start()
        game.accept_answer("yes")
        game.reveal_and_learn("Alpha")
        rows = {row[OBJECT_NAME_KEY]: row for row in self.read_learned()}
        self.assertEqual(rows["Alpha"][QUESTIONS[0]], "No")

    def test_new_object_gets_complete_row_and_case_insensitive_merge(self) -> None:
        self.reveal_after_second_question("  New Thing  ", "yes")
        rows = self.read_learned()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][OBJECT_NAME_KEY], "New Thing")
        self.assertEqual(rows[0][QUESTIONS[0]], "Unknown")
        self.assertEqual(rows[0][QUESTIONS[1]], "Yes")
        self.reveal_after_second_question("new thing", "no")
        self.assertEqual(len(self.read_learned()), 1)
        self.assertEqual(self.read_learned()[0][QUESTIONS[1]], "Yes")

    def test_no_change_does_not_create_learned_file_and_write_is_atomic(self) -> None:
        game = self.make_game()
        game.start()
        game.accept_answer("yes")
        response = game.reveal_and_learn("Alpha")
        self.assertIn("thinking of Alpha", response)
        self.assertFalse(self.learned.exists())

        import os

        with patch("bmo.twenty_questions.os.replace", wraps=os.replace) as replace:
            self.reveal_after_second_question("Delta", "yes")
        replace.assert_called_once()
        self.assertTrue(self.learned.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual(list(self.learned.parent.glob("*.tmp")), [])

    def test_learned_overlay_is_loaded_by_a_future_game(self) -> None:
        self.reveal_after_second_question("Delta", "yes")
        catalog = TwentyQuestionsDatasetLoader(self.base, self.learned).load()
        delta = catalog.row_by_name("DELTA")
        self.assertIsNotNone(delta)
        self.assertEqual(delta.answers[1], "yes")


class AnswerParsingTests(unittest.TestCase):
    def test_only_four_canonical_answers_and_aliases(self) -> None:
        self.assertEqual(
            {normalize_player_answer(value) for value in (
                "yes", "no", "sometimes", "unknown",
            )},
            {"yes", "no", "sometimes", "unknown"},
        )
        self.assertEqual(normalize_player_answer("maybe"), "sometimes")
        self.assertEqual(normalize_player_answer("Often"), "sometimes")
        self.assertEqual(normalize_player_answer("I don’t know"), "unknown")
        self.assertIsNone(normalize_player_answer("not yes"))

    def test_invalid_prompt_lists_exactly_the_four_player_choices(self) -> None:
        self.assertEqual(ANSWER_PROMPT, "Please answer yes, no, sometimes, or I don't know.")


if __name__ == "__main__":
    unittest.main()
