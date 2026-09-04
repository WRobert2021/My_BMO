---
id: plugin.learning
type: plugin
plugin_type: feature
entrypoint: bmo.features.learning
status: stable
tests: [tests/test_learning_curriculum.py, tests/test_learning_feature.py, tests/test_learning_store.py, tests/test_learning_qt.py]
---

# Plugin: Learning

## Purpose

Offline, touch-only Pre-K learning for the 800x480 kiosk. It owns data-driven
lessons, learner sessions, a PIN-gated teacher area, scoring/mastery, plans,
reports, and private local progress. It has no tool/voice route; spoken prompts
use scoped announcements.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/lifecycle | `bmo/features/learning/__init__.py` |
| configuration | `learning/config.py`, `config/example.learning.json` |
| models/curriculum/engine | `models.py`, `curriculum.py`, `engine.py`, `view_model.py` |
| analytics | `analytics.py` |
| persistence | `codec.py`, `store.py`, `errors.py` |
| production adapter/QML | `bmo/qt/views/learning.py`, `bmo/qt/qml/LearningView.qml` |
| legacy UI | `bmo/ui/learning.py` |

The menu metadata hook checks visibility without constructing a store or UI.
Opening loads private config/store and creates a toolkit-neutral interaction
controller plus hosted view. Activities are generic interaction kinds; lesson
IDs must not create UI branches. Seeded generation is deterministic and catalog
validation rejects duplicate IDs, missing/cyclic prerequisites, invalid answer
counts, and unusable banks.

## Scoring, persistence, and failure

Attempts preserve stable IDs, responses, retry/scaffold state, correctness,
elapsed time, timestamp, and generation metadata. Grade is 60% first-try plus
40% eventual accuracy; mastery uses bounded recent evidence and configured
thresholds. Completion is separate from accuracy.

Profiles, plans, attempts, and resumable sessions use strict version-one JSON
and atomic replacement under the contained `bmo/data/learning` root. Malformed/future data is
preserved and the feature enters safe read-only mode. Missing/malformed config
uses in-memory defaults. Learner data never enters conversation memory,
archives, logs, or network. If scoped speech is unavailable, replay is disabled
while visual learning remains usable. Close cancels speech and view state.

## Tests and interfaces

Primary: all `tests/test_learning_*.py`. Consumes scoped announcements and
shared atomic persistence. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
