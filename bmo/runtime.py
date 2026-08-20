"""Toolkit-neutral production assistant runtime."""

from __future__ import annotations

import re
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import ollama

from bmo.archive import InteractionArchive, InteractionArchiveManager
from bmo.audio import AudioRecorder, PiperSpeaker, SoundPlayer, describe_input_device, resolve_input_device
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
from bmo.kiosk_access import KioskAccessPolicy, load_quiet_hours_config
from bmo.memory import load_chat_history, save_chat_history
from bmo.modes import ModeRuntimeContext, load_mode_registry
from bmo.prompts import build_system_prompt
from bmo.runtime_extensions import RuntimeExtensionCoordinator
from bmo.runtime_loop import RuntimeTurnCoordinator, RuntimeTurnKind, RuntimeWorkerLoop
from bmo.runtime_voice import RuntimeVoiceTurnExecutor
from bmo.speech import WakeWordDetector, WhisperTranscriber, extract_json_from_text
from bmo.state import BotStates
from bmo.tools import ToolRouter


class RuntimePresentation(Protocol):
    """Small UI port consumed by the assistant runtime."""

    def call_soon(self, callback: Callable[[], None]) -> None: ...

    def set_state(self, state: str, status: str = "", overlay_path: str | None = None) -> None: ...

    def append_response(self, text: str, *, newline: bool = True) -> None: ...

    def attention_changed(self, attentions: tuple[RuntimeAttention, ...]) -> None: ...

    def quiet_hours_changed(self, locked: bool) -> None: ...


@dataclass
class _SpeechQueueItem:
    text: str
    archive_path: Path | None
    scope: object | None = None
    on_complete: Callable[[], None] | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


class _ScopedInterrupt:
    def __init__(self, global_event: threading.Event, scoped_event: threading.Event) -> None:
        self.global_event = global_event
        self.scoped_event = scoped_event

    def is_set(self) -> bool:
        return self.global_event.is_set() or self.scoped_event.is_set()


class _FeatureAnnouncer:
    def __init__(self, runtime: "AssistantRuntime") -> None:
        self.runtime = runtime
        self.scope = object()

    @property
    def available(self) -> bool:
        return not self.runtime.exiting and not self.runtime.quiet_hours_locked()

    def speak(self, text: str, on_complete: Callable[[], None] | None = None) -> bool:
        if not self.available:
            return False

        def finished() -> None:
            self.runtime.set_state(BotStates.IDLE, "Ready")
            if on_complete is not None:
                on_complete()

        self.runtime.set_state(BotStates.SPEAKING, "Speaking...")
        self.runtime._enqueue_scoped_speech(text, scope=self.scope, on_complete=finished)
        return True

    def cancel(self) -> None:
        self.runtime._cancel_speech_scope(self.scope)


