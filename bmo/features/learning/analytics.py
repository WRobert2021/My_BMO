"""Pure, persistence-independent Learning progress calculations."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import (
    AttemptRecord,
    LearningPlan,
    MasteryStatus,
    PlanReport,
    SkillMastery,
)


DEFAULT_RECENT_EVIDENCE = 20


def _question_evidence(
    attempts: Iterable[AttemptRecord],
) -> list[list[AttemptRecord]]:
    grouped: dict[tuple[str, str], list[AttemptRecord]] = {}
    for attempt in attempts:
        key = (attempt.session_id, attempt.question_id)
        grouped.setdefault(key, []).append(attempt)
    ordered = sorted(
        grouped.values(),
        key=lambda group: max(item.timestamp for item in group),
    )
    return [
        sorted(group, key=lambda item: item.attempt_number)
        for group in ordered
    ]


def _rates(
    attempts: Sequence[AttemptRecord],
) -> tuple[int, float, float, float, float]:
    evidence = _question_evidence(attempts)
    if not evidence:
        return 0, 0.0, 0.0, 0.0, 0.0
    first = sum(
        bool(group[0].correct and group[0].attempt_number == 1)
        for group in evidence
    ) / len(evidence)
    eventual = sum(
        any(item.correct for item in group)
        for group in evidence
    ) / len(evidence)
    grade = 0.60 * first + 0.40 * eventual
    recent = evidence[-min(5, len(evidence)) :]
    trend = sum(
        any(item.correct for item in group)
        for group in recent
    ) / len(recent)
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
    if (
        not isinstance(recent_evidence_limit, int)
        or recent_evidence_limit < minimum_evidence
    ):
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
        practiced_seconds=round(
            sum(item.elapsed_seconds for item in recent_attempts),
            2,
        ),
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
    started = sum(
        item.status is not MasteryStatus.NOT_STARTED
        for item in lesson_mastery
    )
    mastered = sum(
        item.status is MasteryStatus.MASTERED
        for item in lesson_mastery
    )
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
    elif any(
        item.status is MasteryStatus.NEEDS_PRACTICE
        for item in lesson_mastery
    ):
        status = MasteryStatus.NEEDS_PRACTICE
    else:
        status = MasteryStatus.IN_PROGRESS
    skill_ids = tuple(
        dict.fromkeys(
            skill
            for attempt in plan_attempts
            for skill in attempt.skills
        )
    )
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
        practiced_seconds=round(
            sum(attempt.elapsed_seconds for attempt in plan_attempts),
            2,
        ),
        skills=skill_mastery,
    )


summarize_progress = summarize_plan


__all__ = [
    "DEFAULT_RECENT_EVIDENCE",
    "summarize_mastery",
    "summarize_plan",
    "summarize_progress",
]
