"""Tkinter application coordinator for the Be More Agent."""

from __future__ import annotations

import atexit
import os
import random
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import ollama
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
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
from bmo.conversation import LoggedModelClient, ToolResultPresenter
from bmo.features.contracts import (
    FeatureMenuContext,
    RuntimeAttention,
    RuntimeAttentionDismissal,
    RuntimeAttentionEvent,
    RuntimeNotification,
    ToolAttachmentKind,
    ToolContext,
    ToolEvent,
    ToolResult,
    ToolStatusUpdate,
)
from bmo.intent import infer_tool_action
from bmo.memory import load_chat_history, save_chat_history
from bmo.menu_catalog import MenuSelectionRequest
from bmo.kiosk_access import KioskAccessPolicy, load_quiet_hours_config
from bmo.modes import (
    ModeRuntimeContext,
    load_mode_registry,
)
from bmo.prompts import build_system_prompt
from bmo.runtime_extensions import RuntimeExtensionCoordinator
from bmo.runtime_loop import (
    RuntimeTurnCoordinator,
    RuntimeTurnKind,
    RuntimeWorkerLoop,
)
from bmo.runtime_menu import RuntimeMenuCoordinator
from bmo.runtime_voice import RuntimeVoiceTurnExecutor
from bmo.speech import WakeWordDetector, WhisperTranscriber, extract_json_from_text
from bmo.state import BotStates
from bmo.tools import ToolRouter
from bmo.ui.compact_face import load_compact_face_config
from bmo.ui import (
    GestureKind,
    HorizontalSwipeRecognizer,
    IconMenuPage,
    MenuApp,
    QuietHoursOverlay,
)


@dataclass
class _SpeechQueueItem:
    """One queued utterance, optionally owned by a feature-menu scope."""

    text: str
    archive_path: Path | None
    scope: object | None = None
    on_complete: Callable[[], None] | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


class _ScopedInterrupt:
    """Present the Event interface while combining global and scoped stops."""

    def __init__(
        self,
        global_event: threading.Event,
        scoped_event: threading.Event,
    ) -> None:
        self.global_event = global_event
        self.scoped_event = scoped_event

    def is_set(self) -> bool:
        return self.global_event.is_set() or self.scoped_event.is_set()


class _FeatureMenuAnnouncer:
    """Narrow, cancellable access to BMO speech for one open feature view."""

    def __init__(self, gui: BotGUI) -> None:
        self.gui = gui
        self.scope = object()

    def _release_speaking_state(self) -> None:
        if getattr(self.gui, "_feature_speaking_scope", None) is not self.scope:
            return
        self.gui._feature_speaking_scope = None
        self.gui.set_state(BotStates.IDLE, "Ready")

    @property
    def available(self) -> bool:
        return (
            not getattr(self.gui, "exiting", True)
            and not self.gui._quiet_hours_locked()
            and hasattr(self.gui, "speaker")
            and hasattr(self.gui, "tts_queue_lock")
        )

    def speak(
        self,
        text: str,
        on_complete: Callable[[], None] | None = None,
    ) -> bool:
        if not self.available:
            return False

        def finished() -> None:
            self._release_speaking_state()
            if on_complete is not None:
                on_complete()

        self.gui._feature_speaking_scope = self.scope
        self.gui.set_state(BotStates.SPEAKING, "Speaking...")
        self.gui._enqueue_scoped_speech(
            text,
            scope=self.scope,
            on_complete=finished,
        )
        return True

    def cancel(self) -> None:
        if hasattr(self.gui, "tts_queue_lock"):
            self.gui._cancel_speech_scope(self.scope)
            self._release_speaking_state()


