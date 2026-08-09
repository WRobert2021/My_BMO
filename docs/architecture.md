# Architecture

The application keeps `agent.py` as the stable startup command while implementation lives in the `bmo` package.

## Module boundaries

- `bmo.app` — Tkinter UI and top-level interaction workflow.
- `bmo.audio` — audio-device discovery, microphone recording, sound effects, and Piper playback.
- `bmo.speech` — OpenWakeWord detection, Whisper transcription, and action-JSON extraction.
- `bmo.tools` — stable compatibility router over the enabled feature registry.
- `bmo.features` — typed contracts, lazy loading, and registry-backed dispatch.
- `bmo.features.camera` — Raspberry Pi still capture and configured rotation.
- `bmo.features.loader` — standard-library module loading from `features` config.
- `bmo.features.get_time` — current-time action, alias, and direct phrases.
- `bmo.features.get_location` — configured-location action and failure handling.
- `bmo.features.get_weather` — weather action, place cleanup, and failures.
- `bmo.features.search_web` — web-search action, formatting, and archive details.
- `bmo.features.capture_image` — camera request metadata and UI capture signal.
- `bmo.features.set_timer` — natural durations and a single condition-driven
  priority-queue scheduler for all active timers.
- `bmo.memory` — conversation-history loading and atomic persistence.
- `bmo.archive` — append-only, per-interaction artifacts and event metadata.
- `bmo.config` — defaults, paths, Ollama options, and JSON loading.
- `bmo.prompts` — system-prompt construction.
- `bmo.state` — shared UI/application states.

## Runtime flow

1. `agent.py` creates Tkinter and `BotGUI`.
2. `BotGUI` loads enabled feature modules and constructs services using
   `config.json`. A failed enabled module is reported and skipped.
3. The wake-word service waits for wake word or push-to-talk.
4. A unique dated interaction archive is created.
5. The recorder captures a WAV directly into that archive.
6. Whisper transcribes the WAV and retains its raw stdout/stderr.
7. Ollama produces either normal text or an allowlisted tool request; requests and typed tool results are logged and processed through the same presentation path as direct actions.
8. Tool calls, full web results, and camera images are stored under the same interaction.
9. Piper streams speech through `sounddevice` while also writing archival WAVs.
10. Shutdown stops audio, saves recent memory atomically, unloads the text model, and closes Tkinter.

## Platform behavior

The same Python entry point is used on macOS and Raspberry Pi.

- Piper uses `./piper/piper` when the bundled Pi binary exists.
- Otherwise Piper runs through the active environment with `python -m piper`.
- Whisper paths can be overridden with `whisper_binary` and `whisper_model` in `config.json`.
- Raspberry Pi camera execution and rotation live in `bmo.features.camera`.
  `BotGUI.capture_image()` retains UI-state and interaction-archive coordination,
  while action aliases, matching, and prompt metadata live in
  `bmo.features.capture_image`.

## Feature configuration

`features` is an ordered list of objects with `module`, `enabled`, and
`settings` fields. Each enabled module provides `register(registry, settings)`.
Disabled entries are skipped before import. When `features` is omitted, all
six built-in actions are enabled. Per-module registration is transactional, so
an import error, hook error, or duplicate action cannot remove features that
loaded successfully.

Asynchronous features send typed runtime notifications through the callback
owned by `ToolRegistry`. The application callback forwards timer expiration to
the existing Tk UI and TTS queue. Registry shutdown closes feature resources;
for timers this cancels pending deadlines, wakes the scheduler condition, and
joins its one worker thread.

## Next extraction

The current `BotGUI` still combines presentation and conversation orchestration. The next safe step is to move widget/animation behavior into `bmo.ui` and move Ollama streaming/tool-response handling into `bmo.conversation`, after this extraction has been verified on both macOS and Raspberry Pi.

## Shutdown ownership

Audio streams are closed cooperatively by the thread that created them. The UI shutdown path sets a shared event, wakes any push-to-talk wait, joins the interaction and TTS threads, and then exits Tkinter. It deliberately does not call process-wide `sounddevice.stop()` while another thread owns an input stream; doing so can crash Core Audio on macOS.
