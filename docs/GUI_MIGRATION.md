# Qt 6 / QML GUI migration

This document defines the incremental path from the production Tk interface to
PySide6 and Qt Quick/QML. The Raspberry Pi kiosk remains usable at every gate;
`agent.py` stays on the last validated production path until the Qt runtime owns
the same lifecycle safely.

## Completed gates

1. **Target compatibility** — PySide6 Essentials 6.11.1 installs and imports on
   Raspberry Pi 5, Python 3.13.5, Debian 13/aarch64. Qt Quick Controls loads,
   Wayland uses the Broadcom V3D OpenGL renderer, and VNC plus physical touch
   input work.
2. **Conversation boundary** — model-call logging and typed tool-result
   presentation live outside the Tk coordinator.
3. **Qt face shell** — QML owns the fullscreen face, frame timing, state/status,
   response HUD, camera-overlay surface, keyboard shortcuts, and touch gestures.
4. **Shared menu model** — Tk and QML use the same ordered 5x3 pagination,
   padded hit geometry, and swipe history.
5. **Typed menu catalog boundary** — production registries compose namespaced
   menu items through `MenuCatalog`; QML selections emit a validated
   `MenuSelectionRequest(owner, name)` without executing a Tk view.
6. **Runtime menu coordinator** — production Tk and the Qt shell both use one
   UI-neutral live-catalog and typed-dispatch owner. It rejects selections that
   are no longer visible before calling the mode or feature launch boundary.

## Remaining gates

### 1. Extract the application runtime from `BotGUI`

Move audio, wake-word input, transcription, model/tool/mode routing, speech,
memory, archives, attentions, worker queues, and shutdown into a UI-independent
runtime owner. Define a narrow presentation port for dispatch, state/status,
response streaming, overlays, menu catalogs, selection requests, PTT,
interrupt, and exit. Keep the existing Tk implementation as an adapter while
the Qt adapter is developed. Menu snapshot and selection ownership have already
moved into `RuntimeMenuCoordinator`.

Completion evidence:

- runtime tests construct no Tk root;
- importing the Qt runtime path does not import Tkinter;
- Tk production behavior and failure isolation remain unchanged.

### 2. Connect the full runtime to Qt

Create the production-capable Qt launcher and connect `QtFaceController` to the
runtime presentation port. Replace diagnostic menu metadata with the enabled
feature/mode catalog and route typed selection requests to the runtime worker.
Voice, PTT, streaming responses, TTS interruption, memory, archives, and clean
shutdown must match Tk.

Before constructing the live registries in the Qt process, move remaining
top-level Tk view imports behind their feature/mode launch boundaries. Metadata
and runtime service construction must not import Tkinter merely because a menu
item is enabled.

### 3. Convert global overlays

Implement QML equivalents for persistent attention badges, acknowledgement,
quiet-hours sleeping cover and parent PIN keypad, typed-debug input, and any
remaining fullscreen camera/error overlays. These are global runtime surfaces,
not feature-owned views.

### 4. Convert feature views independently

Replace Tk feature views one module at a time while preserving each feature's
registration, settings, failure isolation, cleanup, and provider-unavailable
tests:

- Timer
- Calendar
- Album
- Learning
- Weather kiosk lifecycle/bridge integration

Each converted feature must still load when unrelated features are disabled or
fail, and optional actions must become visibly disabled when their provider is
unavailable.

### 5. Convert interaction-mode views independently

Replace the Pup Pairs and Twenty Questions Tk canvases with QML views while
retaining their mode lifecycle, suspended/continuous input policies, speech,
history, learning overlay, replay, and cleanup behavior.

### 6. Switch production startup

After parity, make `agent.py`, `start_agent.sh`, and the desktop launcher start
Qt by default. Retain an explicit Tk fallback for one validation cycle, then
remove it only after all Tk-owned feature/mode views are gone and no supported
configuration imports Tkinter.

### 7. Final Pi acceptance

Run the full suite plus physical-kiosk checks for cold start, repeated menu/view
cycles, voice and PTT, touch and VNC, quiet hours, attentions, every enabled
feature/mode, interrupted speech, clean exit, restart, memory persistence, and
long-running stability. Record Qt scene-graph backend, frame responsiveness,
RAM use, worker cleanup, and absence of orphan Chromium/audio processes.

## Definition of complete

The conversion is complete when Qt is the default production event loop, every
supported UI is QML/Qt-owned, the normal Qt import/runtime path does not import
Tkinter, all extension isolation contracts still pass, and the Raspberry Pi
acceptance run shows correct touch, audio, rendering, persistence, and cleanup.