class BotGUI:
    """Own the UI and coordinate the application services."""

    BG_WIDTH, BG_HEIGHT = 800, 480
    OVERLAY_WIDTH, OVERLAY_HEIGHT = 400, 300
    INTERACTION_FAILURE_MESSAGE = "Something went wrong. Please try again."

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.runtime_attentions: dict[tuple[str, str], RuntimeAttention] = {}
        self.runtime_attentions_lock = threading.Lock()
        self.current_attention_frame: ImageTk.PhotoImage | None = None
        self._attention_overlay_cache: dict[Path, Image.Image] = {}
        self.config = load_config()
        self.compact_face_config = load_compact_face_config()
        self.kiosk_access = KioskAccessPolicy(
            load_quiet_hours_config(self.config["quiet_hours_config_path"])
        )
        self.quiet_hours_after_id: str | None = None
        self.quiet_hours_active = False
        self.text_model = str(self.config["text_model"])
        self.vision_model = str(self.config["vision_model"])
        self.tool_router = ToolRouter(
            self.config,
            runtime_callback=self._handle_runtime_notification,
            attention_callback=self._handle_runtime_attention,
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
        self.model_client = LoggedModelClient(
            ollama.chat,
            lambda: self.current_interaction,
        )

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
        self.face_gesture = HorizontalSwipeRecognizer()
        self.menu_ui: MenuApp | None = None

        self.permanent_memory = load_chat_history(MEMORY_FILE, self.system_prompt)
        self.session_memory: list[dict[str, str]] = []
        self.thinking_sound_active = threading.Event()
        self.tool_result_presenter = self._build_tool_result_presenter()

        self.last_ptt_time = 0.0
        self.ptt_event = threading.Event()
        self.recording_active = threading.Event()
        self.interrupted = threading.Event()

        self.tts_queue: list[_SpeechQueueItem] = []
        self.tts_queue_lock = threading.Lock()
        self.tts_thread: threading.Thread | None = None
        self.tts_active = threading.Event()
        self.active_tts_item: _SpeechQueueItem | None = None
        self._feature_speaking_scope: object | None = None
        self.exiting = False
        self.main_thread: threading.Thread | None = None
        mode_result = load_mode_registry(
            self.config,
            context=ModeRuntimeContext(
                master=self.master,
                text_model=self.text_model,
                chat=self._logged_chat,
                speak_response=self._speak_complete_response,
                remember_turn=self._remember_turn,
                wait_for_tts=self.wait_for_tts,
                set_state=self.set_state,
                announce=self.enqueue_speech,
                face_provider=self._current_mode_face,
                dispatch_ui=self._dispatch_ui,
            ),
            shared_settings={
                key: value
                for key, value in self.config.items()
                if key != "modes"
            },
        )
        self.mode_registry = mode_result.registry
        self.mode_failures = mode_result.failures
        self.mode_modules = mode_result.modules
        self.extension_runtime = RuntimeExtensionCoordinator(
            self.mode_registry,
            self.tool_router.registry,
            launch_feature=self._open_feature_menu,
        )
        self.runtime_menu = self.extension_runtime.menu
        self.menu_action_event = self.extension_runtime.wake_event
        self.runtime_turns = self._build_runtime_turn_coordinator()
        self.voice_turn_runtime = self._build_voice_turn_executor()
        atexit.register(self.safe_exit)

        self._build_gui()
        self._poll_quiet_hours()
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
        self._bind_face_gestures(self.background_label)

        self.overlay_label = tk.Label(self.master, bg="black")
        self._bind_face_gestures(self.overlay_label)

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
        self.attention_badge = tk.Label(
            self.master,
            bg="#b52335",
            fg="white",
            padx=10,
            pady=7,
            cursor="hand2",
            font=("Arial Rounded MT Bold", 13, "bold"),
        )
        self.attention_badge.bind(
            "<Button-1>",
            lambda _event: self._acknowledge_runtime_attention(),
        )
        self.quiet_hours_ui = QuietHoursOverlay(
            self.master,
            sleeping_face_directory=(
                self.kiosk_access.config.sleeping_face_directory
            ),
            unlock=self._unlock_quiet_hours,
        )
        self._refresh_runtime_attention_ui()

    def _dispatch_ui(self, callback: Callable[[], None]) -> None:
        """Queue immediate work on the active presentation event thread."""
        self.master.after(0, callback)

    def safe_exit(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        print("\n--- SHUTDOWN SEQUENCE ---", flush=True)

        menu_ui = getattr(self, "menu_ui", None)
        if menu_ui is not None:
            menu_ui.close()
        quiet_hours_after_id = getattr(self, "quiet_hours_after_id", None)
        if quiet_hours_after_id is not None:
            try:
                self.master.after_cancel(quiet_hours_after_id)
            except tk.TclError:
                pass
            self.quiet_hours_after_id = None
        quiet_hours_ui = getattr(self, "quiet_hours_ui", None)
        if quiet_hours_ui is not None:
            quiet_hours_ui.close()

        # Cooperative cancellation is critical on macOS. Never call the global
        # sounddevice.stop() while the wake-word thread owns an InputStream.
        self.shutdown_event.set()
        extension_runtime = getattr(self, "extension_runtime", None)
        if extension_runtime is not None:
            extension_runtime.close()
        else:
            self.tool_router.close()
            self.mode_registry.close()
        self.interrupted.set()
        self.ptt_event.set()
        self.recording_active.clear()
        self.thinking_sound_active.clear()
        with self.tts_queue_lock:
            for item in self.tts_queue:
                item.cancelled.set()
            self.tts_queue.clear()
            active_item = getattr(self, "active_tts_item", None)
            if active_item is not None:
                active_item.cancelled.set()
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

    def _bind_face_gestures(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._handle_face_press)
        widget.bind("<ButtonRelease-1>", self._handle_face_release)

    def _quiet_hours_locked(self) -> bool:
        policy = getattr(self, "kiosk_access", None)
        return policy is not None and policy.is_locked()

    def _poll_quiet_hours(self) -> None:
        if self.exiting:
            return
        locked = self._quiet_hours_locked()
        if locked:
            if not self.quiet_hours_active:
                self.quiet_hours_active = True
                self.menu_action_event.set()
                self.interrupted.set()
                self.thinking_sound_active.clear()
                with self.tts_queue_lock:
                    for item in self.tts_queue:
                        item.cancelled.set()
                    self.tts_queue.clear()
                    if self.active_tts_item is not None:
                        self.active_tts_item.cancelled.set()
                self.speaker.stop()
            self.quiet_hours_ui.show()
        else:
            if self.quiet_hours_active:
                self.quiet_hours_active = False
                self.interrupted.clear()
                self.set_state(BotStates.IDLE, "Ready")
            self.quiet_hours_ui.hide()
        self._refresh_runtime_attention_ui()
        self.quiet_hours_after_id = self.master.after(1000, self._poll_quiet_hours)

    def _unlock_quiet_hours(self, passcode: str) -> bool:
        unlocked = self.kiosk_access.unlock(passcode)
        if unlocked:
            self.quiet_hours_active = False
            self.interrupted.clear()
            self.quiet_hours_ui.hide()
            self.set_state(BotStates.IDLE, "Ready")
            self._refresh_runtime_attention_ui()
        return unlocked

    @staticmethod
    def _gesture_event_point(event: tk.Event) -> tuple[int, int]:
        return int(event.x_root), int(event.y_root)

    def _handle_face_press(self, event: tk.Event) -> str:
        self.face_gesture.press(*self._gesture_event_point(event))
        return "break"

    def _handle_face_release(self, event: tk.Event) -> str:
        gesture = self.face_gesture.release(*self._gesture_event_point(event))
        if gesture == GestureKind.SWIPE_LEFT:
            self.open_menu()
        elif gesture == GestureKind.TAP:
            self.toggle_hud_visibility()
        return "break"

    def open_menu(self) -> None:
        """Open the first menu page over the full-screen face."""
        if self.exiting or self.menu_ui is not None or self._quiet_hours_locked():
            return
        self._refresh_runtime_attention_ui()
        catalog = self._runtime_menu_coordinator().catalog()
        self.menu_ui = MenuApp(
            self.master,
            on_close=self._handle_menu_close,
            face_provider=self._current_mode_face,
            on_select=self._select_menu_item,
            pages=IconMenuPage.paginate(catalog.items),
        )
        self._refresh_runtime_attention_ui()

    def _handle_menu_close(self) -> None:
        self.menu_ui = None
        self._refresh_runtime_attention_ui()

    def _select_menu_item(self, selection: str) -> None:
        """Route a namespaced menu selection to its owning extension registry."""
        request = MenuSelectionRequest.parse(selection)
        self._runtime_menu_coordinator().dispatch(request)

    def _runtime_menu_coordinator(self) -> RuntimeMenuCoordinator:
        """Return the UI-neutral live catalog and selection owner."""
        coordinator = getattr(self, "runtime_menu", None)
        if coordinator is None:
            extension_runtime = RuntimeExtensionCoordinator(
                self.mode_registry,
                self.tool_router.registry,
                launch_feature=self._open_feature_menu,
            )
            self.extension_runtime = extension_runtime
            self.menu_action_event = extension_runtime.wake_event
            coordinator = extension_runtime.menu
            self.runtime_menu = coordinator
        return coordinator

    def _open_feature_menu(self, name: str) -> None:
        """Open one Tk-owned feature view selected by the runtime boundary."""

        menu_ui = self.menu_ui
        if menu_ui is None:
            return

        def finish_selection() -> None:
            announcer.cancel()
            if self.menu_ui is menu_ui:
                menu_ui.finish_selection()

        announcer = _FeatureMenuAnnouncer(self)

        self.tool_router.registry.open_menu_item(
            name,
            FeatureMenuContext(
                master=self.master,
                on_close=finish_selection,
                face_provider=self._current_mode_face,
                vision_requester=self._queue_menu_vision,
                announcer=announcer,
            ),
        )

    def _queue_menu_vision(
        self,
        image_path: Path,
        on_complete: Callable[[], None],
    ) -> None:
        """Wake the interaction worker for a feature-requested vision turn."""
        if self.exiting:
            try:
                self._dispatch_ui(on_complete)
            except tk.TclError:
                pass
            return
        self.extension_runtime.queue_vision(image_path, on_complete)

    def _start_pending_menu_mode(self) -> bool:
        """Start one queued menu mode on the normal interaction thread."""
        runtime = getattr(self, "extension_runtime", None)
        if runtime is None:
            return False
        menu_ui = getattr(self, "menu_ui", None)

        def finish_selection() -> None:
            if menu_ui is None:
                return
            try:
                self._dispatch_ui(menu_ui.finish_selection)
            except tk.TclError:
                pass

        return runtime.start_pending_mode(on_complete=finish_selection)

    def _start_pending_menu_vision(self) -> bool:
        """Run one queued menu image through the normal vision pipeline."""
        runtime = getattr(self, "extension_runtime", None)
        if runtime is None:
            return False
        request = runtime.take_pending_vision()
        if request is None:
            return False
        image_path = request.image_path
        on_complete = request.on_complete
        self._start_interaction("MENU_VISION")
        self.interrupted.clear()
        try:
            self.chat_and_respond(
                "What do you see in this image?",
                image_path=str(image_path),
            )
        except Exception as exc:
            self._finish_interaction("error", str(exc))
            raise
        else:
            self._finish_interaction("completed")
        finally:
            try:
                self._dispatch_ui(on_complete)
            except tk.TclError:
                pass
        return True

    def _start_pending_menu_action(self) -> bool:
        """Start the next generic feature or mode request from the touch menu."""
        if self._start_pending_menu_vision() or self._start_pending_menu_mode():
            return True
        runtime = getattr(self, "extension_runtime", None)
        if runtime is not None:
            runtime.clear_wake_if_idle()
        return False

    def handle_ptt_toggle(self, event: tk.Event | None = None) -> None:
        del event
        if self._quiet_hours_locked():
            return
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
            for item in self.tts_queue:
                item.cancelled.set()
            self.tts_queue.clear()
            active_item = getattr(self, "active_tts_item", None)
            if active_item is not None:
                active_item.cancelled.set()
        self.speaker.stop()
        self.set_state(BotStates.IDLE, "Interrupted.")

    def load_animations(self) -> None:
        for state in self.compact_face_config.states or ():
            self.animations[state] = []
            for image_path in self.compact_face_config.frame_paths(state):
                try:
                    with Image.open(image_path) as source:
                        image = source.convert("RGB").resize(
                            (self.BG_WIDTH, self.BG_HEIGHT),
                            Image.Resampling.LANCZOS,
                        )
                    self.animations[state].append(ImageTk.PhotoImage(image))
                except (OSError, ValueError, tk.TclError):
                    continue

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
        animation_attention = self._runtime_animation_attention()
        animation_state = (
            animation_attention.animation_state
            if animation_attention is not None
            else self.current_state
        )
        frames = self.animations.get(animation_state, []) or self.animations.get(
            BotStates.IDLE, []
        )
        if not frames:
            self.master.after(500, self.update_animation)
            return

        if animation_state == BotStates.SPEAKING:
            self.current_frame_index = (
                random.randint(1, len(frames) - 1) if len(frames) > 1 else 0
            )
        else:
            self.current_frame_index = (self.current_frame_index + 1) % len(frames)

        frame = frames[self.current_frame_index]
        if self._runtime_attention_is_visible():
            frame = self._compose_runtime_attention_frame(frame)
            self.current_attention_frame = frame
        else:
            self.current_attention_frame = None
        self.background_label.config(image=frame)
        self._refresh_runtime_attention_ui()
        speed = self.compact_face_config.state_duration(animation_state)
        self.master.after(speed, self.update_animation)

    def _runtime_animation_attention(self) -> RuntimeAttention | None:
        if self._quiet_hours_locked() or getattr(self, "menu_ui", None) is not None:
            return None
        with self.runtime_attentions_lock:
            candidates = tuple(
                attention
                for _key, attention in sorted(self.runtime_attentions.items())
                if attention.animation_state
            )
        return candidates[0] if candidates else None

    def _runtime_attention_is_visible(self) -> bool:
        if self._runtime_animation_attention() is not None:
            return False
        if self.current_state != BotStates.IDLE:
            return False
        if self._quiet_hours_locked():
            return False
        if getattr(self, "menu_ui", None) is not None:
            return False
        lock = getattr(self, "runtime_attentions_lock", None)
        if lock is None:
            return False
        with lock:
            return any(
                attention.animation_state is None
                for attention in self.runtime_attentions.values()
            )

    def _first_runtime_attention(self) -> RuntimeAttention | None:
        with self.runtime_attentions_lock:
            if not self.runtime_attentions:
                return None
            key = min(
                self.runtime_attentions,
                key=lambda item: (
                    self.runtime_attentions[item].animation_state is None,
                    item,
                ),
            )
            return self.runtime_attentions[key]

    def _compose_runtime_attention_frame(
        self,
        frame: ImageTk.PhotoImage,
    ) -> ImageTk.PhotoImage:
        """Overlay optional calendar art without replacing BMO's base face."""
        base = ImageTk.getimage(frame).convert("RGBA").resize(
            (self.BG_WIDTH, self.BG_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        attention = self._first_runtime_attention()
        if attention is None:
            return frame
        overlay = None
        overlay_path = attention.overlay_path
        if overlay_path is not None and overlay_path.is_file():
            try:
                overlay = self._attention_overlay_cache.get(overlay_path)
                if overlay is None:
                    with Image.open(overlay_path) as source:
                        overlay = source.convert("RGBA").resize(
                            (self.BG_WIDTH, self.BG_HEIGHT),
                            Image.Resampling.LANCZOS,
                        )
                    self._attention_overlay_cache[overlay_path] = overlay
            except (OSError, ValueError):
                overlay = None
        if overlay is not None:
            base.alpha_composite(overlay)
        else:
            draw = ImageDraw.Draw(base)
            colors = ("#ffd34d", "#e64f83", "#51d3c7", "#ff8c42")
            for index, x_value in enumerate(range(18, self.BG_WIDTH - 18, 32)):
                color = colors[index % len(colors)]
                draw.ellipse((x_value - 6, 7, x_value + 6, 19), fill=color)
                draw.ellipse(
                    (x_value - 6, self.BG_HEIGHT - 19, x_value + 6, self.BG_HEIGHT - 7),
                    fill=color,
                )
        return ImageTk.PhotoImage(base.convert("RGB"))

    def _handle_runtime_attention(self, event: RuntimeAttentionEvent) -> None:
        """Add or remove a persistent fullscreen-only attention badge."""
        if getattr(self, "exiting", False):
            return
        key = (event.source, event.attention_id)
        with self.runtime_attentions_lock:
            if isinstance(event, RuntimeAttention):
                self.runtime_attentions[key] = event
            elif isinstance(event, RuntimeAttentionDismissal):
                self.runtime_attentions.pop(key, None)
            else:
                raise TypeError("Unknown runtime attention event.")
        try:
            self._dispatch_ui(self._refresh_runtime_attention_ui)
        except tk.TclError:
            pass

    def _refresh_runtime_attention_ui(self) -> None:
        badge = getattr(self, "attention_badge", None)
        if badge is None:
            return
        with self.runtime_attentions_lock:
            count = len(self.runtime_attentions)
        # This root-owned widget is deliberately hidden whenever a menu or
        # feature view covers the fullscreen face; PIP faces never receive it.
        animation_attention = self._runtime_animation_attention()
        visible = (
            count > 0
            and getattr(self, "menu_ui", None) is None
            and (
                self.current_state == BotStates.IDLE
                or animation_attention is not None
            )
            and not self._quiet_hours_locked()
        )
        if visible:
            attention = self._first_runtime_attention()
            label = attention.badge_label if attention is not None else None
            badge.configure(text=f"{label or 'ITEMS'}  {count}")
            badge.place(x=640, y=14, width=145, height=44)
            badge.lift()
        else:
            badge.place_forget()

    def _acknowledge_runtime_attention(self) -> None:
        attention = self._first_runtime_attention()
        if attention is None:
            return
        try:
            acknowledged = attention.acknowledge()
        except Exception as exc:
            print(
                f"[FEATURE] Could not acknowledge {attention.attention_id}: {exc}",
                flush=True,
            )
            return
        if not acknowledged:
            return
        with self.runtime_attentions_lock:
            self.runtime_attentions.pop(
                (attention.source, attention.attention_id),
                None,
            )
        if not attention.announce_on_acknowledge:
            self.set_state(BotStates.IDLE, "Ready")
            self._refresh_runtime_attention_ui()
            return
        self.set_state(BotStates.SPEAKING, attention.message)
        self.append_to_text(f"BOT: {attention.message}")
        speech_path = (
            self.current_interaction.speech_path()
            if getattr(self, "current_interaction", None)
            else None
        )
        with self.tts_queue_lock:
            self.tts_queue.append(
                _SpeechQueueItem(
                    attention.message,
                    speech_path,
                    on_complete=lambda: self.set_state(BotStates.IDLE, "Ready"),
                )
            )
        self._refresh_runtime_attention_ui()

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

        self._dispatch_ui(update)

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

        self._dispatch_ui(update)

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
        if self._quiet_hours_locked():
            return
        self.set_state(BotStates.SPEAKING, notification.message)
        self.append_to_text(f"BOT: {notification.message}")
        speech_path = (
            self.current_interaction.speech_path()
            if self.current_interaction
            else None
        )
        with self.tts_queue_lock:
            self.tts_queue.append(
                _SpeechQueueItem(
                    notification.message,
                    speech_path,
                    on_complete=lambda: self.set_state(BotStates.IDLE, "Ready"),
                )
            )

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

        self._dispatch_ui(update)

    def safe_main_execution(self) -> None:
        self._run_runtime_worker(self._run_voice_interaction)

    def _run_runtime_worker(
        self,
        run_iteration: Callable[[], bool],
        *,
        after_initialize: Callable[[], None] | None = None,
    ) -> None:
        """Run one launcher adapter through the neutral resilient worker."""

        def initialize() -> None:
            self.warm_up_logic()
            self.tts_thread = threading.Thread(
                target=self._tts_worker,
                name="bmo-tts",
                daemon=True,
            )
            self.tts_thread.start()
            if after_initialize is not None:
                after_initialize()

        RuntimeWorkerLoop(
            initialize=initialize,
            run_iteration=run_iteration,
            recover_failure=self._recover_interaction_failure,
            handle_startup_failure=self._handle_worker_startup_failure,
            handle_shutdown_failure=self._handle_worker_shutdown_failure,
            is_exiting=lambda: self.exiting,
            shutdown_event=self.shutdown_event,
        ).run()

    def _handle_worker_startup_failure(self, exc: Exception) -> None:
        """Expose a startup failure without entering turn-level recovery."""
        if self.exiting:
            return
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        self.set_state(BotStates.ERROR, f"Fatal Error: {str(exc)[:40]}")

    def _handle_worker_shutdown_failure(self, exc: Exception) -> None:
        """Finish an interrupted archive when shutdown races active work."""
        self.thinking_sound_active.clear()
        self._finish_interaction("error", str(exc))

    def _build_runtime_turn_coordinator(self) -> RuntimeTurnCoordinator:
        """Bind the neutral voice-turn owner to current runtime adapters."""
        return RuntimeTurnCoordinator(
            shutdown_event=self.shutdown_event,
            interrupted_event=self.interrupted,
            is_exiting=lambda: self.exiting,
            quiet_hours_locked=self._quiet_hours_locked,
            start_pending_action=self._start_pending_menu_action,
            input_policy=self.mode_registry.input_policy,
            wait_for_wake_trigger=self.detect_wake_word_or_ptt,
            set_state=self.set_state,
        )

    def _runtime_turn_coordinator(self) -> RuntimeTurnCoordinator:
        """Return the voice-turn owner, constructing old test fixtures lazily."""
        coordinator = getattr(self, "runtime_turns", None)
        if coordinator is None:
            coordinator = self._build_runtime_turn_coordinator()
            self.runtime_turns = coordinator
        return coordinator

    def _build_voice_turn_executor(self) -> RuntimeVoiceTurnExecutor:
        """Bind capture and transcription services to the neutral turn owner."""
        return RuntimeVoiceTurnExecutor(
            recorder=self.recorder,
            transcriber=self.transcriber,
            recording_active_event=self.recording_active,
            shutdown_event=self.shutdown_event,
            interrupted_event=self.interrupted,
            start_interaction=self._start_interaction,
            current_archive=lambda: self.current_interaction,
            finish_interaction=self._finish_interaction,
            play_acknowledgement=lambda: self.play_sound(
                self.random_sound("ack")
            ),
            mode_is_active=self.mode_registry.is_active,
            set_state=self.set_state,
            present_transcript=lambda text: self.append_to_text(f"YOU: {text}"),
            chat=self.chat_and_respond,
        )

    def _voice_turn_executor(self) -> RuntimeVoiceTurnExecutor:
        """Return the voice executor, constructing old test fixtures lazily."""
        executor = getattr(self, "voice_turn_runtime", None)
        if executor is None:
            executor = self._build_voice_turn_executor()
            self.voice_turn_runtime = executor
        return executor

    def _run_voice_interaction(self) -> bool:
        """Run one voice-loop iteration, returning false when it should stop."""
        turn = self._runtime_turn_coordinator().next_turn()
        if turn.kind is RuntimeTurnKind.HANDLED:
            return True
        if turn.kind is RuntimeTurnKind.STOPPED:
            return False
        return self._voice_turn_executor().execute(turn)

    def _recover_interaction_failure(self, exc: Exception) -> None:
        """Report one failed turn and restore the loop to a usable state."""
        print(
            f"[INTERACTION] Unexpected failure: {type(exc).__name__}: {exc}",
            flush=True,
        )
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        self.thinking_sound_active.clear()
        self.interrupted.clear()
        try:
            self.set_state(BotStates.ERROR, "Something went wrong.")
            self._speak_complete_response(
                self.INTERACTION_FAILURE_MESSAGE,
                None,
            )
            self.wait_for_tts()
        except Exception as recovery_exc:
            print(
                "[INTERACTION] Could not present the failure message: "
                f"{type(recovery_exc).__name__}: {recovery_exc}",
                flush=True,
            )
            traceback.print_exception(
                type(recovery_exc),
                recovery_exc,
                recovery_exc.__traceback__,
            )
        finally:
            self.thinking_sound_active.clear()
            self._finish_interaction("error", str(exc))
            try:
                self.set_state(BotStates.IDLE, "Ready")
            except Exception as state_exc:
                print(
                    "[INTERACTION] Could not restore the idle state: "
                    f"{type(state_exc).__name__}: {state_exc}",
                    flush=True,
                )

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
        trigger = self.wake_word.wait_for_trigger(
            self.ptt_event,
            self.shutdown_event,
            alternate_event=self.menu_action_event,
        )
        return "MENU" if trigger == "ALTERNATE" else trigger

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
        return self.model_client(**kwargs)

    def _execute_tool(self, action_data: dict[str, Any]) -> ToolResult:
        action_name = self.tool_router.normalize_action(action_data)
        started = time.monotonic()
        try:
            result = self.tool_router.execute(
                action_data,
                context=self._tool_context(),
            )
        except Exception as exc:
            if self.current_interaction:
                self.current_interaction.append_json(
                    "output",
                    "tools.jsonl",
                    {
                        "action": action_name,
                        "request": action_data,
                        "error": str(exc),
                        "duration_seconds": time.monotonic() - started,
                    },
                )
            print(
                f"[FEATURE] Unexpected failure in '{action_name}': "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            raise
        if self.current_interaction:
            archive = result.archive
            self.current_interaction.append_json(
                archive.category,
                archive.filename,
                {
                    "action": action_name,
                    "request": action_data,
                    "result": result.archive_value(),
                    "details": archive.details,
                    "duration_seconds": time.monotonic() - started,
                },
            )
        return result

    def _tool_context(self) -> ToolContext:
        """Create the approved runtime-service view for one tool execution."""
        return ToolContext(
            artifact_allocator=self._allocate_tool_artifact,
            event_recorder=self._record_tool_event,
            status_requester=self._request_tool_status,
        )

    def _allocate_tool_artifact(
        self,
        kind: ToolAttachmentKind,
        suffix: str,
    ) -> Path:
        """Allocate an interaction artifact without exposing the archive."""
        if kind is not ToolAttachmentKind.IMAGE:
            raise ValueError(f"Unsupported tool artifact kind: {kind.value}")
        if self.current_interaction:
            return self.current_interaction.image_path(suffix)
        return BMO_IMAGE_FILE

    def _record_tool_event(self, event: ToolEvent) -> None:
        """Record a feature event without exposing archive internals."""
        if self.current_interaction:
            self.current_interaction.event(event.name, dict(event.data))

    def _request_tool_status(self, update: ToolStatusUpdate) -> None:
        """Forward a feature's generic status request to the UI owner."""
        self.set_state(update.state, update.message)

    def _archive_assistant_text(self, text: str) -> None:
        if not self.current_interaction:
            return
        self.current_interaction.append_text(
            "output", "assistant.txt", text
        )
        self.current_interaction.append_json(
            "output", "responses.jsonl", {"text": text}
        )

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
        except Exception:
            self.thinking_sound_active.clear()
            raise

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
        tool_result = self._execute_tool(action_data)
        self._process_tool_result(
            user_text,
            tool_result,
            image_path=None,
            model_to_use=self.text_model,
            direct=True,
        )
        if tool_result.follow_up is not None:
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

        tool_result = self._execute_tool(action_data)
        self._process_tool_result(
            text,
            tool_result,
            image_path=image_path,
            model_to_use=model_to_use,
            direct=False,
        )

    def _process_tool_result(
        self,
        user_text: str,
        tool_result: ToolResult,
        *,
        image_path: str | None,
        model_to_use: str,
        direct: bool,
    ) -> None:
        """Present one typed tool result, regardless of how it was routed."""
        presenter = getattr(self, "tool_result_presenter", None)
        if presenter is None:
            # Narrow tests and compatibility callers sometimes construct the
            # coordinator with __new__ instead of running application startup.
            presenter = self._build_tool_result_presenter()
        presenter.present(
            user_text,
            tool_result,
            image_path=image_path,
            model_to_use=model_to_use,
            direct=direct,
        )

    def _build_tool_result_presenter(self) -> ToolResultPresenter:
        """Build the UI-neutral typed-result presentation collaborator."""
        def set_thinking_active(active: bool) -> None:
            if active:
                self.thinking_sound_active.set()
            else:
                self.thinking_sound_active.clear()

        def request_vision_follow_up(user_text: str, path: str) -> None:
            self.chat_and_respond(user_text, image_path=path)

        return ToolResultPresenter(
            model_chat=self._logged_chat,
            model_options=OLLAMA_OPTIONS,
            set_state=self.set_state,
            set_thinking_active=set_thinking_active,
            speak_complete_response=self._speak_complete_response,
            remember_turn=self._remember_turn,
            request_vision_follow_up=request_vision_follow_up,
        )

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
        if self._quiet_hours_locked():
            return
        speech_path = (
            self.current_interaction.speech_path()
            if self.current_interaction
            else None
        )
        with self.tts_queue_lock:
            self.tts_queue.append(_SpeechQueueItem(text, speech_path))

    def _enqueue_scoped_speech(
        self,
        text: str,
        *,
        scope: object,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Replace pending speech owned by one feature-menu view."""
        if self._quiet_hours_locked():
            return
        speech_path = (
            self.current_interaction.speech_path()
            if self.current_interaction
            else None
        )
        with self.tts_queue_lock:
            retained: list[_SpeechQueueItem] = []
            for item in self.tts_queue:
                if item.scope is scope:
                    item.cancelled.set()
                else:
                    retained.append(item)
            self.tts_queue[:] = retained
            active_item = getattr(self, "active_tts_item", None)
            if active_item is not None and active_item.scope is scope:
                active_item.cancelled.set()
            self.tts_queue.append(
                _SpeechQueueItem(
                    text,
                    speech_path,
                    scope=scope,
                    on_complete=on_complete,
                )
            )

    def _cancel_speech_scope(self, scope: object) -> None:
        """Cancel only speech owned by the supplied feature-menu scope."""
        with self.tts_queue_lock:
            retained: list[_SpeechQueueItem] = []
            for item in self.tts_queue:
                if item.scope is scope:
                    item.cancelled.set()
                else:
                    retained.append(item)
            self.tts_queue[:] = retained
            active_item = getattr(self, "active_tts_item", None)
            if active_item is not None and active_item.scope is scope:
                active_item.cancelled.set()

    def wait_for_tts(self) -> None:
        while self.tts_queue or self.tts_active.is_set():
            if self.interrupted.is_set() or self.exiting:
                break
            time.sleep(0.1)

    def _tts_worker(self) -> None:
        while not self.exiting:
            queued_speech: _SpeechQueueItem | None = None
            with self.tts_queue_lock:
                if self.tts_queue:
                    queued_speech = self.tts_queue.pop(0)
                    if not queued_speech.cancelled.is_set():
                        self.active_tts_item = queued_speech
                        self.tts_active.set()
            if queued_speech:
                if not queued_speech.cancelled.is_set():
                    self.speaker.speak(
                        queued_speech.text,
                        _ScopedInterrupt(
                            self.interrupted,
                            queued_speech.cancelled,
                        ),
                        self.shutdown_event,
                        archive_path=queued_speech.archive_path,
                    )
                with self.tts_queue_lock:
                    if self.active_tts_item is queued_speech:
                        self.active_tts_item = None
                    self.tts_active.clear()
                if (
                    queued_speech.on_complete is not None
                    and not queued_speech.cancelled.is_set()
                    and not self.exiting
                ):
                    self._dispatch_ui(queued_speech.on_complete)
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
