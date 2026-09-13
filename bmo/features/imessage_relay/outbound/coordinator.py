"""Resource-owning kiosk coordinator behind the Stage 13 confirmation UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Callable, Protocol
from uuid import uuid4

from .client import OutboundClientError
from .confirmation import (
    OutboundConfirmation,
    OutboundConfirmationError,
    OutboundConfirmationGate,
)
from .protocol import OutboundDestination, OutboundTextCommand
from .state import OutboundCommandRecord, OutboundStateError


class TextCommandClient(Protocol):
    def submit(self, command: OutboundTextCommand) -> OutboundCommandRecord:
        """Persist and submit one already-confirmed command."""

    def close(self) -> None:
        """Release client resources."""


@dataclass(frozen=True, slots=True)
class OutboundCoordinatorStatus:
    state: str
    command_id: str | None
    error_code: str | None


class OutboundTextCoordinator:
    """Prepare text in memory and submit it once on exact confirmation."""

    def __init__(
        self,
        client: TextCommandClient,
        *,
        confirmation_gate: OutboundConfirmationGate | None = None,
        identifier_factory: Callable[[], str] | None = None,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        if not hasattr(client, "submit") or not hasattr(client, "close"):
            raise TypeError("outbound client is invalid")
        self._client = client
        self._gate = confirmation_gate or OutboundConfirmationGate()
        self._identifier_factory = identifier_factory or (lambda: uuid4().hex)
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._closed = False
        self._thread: threading.Thread | None = None
        self._status = OutboundCoordinatorStatus("idle", None, None)

    def prepare_text(
        self,
        *,
        recipient_ids: tuple[str, ...],
        text: str,
        chat_id: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> OutboundConfirmation:
        with self._lock:
            self._require_open()
            if self._thread is not None and self._thread.is_alive():
                raise OutboundConfirmationError("outbound_submit_running")
            supplied_now = self._utc_now()
            if supplied_now.tzinfo is None or supplied_now.utcoffset() is None:
                raise ValueError("outbound UTC clock must be timezone-aware")
            now = supplied_now.astimezone(timezone.utc).replace(microsecond=0)
            command = OutboundTextCommand(
                command_id=self._identifier_factory(),
                created_at_utc=now.isoformat(timespec="seconds"),
                destination=OutboundDestination(
                    tuple(recipient_ids),
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                ),
                text=text,
            )
            confirmation = self._gate.prepare(command)
            self._status = OutboundCoordinatorStatus(
                "awaiting_confirmation", command.command_id, None
            )
            return confirmation

    def confirm(
        self,
        confirmation_id: str,
        on_complete: Callable[[], None] | None = None,
    ) -> bool:
        if on_complete is not None and not callable(on_complete):
            raise TypeError("outbound completion must be callable")
        with self._lock:
            self._require_open()
            if self._thread is not None and self._thread.is_alive():
                return False
            command = self._gate.confirm(confirmation_id)
            self._status = OutboundCoordinatorStatus(
                "submitting", command.command_id, None
            )
            thread = threading.Thread(
                target=self._submit,
                args=(command, on_complete),
                name="imessage-relay-outbound-text",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return True

    def cancel(self, confirmation_id: str) -> None:
        with self._lock:
            self._require_open()
            self._gate.cancel(confirmation_id)
            self._status = OutboundCoordinatorStatus("idle", None, None)

    def status(self) -> OutboundCoordinatorStatus:
        with self._lock:
            return self._status

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._gate.close()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._client.close()
        with self._lock:
            self._status = OutboundCoordinatorStatus("closed", None, None)

    def _submit(
        self,
        command: OutboundTextCommand,
        on_complete: Callable[[], None] | None,
    ) -> None:
        try:
            record = self._client.submit(command)
        except OutboundClientError as exc:
            state = "failed"
            error_code = exc.code
        except OutboundStateError:
            state = "failed"
            error_code = "outbound_state_unavailable"
        except Exception:
            state = "failed"
            error_code = "outbound_submit_failed"
        else:
            state = record.state
            error_code = record.error_code
        with self._lock:
            if not self._closed:
                self._status = OutboundCoordinatorStatus(
                    state, command.command_id, error_code
                )
        if on_complete is not None:
            try:
                on_complete()
            except Exception:
                pass

    def _require_open(self) -> None:
        if self._closed:
            raise OutboundConfirmationError("outbound_coordinator_closed")


__all__ = [
    "OutboundCoordinatorStatus",
    "OutboundTextCoordinator",
    "TextCommandClient",
]
