"""UI-neutral extension registry ownership and menu-action scheduling."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
from typing import Protocol

from bmo.menu_catalog import MenuCatalog, MenuContribution, MenuSelectionRequest
from bmo.runtime_menu import RuntimeMenuCoordinator


Completion = Callable[[], None]
FeatureMenuLauncher = Callable[[str], None]


class FeatureRegistryPort(Protocol):
    """Feature-registry surface owned by the extension runtime."""

    @property
    def menu_items(self) -> Iterable[MenuContribution]:
        """Return currently visible feature menu contributions."""

    def close(self) -> None:
        """Release all feature-owned resources."""


class ModeRegistryPort(Protocol):
    """Mode-registry surface owned by the extension runtime."""

    @property
    def menu_items(self) -> Iterable[MenuContribution]:
        """Return currently visible mode menu contributions."""

    def start_menu_item(self, name: str) -> None:
        """Start one registered menu-visible interaction mode."""

    def close(self) -> None:
        """Release all mode-owned resources."""


@dataclass(frozen=True)
class RuntimeVisionRequest:
    """One feature-owned image queued for the normal interaction worker."""

    image_path: Path
    on_complete: Completion

    def __post_init__(self) -> None:
        if not isinstance(self.image_path, Path):
            raise TypeError("Runtime vision image_path must be pathlib.Path.")
        if not callable(self.on_complete):
            raise TypeError("Runtime vision completion must be callable.")


class RuntimeExtensionCoordinator:
    """Own extension registries and serialize cross-thread menu work."""

    def __init__(
        self,
        mode_registry: ModeRegistryPort,
        feature_registry: FeatureRegistryPort,
        *,
        launch_feature: FeatureMenuLauncher,
    ) -> None:
        for name, registry in (
            ("mode_registry", mode_registry),
            ("feature_registry", feature_registry),
        ):
            if not hasattr(registry, "menu_items") or not callable(
                getattr(registry, "close", None)
            ):
                raise TypeError(
                    f"Runtime extension {name} must expose menu_items and close()."
                )
        if not callable(getattr(mode_registry, "start_menu_item", None)):
            raise TypeError(
                "Runtime extension mode_registry must expose start_menu_item()."
            )
        if not callable(launch_feature):
            raise TypeError("Runtime extension launch_feature must be callable.")

        self.mode_registry = mode_registry
        self.feature_registry = feature_registry
        self.wake_event = threading.Event()
        self._closed = threading.Event()
        self._queue_lock = threading.Lock()
        self._mode_requests: queue.Queue[str] = queue.Queue()
        self._vision_requests: queue.Queue[RuntimeVisionRequest] = queue.Queue()
        self.menu = RuntimeMenuCoordinator.from_registries(
            mode_registry,
            feature_registry,
            launch_mode=self.queue_mode,
            launch_feature=launch_feature,
        )

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def catalog(self) -> MenuCatalog:
        """Return the current live registry-backed menu catalog."""
        return self.menu.catalog()

    def dispatch_menu(self, request: MenuSelectionRequest) -> None:
        """Validate and route one presentation-owned menu selection."""
        if self.closed:
            raise RuntimeError("Cannot dispatch menu selections after shutdown.")
        self.menu.dispatch(request)

    def queue_mode(self, name: str) -> None:
        """Queue one mode launch and wake the interaction worker."""
        normalized = str(name).strip().lower()
        if not normalized:
            raise ValueError("Queued mode name cannot be empty.")
        with self._queue_lock:
            if self.closed:
                raise RuntimeError("Cannot queue mode launches after shutdown.")
            self._mode_requests.put(normalized)
            self.wake_event.set()

    def queue_vision(
        self,
        image_path: Path,
        on_complete: Completion,
    ) -> None:
        """Queue one feature vision turn and wake the interaction worker."""
        request = RuntimeVisionRequest(image_path, on_complete)
        with self._queue_lock:
            if self.closed:
                raise RuntimeError("Cannot queue vision requests after shutdown.")
            self._vision_requests.put(request)
            self.wake_event.set()

    def take_pending_vision(self) -> RuntimeVisionRequest | None:
        """Take the next vision request without blocking the worker."""
        with self._queue_lock:
            if self.closed:
                return None
            try:
                request = self._vision_requests.get_nowait()
            except queue.Empty:
                return None
            self._clear_wake_if_idle_locked()
            return request

    def start_pending_mode(
        self,
        *,
        on_complete: Completion | None = None,
    ) -> bool:
        """Start one queued mode on the caller's worker thread."""
        if on_complete is not None and not callable(on_complete):
            raise TypeError("Mode launch completion must be callable.")
        with self._queue_lock:
            if self.closed:
                return False
            try:
                name = self._mode_requests.get_nowait()
            except queue.Empty:
                return False
            self._clear_wake_if_idle_locked()
        try:
            self.mode_registry.start_menu_item(name)
        finally:
            if on_complete is not None:
                on_complete()
        return True

    def clear_wake_if_idle(self) -> None:
        """Clear the wake signal only after both action queues drain."""
        with self._queue_lock:
            self._clear_wake_if_idle_locked()

    def _clear_wake_if_idle_locked(self) -> None:
        if (
            not self.closed
            and self._mode_requests.empty()
            and self._vision_requests.empty()
        ):
            self.wake_event.clear()

    def close(self) -> None:
        """Stop new work, wake waiters, and close both registries once."""
        with self._queue_lock:
            if self._closed.is_set():
                return
            self._closed.set()
            self.wake_event.set()
            self._drain(self._vision_requests)
            self._drain(self._mode_requests)
        for owner, registry in (
            ("feature", self.feature_registry),
            ("mode", self.mode_registry),
        ):
            try:
                registry.close()
            except Exception as exc:
                print(
                    f"[RUNTIME] Could not close {owner} registry: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

    @staticmethod
    def _drain(requests: queue.Queue[object]) -> None:
        while True:
            try:
                requests.get_nowait()
            except queue.Empty:
                return


__all__ = [
    "FeatureRegistryPort",
    "ModeRegistryPort",
    "RuntimeExtensionCoordinator",
    "RuntimeVisionRequest",
]
