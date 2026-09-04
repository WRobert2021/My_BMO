---
id: plugin.alarm_clock
type: plugin
plugin_type: feature
entrypoint: bmo.features.alarm_clock
status: stable
tests: [tests/test_alarm_clock.py, tests/test_qt_shell.py]
---

# Plugin: Alarm Clock

## Purpose

Provide persistent local wall-clock alarms through voice/model operations and
a touch clock/list/editor, including repeats, snooze, dismiss, and ringing
attentions.

## Ownership

| Area | Owner/path |
| --- | --- |
| tool, worker, view lifecycle | `bmo/features/alarm_clock.py` |
| private config | `bmo/features/alarm_config.py` |
| persistence/view records | `alarm_store.py`, `alarm_view.py` |
| production adapter/QML | `bmo/qt/views/alarm_clock.py`, `bmo/qt/qml/AlarmClockView.qml` |
| legacy UI | `bmo/ui/alarm_clock.py` |
| tracked schema | `config/example.alarm_clock.json` |
| background resource | one cooperative wall-clock worker |

The feature owns set/list/enable/disable/delete/snooze/dismiss routing and a
menu contribution. Resource-free metadata registration does not create a
store or worker. Runtime registration loads private configuration, opens the
store, starts one worker, and publishes immutable view snapshots. System local
time is authoritative. One-time alarms disable after firing; weekday repeats
remain enabled; snooze deadlines are persisted atomically.

## Persistence and failure

Private state defaults under `bmo/data/alarms`; configuration controls visibility,
state path, 12/24-hour display, and snooze minutes. Strict schema or malformed
state becomes visibly read-only rather than overwritten or blocking startup.
Ringing uses a plugin-owned persistent attention and optional animation state.

`close()` closes the open view, stops/joins the worker, closes persistence, and
removes owned attention state. Invalid config or local feature failures stay
isolated. Disabled registration starts no worker/store.

## Tests and interfaces

Primary: `tests/test_alarm_clock.py`; shared Qt/menu coverage:
`tests/test_qt_shell.py`. Consumes atomic JSON and runtime attentions; exposes
no cross-plugin API.

For continuation/status, read `progress.md`.
