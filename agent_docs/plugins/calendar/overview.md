---
id: plugin.calendar
type: plugin
plugin_type: feature
entrypoint: bmo.features.calendar
status: stable
tests: [tests/test_calendar.py, tests/test_qt_shell.py]
---

# Plugin: Calendar

## Purpose

Own read-only spoken calendar queries, editable touch day/month/year views,
recurrence, US holidays, and current-day persistent attentions.

## Ownership

| Area | Owner/path |
| --- | --- |
| tool, registration, attention worker | `bmo/features/calendar.py` |
| private configuration | `bmo/features/calendar_config.py` |
| events/recurrence/persistence | `bmo/features/calendar_store.py` |
| neutral UI records | `bmo/features/calendar_view.py` |
| production adapter/QML | `bmo/qt/views/calendar.py`, `bmo/qt/qml/CalendarView.qml` |
| legacy UI | `bmo/ui/calendar.py` |
| background resource | local-date refresh worker |

Voice routing summarizes dates/ranges but exposes no mutation. The touch editor
owns names, times, categories/colors, notes, weekly/monthly/yearly recurrence,
end rules, and occurrence-versus-series changes. Built-in holidays are
read-only. `register_metadata` and `register_menu_metadata` preserve routing or
visibility without opening stores or starting the worker.

## Configuration, persistence, and lifecycle

`config/example.calendar.json` documents the private data/overlay roots,
visibility, holiday choice, note narration, and categories. Versioned event and
acknowledgement JSON is atomically replaced. Recurrence is lazily expanded with
bounded arithmetic. Malformed/future data becomes read-only rather than being
overwritten.

At registration and local-date changes, one feature worker publishes an
attention per unacknowledged current-day occurrence. `close()` closes the view,
stops the worker, and releases feature state. Missing optional overlay art
falls back without affecting core behavior.

## Tests and interfaces

Primary: `tests/test_calendar.py`; shared Qt/menu:
`tests/test_qt_shell.py`. Consumes scoped announcements, runtime attentions,
and shared atomic JSON. Exposes no cross-plugin API.

For continuation/status, read `progress.md`.
