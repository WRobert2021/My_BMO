from __future__ import annotations

from datetime import datetime, timezone
import itertools
import json
import random
import re
import unittest

from bmo.features.learning.curriculum import (
    CASE_MATCH_GROUPS,
    CONFUSED_LETTER_GROUPS,
    CURRICULUM,
    LETTER_REVIEW_BLOCKS,
    LETTERS,
    READABLE_FONTS,
    READABLE_GLYPH_COLORS,
    SIGHT_WORD_SETS,
    Catalog,
    prerequisite_warnings,
    validate_catalog,
)
from bmo.features.learning.engine import (
    LearningEngine,
    summarize_mastery,
    summarize_plan,
)
from bmo.features.learning.models import (
    AttemptRecord,
    ContentItem,
    InteractionKind,
    LearningDataError,
    LearningPlan,
    LearningSession,
    LessonDefinition,
    MasteryStatus,
)


NOW = "2026-08-12T12:00:00+00:00"


class CatalogTests(unittest.TestCase):
    def test_catalog_is_unique_acyclic_and_covers_all_domains(self) -> None:
        self.assertIs(validate_catalog(CURRICULUM), CURRICULUM)
        self.assertEqual(len(CURRICULUM.lesson_ids), len(set(CURRICULUM.lesson_ids)))
        self.assertGreaterEqual(len(CURRICULUM.for_domain("literacy")), 200)
        self.assertGreaterEqual(len(CURRICULUM.for_domain("math")), 20)
        self.assertGreaterEqual(len(CURRICULUM.for_domain("readiness")), 15)

    def test_every_letter_has_both_cases_and_both_required_interactions(self) -> None:
        ids = set(CURRICULUM.lesson_ids)
        for letter in LETTERS:
            slug = letter.lower()
            for case in ("upper", "lower"):
                self.assertIn(f"literacy.letter.{case}.{slug}.single", ids)
                self.assertIn(f"literacy.letter.{case}.{slug}.multi", ids)

    def test_exact_ordered_letter_review_blocks_are_retained_including_repeats(self) -> None:
        reviews = tuple(
            lesson
            for lesson in CURRICULUM.lessons
            if lesson.lesson_id.startswith("literacy.letter_review.")
        )
        self.assertEqual(
            tuple(lesson.setting("review_block") for lesson in reviews),
            LETTER_REVIEW_BLOCKS,
        )
        self.assertEqual(
            tuple(lesson.setting("source_order") for lesson in reviews),
            tuple(range(1, 11)),
        )
        self.assertEqual(sum(lesson.setting("review_block") == "A-D" for lesson in reviews), 2)

    def test_exact_case_sound_and_sight_groups_are_data_not_ui_branches(self) -> None:
        for direction in ("lower", "upper"):
            for index, source_group in enumerate(CASE_MATCH_GROUPS, 1):
                lesson = CURRICULUM.get(
                    f"literacy.case_match.{direction}.group{index}"
                )
                expected = (
                    source_group
                    if direction == "lower"
                    else tuple(letter.upper() for letter in source_group)
                )
                self.assertEqual(lesson.setting("target_pool"), expected)
        self.assertIn(("b", "d", "p", "q"), CONFUSED_LETTER_GROUPS.values())
        for number, words in SIGHT_WORD_SETS.items():
            self.assertEqual(
                CURRICULUM.get(f"literacy.sight.set{number}").setting("words"),
                words,
            )

    def test_all_brief_literacy_families_have_stable_lessons(self) -> None:
        required = {
            "literacy.identify.alphabet.lower",
            "literacy.identify.alphabet.upper",
            "literacy.identify.heard",
            "literacy.case_match.find_all_lower",
            "literacy.case_match.find_all_upper",
            "literacy.words.same",
            "literacy.words.spacing",
            "literacy.words.find_in_sentence",
            "literacy.rhyme.one",
            "literacy.rhyme.two",
            "literacy.rhyme.picture",
            "literacy.syllables.blend",
            "literacy.phoneme.onset_rime",
            "literacy.phoneme.blend",
            "literacy.phoneme.initial",
            "literacy.phoneme.order",
            "literacy.sound.beginning_pair",
            "literacy.sound.ending_one",
            "literacy.sound.ending_pair",
            "literacy.letter_sound.upper.review",
            "literacy.letter_sound.lower.word",
            "literacy.letter_sound.lower.review",
            "literacy.sight.same",
            "literacy.sight.review.1_3",
            "literacy.sight.review.4_6",
            "literacy.sight.review.7_10",
            "literacy.sight.review.1_10",
            "literacy.reading.book_parts",
            "literacy.reading.reality",
            "literacy.reading.feeling",
            "literacy.reading.next",
            "literacy.vocabulary.colors",
            "literacy.vocabulary.number_words.1_5",
            "literacy.vocabulary.number_words.6_10",
            "literacy.vocabulary.number_words.1_10",
            "literacy.vocabulary.nouns",
            "literacy.vocabulary.verbs",
            "literacy.vocabulary.adjectives",
            "literacy.vocabulary.location.inside_outside",
            "literacy.vocabulary.location.above_below",
            "literacy.vocabulary.location.next_to",
            "literacy.vocabulary.antonyms",
            "literacy.vocabulary.categories",
            "literacy.vocabulary.odd_one_out",
        }
        for vowel in "aeiou":
            required.add(f"literacy.vowel.short_{vowel}.identify")
            required.add(f"literacy.vowel.short_{vowel}.picture_match.upper")
            required.add(f"literacy.vowel.short_{vowel}.picture_match.lower")
        self.assertFalse(required.difference(CURRICULUM.lesson_ids))

    def test_full_bounded_math_and_readiness_suite_is_present(self) -> None:
        required = {
            "math.number.0_10",
            "math.number.11_20",
            "math.count.0_10",
            "math.count.11_20",
            "math.match.number_forms",
            "math.compare.more_fewer_same",
            "math.sequence.before_after",
            "math.sequence.missing",
            "math.operation.compose",
            "math.operation.add",
            "math.operation.subtract",
            "math.shapes.2d",
            "math.shapes.solid",
            "math.colors",
            "math.same_different",
            "math.attributes.one",
            "math.attributes.two",
            "math.pattern.ab",
            "math.pattern.aab",
            "math.pattern.abb",
            "math.pattern.abc",
            "math.ordinal",
            "math.spatial",
            "math.measure",
            "readiness.body_parts",
            "readiness.five_senses",
            "readiness.animals_habitats",
            "readiness.plant_growth",
            "readiness.day_night",
            "readiness.weather",
            "readiness.seasons",
            "readiness.living_nonliving",
            "readiness.healthy_routines",
            "readiness.safety_choices",
            "readiness.feeling_recognition",
            "readiness.calming",
            "readiness.social",
            "readiness.visual_sequence",
            "readiness.classification",
            "readiness.directions",
        }
        self.assertFalse(required.difference(CURRICULUM.lesson_ids))

    def test_validation_rejects_missing_prerequisite_duplicate_and_cycle(self) -> None:
        bank = {
            "test.bank": (
                ContentItem("one", "one"),
                ContentItem("two", "two"),
                ContentItem("three", "three"),
                ContentItem("four", "four"),
            )
        }

        def definition(lesson_id: str, prerequisites: tuple[str, ...]) -> LessonDefinition:
            return LessonDefinition(
                lesson_id=lesson_id,
                domain="test",
                title=lesson_id,
                skills=("test.skill",),
                prerequisites=prerequisites,
                prompt_templates=("Choose.",),
                interaction=InteractionKind.SINGLE_CHOICE,
                generator="letter_single",
                bank_refs=("test.bank",),
            )

        with self.assertRaisesRegex(LearningDataError, "missing prerequisite"):
            validate_catalog(Catalog((definition("test.one", ("test.missing",)),), bank))
        duplicate = definition("test.one", ())
        with self.assertRaisesRegex(LearningDataError, "duplicate lesson"):
            validate_catalog(Catalog((duplicate, duplicate), bank))
        with self.assertRaisesRegex(LearningDataError, "cycle"):
            validate_catalog(
                Catalog(
                    (
                        definition("test.one", ("test.two",)),
                        definition("test.two", ("test.one",)),
                    ),
                    bank,
                )
            )

    def test_prerequisite_warnings_respect_plan_order(self) -> None:
        advanced = "literacy.letter.upper.a.multi"
        foundation = "literacy.letter.upper.a.single"
        self.assertIn((advanced, foundation), prerequisite_warnings(CURRICULUM, (advanced,)))
        self.assertEqual(
            prerequisite_warnings(CURRICULUM, (foundation, advanced)),
            (),
        )


