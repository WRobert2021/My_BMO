# AGENT GUIDE: BMO Pre-K Learning

Learning is an offline, touch-only feature for the 800x480 BMO kiosk. It is
registered through the normal feature allowlist but contributes only the
`graphics/icons/learning.png` menu item: it has no voice phrase, model prompt,
tool alias, or executable action. Spoken lesson instructions and feedback use
the menu view's scoped announcement service, which means they are rendered by
the same configured Piper voice as BMO's other speech.

## Enable the feature

When `features` is omitted from `config/features.json`, Learning is one of the
built-in feature modules. When an explicit allowlist is present, copy the
Learning entry from `config/example.features.json` into that list:

```json
{
  "module": "bmo.features.learning",
  "enabled": true,
  "settings": {
    "config_path": "config/learning.json"
  }
}
```

Restart the agent after changing feature wiring. Learning can then be opened
only by swiping to the menu and tapping its icon. Setting `show_in_menu` to
`false` in the private Learning configuration prevents registration entirely;
it does not expose an alternate launch path.

## Private configuration

Copy `config/example.learning.json` to the ignored
`config/learning.json` and edit the local copy. The feature owns this file; its
contents are not merged into shared agent settings. A missing or malformed
file reports a local warning and uses safe in-memory defaults instead of
preventing BMO from starting.

The schema controls:

- the contained `data_directory` and optional read-only
  `graphics_directory`;
- menu visibility and the four-digit teacher-area PIN;
- default session length and the accuracy/evidence thresholds used for
  mastery;
- bounded attempt/mastery history retention;
- readable font fallbacks available on the Raspberry Pi;
- lesson replay speech and the optional deterministic debug seed.

The teacher PIN is a convenience boundary for a local child-facing kiosk, not
cryptographic authentication. Do not reuse an important PIN. Neither it nor
learner display names are written to logs.

## Learner and teacher areas

The learner home selects a local profile and one of its enabled plans. A
session presents one uncluttered activity at a time with large touch targets,
a consistent replay control, specific feedback, a bounded retry followed by a
gentle demonstration, and visible progress. Replaying speech never changes a
score. If runtime speech is unavailable, replay controls are disabled while
visual activities continue to work.

The PIN-gated teacher area manages profiles and ordered learning plans. Lesson
prerequisites provide warnings and a recommended foundation-first order; a
teacher can deliberately override that order. Each plan controls its ordered
lessons, 1-10 varied presentations per lesson visit, 3-20 questions per
session, enabled state, and optional mastery gate. Reports keep completion,
first-try accuracy, eventual accuracy, recent trend, practice time, and
per-skill mastery separate so an unfinished plan cannot appear fully
completed. Destructive profile, plan, and progress actions require explicit
confirmation.

The **mastery gate** controls when a plan introduces later lessons. When it is
on, Learning offers the foundation lessons first and unlocks dependent lessons
after the configured amount of accurate recent practice. When it is off, every
lesson in the teacher's ordered plan can be used immediately. Turning the gate
off does not erase scores or change the lesson order.

## Scoring and mastery

Every recorded attempt includes stable profile, plan, lesson, question, and
session identifiers; normalized response and correct targets; attempt number;
hint/scaffolding state; correctness; elapsed response time; UTC timestamp; and
question-generation version metadata. Generated questions carry both a
`domain.<name>` evidence tag and narrower skill tags, which lets reports page
through domain-level and per-skill mastery without a second source of truth.

The report formulas are deliberately explainable:

- **First-try accuracy** is first-attempt correct questions divided by distinct
  attempted questions.
- **Eventual accuracy** is questions eventually answered correctly divided by
  distinct attempted questions.
- **Percentage grade** is 60 percent first-try accuracy plus 40 percent
  eventual accuracy. This rewards independent answers while still recognizing
  learning after feedback.
- **Recent trend** is eventual correctness across the five most recently
  attempted distinct questions (or all distinct questions when fewer than
  five exist).
- **Plan completion** is mastered planned lessons divided by the plan's total
  lesson count; completion is displayed separately from accuracy and grade.
- **Mastery** requires the configured recent-evidence count, eventual accuracy
  at or above the configured threshold, and first-try accuracy at or above the
  greater of 50 percent or 20 percentage points below that threshold. Only the
  configured bounded recent window is considered, so one lucky answer is never
  enough.

The child view uses friendly progress and practice states. Percentages and
detailed grades stay in the teacher area.

## Data ownership, recovery, and retention

Learning creates nothing at import time. On its first successful save it
creates three schema-version-1 JSON documents beneath `data/learning/`:
`profiles.json`, `plans.json`, and `progress.json`. The progress document holds
bounded attempt history and resumable sessions together so recording an answer
and its updated session is one atomic transaction. Profiles, plans, sessions,
and attempt history never enter conversation memory or interaction archives
and are never sent over the network. Writes use a same-directory temporary
file, flush, and atomic replacement so an interruption cannot leave a
half-written record.

Paths are resolved beneath the configured Learning root and symbolic-link
escapes are rejected. History is bounded by configuration. If a store file is
malformed, Learning preserves the file, reports a non-sensitive error, and
enters a safe read-only state rather than silently replacing learner data.
An unsupported future schema is handled the same way and is never silently
downgraded or overwritten. Derived grades and mastery can be rebuilt from the
attempt records.
Back up or restore the entire `data/learning/` folder while the kiosk is
stopped. Use the confirmed teacher controls for narrow resets instead of
manually editing JSON.

## Adding a lesson

Lessons are data-driven and live in the Learning curriculum module. A new
definition needs a globally stable ID, domain, title, skill tags,
prerequisites, interaction kind, prompt/spoken prompt, difficulty metadata, and
a content bank that can produce unambiguous answers and distractors. Prefer an
existing generic interaction kind such as single choice, multi-select,
alphabet grid, ordering, sorting, or picture choice instead of branching in
the Tk view for one lesson.

After adding it:

1. Add prerequisite links and content using locally authored material.
2. Run catalog validation to catch duplicate IDs, missing/cyclic
   prerequisites, invalid answer counts, and empty banks.
3. Add deterministic generation tests over many seeds, including answer and
   contrast checks.
4. Add engine tests for feedback, retry/reveal, scoring, and persistence.
5. Run `.venv/bin/python -m pytest -q`.

## Artwork and platform behavior

The current repository policy makes `graphics/` read-only. Learning therefore
references the existing menu icon and draws its original lesson visuals using
Tk Canvas primitives. Optional future asset lookup is strictly contained under
`graphics/learning/` and always has a programmatic fallback. If the policy is
later changed, add only original or clearly licensed assets and record their
licenses.

Learning uses the Python standard library and the project's existing
Tkinter/Pillow stack. It has no network, browser, model, microphone, or new
package requirement and is designed for 64-bit Raspberry Pi OS on a Raspberry
Pi 5 with Python 3.13.5.
