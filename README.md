# Be More Agent 🤖
**A Customizable, Offline-First AI Agent for Raspberry Pi**

[![Watch the Demo](https://img.youtube.com/vi/l5ggH-YhuAw/maxresdefault.jpg)](https://youtu.be/l5ggH-YhuAw)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-red) ![License](https://img.shields.io/badge/License-MIT-green)

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
├── config.json                # Local user settings (copied from the example)
├── chat_memory.json           # Conversation history
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
system libraries, creates local folders, builds Whisper.cpp, downloads the
`base.en` speech model and Piper voices, creates the Python environment, pulls
the Ollama models, and installs the default wake-word model. It is safe to run
again and reuses valid existing downloads.*

### 4. Configure the Wake Word
The setup script downloads a default wake word ("Hey Jarvis"). To use your own:
1. Train a model at [OpenWakeWord](https://github.com/dscripka/openWakeWord).
2. Place the `.onnx` file in the root folder.
3. Rename it to `wakeword.onnx`.

### 5. Run the Agent
```bash
source venv/bin/activate
python agent.py
```

---

## 📂 Configuration (`config.json`)

The application reads local settings from `config.json`, but it does **not**
create that file. If the file is absent or invalid, BMO reports a parsing error
when applicable and runs with the defaults in `bmo/config.py` without writing
anything. To keep a local configuration, copy the tracked example and edit the
copy:

```bash
cp example.config.json config.json
```

For example:

```json
{
    "text_model": "gemma3:1b",
    "vision_model": "moondream",
    "voice_model": "piper/en_GB-semaine-medium.onnx",
    "chat_memory": true,
    "camera_rotation": 0,
    "interaction_logging": true,
    "interaction_log_directory": "interaction_logs",
    "system_prompt_extras": "You are a helpful robot assistant. Keep responses short and cute."
}
```

### Features and modes

A **feature** is a short-lived, model-routable action such as checking the time
or setting a timer. Feature modules are selected by the ordered `features` list
shown in `example.config.json`:

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
- Built-in Twenty Questions settings are `answer_wait_seconds` and `debug`.
  Historical top-level `game_answer_wait_seconds` and
  `twenty_questions_debug` values remain supported when mode settings do not
  override them.

Mode registration receives a constrained runtime context containing only the Tk
master and approved model, speech, memory, state, announcement, and face
callbacks. Mode modules never receive the complete `BotGUI` object.

The complete feature and mode contracts, failure boundaries, and a minimal
`say_hello` feature are in [the architecture guide](docs/architecture.md#extension-contracts).

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

1.  **Faces:** The script looks for PNG sequences in `faces/[state]/`. It will loop through all images found in the folder.
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
4. Ensure your `config.json` file points to the new model:
   ```json
   {
     "voice_model": "voices/bmo.onnx"
   }
   ```

---

## ⚠️ Troubleshooting

* **"No search library found":** If web search fails, ensure you are in the virtual environment and `ddgs` is installed via pip.
* **Shutdown Errors:** When you exit the script (Ctrl+C), you might see `Expression 'alsa_snd_pcm_mmap_begin' failed`. **This is normal.** It just means the audio stream was cut off mid-sample. It does not affect the functionality.
* **Audio Glitches:** If the voice sounds fast or slow, the script attempts to auto-detect sample rates. Ensure your `config.json` points to a valid `.onnx` voice model in the `piper/` folder.
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

## ⚖️ Legal Disclaimer
Disclaimer: Fan Project
This repository and the associated voice model are a non-commercial, open-source fan project. "BMO" and Adventure Time are registered trademarks and copyrights of Cartoon Network and Warner Bros. Discovery. This project is not affiliated with, endorsed by, or sponsored by Cartoon Network or its parent companies.

Voice Model Attribution
The text-to-speech capabilities of this project are powered by Piper. The custom voice model was fine-tuned locally using Piper's base "Amy" model (en_US-amy-medium). The original Piper engine and base models are developed by the Rhasspy project and distributed under the MIT License.