class QuestionGenerationTests(unittest.TestCase):
    def test_every_lesson_generates_valid_questions_across_many_seeds(self) -> None:
        for seed in range(40):
            engine = LearningEngine(
                CURRICULUM,
                rng=random.Random(seed),
                id_factory=lambda: "fixed",
            )
            for lesson in CURRICULUM.lessons:
                with self.subTest(seed=seed, lesson=lesson.lesson_id):
                    question = engine.generate_question(lesson.lesson_id)
                    self.assertEqual(question.lesson_id, lesson.lesson_id)
                    self.assertIn(f"domain.{lesson.domain}", question.skills)
                    self.assertTrue(set(lesson.skills).issubset(question.skills))
                    self.assertEqual(len(question.choices), lesson.choice_count)
                    choice_ids = tuple(choice.id for choice in question.choices)
                    self.assertEqual(len(choice_ids), len(set(choice_ids)))
                    self.assertTrue(question.correct_answers)
                    self.assertTrue(
                        lesson.minimum_correct
                        <= len(question.correct_answers)
                        <= lesson.maximum_correct
                    )
                    self.assertTrue(
                        all(answer.split("=", 1)[0] in choice_ids for answer in question.correct_answers)
                    )

    def test_letter_questions_preserve_pedagogical_case_fonts_and_contrast(self) -> None:
        for case, target in (("upper", "A"), ("lower", "a")):
            engine = LearningEngine(rng=random.Random(71), id_factory=lambda: "id")
            single = engine.generate_question(f"literacy.letter.{case}.a.single")
            self.assertEqual(len({choice.label for choice in single.choices}), 4)
            correct = single.choice(single.correct_answers[0])
            self.assertIsNotNone(correct)
            self.assertEqual(correct.label, target)
            self.assertEqual(single.meta("example_color"), "#000000")
            for choice in single.choices:
                self.assertIn(choice.meta("font"), READABLE_FONTS)
                self.assertIn(choice.meta("color"), READABLE_GLYPH_COLORS)
                self.assertEqual(choice.label.isupper(), case == "upper")

            multi = engine.generate_question(f"literacy.letter.{case}.a.multi")
            self.assertTrue(multi.requires_submit)
            self.assertEqual(len(multi.choices), 5)
            self.assertTrue(
                all(multi.choice(answer).label == target for answer in multi.correct_answers)
            )

    def test_review_and_spoken_recognition_prompts_do_not_show_target(self) -> None:
        engine = LearningEngine(rng=random.Random(4), id_factory=lambda: "id")
        review = engine.generate_question("literacy.letter_review.ad.1")
        self.assertTrue(review.hidden_prompt)
        self.assertEqual(review.prompt, "Tap Speak to hear the question.")
        self.assertIn(str(review.meta("target")), review.spoken_prompt)
        sight = engine.generate_question("literacy.sight.set1")
        self.assertTrue(sight.hidden_prompt)
        visible_words = re.findall(r"[A-Za-z]+", sight.prompt.casefold())
        self.assertNotIn(str(sight.meta("target")).casefold(), visible_words)
        self.assertIn(str(sight.meta("target")), sight.spoken_prompt)

    def test_same_seed_is_reproducible_and_global_random_is_untouched(self) -> None:
        before = random.getstate()
        first = LearningEngine(rng=random.Random(2026), id_factory=lambda: "same")
        second = LearningEngine(rng=random.Random(2026), id_factory=lambda: "same")
        ids = CURRICULUM.lesson_ids[:80]
        self.assertEqual(
            tuple(first.generate_question(lesson_id) for lesson_id in ids),
            tuple(second.generate_question(lesson_id) for lesson_id in ids),
        )
        self.assertEqual(random.getstate(), before)


