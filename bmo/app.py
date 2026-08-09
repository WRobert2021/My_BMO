"""Tkinter application coordinator for the Be More Agent."""

from __future__ import annotations

import atexit
import os
import random
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import ollama
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import ttk

from bmo.archive import InteractionArchive, InteractionArchiveManager
from bmo.audio import (
    AudioRecorder,
    PiperSpeaker,
    SoundPlayer,
    describe_input_device,
    resolve_input_device,
)
from bmo.config import (
    BMO_IMAGE_FILE,
    MEMORY_FILE,
    OLLAMA_OPTIONS,
    SOUND_DIRECTORIES,
    WAKE_WORD_MODEL,
    WAKE_WORD_THRESHOLD,
    load_config,
)
from bmo.features.camera import capture_image as capture_camera_image
from bmo.features.contracts import (
    RuntimeNotification,
    ToolResult,
    ToolResultKind,
)
from bmo.intent import infer_tool_action
from bmo.memory import load_chat_history, save_chat_history
from bmo.modes import InputPolicyKind, ModeRegistry
from bmo.modes.games import MatchingGameMode, TwentyQuestionsMode
from bmo.prompts import build_system_prompt
from bmo.speech import WakeWordDetector, WhisperTranscriber, extract_json_from_text
from bmo.state import BotStates
from bmo.tools import ToolRouter
from bmo.twenty_questions import TwentyQuestionsGame


