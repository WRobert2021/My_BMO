# Qt 6 / QML GUI migration

This document records the transition from the production Tk interface to
PySide6 and Qt Quick/QML and the remaining physical-kiosk acceptance work.

## Completed gates

1. **Target compatibility** — PySide6 Essentials 6.11.1 installs and imports on
   Raspberry Pi 5, Python 3.13.5, Debian 13/aarch64. Qt Quick Controls loads,
   Wayland uses the Broadcom V3D OpenGL renderer, and VNC plus physical touch
   input work.
2. **Conversation boundary** — model-call logging and typed tool-result
   presentation live outside either GUI adapter.
3. **Qt face shell** — QML owns the fullscreen face, frame timing, state/status,
   response HUD, camera-overlay surface, keyboard shortcuts, and touch gestures.
4. **Shared menu model** — the legacy Tk adapter and QML use the same ordered
   5x3 pagination, padded hit geometry, and swipe history.
5. **Typed menu catalog** — registries compose namespaced menu items through
   `MenuCatalog`; QML selections emit a validated
   `MenuSelectionRequest(owner, name)`.
6. **Runtime menu coordinator** — one UI-neutral owner provides live catalogs,
   validates stale selections, and dispatches mode/feature launches.
7. **Extension import isolation** — built-in menu extensions defer their
   concrete view choice until launch, and importing them does not import
   `tkinter`.
8. **Configured resource-free menu** — metadata hooks build the enabled,
   ordered menu without starting UI, workers, stores, clients, audio, or model
   services. Per-extension failures roll back independently.
9. **Extension runtime coordinator** — registry lifetime, menu dispatch, worker
   wakes, queued modes, and feature vision requests have a toolkit-neutral
   owner.
10. **Assistant worker and trigger loop** — quiet hours, queued menu work,
    suspended/continuous modes, wake/PTT, interruption, and shutdown use typed
    decisions outside the presentation event loop.
11. **Voice-turn executor** — PTT/adaptive capture, transcription, transcript
    archival, retry states, and conversation handoff use narrow injected ports.
12. **Production runtime and Qt port** — `AssistantRuntime` owns concrete
    services, conversation execution, speech, memory, attentions, worker
    queues, persistence, and shutdown without importing a GUI toolkit.
    `QtRuntimePresentation` marshals worker updates to the Qt event thread.
13. **QML global surfaces** — persistent attentions, acknowledgement,
    quiet-hours sleeping/PIN cover, camera overlay, error/status presentation,
    and typed-debug input are Qt-owned.
14. **QML extension views** — Timer, Calendar, Album, Learning, Weather, Pup
    Pairs, and Twenty Questions use hosted QML adapters. Default extension view
    factories discover the active host before lazily falling back to Tk.
15. **Production switch** — `agent.py`, `qt_agent.py`, `start_agent.sh`, and the
    desktop launcher use Qt. `typed_agent.py` is also Qt. `tk_agent.py` is the
    explicit temporary rollback path.

## Ownership after the switch

- `bmo.runtime.AssistantRuntime` owns assistant services and lifecycle.
- `bmo.qt.presentation.QtRuntimePresentation` is the queued presentation port.
- `bmo.qt.controller.QtFaceController` owns QML-visible state and user signals.
- `bmo.qt.view_host.QtViewHost` owns one active feature or mode view.
- `bmo.qt.views` adapts existing extension callbacks to serializable QML view
  models without coupling feature registration to Qt.
- `bmo.app.BotGUI` and `bmo.ui` are legacy fallback code, not the production
  composition root.

The wake-word input-overflow investigation is tracked separately from the GUI
conversion because PTT capture and transcription already use the same neutral
runtime and Qt presentation path.

## Remaining acceptance

Run the full suite plus physical-kiosk checks for cold start, repeated
menu/view cycles, PTT, touch and VNC, quiet hours, attentions, every enabled
feature/mode, interrupted speech, clean exit, restart, memory persistence, and
long-running stability. Record the Qt scene-graph backend, frame
responsiveness, RAM use, worker cleanup, and absence of orphan audio processes.

Keep `tk_agent.py` for one validation cycle. Remove the fallback and dead Tk
presentation modules only after the Raspberry Pi acceptance run is signed off;
removing the fallback is a separate dependency/code-removal task.

## Definition of complete

The code conversion is complete when Qt is the default production event loop,
built-in supported UI paths are QML/Qt-owned, the normal and typed Qt import
paths do not import Tkinter, and all extension isolation contracts pass.
Deployment acceptance is complete only after the final Raspberry Pi run shows
correct touch, audio, rendering, persistence, and cleanup.
