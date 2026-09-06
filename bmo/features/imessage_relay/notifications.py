"""Read-only notification counters for the durable incoming relay store."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import stat

from .receiver.store import RECEIVER_APPLICATION_ID, RECEIVER_SCHEMA_VERSION


class NotificationCountError(RuntimeError):
    """Raised when the private receiver state cannot be counted safely."""


def received_message_count(database_path: Path | str) -> int:
    """Return the number of durably received message events without mutation."""

    path = _validated_database_path(database_path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=1.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA query_only = ON")
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if (
            application_id != RECEIVER_APPLICATION_ID
            or user_version != RECEIVER_SCHEMA_VERSION
        ):
            raise NotificationCountError("receiver database schema is unsupported")
        row = connection.execute(
            "SELECT COUNT(*) FROM received_events WHERE event_kind = 'message'"
        ).fetchone()
        if row is None:
            raise NotificationCountError("receiver message count is unavailable")
        return int(row[0])
    except NotificationCountError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise NotificationCountError("receiver message count is unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


def new_message_count(database_path: Path | str, previous_total: int) -> int:
    """Return the nonnegative count added since a caller-owned checkpoint."""

    if (
        isinstance(previous_total, bool)
        or not isinstance(previous_total, int)
        or previous_total < 0
    ):
        raise ValueError("previous message total must be a nonnegative integer")
    return max(0, received_message_count(database_path) - previous_total)


def _validated_database_path(value: Path | str) -> Path:
    unresolved = Path(value).expanduser()
    if unresolved.is_symlink():
        raise NotificationCountError("receiver database cannot be a symbolic link")
    path = unresolved.resolve(strict=False)
    if not path.exists() or not path.is_file():
        raise NotificationCountError("receiver database is unavailable")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise NotificationCountError("receiver database is unavailable") from exc
    if mode & 0o077:
        raise NotificationCountError("receiver database is not private")
    return path
