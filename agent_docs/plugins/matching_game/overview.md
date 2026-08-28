---
id: plugin.matching_game
type: plugin
plugin_type: mode
entrypoint: bmo.modes.matching_game
status: stable
tests: [tests/test_matching_game.py, tests/test_modes.py]
---

# Plugin: Pup Pairs

## Purpose

Own the multi-turn/touch matching-card game, imperfect BMO opponent memory,
score history, voice start matching, and menu lifecycle.

## Ownership

| Area | Owner/path |
| --- | --- |
| registration/mode lifecycle | `bmo/modes/matching_game.py` |
| neutral game state/opponent | `bmo/matching_game_core.py` |
| start text normalization | `bmo/matching_game_text.py` |
| production adapter/QML surface | `bmo/qt/views/matching_game.py`, shared hosted QML |
| legacy presentation | `bmo/matching_game.py` |
| persistence/assets | score history and referenced card assets |

`register(registry, context, settings)` creates `MatchingGameMode` from the
constrained mode context; `register_menu_metadata` adds Pup Pairs without
creating UI. Voice launch and the synthetic menu start request reach the same
mode. While its embedded board owns interaction, input policy is suspended;
active-mode launches are idempotent and another mode cannot replace it.

The core validates pair counts and artwork-derived limits, owns card matching,
turns, scores, and BMO memory independently of UI. The Qt view exposes large
pair-count controls and retains minimum touch geometry. Announcements use the
mode/runtime speech boundary; stale completion callbacks cannot overwrite a
new round.

## Failure and lifecycle

Missing/corrupt assets or presentation failure ends/quarantines only this mode
and returns normal input ownership. `close()` destroys its view/resources and
is safe during registry shutdown. Disabled mode import contributes no matcher,
menu item, or UI.

## Tests and interfaces

Primary: `tests/test_matching_game.py`, `tests/test_modes.py`; shared mode/menu:
`tests/test_mode_loading.py`, `tests/test_qt_shell.py`. Consumes mode context and
hosted-view contracts. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
