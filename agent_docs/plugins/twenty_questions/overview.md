---
id: plugin.twenty_questions
type: plugin
plugin_type: mode
entrypoint: bmo.modes.twenty_questions
status: stable
tests: [tests/test_twenty_questions.py, tests/test_modes.py]
---

# Plugin: Twenty Questions

## Purpose

Own the indexed yes/no guessing game, voice and touch answers, local-model
fallback guesses, learned answer overlay, and recent-target history.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/mode adapter | `bmo/modes/twenty_questions.py` |
| dataset/index/game engine | `bmo/twenty_questions.py` |
| text/errors | `bmo/twenty_questions_text.py`, `twenty_questions_contracts.py` |
| production adapter | `bmo/qt/views/twenty_questions.py`, hosted QML surface |
| legacy touch UI | `bmo/twenty_questions_ui.py` |
| persistence | immutable base JSONL, learned JSONL, bounded history JSON under `bmo/data/20_questions` |

The mode lazily loads the base catalog at game start, builds an integer-bitset
partition index, and treats dataset Often/learned Unknown as wildcards.
Canonical player responses are yes/no/sometimes/unknown. Confirmed guesses and
reveals atomically update the learned overlay; completed targets update bounded
newest-first history. Paths must be distinct.

The mode owns input until complete. Its policy is continuous for voice play and
suspended while the embedded touch board is open. It uses model inference only
at bounded fallback/round-ending points. Resource-free menu metadata avoids
loading the dataset, model inference, wake-word, or UI.

## Configuration and failure

Settings cover menu visibility, answer timeout, debug, base/learned/history
paths, and prompt limits. A missing/corrupt base ends only this mode. Malformed
learned state disables learning for that session without changing the base.
`close()` releases view/input ownership. Disabled configuration imports and
starts nothing.

## Tests and interfaces

Primary: `tests/test_twenty_questions.py`, `tests/test_modes.py`; shared:
`tests/test_mode_loading.py`, `tests/test_qt_shell.py`. Consumes mode context,
atomic JSON/JSONL, and hosted-view contracts. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
