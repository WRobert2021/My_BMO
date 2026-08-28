# Scoped Feature Announcements

owner: `bmo.features.contracts.FeatureAnnouncer` and
`FeatureMenuContext.announce`

Purpose: let an open feature view speak through the runtime's configured voice
without receiving Piper, audio, or the application coordinator.

Input is non-empty text plus an optional completion callback. `announce()`
returns `False` when the runtime did not provide speech or Quiet Hours blocks
it; visual plugin behavior must remain usable. Within one view scope, newer
speech replaces queued speech from that scope only. `cancel_announcements()` or
view close cancels that scope without clearing unrelated speech.

The runtime sets speaking/idle presentation state and marshals completion to
the presentation thread. Importing or registering the interface starts no
resource; concrete speech runs only through the already-owned runtime queue.

Known consumers include Calendar, Weather, Learning, and menu-launched mode/UI
adapters that need bounded announcements. Provider-unavailable behavior is
covered in feature/UI tests; contract behavior is covered by
`tests/test_tool_registry.py` and runtime tests.