class EngineTransitionTests(unittest.TestCase):
    def make_engine(self) -> LearningEngine:
        identifiers = (f"id{number}" for number in itertools.count())
        return LearningEngine(
            rng=random.Random(9),
            clock=lambda: datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
            id_factory=lambda: next(identifiers),
        )

    @staticmethod
    def wrong_answer(question) -> str:
        correct_ids = {answer.split("=", 1)[0] for answer in question.correct_answers}
        return next(choice.id for choice in question.choices if choice.id not in correct_ids)

    def test_evaluate_retries_then_reveals_without_shame(self) -> None:
        engine = self.make_engine()
        question = engine.generate_question("literacy.letter.upper.a.single")
        wrong = self.wrong_answer(question)
        first = engine.evaluate(question, wrong, attempt_number=1)
        self.assertFalse(first.correct)
        self.assertTrue(first.try_again)
        self.assertFalse(first.reveal_answer)
        self.assertIn("Try once more", first.feedback)
        second = engine.evaluate(question, wrong, attempt_number=2, scaffold_used=True)
        self.assertFalse(second.correct)
        self.assertFalse(second.try_again)
        self.assertTrue(second.reveal_answer)
        self.assertEqual(second.revealed_answers, question.correct_answers)
        correct = engine.evaluate(question, question.correct_answers[0])
        self.assertTrue(correct.correct)
        self.assertIn(question.explanation, correct.feedback)

    def test_session_retry_advance_complete_resume_and_replay(self) -> None:
        engine = self.make_engine()
        session = engine.start_session(
            "profile-one",
            "plan-one",
            lesson_ids=(
                "literacy.letter.upper.a.single",
                "math.number.0_10",
            ),
            question_count=2,
        )
        first_question = session.current_question
        self.assertIsNotNone(first_question)
        replayed = engine.record_replay(session)
        self.assertEqual(replayed.replay_count, 1)
        self.assertEqual(replayed.attempts, ())
        self.assertEqual(engine.replay(replayed), first_question.spoken_prompt)

        wrong = self.wrong_answer(first_question)
        retry = engine.submit(replayed, wrong, elapsed_seconds=2.5)
        self.assertTrue(retry.evaluation.try_again)
        self.assertEqual(retry.session.question_index, 0)
        self.assertTrue(retry.session.scaffolded)
        self.assertEqual(retry.attempt.attempt_number, 1)

        eventual = engine.submit(
            retry.session,
            first_question.correct_answers,
            elapsed_seconds=1.0,
        )
        self.assertTrue(eventual.evaluation.correct)
        self.assertEqual(eventual.session.question_index, 1)
        self.assertTrue(eventual.attempt.hint_used)
        self.assertTrue(eventual.attempt.scaffolded)
        second_question = eventual.next_question
        self.assertIsNotNone(second_question)
        done = engine.submit(eventual.session, second_question.correct_answers[0])
        self.assertTrue(done.complete)
        self.assertIsNone(done.next_question)

        encoded = json.loads(json.dumps(done.session.to_json()))
        resumed = LearningSession.from_json(encoded)
        self.assertEqual(resumed, done.session)

    def test_session_repetitions_group_fresh_questions_before_advancing(self) -> None:
        first = "literacy.letter.upper.a.single"
        second = "math.number.0_10"
        engine = self.make_engine()
        ordinary = engine.start_session(
            "profile-one",
            lesson_ids=(first, second),
            question_count=6,
        )
        repeated = engine.start_session(
            "profile-one",
            lesson_ids=(first, second),
            question_count=6,
            repetitions=2,
        )
        self.assertEqual(
            tuple(question.lesson_id for question in ordinary.questions),
            (first, second, first, second, first, second),
        )
        self.assertEqual(
            tuple(question.lesson_id for question in repeated.questions),
            (first, first, second, second, first, first),
        )
        self.assertEqual(
            len({question.question_id for question in repeated.questions}),
            len(repeated.questions),
        )
        self.assertIsNot(repeated.questions[0], repeated.questions[1])

    def test_plan_repetitions_are_inherited_and_explicit_value_can_override(self) -> None:
        first = "literacy.letter.upper.a.single"
        second = "math.number.0_10"
        plan = LearningPlan(
            "plan-one",
            "profile-one",
            "Repeated Practice",
            (first, second),
            repetitions=3,
            questions_per_session=6,
            created_at=NOW,
            updated_at=NOW,
        )
        engine = self.make_engine()
        inherited = engine.start_session("profile-one", plan=plan)
        overridden = engine.start_session(
            "profile-one",
            plan=plan,
            question_count=4,
            repetitions=2,
        )
        self.assertEqual(
            tuple(question.lesson_id for question in inherited.questions),
            (first, first, first, second, second, second),
        )
        self.assertEqual(
            tuple(question.lesson_id for question in overridden.questions),
            (first, first, second, second),
        )

    def test_invalid_session_repetition_bounds_are_rejected(self) -> None:
        engine = self.make_engine()
        for invalid in (0, 11, True, 1.5):
            with self.subTest(repetitions=invalid):
                with self.assertRaisesRegex(ValueError, "repetitions"):
                    engine.start_session(
                        "profile-one",
                        lesson_ids=("math.number.0_10",),
                        question_count=1,
                        repetitions=invalid,  # type: ignore[arg-type]
                    )