class AssistantRuntime:
    """Own assistant services while delegating all rendering to a UI port."""

    INTERACTION_FAILURE_MESSAGE = "Something went wrong. Please try again."

    def __init__(self, presentation: RuntimePresentation, view_host: Any) -> None:
        self.presentation = presentation
        self.view_host = view_host
        self.config = load_config()
        self.kiosk_access = KioskAccessPolicy(
            load_quiet_hours_config(self.config["quiet_hours_config_path"])
        )
        self.text_model = str(self.config["text_model"])
        self.vision_model = str(self.config["vision_model"])
        self.current_state = BotStates.WARMUP
        self.current_status = "Initializing..."
        self.runtime_attentions: dict[tuple[str, str], RuntimeAttention] = {}
        self.runtime_attentions_lock = threading.Lock()
        self.tool_router = ToolRouter(
            self.config,
            runtime_callback=self._handle_runtime_notification,
            attention_callback=self._handle_runtime_attention,
        )
        self.system_prompt = build_system_prompt(self.config, self.tool_router.registry)
        self.shutdown_event = threading.Event()
        self.archive_manager = InteractionArchiveManager(
            self.config.get("interaction_log_directory", "interaction_logs"),
            enabled=bool(self.config.get("interaction_logging", True)),
        )
        self.current_interaction: InteractionArchive | None = None
        self.model_client = LoggedModelClient(ollama.chat, lambda: self.current_interaction)

        input_device = resolve_input_device(self.config)
        describe_input_device(input_device)
        preferred_rate = self.config.get("input_sample_rate")
        self.sound_player = SoundPlayer()
        self.recorder = AudioRecorder(input_device, preferred_rate)
        self.transcriber = WhisperTranscriber(
            self.config["whisper_binary"], self.config["whisper_model"]
        )
        self.wake_word = WakeWordDetector(
            WAKE_WORD_MODEL,
            WAKE_WORD_THRESHOLD,
            input_device,
            preferred_rate,
        )
        self.speaker = PiperSpeaker(str(self.config["voice_model"]))

        self.permanent_memory = load_chat_history(MEMORY_FILE, self.system_prompt)
        self.session_memory: list[dict[str, str]] = []
        self.thinking_sound_active = threading.Event()
        self.last_ptt_time = 0.0
        self.ptt_event = threading.Event()
        self.recording_active = threading.Event()
        self.interrupted = threading.Event()
        self.tts_queue: list[_SpeechQueueItem] = []
        self.tts_queue_lock = threading.Lock()
        self.tts_thread: threading.Thread | None = None
        self.tts_active = threading.Event()
        self.active_tts_item: _SpeechQueueItem | None = None
        self.exiting = False
        self._quiet_hours_active = False
        self._typed_requests: queue.Queue[str] = queue.Queue()
        self.main_thread: threading.Thread | None = None

        mode_result = load_mode_registry(
            self.config,
            context=ModeRuntimeContext(
                master=self.view_host,
                text_model=self.text_model,
                chat=self._logged_chat,
                speak_response=self._speak_complete_response,
                remember_turn=self._remember_turn,
                wait_for_tts=self.wait_for_tts,
                set_state=self.set_state,
                announce=self.enqueue_speech,
                face_provider=lambda: None,
                dispatch_ui=self.presentation.call_soon,
            ),
            shared_settings={key: value for key, value in self.config.items() if key != "modes"},
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
        self.tool_result_presenter = self._build_tool_result_presenter()

    @property
    def menu_catalog(self) -> Any:
        return self.extension_runtime.catalog()

    def start(self) -> None:
        if self.main_thread is not None:
            return
        self.main_thread = threading.Thread(
            target=self._run_runtime_worker,
            name="bmo-main-loop",
            daemon=True,
        )
        self.main_thread.start()

    def quiet_hours_locked(self) -> bool:
        return self.kiosk_access.is_locked()

    def check_quiet_hours(self) -> bool:
        """Apply the current global kiosk lock and return its state."""
        locked = self.quiet_hours_locked()
        if locked and not self._quiet_hours_active:
            self._quiet_hours_active = True
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
        elif not locked and self._quiet_hours_active:
            self._quiet_hours_active = False
            self.interrupted.clear()
            self.set_state(BotStates.IDLE, "Ready")
        self.presentation.quiet_hours_changed(locked)
        return locked

    def unlock_quiet_hours(self, passcode: str) -> bool:
        unlocked = self.kiosk_access.unlock(str(passcode))
        if unlocked:
            self._quiet_hours_active = False
            self.interrupted.clear()
            self.presentation.quiet_hours_changed(False)
            self.set_state(BotStates.IDLE, "Ready")
        return unlocked

    def dispatch_menu(self, request: Any) -> None:
        self.extension_runtime.dispatch_menu(request)

    def submit_text(self, text: str) -> None:
        """Queue one typed-debug turn through the normal interaction worker."""
        value = str(text).strip()
        if not value or self.exiting:
            return
        self._typed_requests.put(value)
        self.menu_action_event.set()

    def _open_feature_menu(self, name: str) -> None:
        announcer = _FeatureAnnouncer(self)

        def finish() -> None:
            announcer.cancel()

        self.tool_router.registry.open_menu_item(
            name,
            FeatureMenuContext(
                master=self.view_host,
                on_close=finish,
                face_provider=lambda: None,
                vision_requester=self._queue_menu_vision,
                announcer=announcer,
            ),
        )

    def _queue_menu_vision(self, image_path: Path, on_complete: Callable[[], None]) -> None:
        if self.exiting:
            self.presentation.call_soon(on_complete)
            return
        self.extension_runtime.queue_vision(image_path, on_complete)

    def _start_pending_menu_mode(self) -> bool:
        return self.extension_runtime.start_pending_mode()

    def _start_pending_menu_vision(self) -> bool:
        request = self.extension_runtime.take_pending_vision()
        if request is None:
            return False
        self._start_interaction("MENU_VISION")
        self.interrupted.clear()
        try:
            self.chat_and_respond("What do you see in this image?", image_path=str(request.image_path))
        except Exception as exc:
            self._finish_interaction("error", str(exc))
            raise
        else:
            self._finish_interaction("completed")
        finally:
            self.presentation.call_soon(request.on_complete)
        return True

    def _start_pending_menu_action(self) -> bool:
        if (
            self._start_pending_typed()
            or self._start_pending_menu_vision()
            or self._start_pending_menu_mode()
        ):
            return True
        self.extension_runtime.clear_wake_if_idle()
        return False

    def _start_pending_typed(self) -> bool:
        try:
            text = self._typed_requests.get_nowait()
        except queue.Empty:
            return False
        if self._typed_requests.empty():
            self.extension_runtime.clear_wake_if_idle()
        self._start_interaction("TYPED")
        if self.current_interaction:
            self.current_interaction.write_text("input", "transcript.txt", text + "\n")
            self.current_interaction.event("typed_input_received", {"text": text})
        self.append_to_text(f"YOU: {text}")
        self.interrupted.clear()
        try:
            self.chat_and_respond(text)
        except Exception as exc:
            self._finish_interaction("error", str(exc))
            raise
        else:
            self._finish_interaction("completed")
        return True

    def toggle_ptt(self) -> None:
        if self.quiet_hours_locked():
            return
        now = time.time()
        if now - self.last_ptt_time < 0.5:
            return
        self.last_ptt_time = now
        if self.recording_active.is_set():
            print("[PTT] Toggle OFF", flush=True)
            self.recording_active.clear()
        elif self.current_state == BotStates.IDLE or "Wait" in self.current_status:
            print("[PTT] Toggle ON", flush=True)
            self.recording_active.set()
            self.ptt_event.set()

    def interrupt(self) -> None:
        if self.current_state not in (BotStates.SPEAKING, BotStates.THINKING):
            return
        self.interrupted.set()
        self.thinking_sound_active.clear()
        with self.tts_queue_lock:
            for item in self.tts_queue:
                item.cancelled.set()
            self.tts_queue.clear()
            if self.active_tts_item is not None:
                self.active_tts_item.cancelled.set()
        self.speaker.stop()
        self.set_state(BotStates.IDLE, "Interrupted.")

    def set_state(self, state: str, message: str = "", camera_path: str | None = None) -> None:
        if self.exiting:
            return
        if message:
            print(f"[STATE] {state.upper()}: {message}", flush=True)
        self.current_state = state
        if message:
            self.current_status = message
        self.presentation.set_state(state, message, camera_path)

    def append_to_text(self, text: str, newline: bool = True) -> None:
        if not self.exiting:
            self.presentation.append_response(text, newline=newline)

    def _stream_to_text(self, chunk: str) -> None:
        self.append_to_text(chunk, newline=False)

    def _run_runtime_worker(self) -> None:
        def initialize() -> None:
            self.warm_up_logic()
            self.tts_thread = threading.Thread(
                target=self._tts_worker,
                name="bmo-tts",
                daemon=True,
            )
            self.tts_thread.start()

        RuntimeWorkerLoop(
            initialize=initialize,
            run_iteration=self._run_voice_interaction,
            recover_failure=self._recover_interaction_failure,
            handle_startup_failure=self._handle_worker_startup_failure,
            handle_shutdown_failure=self._handle_worker_shutdown_failure,
            is_exiting=lambda: self.exiting,
            shutdown_event=self.shutdown_event,
        ).run()

    def _handle_worker_startup_failure(self, exc: Exception) -> None:
        if self.exiting:
            return
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        self.set_state(BotStates.ERROR, f"Fatal Error: {str(exc)[:40]}")

    def _handle_worker_shutdown_failure(self, exc: Exception) -> None:
        self.thinking_sound_active.clear()
        self._finish_interaction("error", str(exc))

    def _build_runtime_turn_coordinator(self) -> RuntimeTurnCoordinator:
        return RuntimeTurnCoordinator(
            shutdown_event=self.shutdown_event,
            interrupted_event=self.interrupted,
            is_exiting=lambda: self.exiting,
            quiet_hours_locked=self.quiet_hours_locked,
            start_pending_action=self._start_pending_menu_action,
            input_policy=self.mode_registry.input_policy,
            wait_for_wake_trigger=self.detect_wake_word_or_ptt,
            set_state=self.set_state,
        )

    def _build_voice_turn_executor(self) -> RuntimeVoiceTurnExecutor:
        return RuntimeVoiceTurnExecutor(
            recorder=self.recorder,
            transcriber=self.transcriber,
            recording_active_event=self.recording_active,
            shutdown_event=self.shutdown_event,
            interrupted_event=self.interrupted,
            start_interaction=self._start_interaction,
            current_archive=lambda: self.current_interaction,
            finish_interaction=self._finish_interaction,
            play_acknowledgement=lambda: self.play_sound(self.random_sound("ack")),
            mode_is_active=self.mode_registry.is_active,
            set_state=self.set_state,
            present_transcript=lambda text: self.append_to_text(f"YOU: {text}"),
            chat=self.chat_and_respond,
        )

    def _run_voice_interaction(self) -> bool:
        turn = self.runtime_turns.next_turn()
        if turn.kind is RuntimeTurnKind.HANDLED:
            return True
        if turn.kind is RuntimeTurnKind.STOPPED:
            return False
        return self.voice_turn_runtime.execute(turn)

    def _recover_interaction_failure(self, exc: Exception) -> None:
        print(f"[INTERACTION] Unexpected failure: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        self.thinking_sound_active.clear()
        self.interrupted.clear()
        try:
            self.set_state(BotStates.ERROR, "Something went wrong.")
            self._speak_complete_response(self.INTERACTION_FAILURE_MESSAGE, None)
            self.wait_for_tts()
        except Exception as recovery_exc:
            print(
                f"[INTERACTION] Could not present failure: {type(recovery_exc).__name__}: {recovery_exc}",
                flush=True,
            )
        finally:
            self._finish_interaction("error", str(exc))
            self.set_state(BotStates.IDLE, "Ready")

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
        try:
            self.current_interaction = self.archive_manager.begin(trigger)
            if self.current_interaction:
                print(f"[ARCHIVE] {self.current_interaction.path}", flush=True)
        except OSError as exc:
            self.current_interaction = None
            print(f"[ARCHIVE] Could not start interaction log: {exc}", flush=True)

    def _finish_interaction(self, status: str, error: str | None = None) -> None:
        interaction = self.current_interaction
        self.current_interaction = None
        if interaction is None:
            return
        try:
            interaction.finish(status, error)
        except OSError as exc:
            print(f"[ARCHIVE] Could not finish interaction log: {exc}", flush=True)

    def _logged_chat(self, **kwargs: Any) -> Any:
        return self.model_client(**kwargs)

    def _execute_tool(self, action_data: dict[str, Any]) -> ToolResult:
        action_name = self.tool_router.normalize_action(action_data)
        started = time.monotonic()
        try:
            result = self.tool_router.execute(action_data, context=self._tool_context())
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
                f"[FEATURE] Unexpected failure in '{action_name}': {type(exc).__name__}: {exc}",
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
        return ToolContext(
            artifact_allocator=self._allocate_tool_artifact,
            event_recorder=self._record_tool_event,
            status_requester=self._request_tool_status,
        )

    def _allocate_tool_artifact(self, kind: ToolAttachmentKind, suffix: str) -> Path:
        if kind is not ToolAttachmentKind.IMAGE:
            raise ValueError(f"Unsupported tool artifact kind: {kind.value}")
        if self.current_interaction:
            return self.current_interaction.image_path(suffix)
        return BMO_IMAGE_FILE

    def _record_tool_event(self, event: ToolEvent) -> None:
        if self.current_interaction:
            self.current_interaction.event(event.name, dict(event.data))

    def _request_tool_status(self, update: ToolStatusUpdate) -> None:
        self.set_state(update.state, update.message)

    def _archive_assistant_text(self, text: str) -> None:
        if self.current_interaction:
            self.current_interaction.append_text("output", "assistant.txt", text)
            self.current_interaction.append_json("output", "responses.jsonl", {"text": text})

    def chat_and_respond(self, text: str, image_path: str | None = None) -> None:
        if image_path is None and self.mode_registry.route_input(text):
            return
        if "forget everything" in text.lower() or "reset memory" in text.lower():
            self.session_memory = []
            self.permanent_memory = [{"role": "system", "content": self.system_prompt}]
            save_chat_history(MEMORY_FILE, self.permanent_memory, self.session_memory)
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
                    print(f"[ROUTER] Local model inferred: {action_data or 'chat'}", flush=True)
                except Exception as exc:
                    print(f"[ROUTER] Local intent lookup failed: {exc}", flush=True)
            if action_data:
                if self.current_interaction:
                    self.current_interaction.append_json(
                        "output", "routing.jsonl", {"user_text": text, "decision": action_data}
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
            messages = self.permanent_memory + self.session_memory + [
                {"role": "user", "content": text}
            ]
        self.thinking_sound_active.set()
        threading.Thread(target=self._run_thinking_sound_loop, daemon=True).start()
        full_response = ""
        sentence = ""
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
                full_response += content
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
                sentence += content
                if any(mark in content for mark in ".!?\n"):
                    clean = sentence.strip()
                    if clean and re.search(r"[a-zA-Z0-9]", clean):
                        self.enqueue_speech(clean)
                    sentence = ""
            if action_mode:
                self._handle_action_response(text, image_path, model_to_use, full_response)
            else:
                remaining = sentence.strip()
                if remaining and re.search(r"[a-zA-Z0-9]", remaining):
                    self.enqueue_speech(remaining)
                self.append_to_text("")
                self._archive_assistant_text(full_response)
                self._remember_turn(text, full_response)
            self.wait_for_tts()
            self.set_state(BotStates.IDLE, "Ready")
        except Exception:
            self.thinking_sound_active.clear()
            raise

    def _handle_direct_action(self, user_text: str, action_data: dict[str, str]) -> None:
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
        self._process_tool_result(
            text,
            self._execute_tool(action_data),
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
        self.tool_result_presenter.present(
            user_text,
            tool_result,
            image_path=image_path,
            model_to_use=model_to_use,
            direct=direct,
        )

    def _build_tool_result_presenter(self) -> ToolResultPresenter:
        def set_thinking_active(active: bool) -> None:
            if active:
                self.thinking_sound_active.set()
            else:
                self.thinking_sound_active.clear()

        return ToolResultPresenter(
            model_chat=self._logged_chat,
            model_options=OLLAMA_OPTIONS,
            set_state=self.set_state,
            set_thinking_active=set_thinking_active,
            speak_complete_response=self._speak_complete_response,
            remember_turn=self._remember_turn,
            request_vision_follow_up=lambda text, path: self.chat_and_respond(
                text, image_path=path
            ),
        )

    def _speak_complete_response(self, text: str, image_path: str | None) -> None:
        self.thinking_sound_active.clear()
        self.set_state(BotStates.SPEAKING, "Speaking...", image_path)
        self.append_to_text("BOT: ", newline=False)
        self.append_to_text(text)
        self._archive_assistant_text(text)
        self.enqueue_speech(text)

    def _remember_turn(self, user_text: str, assistant_text: str) -> None:
        self.session_memory.extend(
            (
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            )
        )

    def enqueue_speech(self, text: str) -> None:
        if self.quiet_hours_locked():
            return
        path = self.current_interaction.speech_path() if self.current_interaction else None
        with self.tts_queue_lock:
            self.tts_queue.append(_SpeechQueueItem(text, path))

    def _enqueue_scoped_speech(
        self,
        text: str,
        *,
        scope: object,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        if self.quiet_hours_locked():
            return
        path = self.current_interaction.speech_path() if self.current_interaction else None
        with self.tts_queue_lock:
            retained: list[_SpeechQueueItem] = []
            for item in self.tts_queue:
                if item.scope is scope:
                    item.cancelled.set()
                else:
                    retained.append(item)
            self.tts_queue[:] = retained
            if self.active_tts_item is not None and self.active_tts_item.scope is scope:
                self.active_tts_item.cancelled.set()
            self.tts_queue.append(
                _SpeechQueueItem(text, path, scope=scope, on_complete=on_complete)
            )

    def _cancel_speech_scope(self, scope: object) -> None:
        with self.tts_queue_lock:
            retained: list[_SpeechQueueItem] = []
            for item in self.tts_queue:
                if item.scope is scope:
                    item.cancelled.set()
                else:
                    retained.append(item)
            self.tts_queue[:] = retained
            if self.active_tts_item is not None and self.active_tts_item.scope is scope:
                self.active_tts_item.cancelled.set()

    def wait_for_tts(self) -> None:
        while self.tts_queue or self.tts_active.is_set():
            if self.interrupted.is_set() or self.exiting:
                break
            time.sleep(0.1)

    def _tts_worker(self) -> None:
        while not self.exiting:
            item: _SpeechQueueItem | None = None
            with self.tts_queue_lock:
                if self.tts_queue:
                    item = self.tts_queue.pop(0)
                    if not item.cancelled.is_set():
                        self.active_tts_item = item
                        self.tts_active.set()
            if item is None:
                time.sleep(0.05)
                continue
            if not item.cancelled.is_set():
                self.speaker.speak(
                    item.text,
                    _ScopedInterrupt(self.interrupted, item.cancelled),
                    self.shutdown_event,
                    archive_path=item.archive_path,
                )
            with self.tts_queue_lock:
                if self.active_tts_item is item:
                    self.active_tts_item = None
                self.tts_active.clear()
            if item.on_complete is not None and not item.cancelled.is_set() and not self.exiting:
                self.presentation.call_soon(item.on_complete)
        self.tts_active.clear()

    def _run_thinking_sound_loop(self) -> None:
        time.sleep(0.5)
        while self.thinking_sound_active.is_set() and not self.exiting:
            self.play_sound(self.random_sound("thinking"))
            for _ in range(50):
                if not self.thinking_sound_active.is_set() or self.exiting:
                    return
                time.sleep(0.1)

    def random_sound(self, sound_type: str) -> str | None:
        return self.sound_player.random_sound(SOUND_DIRECTORIES[sound_type])

    def play_sound(self, file_path: str | None) -> None:
        self.sound_player.play(file_path)

    def _handle_runtime_notification(self, notification: RuntimeNotification) -> None:
        if self.exiting:
            return
        print(f"[FEATURE] {notification.source}: {notification.message}", flush=True)
        if self.quiet_hours_locked():
            return
        self.set_state(BotStates.SPEAKING, notification.message)
        self.append_to_text(f"BOT: {notification.message}")
        path = self.current_interaction.speech_path() if self.current_interaction else None
        with self.tts_queue_lock:
            self.tts_queue.append(
                _SpeechQueueItem(
                    notification.message,
                    path,
                    on_complete=lambda: self.set_state(BotStates.IDLE, "Ready"),
                )
            )

    def _handle_runtime_attention(self, event: RuntimeAttentionEvent) -> None:
        if self.exiting:
            return
        key = (event.source, event.attention_id)
        with self.runtime_attentions_lock:
            if isinstance(event, RuntimeAttention):
                self.runtime_attentions[key] = event
            elif isinstance(event, RuntimeAttentionDismissal):
                self.runtime_attentions.pop(key, None)
            else:
                raise TypeError("Unknown runtime attention event.")
            current = tuple(self.runtime_attentions.values())
        self.presentation.attention_changed(current)

    def acknowledge_attention(self) -> None:
        with self.runtime_attentions_lock:
            attention = next(iter(self.runtime_attentions.values()), None)
        if attention is None or not attention.acknowledge():
            return
        with self.runtime_attentions_lock:
            self.runtime_attentions.pop((attention.source, attention.attention_id), None)
            current = tuple(self.runtime_attentions.values())
        self.presentation.attention_changed(current)
        if attention.announce_on_acknowledge:
            self._speak_complete_response(attention.message, None)

    def close(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        print("\n--- SHUTDOWN SEQUENCE ---", flush=True)
        self.shutdown_event.set()
        self.extension_runtime.close()
        self.interrupted.set()
        self.ptt_event.set()
        self.recording_active.clear()
        self.thinking_sound_active.clear()
        with self.tts_queue_lock:
            for item in self.tts_queue:
                item.cancelled.set()
            self.tts_queue.clear()
            if self.active_tts_item is not None:
                self.active_tts_item.cancelled.set()
        self.speaker.stop()
        current_thread = threading.current_thread()
        if self.main_thread and self.main_thread is not current_thread:
            self.main_thread.join(timeout=3.0)
        if self.tts_thread and self.tts_thread is not current_thread:
            self.tts_thread.join(timeout=2.0)
        try:
            save_chat_history(MEMORY_FILE, self.permanent_memory, self.session_memory)
        except OSError as exc:
            print(f"Memory save error: {exc}", flush=True)
        try:
            ollama.generate(model=self.text_model, prompt="", keep_alive=0)
        except Exception:
            pass


__all__ = ["AssistantRuntime", "RuntimePresentation"]
