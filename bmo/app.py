"""Tkinter application coordinator for the Be More Agent."""

from __future__ import annotations

import atexit
import os
import random
import re
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import ollama
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import ttk

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
from bmo.memory import load_chat_history, save_chat_history
from bmo.prompts import build_system_prompt
from bmo.speech import WakeWordDetector, WhisperTranscriber, extract_json_from_text
from bmo.state import BotStates
from bmo.tools import ToolRouter


class BotGUI:
    """Own the UI and coordinate the application services."""

    BG_WIDTH, BG_HEIGHT = 800, 480
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.config = load_config()
        self.text_model = str(self.config["text_model"])
        self.vision_model = str(self.config["vision_model"])
        self.system_prompt = build_system_prompt(self.config)
        self.shutdown_event = threading.Event()

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
        self.tool_router = ToolRouter()

        master.title("Pi Assistant")
        master.attributes("-fullscreen", True)
        master.bind("<Escape>", self.exit_fullscreen)
        master.bind("<Return>", self.handle_ptt_toggle)
        master.bind("<space>", self.handle_speaking_interrupt)
        master.protocol("WM_DELETE_WINDOW", self.safe_exit)
        atexit.register(self.safe_exit)

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

        self.tts_queue: list[str] = []
        self.tts_queue_lock = threading.Lock()
        self.tts_thread: threading.Thread | None = None
        self.tts_active = threading.Event()
        self.exiting = False
        self.main_thread: threading.Thread | None = None

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
                trigger_source = self.detect_wake_word_or_ptt()
                if self.exiting:
                    return
                if self.interrupted.is_set():
                    self.interrupted.clear()
                    self.set_state(BotStates.IDLE, "Resetting...")
                    continue

                self.set_state(BotStates.LISTENING, "I'm listening!")
                if trigger_source == "STOP" or self.shutdown_event.is_set():
                    return
                if trigger_source == "PTT":
                    audio_file = self.recorder.record_ptt(
                        self.recording_active,
                        shutdown_event=self.shutdown_event,
                    )
                else:
                    audio_file = self.recorder.record_adaptive(
                        shutdown_event=self.shutdown_event,
                    )

                if not audio_file:
                    self.set_state(BotStates.IDLE, "Heard nothing.")
                    continue

                self.play_sound(self.random_sound("ack"))
                user_text = self.transcriber.transcribe(audio_file)
                if not user_text:
                    self.set_state(BotStates.IDLE, "Transcription empty.")
                    continue

                self.append_to_text(f"YOU: {user_text}")
                self.interrupted.clear()
                self.chat_and_respond(user_text)
        except Exception as exc:
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

    def capture_image(self) -> str | None:
        self.set_state(BotStates.CAPTURING, "Watching...")
        try:
            subprocess.run(
                [
                    "rpicam-still",
                    "-t",
                    "500",
                    "-n",
                    "--width",
                    "640",
                    "--height",
                    "480",
                    "-o",
                    str(BMO_IMAGE_FILE),
                ],
                check=True,
                timeout=15,
            )
            rotation = int(self.config.get("camera_rotation", 0))
            if rotation:
                image = Image.open(BMO_IMAGE_FILE)
                image.rotate(rotation, expand=True).save(BMO_IMAGE_FILE)
            return str(BMO_IMAGE_FILE)
        except Exception as exc:
            print(f"Camera Error: {exc}", flush=True)
            return None

    def chat_and_respond(self, text: str, image_path: str | None = None) -> None:
        if image_path is None:
            direct_action = self.tool_router.match_direct_action(text)
            if direct_action:
                self._handle_direct_action(text, direct_action)
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
            self.enqueue_speech("Okay. Memory wiped.")
            self.set_state(BotStates.IDLE, "Memory Wiped")
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
            stream = ollama.chat(
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
                self.session_memory.append(
                    {"role": "user", "content": text}
                )
                self.session_memory.append(
                    {"role": "assistant", "content": full_response_buffer}
                )

            self.wait_for_tts()
            self.set_state(BotStates.IDLE, "Ready")
        except Exception as exc:
            print(f"LLM Error: {exc}", flush=True)
            self.set_state(BotStates.ERROR, "Brain Freeze!")

    def _handle_direct_action(
        self,
        user_text: str,
        action_data: dict[str, str],
    ) -> None:
        """Execute a clearly requested tool without asking the LLM to route it."""
        self.set_state(BotStates.THINKING, "Thinking...")
        action_name = self.tool_router.normalize_action(action_data)
        tool_result = self.tool_router.execute(action_data)

        if tool_result == "IMAGE_CAPTURE_TRIGGERED":
            image_path = self.capture_image()
            if image_path:
                self.chat_and_respond(user_text, image_path=image_path)
            else:
                fallback = "I could not use the camera right now."
                self._speak_complete_response(fallback, None)
                self._remember_turn(user_text, fallback)
            return

        fallbacks = {
            "INVALID_ACTION": "I am not sure how to do that.",
            "SEARCH_EMPTY": "I searched, but I couldn't find anything about that.",
            "SEARCH_ERROR": "I cannot reach the internet right now.",
        }
        if tool_result in fallbacks:
            response_text = fallbacks[tool_result]
        elif action_name == "search_web" and tool_result:
            self.set_state(BotStates.THINKING, "Reading...")
            summary_prompt = [
                {
                    "role": "system",
                    "content": (
                        "Answer the user's question in one or two short sentences "
                        "using only the supplied search result. Do not mention that "
                        "you are summarizing a result."
                    ),
                },
                {
                    "role": "user",
                    "content": f"RESULT: {tool_result}\nUser Question: {user_text}",
                },
            ]
            final_response = ollama.chat(
                model=self.text_model,
                messages=summary_prompt,
                stream=False,
                options=OLLAMA_OPTIONS,
            )
            response_text = final_response["message"]["content"].strip()
        else:
            response_text = tool_result or "I could not complete that request."

        self._speak_complete_response(response_text, None)
        self._remember_turn(user_text, response_text)
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
        tool_result = self.tool_router.execute(action_data)
        if action_name == "get_time" and tool_result:
            self._speak_complete_response(tool_result, image_path)
            self._remember_turn(text, tool_result)
            return
        if tool_result and tool_result.startswith("CHAT_FALLBACK::"):
            chat_text = tool_result.split("::", 1)[1]
            self._speak_complete_response(chat_text, image_path)
            self._remember_turn(text, chat_text)
            return

        if tool_result == "IMAGE_CAPTURE_TRIGGERED":
            new_image_path = self.capture_image()
            if new_image_path:
                self.chat_and_respond(text, image_path=new_image_path)
            return

        fallbacks = {
            "INVALID_ACTION": "I am not sure how to do that.",
            "SEARCH_EMPTY": "I searched, but I couldn't find any news about that.",
            "SEARCH_ERROR": "I cannot reach the internet right now.",
        }
        if tool_result in fallbacks:
            fallback_text = fallbacks[tool_result]
            self._speak_complete_response(fallback_text, image_path)
            self._remember_turn(text, fallback_text)
            return

        if not tool_result:
            return

        summary_prompt = [
            {
                "role": "system",
                "content": "Summarize this result in one short sentence.",
            },
            {
                "role": "user",
                "content": f"RESULT: {tool_result}\nUser Question: {text}",
            },
        ]
        self.set_state(BotStates.THINKING, "Reading...")
        self.thinking_sound_active.set()
        final_response = ollama.chat(
            model=model_to_use,
            messages=summary_prompt,
            stream=False,
            options=OLLAMA_OPTIONS,
        )
        final_text = final_response["message"]["content"]
        self._speak_complete_response(final_text, image_path)
        self._remember_turn(text, final_text)

    def _speak_complete_response(
        self,
        text: str,
        image_path: str | None,
    ) -> None:
        self.thinking_sound_active.clear()
        self.set_state(BotStates.SPEAKING, "Speaking...", image_path)
        self.append_to_text("BOT: ", newline=False)
        self.append_to_text(text, newline=True)
        self.enqueue_speech(text)

    def _remember_turn(self, user_text: str, assistant_text: str) -> None:
        self.session_memory.append({"role": "user", "content": user_text})
        self.session_memory.append(
            {"role": "assistant", "content": assistant_text}
        )

    def enqueue_speech(self, text: str) -> None:
        with self.tts_queue_lock:
            self.tts_queue.append(text)

    def wait_for_tts(self) -> None:
        while self.tts_queue or self.tts_active.is_set():
            if self.interrupted.is_set() or self.exiting:
                break
            time.sleep(0.1)

    def _tts_worker(self) -> None:
        while not self.exiting:
            text = None
            with self.tts_queue_lock:
                if self.tts_queue:
                    text = self.tts_queue.pop(0)
                    self.tts_active.set()
            if text:
                self.speaker.speak(
                    text,
                    self.interrupted,
                    self.shutdown_event,
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
