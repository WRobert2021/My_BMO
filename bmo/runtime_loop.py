"""UI-neutral assistant worker loop and voice-turn arbitration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import threading

from bmo.modes.contracts import InputPolicy, InputPolicyKind
from bmo.state import BotStates


Initialize = Callable[[], None]
RunIteration = Callable[[], bool]
HandleFailure = Callable[[Exception], None]
IsExiting = Callable[[], bool]
InputPolicyProvider = Callable[[], InputPolicy]
SetState = Callable[[str, str], None]


class RuntimeWorkerLoop:
    """Run resilient assistant iterations without owning a UI event loop."""

    def __init__(
        self,
        *,
        initialize: Initialize,
        run_iteration: RunIteration,
        recover_failure: HandleFailure,
        handle_startup_failure: HandleFailure,
        handle_shutdown_failure: HandleFailure,
        is_exiting: IsExiting,
        shutdown_event: threading.Event,
    ) -> None:
        callbacks = {
            "initialize": initialize,
            "run_iteration": run_iteration,
            "recover_failure": recover_failure,
            "handle_startup_failure": handle_startup_failure,
            "handle_shutdown_failure": handle_shutdown_failure,
            "is_exiting": is_exiting,
        }
        for name, callback in callbacks.items():
            if not callable(callback):
                raise TypeError(f"Runtime worker {name} must be callable.")
        if not isinstance(shutdown_event, threading.Event):
            raise TypeError("Runtime worker shutdown_event must be an Event.")

        self._initialize = initialize
        self._run_iteration = run_iteration
        self._recover_failure = recover_failure
        self._handle_startup_failure = handle_startup_failure
        self._handle_shutdown_failure = handle_shutdown_failure
        self._is_exiting = is_exiting
        self._shutdown_event = shutdown_event

    def run(self) -> None:
        """Initialize once, then isolate failures to their interaction turn."""
        try:
            self._initialize()
        except Exception as exc:
            self._handle_startup_failure(exc)
            return

        while not self._is_exiting() and not self._shutdown_event.is_set():
            try:
                if not self._run_iteration():
                    return
            except Exception as exc:
                if self._is_exiting() or self._shutdown_event.is_set():
                    self._handle_shutdown_failure(exc)
                    return
                self._recover_failure(exc)


class RuntimeTurnKind(str, Enum):
    """Result of preparing the next assistant worker turn."""

    READY = "ready"
    HANDLED = "handled"
    STOPPED = "stopped"


@dataclass(frozen=True)
class RuntimeTurn:
    """A voice turn ready for capture, or work handled without capture."""

    kind: RuntimeTurnKind
    input_policy: InputPolicy | None = None
    trigger_source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RuntimeTurnKind):
            raise TypeError("Runtime turn kind must be a RuntimeTurnKind.")
        if self.kind is RuntimeTurnKind.READY:
            if not isinstance(self.input_policy, InputPolicy):
                raise TypeError("A ready runtime turn requires an InputPolicy.")
            source = str(self.trigger_source or "").strip()
            if not source:
                raise ValueError("A ready runtime turn requires a trigger source.")
            object.__setattr__(self, "trigger_source", source)
            return
        if self.input_policy is not None or self.trigger_source is not None:
            raise ValueError("A non-ready runtime turn cannot carry input details.")

    @classmethod
    def ready(cls, input_policy: InputPolicy, trigger_source: str) -> RuntimeTurn:
        return cls(RuntimeTurnKind.READY, input_policy, trigger_source)

    @classmethod
    def handled(cls) -> RuntimeTurn:
        return cls(RuntimeTurnKind.HANDLED)

    @classmethod
    def stopped(cls) -> RuntimeTurn:
        return cls(RuntimeTurnKind.STOPPED)


class RuntimeTurnCoordinator:
    """Choose menu, mode, wake-word, PTT, interrupt, or shutdown work."""

    def __init__(
        self,
        *,
        shutdown_event: threading.Event,
        interrupted_event: threading.Event,
        is_exiting: IsExiting,
        quiet_hours_locked: Callable[[], bool],
        start_pending_action: Callable[[], bool],
        input_policy: InputPolicyProvider,
        wait_for_wake_trigger: Callable[[], str],
        set_state: SetState,
    ) -> None:
        callbacks = {
            "is_exiting": is_exiting,
            "quiet_hours_locked": quiet_hours_locked,
            "start_pending_action": start_pending_action,
            "input_policy": input_policy,
            "wait_for_wake_trigger": wait_for_wake_trigger,
            "set_state": set_state,
        }
        for name, callback in callbacks.items():
            if not callable(callback):
                raise TypeError(f"Runtime turn {name} must be callable.")
        for name, event in (
            ("shutdown_event", shutdown_event),
            ("interrupted_event", interrupted_event),
        ):
            if not isinstance(event, threading.Event):
                raise TypeError(f"Runtime turn {name} must be an Event.")

        self._shutdown_event = shutdown_event
        self._interrupted_event = interrupted_event
        self._is_exiting = is_exiting
        self._quiet_hours_locked = quiet_hours_locked
        self._start_pending_action = start_pending_action
        self._input_policy = input_policy
        self._wait_for_wake_trigger = wait_for_wake_trigger
        self._set_state = set_state

    def next_turn(self) -> RuntimeTurn:
        """Wait until one worker turn is ready or non-voice work is handled."""
        while self._quiet_hours_locked() and not self._stopping():
            self._shutdown_event.wait(0.1)
        if self._stopping():
            return RuntimeTurn.stopped()
        if self._start_pending_action():
            return RuntimeTurn.handled()

        input_policy = self._require_input_policy(self._input_policy())
        while (
            input_policy.kind is InputPolicyKind.SUSPENDED
            and not self._stopping()
        ):
            self._shutdown_event.wait(0.1)
            input_policy = self._require_input_policy(self._input_policy())
        if self._stopping():
            return RuntimeTurn.stopped()

        if input_policy.kind is InputPolicyKind.CONTINUOUS:
            trigger_source = input_policy.trigger_source
            self._set_state(BotStates.LISTENING, input_policy.listening_status)
        else:
            self._set_state(BotStates.IDLE, "Waiting...")
            trigger_source = str(self._wait_for_wake_trigger()).strip().upper()

        if trigger_source == "MENU":
            self._start_pending_action()
            return RuntimeTurn.handled()
        if self._is_exiting():
            return RuntimeTurn.stopped()
        if self._interrupted_event.is_set():
            self._interrupted_event.clear()
            self._set_state(BotStates.IDLE, "Resetting...")
            return RuntimeTurn.handled()
        if input_policy.kind is InputPolicyKind.WAKE_WORD:
            self._set_state(BotStates.LISTENING, input_policy.listening_status)
        if trigger_source == "STOP" or self._shutdown_event.is_set():
            return RuntimeTurn.stopped()
        return RuntimeTurn.ready(input_policy, trigger_source)

    def _stopping(self) -> bool:
        return self._is_exiting() or self._shutdown_event.is_set()

    @staticmethod
    def _require_input_policy(value: InputPolicy) -> InputPolicy:
        if not isinstance(value, InputPolicy):
            raise TypeError("Runtime turn input_policy must return InputPolicy.")
        return value


__all__ = [
    "RuntimeTurn",
    "RuntimeTurnCoordinator",
    "RuntimeTurnKind",
    "RuntimeWorkerLoop",
]
