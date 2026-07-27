# Architecture

The application keeps `agent.py` as the stable startup command while implementation lives in the `bmo` package.

## Module boundaries

- `bmo.app` — Tkinter UI and top-level interaction workflow.
- `bmo.audio` — audio-device discovery, microphone recording, sound effects, and Piper playback.
- `bmo.speech` — OpenWakeWord detection, Whisper transcription, and action-JSON extraction.
- `bmo.tools` — allowlisted tool routing for time, web search, and camera requests.
- `bmo.memory` — conversation-history loading and atomic persistence.
- `bmo.config` — defaults, paths, Ollama options, and JSON loading.
- `bmo.prompts` — system-prompt construction.
- `bmo.state` — shared UI/application states.

## Runtime flow

1. `agent.py` creates Tkinter and `BotGUI`.
2. `BotGUI` constructs the services using `config.json`.
3. The wake-word service waits for wake word or push-to-talk.
4. The recorder captures a WAV file.
5. Whisper transcribes the WAV file.
6. Ollama produces either normal text or an allowlisted tool request.
7. Piper streams speech through `sounddevice`.
8. Shutdown stops audio, saves recent memory atomically, unloads the text model, and closes Tkinter.

## Platform behavior

The same Python entry point is used on macOS and Raspberry Pi.

- Piper uses `./piper/piper` when the bundled Pi binary exists.
- Otherwise Piper runs through the active environment with `python -m piper`.
- Whisper paths can be overridden with `whisper_binary` and `whisper_model` in `config.json`.
- Raspberry Pi camera capture remains isolated in `BotGUI.capture_image()` until the camera service grows enough to justify a dedicated module.

## Next extraction

The current `BotGUI` still combines presentation and conversation orchestration. The next safe step is to move widget/animation behavior into `bmo.ui` and move Ollama streaming/tool-response handling into `bmo.conversation`, after this extraction has been verified on both macOS and Raspberry Pi.

## Shutdown ownership

Audio streams are closed cooperatively by the thread that created them. The UI shutdown path sets a shared event, wakes any push-to-talk wait, joins the interaction and TTS threads, and then exits Tkinter. It deliberately does not call process-wide `sounddevice.stop()` while another thread owns an input stream; doing so can crash Core Audio on macOS.
