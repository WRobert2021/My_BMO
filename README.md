# Be More Agent 🤖
**A Customizable, Offline-First AI Agent for Raspberry Pi**

[![Watch the Demo](https://img.youtube.com/vi/l5ggH-YhuAw/maxresdefault.jpg)](https://youtu.be/l5ggH-YhuAw)

![Python](https://img.shields.io/badge/Python-3.13.5-blue) ![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-red) ![License](https://img.shields.io/badge/License-MIT-green)

This project turns a Raspberry Pi into a fully functional, conversational AI agent. Unlike cloud-based assistants, this agent runs **100% locally** on your device. It listens for a wake word, processes speech, "thinks" using a local Large Language Model (LLM), and speaks back with a low-latency neural voice—all while displaying reactive face animations.

**It is designed as a blank canvas:** You can easily swap the face images and sound effects to create your own character!

## ✨ Features

* **100% Local Intelligence**: Powered by **Ollama** (LLM) and **Whisper.cpp** (Speech-to-Text). No API fees, no cloud data usage.
* **Open Source Wake Word**: Wakes up to your custom model using **OpenWakeWord** (Offline & Free). No access keys required.
* **Hardware-Aware Audio**: Automatically detects your microphone's sample rate and resamples audio on the fly to prevent ALSA errors.
* **Smart Web Search**: Uses DuckDuckGo to find real-time news and information when the LLM doesn't know the answer.
* **Reactive Faces**: The GUI updates the character's face based on its state (Listening, Thinking, Speaking, Idle).
* **Fast Text-to-Speech**: Uses **Piper TTS** for low-latency, high-quality voice generation on the Pi.
* **Vision Capable**: Can "see" and describe the world using a connected camera and the **Moondream** vision model.

## 🛠️ Hardware Requirements

* **Raspberry Pi 5** (Recommended) or Pi 4 (4GB RAM minimum)
* USB Microphone & Speaker
* LCD Screen (DSI or HDMI)
* Raspberry Pi Camera Module

---

## 📂 Project Structure

```text
be-more-agent/
├── agent.py                   # The main brain script
├── setup.sh                   # Auto-installer script
├── wakeword.onnx              # OpenWakeWord model (The "Ear")
├── config/                    # Split user and extension configuration
│   ├── example.settings.json  # Tracked user-settings example
│   ├── example.features.json  # Tracked feature/mode example
│   ├── example.weather.json   # Tracked weather-view example
│   ├── example.calendar.json  # Tracked calendar example
│   ├── example.quiet_hours.json # Tracked global kiosk-lock example
│   ├── example.learning.json  # Tracked Pre-K learning example
│   ├── example.compact_face.json # Tracked shared compact-face example
│   ├── settings.json          # Local user settings (ignored by Git)
│   ├── features.json          # Local feature/mode wiring (ignored by Git)
│   ├── weather.json           # Local locations/weather UI settings (ignored)
│   ├── calendar.json          # Local calendar behavior settings (ignored)
│   ├── quiet_hours.json       # Local global quiet-hours settings (ignored)
│   ├── learning.json          # Local learning behavior/settings (ignored)
│   └── compact_face.json      # Local shared face layout/animation settings
├── data/calendar/             # Local events and acknowledgments (ignored)
├── data/learning/             # Local learners, plans, and progress (ignored)
├── memory.json                # Conversation history
├── interaction_logs/          # Private, durable per-turn archives
├── requirements.txt           # Python dependencies
├── whisper.cpp/               # Speech-to-Text engine
├── piper/                     # Piper TTS engine & voice models
├── sounds/                    # Sound effects folder
│   ├── greeting_sounds/       # Startup .wav files
│   ├── thinking_sounds/       # Looping .wav files
│   ├── ack_sounds/            # "I heard you" .wav files
│   └── error_sounds/          # Error/Confusion .wav files
└── faces/                     # Face images folder
    ├── idle/                  # .png sequence for idle state
    ├── listening/             # .png sequence for listening
    ├── thinking/              # .png sequence for thinking
    ├── speaking/              # .png sequence for speaking
    ├── error/                 # .png sequence for errors
    └── warmup/                # .png sequence for startup
```

---

## 🚀 Installation

### 1. Prerequisites
Ensure your Raspberry Pi OS is up to date.
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install git -y
```

### 2. Install Ollama
This agent relies on [Ollama](https://ollama.com) to run the brain.
```bash
curl -fsSL https://ollama.com/install.sh | sh
```
*Pull the required models:*
```bash
ollama pull gemma3:1b
ollama pull moondream
```

### 3. Clone & Setup
```bash
git clone https://github.com/brenpoly/be-more-agent.git
cd be-more-agent
chmod +x setup.sh
./setup.sh
```
*The setup script supports 64-bit Raspberry Pi OS. It installs the required
system libraries and Chromium, creates local folders, builds Whisper.cpp,
downloads the
`base.en` speech model and Piper voices, creates the Python environment, pulls
the Ollama models, installs the default wake-word model, and installs the
PySide6 Essentials Qt Quick/QML runtime used by the in-progress interface
migration. It is safe to run again and reuses valid existing downloads.*

### 4. Configure the Wake Word
The setup script downloads a default wake word ("Hey Jarvis"). To use your own:
1. Train a model at [OpenWakeWord](https://github.com/dscripka/openWakeWord).
2. Place the `.onnx` file in the root folder.
3. Rename it to `wakeword.onnx`.

### 5. Run the Agent
```bash
source .venv/bin/activate
python agent.py
```

### Qt/QML Migration Preview

The production launcher remains Tk-based while the interface is migrated in
tested slices. To run the current fullscreen Qt shell with BMO's real face
frames, animation timing, touch gestures, image-overlay surface, and diagnostic
HUD:

```bash
QT_QPA_PLATFORM=wayland python qt_agent.py
```

Tap the face to show or hide the HUD. Swipe left to open the QML icon menu, tap
an icon to confirm its selection at the bottom of the screen, and swipe right
from the first page or tap the compact face to return. Use **Exit Preview** in
the HUD to close the shell. Menu selections are diagnostic only; the preview
prints their typed mode/feature request but does not start the microphone,
models, tools, or modes yet. See the [GUI migration roadmap](docs/GUI_MIGRATION.md)
for completed gates and the remaining production conversion work.

### Development Tests

Pytest is a development dependency rather than a kiosk runtime dependency:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

---

## 📂 Configuration (`config/`)

Configuration is split by audience:

- `config/settings.json` contains user-relevant runtime choices such as models,
  audio, camera, prompt, the weather-config path, and interaction logging.
- `config/features.json` contains extension wiring: the ordered `features` and
  `modes` lists and their module-specific settings.
- `config/weather.json` is owned only by the weather feature. It contains the
  ordered private locations shown in the weather carousel.
- `config/calendar.json` is owned only by the calendar feature. It selects its
  data/overlay directories, holiday behavior, categories, and whether notes are
  included in spoken summaries.
- `config/quiet_hours.json` is a global kiosk policy. It can cover the entire
  UI with sleeping BMO on a local schedule until the period ends or a parent
  enters its four-digit PIN.
- `config/learning.json` is owned only by the menu-launched Pre-K learning
  feature. It controls its contained data/art roots, teacher PIN, session and
  mastery limits, readable fonts, and scoped speech/replay behavior.
- `config/compact_face.json` is owned by the neutral UI layer. It maps runtime
  states to contained PNG directories under `faces/` and controls the one
  shared refresh/layout specification used by Menu, features, modes, and
  Weather. Its outer viewport is always 108×65; invalid files safely use
  defaults.

The application does **not** create these local files. If a file is absent or
invalid, BMO reports a parsing error when applicable and uses defaults for that
file without writing anything. To keep local configuration, copy the tracked
examples and edit the copies:

```bash
cp config/example.settings.json config/settings.json
cp config/example.features.json config/features.json
cp config/example.weather.json config/weather.json
cp config/example.calendar.json config/calendar.json
cp config/example.quiet_hours.json config/quiet_hours.json
cp config/example.learning.json config/learning.json
cp config/example.compact_face.json config/compact_face.json
```

When upgrading from the former root `config.json`, move its `features` and
`modes` entries into `config/features.json` and put every other entry in
`config/settings.json`. The legacy file remains ignored by Git but is no longer
read by the application.

For example, `config/settings.json` can contain:

```json
{
    "text_model": "gemma3:1b",
    "vision_model": "moondream",
    "voice_model": "piper/en_GB-semaine-medium.onnx",
    "chat_memory": true,
    "camera_rotation": 0,
    "weather_config_path": "config/weather.json",
    "quiet_hours_config_path": "config/quiet_hours.json",
    "interaction_logging": true,
    "interaction_log_directory": "interaction_logs",
    "system_prompt_extras": "You are a helpful robot assistant. Keep responses short and cute."
}
```

### Features and modes

A **feature** is a short-lived, model-routable action such as checking the time
or setting a timer. Feature modules are selected by the ordered `features` list
shown in `config/example.features.json`:

- Omitting `features` enables all built-in feature modules. Once the list is
  present, it is an allowlist: only entries with `"enabled": true` are loaded,
  and an empty list disables every feature.
- `enabled` defaults to `true`, and `settings` defaults to `{}`. A disabled
  entry is skipped before its module name or settings are validated, so it is
  never imported and cannot start workers or register prompt/routing metadata.
- Invalid entries, import failures, missing `register` hooks, and
  registration conflicts are reported per enabled entry. Other valid entries
  still load, and a failed registration leaves none of that module's partial
  tools behind.
- The system and routing prompts advertise only tools that registered
  successfully. Disabling `set_timer`, for example, removes timer routing and
  avoids constructing its scheduler.
- Enabled features may contribute a touch-menu icon and a menu-only view without
  changing their voice actions. The timer feature does this by default; its
  `show_in_menu` setting hides or shows the timer icon independently from voice
  routing.
- The calendar feature contributes `graphics/icons/calendar.png` and opens its
  full-screen view only from that touch-menu icon. It starts on today and
  provides day, month, and birthstone-colored year views. Day rows swipe
  vertically when more than four events exist; month dots use each event's
  chosen color and stay within their day cell. The editor supports categories,
  unrestricted colors, all-day or timed events, notes, and weekly/monthly/yearly
  recurrence with occurrence-or-series edit/delete choices. Requested common
  US holidays can be included as read-only events.
- Spoken questions such as “what's on my calendar tomorrow?” and “what is my
  schedule next week?” receive deterministic summaries. Voice routing is
  intentionally read-only: adding, editing, and deleting events requires the
  touch calendar. Notes are omitted from speech unless `speak_notes` is enabled
  in `config/calendar.json`.
- Unacknowledged events occurring today publish a badge at startup and each
  local midnight. The badge is visible only on BMO's full-screen idle face,
  never on the upper-right PIP face. Tapping it acknowledges that occurrence
  persistently and BMO speaks the event. Optional PNGs under `faces/calendar`
  decorate the normal idle face; missing art cannot prevent startup.
- The weather feature contributes `graphics/icons/weather.png` by reference
  and keeps the existing spoken “what is the weather” action. Its full-screen
  child-friendly view renders weather-owned HTML/CSS/SVG through a dedicated
  Chromium kiosk process. It animates sun, moon phases, cloud, fog, rain,
  sleet, snow, thunder, hail, wind, seasonal scenery, and day/night layers.
  Chromium uses a temporary profile and a tokenized loopback-only bridge;
  it bypasses desktop credential stores because the kiosk never accepts or
  retains credentials. Closing Weather stops both resources and reveals the
  unchanged Tk menu. A renderer heartbeat automatically returns to the menu if
  Chromium ever opens without a working weather page.
  Temperature,
  feels-like, high/low, precipitation chance, condition, alert, and hourly
  cards are tappable BMO announcements. Swiping left or right wraps through
  the ordered locations in `config/weather.json`; `show_in_menu: false` hides
  only the icon. Forecasts come from Open-Meteo. Optional U.S. official alerts
  come from the National Weather Service and fail independently of the normal
  forecast. BMO does not infer a location from the device IP address.
- `config/weather.json` supports `units`, `default_location`, `season_style`,
  `animations`, `debug`, `alerts`, and `locations`. Set `debug` to `true` to
  show a weather-owned preview panel covering every supported condition,
  season, time period, and basic moon phase; **Live weather** exits the preview
  without changing forecast data. A location may provide coordinates
  to avoid geocoding or only a place name to resolve at lookup time. If the
  file is missing or malformed, weather safely falls back to the legacy
  `location` and `weather_units` settings when available. The local weather
  file is ignored by Git; only `config/example.weather.json` is tracked. The
  spoken rain-chance value is explicitly the highest hourly precipitation
  probability for the day, not forecast rainfall volume.
- Global quiet hours use the system's local clock and are disabled by default.
  Configure the schedule, active weekdays, and four-digit parent PIN in
  `config/quiet_hours.json` (`0` is Monday and `6` is Sunday); optional sleeping art can live under
  `faces/sleeping`. During an active period, the sleeping cover blocks the
  menu, push-to-talk, voice turns, announcements, and notification badges.
  Entering the PIN unlocks only the current period. The PIN is a convenience
  control stored as plain text, not a security boundary.
- The camera feature saves its interaction image for vision processing and also
  copies it to persistent storage. Configure `save_directory` in that feature's
  `settings`; the tracked example uses
  `/home/pi-bmo/Pictures/bmo/what_do_you_see`. If the setting is omitted, it
  defaults to `~/Pictures/bmo/what_do_you_see`; set it to `null` to keep only
  the per-interaction archive copy.
- The menu-only album feature uses `graphics/icons/album.png` and recursively
  browses supported images under its configured `photo_root` (default:
  `~/Pictures`). It supports swipeable thumbnail pages, fullscreen viewing,
  recoverable Wastebasket moves, and BMO vision analysis of a selected image.
  Its `wastebasket_root`, `bmo_button_image`, and `photos_per_page` settings are
  shown in `config/example.features.json`. Album paths are resolved and must
  remain inside `photo_root`; symbolic-link escapes are excluded.
- The menu-only Learning feature uses `graphics/icons/learning.png` and opens
  an offline 800x480 Pre-K suite only when that icon is tapped. Its data-driven
  curriculum covers literacy, vocabulary, early math, and general readiness.
  Learner profiles,
  teacher-authored prerequisite-aware plans, bounded attempt history, mastery,
  and reports stay under `data/learning`. Instructions and feedback use BMO's
  existing view-scoped Piper voice; no model, microphone, direct phrase, or
  separate TTS path is exposed. See [the Learning guide](docs/AGENT_LEARNING.md) for
  configuration, scoring, storage recovery, and lesson-extension details.

A **mode** is a long-lived interaction, such as Twenty Questions or the Pup
Pairs UI. Modes have an active/inactive lifecycle and choose whether input uses
the wake word, continues listening, or is suspended while a UI owns the turn.
Only one mode can own input at a time. Mode modules use the same ordered,
configuration-driven loading rules as features:

- Omitting `modes` preserves the historical behavior by loading Pup Pairs and
  Twenty Questions in their original registration order. Once `modes` is
  present, it is an allowlist, and an empty list disables every mode.
- Each entry has `module`, `enabled`, and `settings` fields. Disabled entries are
  skipped before validation or import, so disabling Twenty Questions does not
  import its game engine, and disabling Pup Pairs does not import its Tk game UI.
- Configuration, import, missing-hook, duplicate-name, and registration failures
  are isolated per module. Later valid modes still load, and a failed hook leaves
  none of its partial registrations behind.
- Twenty Questions reads its immutable base catalog from
  `data/20_questions/data.jsonl`. The downloaded catalog is intentionally
  untracked; BMO validates and loads it lazily when the game starts and reports
  a short mode-local error if it is missing or corrupt. It uses adaptive
  attribute partitioning over the catalog, not alphabetical object-name search.
- The only player choices BMO presents are **Yes**, **No**, **Sometimes**, and
  **I don't know**. Dataset **Often** is an internal wildcard: it survives a
  matching Yes, No, or Sometimes answer. A spoken “maybe” is accepted as
  Sometimes, but BMO never advertises Maybe or Often as a choice.
- A touch-menu launch opens an embedded 800×480 Twenty Questions board with BMO,
  the current question, touch answer buttons, guess controls, and a reveal
  field before BMO speaks the introduction. The board also shows the candidate
  count, decision/question counters, and the five most recently identified
  things from completed games. Voice launches remain voice-driven; the touch
  board suspends voice capture until it is closed.
- The normal round always continues through 20 question prompts after a wrong
  guess. If the indexed pool is empty after question 19, the local model makes
  one fallback guess; the model is also used for the round-ending guess at
  question 20. If BMO is still wrong, the player wins that round and the board
  asks four bonus questions before a model guess at question 25. The board
  offers PLAY AGAIN after a completed game.
- Confirmed guesses and revealed objects update the optional learned overlay at
  `data/20_questions/learned.jsonl`. It is also untracked, written atomically,
  and stores one stable wide row per object. Learned definite answers can
  refine base Often values; learned Unknown values remain wildcards until a
  later confirmed observation. A malformed learned file disables learning for
  that session without destroying the base catalog.
- Completed target names are kept newest-first in the bounded, atomically
  written `history_path` file. Its path must be distinct from the base and
  learned catalog files.
- Built-in Twenty Questions settings include `show_in_menu`,
  `answer_wait_seconds`, `debug`, `data_path`, `learned_path`, `history_path`,
  `informative_question_limit`, and `total_prompt_limit`. Historical top-level
  `game_answer_wait_seconds` and `twenty_questions_debug` values remain
  supported when mode settings do not override them.
- Enabled modes and features may contribute touch-menu items. Pup Pairs
  contributes its Matching Game icon by default and Twenty Questions contributes
  `graphics/icons/20_questions.png`; set either `show_in_menu` setting to
  `false` to keep voice launch enabled while hiding only that entry.
- Voice launch accepts “Twenty questions”, “Play twenty questions”, “Let's play
  20 questions”, and “Start 20 questions”. Selecting the touch-menu item queues
  the mode through the normal interaction worker and opens its embedded board.
- Menu actions are arranged in six-item grid pages. A game launched from the
  menu leaves that live page underneath it, so exiting the game returns to the
  same page instead of briefly showing BMO's full-screen face.

Mode registration receives a constrained runtime context containing only the Tk
master and approved model, speech, memory, state, announcement, and face
callbacks. Mode modules never receive the complete `BotGUI` object.

The complete feature and mode contracts, failure boundaries, and a minimal
`say_hello` feature are in [the architecture guide](docs/AGENT_ARCHITECTURE.md#extension-contracts).

## Interaction archives

Interaction logging is enabled by default. BMO creates a new directory for every
wake-word, push-to-talk, or game turn instead of reusing `input.wav` and
`current_image.jpg`:

```text
interaction_logs/YYYY/MM/DD/<timestamp-and-id>/
├── manifest.json              # Trigger, timestamps, and completion status
├── events.jsonl               # Ordered lifecycle and camera events
├── input/                     # Voice WAV, transcript, and Whisper output
├── output/                    # Answers, model calls, routes, tools, and speech WAVs
├── web/                       # Search query, raw results, summary input, and timing
└── images/                    # Original camera captures used by the vision model
```

The model-call log stores the prompts and text actually emitted by Ollama. It
does not invent or expose reasoning that the model did not return. Archives have
no automatic deletion policy. They can contain voices, photos, location/search
data, and full conversation context, so `interaction_logs/` is Git-ignored and
should be protected like other private data. Set `interaction_logging` to
`false` to disable it, or change `interaction_log_directory` to place it on a
larger/private disk.

---

## 🎨 Customizing Your Character

This software is a generic framework. You can give it a new personality by replacing the assets:

1.  **Faces:** The directories and deterministic PNG sequences are configured
    in `config/compact_face.json`; start from
    `config/example.compact_face.json`. Add frames or map a new state there
    without editing individual feature screens. Every compact view uses the
    same fixed top-right 108×65 component, and 5:3 artwork is letterboxed
    without stretching.
2.  **Sounds:** Put multiple `.wav` files in the `sounds/[category]/` folders. The robot will pick one at random each time (e.g., different "thinking" hums or "error" buzzes).

---
## 🗣️ The Custom BMO Voice

This project features a custom, locally fine-tuned text-to-speech model to make the agent sound authentic! 

When you run the `setup.sh` script, it downloads the compiled `.onnx` model and
its `.json` configuration file from the pinned
[`v1.0-voice` release](https://github.com/brenpoly/be-more-agent/releases/tag/v1.0-voice)
and places them in the local `voices/` directory.

**Manual Installation (if you are not using setup.sh):**
1. Download `bmo.onnx` and `bmo.onnx.json` from the [`v1.0-voice` release](https://github.com/brenpoly/be-more-agent/releases/tag/v1.0-voice).
2. Create a folder named `voices/` in the root directory of this repository.
3. Place both downloaded files inside the `voices/` folder.
4. Ensure your `config/settings.json` file points to the new model:
   ```json
   {
     "voice_model": "voices/bmo.onnx"
   }
   ```

---

## ⚠️ Troubleshooting

* **"No search library found":** If web search fails, ensure you are in the virtual environment and `ddgs` is installed via pip.
* **Shutdown Errors:** When you exit the script (Ctrl+C), you might see `Expression 'alsa_snd_pcm_mmap_begin' failed`. **This is normal.** It just means the audio stream was cut off mid-sample. It does not affect the functionality.
* **Audio Glitches:** If the voice sounds fast or slow, the script attempts to auto-detect sample rates. Ensure your `config/settings.json` points to a valid `.onnx` voice model in the `piper/` folder.
If your custom BMO voice sounds incredibly deep, slow, or "demonic," don't panic! This is not an issue with the Piper installation or the setup script. It is almost always caused by a **Sample Rate (Hz)** mismatch between the model and the audio player.

Here is how to fix it:

**Fix 1: Match the Sample Rate**
By default, the application expects "medium" quality models and plays audio at
22050 Hz. If your custom model was trained at a different quality (like 48000 Hz
or 16000 Hz), playing it at the default rate will stretch or compress the audio,
severely altering the pitch.

1. Open your model's configuration file (e.g., `voices/bmo.onnx.json`).
2. Look for the `"sample_rate"` property and note the number (e.g., `22050`, `16000`, `48000`).
3. Open `bmo/audio.py` and find the line: `PIPER_RATE = 22050`.
4. Change that number to match the sample rate in your `.json` file.
5. Save the file and restart the agent.

**Fix 2: Check the Length Scale**
If the sample rates match perfectly, the issue might be the model's internal pacing setting.

1. Open your `voices/bmo.onnx.json` file.
2. Look inside the `"inference"` block for a setting called `"length_scale"`. 
3. Piper uses this to determine the speed of the voice. If this value is set significantly higher than `1.0`, it will stretch the audio and make BMO sound like a zombie. Lower it closer to `1.0` to speed the voice back up to normal.

## 📄 License
This project is dual-licensed:

* **Software / Code:** All source code is licensed under the [MIT License](LICENSE).
* **Hardware / 3D Models:** The `.obj`, `.stl`, and other 3D modeling files associated with the physical case are licensed under the [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-nc-sa/4.0/)
* **Qt for Python dependency:** PySide6 is distributed separately under
  LGPL-3.0-only, GPL-2.0-only, GPL-3.0-only, or a commercial Qt license; it is
  not relicensed by this project's MIT license.

## ⚖️ Legal Disclaimer
Disclaimer: Fan Project
This repository and the associated voice model are a non-commercial, open-source fan project. "BMO" and Adventure Time are registered trademarks and copyrights of Cartoon Network and Warner Bros. Discovery. This project is not affiliated with, endorsed by, or sponsored by Cartoon Network or its parent companies.

Voice Model Attribution
The text-to-speech capabilities of this project are powered by Piper. The custom voice model was fine-tuned locally using Piper's base "Amy" model (en_US-amy-medium). The original Piper engine and base models are developed by the Rhasspy project and distributed under the MIT License.
