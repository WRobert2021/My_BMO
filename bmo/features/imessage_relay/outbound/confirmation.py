"""In-memory user-confirmation boundary for Stage 13 outbound commands."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Callable

from .protocol import (
    OutboundCommand,
    OutboundMediaCommand,
    OutboundReactionCommand,
    OutboundTextCommand,
    encode_command,
)


DEFAULT_CONFIRMATION_TIMEOUT_SECONDS = 120


class OutboundConfirmationError(ValueError):
    """A command was not explicitly confirmed through the active prompt."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OutboundConfirmation:
    """Display-safe details for one pending confirmation prompt."""

    confirmation_id: str
    command_id: str
    kind: str
    recipient_ids: tuple[str, ...]
    is_reply: bool
    text: str | None
    media_names: tuple[str, ...]
    reaction_kind: str | None
    reaction_operation: str | None
    expires_in_seconds: int


class OutboundConfirmationGate:
    """Hold exactly one command in memory until an exact one-shot confirmation."""

    def __init__(
        self,
        *,
        timeout_seconds: int = DEFAULT_CONFIRMATION_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 10 <= timeout_seconds <= 600
        ):
            raise ValueError("confirmation timeout must be from 10 through 600 seconds")
        if not callable(clock) or not callable(token_factory):
            raise TypeError("confirmation clock and token factory must be callable")
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._token_factory = token_factory
        self._pending: tuple[str, float, OutboundCommand] | None = None
        self._closed = False

    def prepare(self, command: OutboundCommand) -> OutboundConfirmation:
        """Hold a validated command and return the exact prompt representation."""

        self._require_open()
        self._discard_expired()
        if self._pending is not None:
            raise OutboundConfirmationError("confirmation_already_pending")
        # Reuse the canonical encoder as the single validation/type boundary.
        encode_command(command)
        confirmation_id = self._token_factory()
        if (
            not isinstance(confirmation_id, str)
            or not confirmation_id
            or len(confirmation_id) > 128
            or not confirmation_id.isascii()
            or not confirmation_id.isalnum()
        ):
            raise OutboundConfirmationError("confirmation_token_invalid")
        expires_at = self._clock() + self._timeout_seconds
        self._pending = (confirmation_id, expires_at, command)
        return _confirmation(
            confirmation_id,
            command,
            expires_in_seconds=self._timeout_seconds,
        )

    def pending(self) -> OutboundConfirmation | None:
        """Return the active prompt without exposing a send operation."""

        self._require_open()
        self._discard_expired()
        if self._pending is None:
            return None
        confirmation_id, expires_at, command = self._pending
        remaining = max(1, int(expires_at - self._clock()))
        return _confirmation(confirmation_id, command, expires_in_seconds=remaining)

    def confirm(self, confirmation_id: str) -> OutboundCommand:
        """Consume and return only the command matching the active prompt."""

        self._require_open()
        if self._pending is None:
            raise OutboundConfirmationError("confirmation_missing")
        expected_id, expires_at, command = self._pending
        if self._clock() >= expires_at:
            self._pending = None
            raise OutboundConfirmationError("confirmation_expired")
        if confirmation_id != expected_id:
            raise OutboundConfirmationError("confirmation_mismatch")
        self._pending = None
        return command

    def cancel(self, confirmation_id: str) -> None:
        """Cancel only the prompt named by its exact opaque identifier."""

        self._require_open()
        self._discard_expired()
        if self._pending is None:
            raise OutboundConfirmationError("confirmation_missing")
        expected_id, _expires_at, _command = self._pending
        if confirmation_id != expected_id:
            raise OutboundConfirmationError("confirmation_mismatch")
        self._pending = None

    def close(self) -> None:
        """Forget any private draft content without sending or persisting it."""

        self._pending = None
        self._closed = True

    def _discard_expired(self) -> None:
        if self._pending is not None and self._clock() >= self._pending[1]:
            self._pending = None

    def _require_open(self) -> None:
        if self._closed:
            raise OutboundConfirmationError("confirmation_gate_closed")


def _confirmation(
    confirmation_id: str,
    command: OutboundCommand,
    *,
    expires_in_seconds: int,
) -> OutboundConfirmation:
    text: str | None = None
    media_names: tuple[str, ...] = ()
    reaction_kind: str | None = None
    reaction_operation: str | None = None
    if isinstance(command, OutboundTextCommand):
        text = command.text
    elif isinstance(command, OutboundMediaCommand):
        text = command.text
        media_names = tuple(item.transfer_name for item in command.media)
    elif isinstance(command, OutboundReactionCommand):
        reaction_kind = command.reaction_kind
        reaction_operation = command.operation
    else:  # pragma: no cover - encode_command rejects this before storage.
        raise TypeError("command has an unsupported type")
    return OutboundConfirmation(
        confirmation_id=confirmation_id,
        command_id=command.command_id,
        kind=command.kind,
        recipient_ids=command.destination.recipient_ids,
        is_reply=command.destination.reply_to_message_id is not None,
        text=text,
        media_names=media_names,
        reaction_kind=reaction_kind,
        reaction_operation=reaction_operation,
        expires_in_seconds=expires_in_seconds,
    )


__all__ = [
    "DEFAULT_CONFIRMATION_TIMEOUT_SECONDS",
    "OutboundConfirmation",
    "OutboundConfirmationError",
    "OutboundConfirmationGate",
]
