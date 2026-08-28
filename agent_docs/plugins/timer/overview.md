---
id: plugin.timer
type: plugin
plugin_type: feature
entrypoint: bmo.features.set_timer
status: stable
tests: [tests/test_set_timer.py, tests/test_timer_ui.py]
---

# Plugin: Timer

## Purpose

Own voice/model countdown operations, a touch editor/list, multiple active
timers, and persistent runtime attentions when timers expire.

## Ownership

| Area | Owner/path |
| --- | --- |
| parsing, tool, scheduler, registration | `bmo/features/set_timer.py` |
| neutral view records | `bmo/features/timer_view.py` |
| production adapter/QML | `bmo/qt/views/timer.py`, `bmo/qt/qml/TimerView.qml` |
| legacy UI | `bmo/ui/timer.py` |
| configuration | feature settings `show_in_menu`, limits |
| persistence | none; timers are process-local |
| background resource | one condition-driven scheduler thread after use |

`register` constructs `SetTimerTool`; `register_menu_metadata` contributes the
Timer icon without starting a scheduler. Natural-duration parsing and direct
phrases normalize to set/list/cancel operations. The scheduler owns an active
index and priority queue, starts lazily, publishes immutable snapshots, and
removes cancelled timers from both structures so they cannot later expire.

Expiration publishes a typed `RuntimeAttention`; acknowledgement/dismissal is
owned by Timer and does not clear other plugins. The Qt view polls snapshots,
creates/cancels timers through feature callbacks, and keeps list scrolling
bounded.

## Lifecycle and failure

`close()` closes an open view, stops the scheduler thread, and dismisses owned
attentions. Invalid durations, configured limit exhaustion, and stale IDs are
expected typed outcomes. Import and metadata discovery start no thread. A
disabled Timer therefore has no scheduler, menu item, route, or attention.

## Tests and interfaces

Primary: `tests/test_set_timer.py`, `tests/test_timer_ui.py`. Shared:
`tests/test_qt_shell.py`, `tests/test_tool_registry.py`. Consumes the persistent
runtime-attention API; exposes its scheduler/view snapshots only to its owned
UI adapter, not as a cross-plugin API.

For continuation/status, read `progress.md`.
