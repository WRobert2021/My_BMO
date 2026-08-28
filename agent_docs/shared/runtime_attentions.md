# Persistent Runtime Attentions

owner: `bmo.features.contracts.RuntimeAttention` and the feature registry

Background features publish a typed attention containing source, stable ID,
message, acknowledgement callback, and optional overlay/animation/badge fields.
The runtime stores attentions by `(source, attention_id)` and the root Qt face
owns generic badge and acknowledgement presentation. Plugins remove their own
items with `RuntimeAttentionDismissal`; feature views never receive or draw the
global attention surface.

Acknowledgement callbacks return success and may trigger bounded speech.
Quiet Hours suppresses presentation without transferring ownership. One
plugin's cleanup or dismissal must not clear another plugin's notice. Importing
the contract starts no resource; producing schedulers/workers remain
plugin-owned and must stop during registry cleanup.

Consumers: Timer expiration, Alarm Clock ringing, and current-day Calendar
events. Tests: `tests/test_set_timer.py`, `tests/test_alarm_clock.py`,
`tests/test_calendar.py`, `tests/test_tool_registry.py`, and
`tests/test_qt_shell.py`.