class ScoringTests(unittest.TestCase):
    def make_attempts(
        self,
        lesson_id: str,
        plan_id: str,
        *,
        skill: str,
    ) -> tuple[AttemptRecord, ...]:
        records: list[AttemptRecord] = []
        for question in range(5):
            if question >= 3:
                records.append(
                    AttemptRecord(
                        attempt_id=f"wrong-{question}",
                        session_id="session-one",
                        profile_id="profile-one",
                        plan_id=plan_id,
                        lesson_id=lesson_id,
                        skills=(skill,),
                        question_id=f"question-{question}",
                        correct_answers=("c0",),
                        response=("c1",),
                        correct=False,
                        attempt_number=1,
                        scaffolded=False,
                        hint_used=False,
                        revealed=False,
                        elapsed_seconds=2,
                        timestamp=NOW,
                    )
                )
            records.append(
                AttemptRecord(
                    attempt_id=f"correct-{question}",
                    session_id="session-one",
                    profile_id="profile-one",
                    plan_id=plan_id,
                    lesson_id=lesson_id,
                    skills=(skill,),
                    question_id=f"question-{question}",
                    correct_answers=("c0",),
                    response=("c0",),
                    correct=True,
                    attempt_number=2 if question >= 3 else 1,
                    scaffolded=question >= 3,
                    hint_used=question >= 3,
                    revealed=False,
                    elapsed_seconds=3,
                    timestamp=NOW,
                )
            )
        return tuple(records)

    def test_mastery_requires_multiple_recent_questions_and_uses_60_40_grade(self) -> None:
        attempts = self.make_attempts(
            "literacy.letter.upper.a.single",
            "plan-one",
            skill="letter.upper",
        )
        mastery = summarize_mastery(
            attempts,
            skill="letter.upper",
            mastery_threshold=0.8,
            minimum_evidence=5,
        )
        self.assertEqual(mastery.status, MasteryStatus.MASTERED)
        self.assertEqual(mastery.evidence_count, 5)
        self.assertEqual(mastery.first_try_accuracy, 0.6)
        self.assertEqual(mastery.eventual_accuracy, 1.0)
        self.assertEqual(mastery.percentage_grade, 76.0)
        one_question = summarize_mastery(
            attempts[:1],
            skill="letter.upper",
            mastery_threshold=0.8,
            minimum_evidence=5,
        )
        self.assertEqual(one_question.status, MasteryStatus.IN_PROGRESS)

    def test_plan_grade_and_mastered_completion_are_separate(self) -> None:
        first_lesson = "literacy.letter.upper.a.single"
        second_lesson = "literacy.letter.lower.a.single"
        plan = LearningPlan(
            "plan-one",
            "profile-one",
            "Letter Plan",
            (first_lesson, second_lesson),
            mastery_gate=True,
            created_at=NOW,
            updated_at=NOW,
        )
        attempts = self.make_attempts(first_lesson, plan.plan_id, skill="letter.upper")
        report = summarize_plan(
            plan,
            attempts,
            mastery_threshold=0.8,
            minimum_evidence=5,
        )
        self.assertEqual(report.started_lessons, 1)
        self.assertEqual(report.mastered_lessons, 1)
        self.assertEqual(report.completion_percent, 50.0)
        self.assertEqual(report.percentage_grade, 76.0)
        self.assertEqual(report.status, MasteryStatus.IN_PROGRESS)
        engine = self.make_engine()
        self.assertEqual(
            engine.eligible_lesson_ids(
                plan,
                attempts,
                mastery_threshold=0.8,
                minimum_evidence=5,
            ),
            plan.lesson_ids,
        )

    def make_engine(self) -> LearningEngine:
        return LearningEngine(rng=random.Random(1), id_factory=lambda: "id")


if __name__ == "__main__":
    unittest.main()