class BotGUI:
    """Own the UI and coordinate the application services."""

    BG_WIDTH, BG_HEIGHT = 800, 480
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.config = load_config()
        self.text_model = str(self.config["text_model"])
        self.vision_model = str(self.config["vision_model"])
        self.tool_router = ToolRouter(
            self.config,
            runtime_callback=self._handle_runtime_notification,
        )
        self.system_prompt = build_system_prompt(
            self.config,
            self.tool_router.registry,
        )
        self.shutdown_event = threading.Event()
        self.archive_manager = InteractionArchiveManager(
            self.config.get("interaction_log_directory", "interaction_logs"),
            enabled=bool(self.config.get("interaction_logging", True)),
        )
        self.current_interaction: InteractionArchive | None = None

        input_device = resolve_input_device(self.config)
        describe_input_device(input_device)
        preferred_rate = self.config.get("input_sample_rate")

        self.sound_player = SoundPlayer()
        self.recorder = AudioRecorder(input_device, preferred_rate)
        self.transcriber = WhisperTranscriber(
            self.config["whisper_binary"],
            self.config["whisper_model"],
        )
        self.wake_word = WakeWordDetector(
            WAKE_WORD_MODEL,
            WAKE_WORD_THRESHOLD,
            input_device,
            preferred_rate,
        )
        self.speaker = PiperSpeaker(str(self.config["voice_model"]))

        master.title("Pi Assistant")
        master.attributes("-fullscreen", True)
        master.bind("<Escape>", self.exit_fullscreen)
        master.bind("<Return>", self.handle_ptt_toggle)
        master.bind("<space>", self.handle_speaking_interrupt)
        master.protocol("WM_DELETE_WINDOW", self.safe_exit)

        self.current_state = BotStates.WARMUP
        self.animations: dict[str, list[ImageTk.PhotoImage]] = {}
        self.current_frame_index = 0
        self.current_overlay_image: ImageTk.PhotoImage | None = None

        self.permanent_memory = load_chat_history(MEMORY_FILE, self.system_prompt)
        self.session_memory: list[dict[str, str]] = []
        self.thinking_sound_active = threading.Event()

        self.last_ptt_time = 0.0
        self.ptt_event = threading.Event()
        self.recording_active = threading.Event()
        self.interrupted = threading.Event()

        self.tts_queue: list[tuple[str, Path | None]] = []
        self.tts_queue_lock = threading.Lock()
        self.tts_thread: threading.Thread | None = None
        self.tts_active = threading.Event()
        self.exiting = False
        self.main_thread: threading.Thread | None = None
        self.mode_registry = ModeRegistry(
            (
                MatchingGameMode(
                    self.master,
                    speak_response=self._speak_complete_response,
                    remember_turn=self._remember_turn,
                    wait_for_tts=self.wait_for_tts,
                    set_state=self.set_state,
                    announce=self.enqueue_speech,
                    face_provider=self._current_mode_face,
                ),
                TwentyQuestionsMode(
                    TwentyQuestionsGame(
                        debug=bool(
                            self.config.get("twenty_questions_debug", False)
                        )
                    ),
                    text_model=self.text_model,
                    chat=self._logged_chat,
                    speak_response=self._speak_complete_response,
                    wait_for_tts=self.wait_for_tts,
                    set_state=self.set_state,
                    answer_wait_seconds=self.config.get(
                        "game_answer_wait_seconds",
                        12,
                    ),
                ),
            )
        )
        atexit.register(self.safe_exit)

        self._build_gui()
        self.load_animations()
        self.update_animation()
        self.main_thread = threading.Thread(
            target=self.safe_main_execution,
            name="bmo-main-loop",
            daemon=True,
        )
        self.main_thread.start()

    def _build_gui(self) -> None:
        self.background_label = tk.Label(self.master)
        self.background_label.place(
            x=0,
            y=0,
            width=self.BG_WIDTH,
            height=self.BG_HEIGHT,
        )
        self.background_label.bind("<Button-1>", self.toggle_hud_visibility)

        self.overlay_label = tk.Label(self.master, bg="black")
        self.overlay_label.bind("<Button-1>", self.toggle_hud_visibility)

        self.response_text = tk.Text(
            self.master,
            height=6,
            width=60,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#ffffff",
            fg="#000000",
            font=("Arial", 12),
        )
        self.status_var = tk.StringVar(value="Initializing...")
        self.status_label = ttk.Label(
            self.master,
            textvariable=self.status_var,
            background="#2e2e2e",
            foreground="white",
        )
        self.exit_button = ttk.Button(
            self.master,
            text="Exit & Save",
            command=self.safe_exit,
        )

    def safe_exit(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        print("\n--- SHUTDOWN SEQUENCE ---", flush=True)

        # Cooperative cancellation is critical on macOS. Never call the global
        # sounddevice.stop() while the wake-word thread owns an InputStream.
        self.shutdown_event.set()
        self.tool_router.close()
        self.mode_registry.close()
        self.interrupted.set()
        self.ptt_event.set()
        self.recording_active.clear()
        self.thinking_sound_active.clear()
        with self.tts_queue_lock:
            self.tts_queue.clear()
        self.speaker.stop()

        current_thread = threading.current_thread()
        if self.main_thread and self.main_thread is not current_thread:
            self.main_thread.join(timeout=3.0)
        if self.tts_thread and self.tts_thread is not current_thread:
            self.tts_thread.join(timeout=2.0)

        try:
            save_chat_history(
                MEMORY_FILE,
                self.permanent_memory,
                self.session_memory,
            )
        except OSError as exc:
            print(f"Memory save error: {exc}", flush=True)

        try:
            ollama.generate(model=self.text_model, prompt="", keep_alive=0)
        except Exception:
            pass

        try:
            self.master.quit()
        except Exception:
            pass

    def exit_fullscreen(self, event: tk.Event | None = None) -> None:
        del event
        self.master.attributes("-fullscreen", False)
        self.safe_exit()

    def toggle_hud_visibility(self, event: tk.Event | None = None) -> None:
        del event
        try:
            if self.response_text.winfo_ismapped():
                self.response_text.place_forget()
                self.status_label.place_forget()
                self.exit_button.place_forget()
            else:
                self.response_text.place(relx=0.5, rely=0.82, anchor=tk.S)
                self.status_label.place(
                    relx=0.5,
                    rely=1.0,
                    anchor=tk.S,
                    relwidth=1,
                )
                self.exit_button.place(x=10, y=10)
        except tk.TclError:
            pass

    def handle_ptt_toggle(self, event: tk.Event | None = None) -> None:
        del event
        current_time = time.time()
        if current_time - self.last_ptt_time < 0.5:
            return
        self.last_ptt_time = current_time

        if self.recording_active.is_set():
            print("[PTT] Toggle OFF", flush=True)
            self.recording_active.clear()
        elif self.current_state == BotStates.IDLE or "Wait" in self.status_var.get():
            print("[PTT] Toggle ON", flush=True)
            self.recording_active.set()
            self.ptt_event.set()

    def handle_speaking_interrupt(self, event: tk.Event | None = None) -> None:
        del event
        if self.current_state not in (BotStates.SPEAKING, BotStates.THINKING):
            return

        self.interrupted.set()
        self.thinking_sound_active.clear()
        with self.tts_queue_lock:
            self.tts_queue.clear()
        self.speaker.stop()
        self.set_state(BotStates.IDLE, "Interrupted.")

    def load_animations(self) -> None:
        base_path = Path("faces")
        states = [
            BotStates.IDLE,
            BotStates.LISTENING,
            BotStates.THINKING,
            BotStates.SPEAKING,
            BotStates.ERROR,
            BotStates.CAPTURING,
            BotStates.WARMUP,
        ]
        for state in states:
            folder = base_path / state
            self.animations[state] = []
            if folder.exists():
                for image_path in sorted(folder.glob("*.png")):
                    image = Image.open(image_path).resize(
                        (self.BG_WIDTH, self.BG_HEIGHT)
                    )
                    self.animations[state].append(ImageTk.PhotoImage(image))

            if not self.animations[state]:
                idle_frames = self.animations.get(BotStates.IDLE, [])
                if idle_frames:
                    self.animations[state] = idle_frames
                else:
                    blank = Image.new(
                        "RGB",
                        (self.BG_WIDTH, self.BG_HEIGHT),
                        color="#0000FF",
                    )
                    self.animations[state].append(ImageTk.PhotoImage(blank))

    def update_animation(self) -> None:
        if self.exiting:
            return
        frames = self.animations.get(self.current_state, []) or self.animations.get(
            BotStates.IDLE, []
        )
        if not frames:
            self.master.after(500, self.update_animation)
            return

        if self.current_state == BotStates.SPEAKING:
            self.current_frame_index = (
                random.randint(1, len(frames) - 1) if len(frames) > 1 else 0
            )
        else:
            self.current_frame_index = (self.current_frame_index + 1) % len(frames)

        self.background_label.config(image=frames[self.current_frame_index])
        speed = 50 if self.current_state == BotStates.SPEAKING else 500
        self.master.after(speed, self.update_animation)

    def set_state(
        self,
        state: str,
        message: str = "",
        camera_path: str | None = None,
    ) -> None:
        if self.exiting:
            return

        def update() -> None:
            if self.exiting:
                return
            if message:
                print(f"[STATE] {state.upper()}: {message}", flush=True)
            if self.current_state != state:
                self.current_state = state
                self.current_frame_index = 0
            if message:
                self.status_var.set(message)

            if (
                camera_path
                and os.path.exists(camera_path)
                and state in (BotStates.THINKING, BotStates.SPEAKING)
            ):
                try:
                    image = Image.open(camera_path).resize(
                        (self.OVERLAY_WIDTH, self.OVERLAY_HEIGHT)
                    )
                    self.current_overlay_image = ImageTk.PhotoImage(image)
                    self.overlay_label.config(image=self.current_overlay_image)
                    self.overlay_label.place(x=200, y=90)
                except Exception:
                    pass
            else:
                self.overlay_label.place_forget()

        self.master.after(0, update)

    def append_to_text(self, text: str, newline: bool = True) -> None:
        if self.exiting:
            return

        def update() -> None:
            if self.exiting:
                return
            self.response_text.config(state=tk.NORMAL)
            self.response_text.insert(tk.END, text + ("\n" if newline else ""))
            self.response_text.see(tk.END)
            self.response_text.config(state=tk.DISABLED)

        self.master.after(0, update)

    def _handle_runtime_notification(
        self,
        notification: RuntimeNotification,
    ) -> None:
        """Forward approved feature notifications to the existing UI and TTS."""
        if self.exiting:
            return
        print(
            f"[FEATURE] {notification.source}: {notification.message}",
            flush=True,
        )
        self.set_state(BotStates.SPEAKING, notification.message)
        self.append_to_text(f"BOT: {notification.message}")
        self.enqueue_speech(notification.message)

    def _stream_to_text(self, chunk: str) -> None:
        if self.exiting:
            return

        def update() -> None:
            if self.exiting:
                return
            self.response_text.config(state=tk.NORMAL)
            self.response_text.insert(tk.END, chunk)
            self.response_text.see(tk.END)
            self.response_text.config(state=tk.DISABLED)

        self.master.after(0, update)

    def safe_main_execution(self) -> None:
        try:
            self.warm_up_logic()
            self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self.tts_thread.start()

            while not self.exiting:
                input_policy = self.mode_registry.input_policy()
                while (
                    input_policy.kind == InputPolicyKind.SUSPENDED
                    and not self.exiting
                ):
                    self.shutdown_event.wait(0.1)
                    input_policy = self.mode_registry.input_policy()
                if self.exiting:
                    return
                if input_policy.kind == InputPolicyKind.CONTINUOUS:
                    trigger_source = input_policy.trigger_source
                    self.set_state(
                        BotStates.LISTENING,
                        input_policy.listening_status,
                    )
                else:
                    trigger_source = self.detect_wake_word_or_ptt()
                if self.exiting:
                    return
                if self.interrupted.is_set():
                    self.interrupted.clear()
                    self.set_state(BotStates.IDLE, "Resetting...")
                    continue

                if input_policy.kind == InputPolicyKind.WAKE_WORD:
                    self.set_state(
                        BotStates.LISTENING,
                        input_policy.listening_status,
                    )
                if trigger_source == "STOP" or self.shutdown_event.is_set():
                    return
                self._start_interaction(trigger_source)
                audio_path = (
                    str(self.current_interaction.audio_path)
                    if self.current_interaction
                    else "input.wav"
                )
                if trigger_source == "PTT":
                    audio_file = self.recorder.record_ptt(
                        self.recording_active,
                        filename=audio_path,
                        shutdown_event=self.shutdown_event,
                    )
                else:
                    audio_file = self.recorder.record_adaptive(
                        filename=audio_path,
                        shutdown_event=self.shutdown_event,
                        initial_silence_timeout=(
                            input_policy.initial_silence_timeout
                        ),
                    )

                if not audio_file:
                    self._finish_interaction("no_speech")
                    if (
                        input_policy.kind == InputPolicyKind.CONTINUOUS
                        and self.mode_registry.is_active()
                    ):
                        self.set_state(
                            BotStates.LISTENING,
                            input_policy.no_speech_status,
                        )
                    else:
                        self.set_state(BotStates.IDLE, "Heard nothing.")
                    continue

                self.play_sound(self.random_sound("ack"))
                user_text = self.transcriber.transcribe(
                    audio_file,
                    archive_directory=(
                        self.current_interaction.path / "input"
                        if self.current_interaction
                        else None
                    ),
                )
                if not user_text:
                    self._finish_interaction("transcription_empty")
                    if (
                        input_policy.kind == InputPolicyKind.CONTINUOUS
                        and self.mode_registry.is_active()
                    ):
                        self.set_state(
                            BotStates.LISTENING,
                            input_policy.empty_transcript_status,
                        )
                    else:
                        self.set_state(
                            BotStates.IDLE,
                            "Transcription empty.",
                        )
                    continue

                if self.current_interaction:
                    self.current_interaction.write_text(
                        "input", "transcript.txt", user_text + "\n"
                    )
                    self.current_interaction.event(
                        "transcription_completed",
                        {"text": user_text, "audio_file": str(audio_file)},
                    )
                self.append_to_text(f"YOU: {user_text}")
                self.interrupted.clear()
                self.chat_and_respond(user_text)
                self._finish_interaction("completed")
        except Exception as exc:
            self._finish_interaction("error", str(exc))
            if not self.exiting:
                traceback.print_exc()
                self.set_state(BotStates.ERROR, f"Fatal Error: {str(exc)[:40]}")

    def warm_up_logic(self) -> None:
        self.set_state(BotStates.WARMUP, "Warming up brains...")
        loaded = True
        try:
            ollama.generate(model=self.text_model, prompt="", keep_alive=-1)
        except Exception as exc:
            loaded = False
            print(f"Failed to load {self.text_model}: {exc}", flush=True)
        self.play_sound(self.random_sound("greeting"))
        print("Models loaded." if loaded else "Model warm-up incomplete.", flush=True)

    def detect_wake_word_or_ptt(self) -> str:
        self.set_state(BotStates.IDLE, "Waiting...")
        return self.wake_word.wait_for_trigger(
            self.ptt_event,
            self.shutdown_event,
        )

    def _start_interaction(self, trigger: str) -> None:
        """Create a fresh archive without letting disk errors stop BMO."""
        try:
            self.current_interaction = self.archive_manager.begin(trigger)
            if self.current_interaction:
                print(
                    f"[ARCHIVE] {self.current_interaction.path}",
                    flush=True,
                )
        except OSError as exc:
            self.current_interaction = None
            print(f"[ARCHIVE] Could not start interaction log: {exc}", flush=True)

    def _finish_interaction(
        self,
        status: str,
        error: str | None = None,
    ) -> None:
        interaction = self.current_interaction
        self.current_interaction = None
        if not interaction:
            return
        try:
            interaction.finish(status, error)
        except OSError as exc:
            print(f"[ARCHIVE] Could not finish interaction log: {exc}", flush=True)

    def _logged_chat(self, **kwargs: Any) -> Any:
        """Call Ollama while retaining observable requests and responses."""
        interaction = self.current_interaction
        started = time.monotonic()
        if interaction:
            interaction.append_json(
                "output",
                "model_calls.jsonl",
                {"phase": "request", "request": kwargs},
            )
        try:
            response = ollama.chat(**kwargs)
        except Exception as exc:
            if interaction:
                interaction.append_json(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "error",
                        "error": str(exc),
                        "duration_seconds": time.monotonic() - started,
                    },
                )
            raise

        if not kwargs.get("stream"):
            if interaction:
                interaction.append_json(
                    "output",
                    "model_calls.jsonl",
                    {
                        "phase": "response",
                        "response": response,
                        "duration_seconds": time.monotonic() - started,
                    },
                )
            return response

        def logged_stream():
            content_parts: list[str] = []
            try:
                for chunk in response:
                    try:
                        content_parts.append(str(chunk["message"]["content"]))
                    except (KeyError, TypeError):
                        pass
                    yield chunk
            except Exception as exc:
                if interaction:
                    interaction.append_json(
                        "output",
                        "model_calls.jsonl",
                        {
                            "phase": "stream_error",
                            "error": str(exc),
                            "partial_content": "".join(content_parts),
                            "duration_seconds": time.monotonic() - started,
                        },
                    )
                raise
            else:
                if interaction:
                    interaction.append_json(
                        "output",
                        "model_calls.jsonl",
                        {
                            "phase": "response",
                            "response": {"content": "".join(content_parts)},
                            "duration_seconds": time.monotonic() - started,
                        },
                    )

        return logged_stream()

    def _execute_tool(self, action_data: dict[str, Any]) -> ToolResult:
        action_name = self.tool_router.normalize_action(action_data)
        started = time.monotonic()
        try:
            result = self.tool_router.execute(action_data)
        except Exception as exc:
            if self.current_interaction:
                self.current_interaction.append_json(
                    "web" if action_name == "search_web" else "output",
                    "searches.jsonl" if action_name == "search_web" else "tools.jsonl",
                    {
                        "action": action_name,
                        "request": action_data,
                        "error": str(exc),
                        "duration_seconds": time.monotonic() - started,
                    },
                )
            raise
        if self.current_interaction:
            self.current_interaction.append_json(
                "web" if action_name == "search_web" else "output",
                "searches.jsonl" if action_name == "search_web" else "tools.jsonl",
                {
                    "action": action_name,
                    "request": action_data,
                    "result": result.archive_value(),
                    "details": self.tool_router.last_tool_details,
                    "duration_seconds": time.monotonic() - started,
                },
            )
        return result

    def _archive_assistant_text(self, text: str) -> None:
        if not self.current_interaction:
            return
        self.current_interaction.append_text(
            "output", "assistant.txt", text
        )
        self.current_interaction.append_json(
            "output", "responses.jsonl", {"text": text}
        )

    def capture_image(self) -> str | None:
        self.set_state(BotStates.CAPTURING, "Watching...")
        image_file = (
            self.current_interaction.image_path()
            if self.current_interaction
            else BMO_IMAGE_FILE
        )
        try:
            rotation = int(self.config.get("camera_rotation", 0))
            captured_path = capture_camera_image(
                image_file,
                rotation=rotation,
            )
            if self.current_interaction:
                self.current_interaction.event(
                    "image_captured",
                    {"path": captured_path, "rotation": rotation},
                )
            return captured_path
        except Exception as exc:
            print(f"Camera Error: {exc}", flush=True)
            if self.current_interaction:
                self.current_interaction.event(
                    "image_capture_failed", {"error": str(exc)}
                )
            return None

    def chat_and_respond(self, text: str, image_path: str | None = None) -> None:
        if image_path is None and self.mode_registry.route_input(text):
            return

        if "forget everything" in text.lower() or "reset memory" in text.lower():
            self.session_memory = []
            self.permanent_memory = [
                {"role": "system", "content": self.system_prompt}
            ]
            save_chat_history(
                MEMORY_FILE,
                self.permanent_memory,
                self.session_memory,
            )
            self._archive_assistant_text("Okay. Memory wiped.")
            self.enqueue_speech("Okay. Memory wiped.")
            self.set_state(BotStates.IDLE, "Memory Wiped")
            return

        if image_path is None:
            action_data = self.tool_router.match_direct_action(text)
            if not action_data:
                try:
                    action_data = infer_tool_action(
                        self.text_model,
                        text,
                        self._logged_chat,
                        self.tool_router,
                    )
                    print(
                        f"[ROUTER] Local model inferred: "
                        f"{action_data or 'chat'}",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"[ROUTER] Local intent lookup failed: {exc}", flush=True)
            if action_data:
                if self.current_interaction:
                    self.current_interaction.append_json(
                        "output",
                        "routing.jsonl",
                        {"user_text": text, "decision": action_data},
                    )
                self._handle_direct_action(text, action_data)
                return

        model_to_use = self.vision_model if image_path else self.text_model
        self.set_state(BotStates.THINKING, "Thinking...", image_path)

        if image_path:
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": text, "images": [image_path]}
            ]
        else:
            user_message = {"role": "user", "content": text}
            messages = self.permanent_memory + self.session_memory + [user_message]

        self.thinking_sound_active.set()
        threading.Thread(target=self._run_thinking_sound_loop, daemon=True).start()

        full_response_buffer = ""
        sentence_buffer = ""

        try:
            stream = self._logged_chat(
                model=model_to_use,
                messages=messages,
                stream=True,
                options=OLLAMA_OPTIONS,
            )
            action_mode = False

            for chunk in stream:
                if self.interrupted.is_set():
                    break
                content = chunk["message"]["content"]
                full_response_buffer += content

                if '{"' in content or "action:" in content.lower():
                    action_mode = True
                    self.thinking_sound_active.clear()
                    continue
                if action_mode:
                    continue

                self.thinking_sound_active.clear()
                if self.current_state != BotStates.SPEAKING:
                    self.set_state(BotStates.SPEAKING, "Speaking...", image_path)
                    self.append_to_text("BOT: ", newline=False)

                self._stream_to_text(content)
                sentence_buffer += content
                if any(punctuation in content for punctuation in ".!?\n"):
                    clean_sentence = sentence_buffer.strip()
                    if clean_sentence and re.search(r"[a-zA-Z0-9]", clean_sentence):
                        self.enqueue_speech(clean_sentence)
                    sentence_buffer = ""

            if action_mode:
                self._handle_action_response(
                    text,
                    image_path,
                    model_to_use,
                    full_response_buffer,
                )
            else:
                remaining = sentence_buffer.strip()
                if remaining and re.search(r"[a-zA-Z0-9]", remaining):
                    self.enqueue_speech(remaining)
                self.append_to_text("")
                self._archive_assistant_text(full_response_buffer)
                self._remember_turn(text, full_response_buffer)

            self.wait_for_tts()
            self.set_state(BotStates.IDLE, "Ready")
        except Exception as exc:
            print(f"LLM Error: {exc}", flush=True)
            self._finish_interaction("error", str(exc))
            self.set_state(BotStates.ERROR, "Brain Freeze!")

    def _current_mode_face(self) -> Image.Image | None:
        frames = self.animations.get(
            self.current_state,
            [],
        ) or self.animations.get(BotStates.IDLE, [])
        if not frames:
            return None
        frame_index = self.current_frame_index % len(frames)
        return ImageTk.getimage(frames[frame_index]).copy()

    def _handle_direct_action(
        self,
        user_text: str,
        action_data: dict[str, str],
    ) -> None:
        """Execute a clearly requested tool without asking the LLM to route it."""
        self.set_state(BotStates.THINKING, "Thinking...")
        action_name = self.tool_router.normalize_action(action_data)
        tool_result = self._execute_tool(action_data)
        self._process_tool_result(
            user_text,
            action_name,
            tool_result,
            image_path=None,
            model_to_use=self.text_model,
            direct=True,
        )
        if tool_result.kind is ToolResultKind.CAPTURE_IMAGE:
            return
        self.wait_for_tts()
        self.set_state(BotStates.IDLE, "Ready")

    def _handle_action_response(
        self,
        text: str,
        image_path: str | None,
        model_to_use: str,
        full_response: str,
    ) -> None:
        action_data = extract_json_from_text(full_response)
        if not action_data:
            return

        action_name = self.tool_router.normalize_action(action_data)
        tool_result = self._execute_tool(action_data)
        self._process_tool_result(
            text,
            action_name,
            tool_result,
            image_path=image_path,
            model_to_use=model_to_use,
            direct=False,
        )

    def _process_tool_result(
        self,
        user_text: str,
        action_name: str,
        tool_result: ToolResult,
        *,
        image_path: str | None,
        model_to_use: str,
        direct: bool,
    ) -> None:
        """Present one typed tool result, regardless of how it was routed."""
        if tool_result.kind is ToolResultKind.CAPTURE_IMAGE:
            new_image_path = self.capture_image()
            if new_image_path:
                self.chat_and_respond(user_text, image_path=new_image_path)
            else:
                fallback = "I could not use the camera right now."
                self._speak_complete_response(fallback, None)
                self._remember_turn(user_text, fallback)
            return

        fallback_text = {
            ToolResultKind.INVALID_ACTION: "I am not sure how to do that.",
            ToolResultKind.ERROR: "I cannot reach the internet right now.",
        }.get(tool_result.kind)
        if tool_result.kind is ToolResultKind.EMPTY:
            fallback_text = (
                "I searched, but I couldn't find anything about that."
                if direct
                else "I searched, but I couldn't find any news about that."
            )
        if fallback_text is not None:
            self._speak_complete_response(fallback_text, image_path)
            self._remember_turn(user_text, fallback_text)
            return

        result_text = tool_result.content
        if not result_text:
            return

        if tool_result.kind is ToolResultKind.CHAT_FALLBACK:
            response_text = result_text
        elif direct and action_name == "search_web":
            self.set_state(BotStates.THINKING, "Reading...")
            summary_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are reading current web-search results for the user. "
                        "Briefly report the useful information contained in the results. "
                        "The user's words may be a search command rather than a question. "
                        "Do not claim the results are irrelevant when their titles or "
                        "snippets clearly concern the requested subject. "
                        "Use only the supplied results. Answer in one or two short sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Search request: {user_text}\n\n"
                        f"Web-search results:\n{result_text}\n\n"
                        "Report what these results say."
                    ),
                },
            ]
            final_response = self._logged_chat(
                model=self.text_model,
                messages=summary_prompt,
                stream=False,
                options=OLLAMA_OPTIONS,
            )
            response_text = final_response["message"]["content"].strip()
        elif direct or action_name in {"get_time", "set_timer"}:
            response_text = result_text
        else:
            summary_prompt = [
                {
                    "role": "system",
                    "content": "Summarize this result in one short sentence.",
                },
                {
                    "role": "user",
                    "content": (
                        f"RESULT: {result_text}\nUser Question: {user_text}"
                    ),
                },
            ]
            self.set_state(BotStates.THINKING, "Reading...")
            self.thinking_sound_active.set()
            final_response = self._logged_chat(
                model=model_to_use,
                messages=summary_prompt,
                stream=False,
                options=OLLAMA_OPTIONS,
            )
            response_text = final_response["message"]["content"]

        self._speak_complete_response(response_text, image_path)
        self._remember_turn(user_text, response_text)

    def _speak_complete_response(
        self,
        text: str,
        image_path: str | None,
    ) -> None:
        self.thinking_sound_active.clear()
        self.set_state(BotStates.SPEAKING, "Speaking...", image_path)
        self.append_to_text("BOT: ", newline=False)
        self.append_to_text(text, newline=True)
        self._archive_assistant_text(text)
        self.enqueue_speech(text)

    def _remember_turn(self, user_text: str, assistant_text: str) -> None:
        self.session_memory.append({"role": "user", "content": user_text})
        self.session_memory.append(
            {"role": "assistant", "content": assistant_text}
        )

    def enqueue_speech(self, text: str) -> None:
        speech_path = (
            self.current_interaction.speech_path()
            if self.current_interaction
            else None
        )
        with self.tts_queue_lock:
            self.tts_queue.append((text, speech_path))

    def wait_for_tts(self) -> None:
        while self.tts_queue or self.tts_active.is_set():
            if self.interrupted.is_set() or self.exiting:
                break
            time.sleep(0.1)

    def _tts_worker(self) -> None:
        while not self.exiting:
            queued_speech: tuple[str, Path | None] | None = None
            with self.tts_queue_lock:
                if self.tts_queue:
                    queued_speech = self.tts_queue.pop(0)
                    self.tts_active.set()
            if queued_speech:
                text, speech_path = queued_speech
                self.speaker.speak(
                    text,
                    self.interrupted,
                    self.shutdown_event,
                    archive_path=speech_path,
                )
                self.tts_active.clear()
            else:
                time.sleep(0.05)
        self.tts_active.clear()

    def _run_thinking_sound_loop(self) -> None:
        time.sleep(0.5)
        while self.thinking_sound_active.is_set() and not self.exiting:
            sound = self.random_sound("thinking")
            if sound:
                self.play_sound(sound)
            for _ in range(50):
                if not self.thinking_sound_active.is_set() or self.exiting:
                    return
                time.sleep(0.1)

    def random_sound(self, sound_type: str) -> str | None:
        return self.sound_player.random_sound(SOUND_DIRECTORIES[sound_type])

    def play_sound(self, file_path: str | None) -> None:
        self.sound_player.play(file_path)
