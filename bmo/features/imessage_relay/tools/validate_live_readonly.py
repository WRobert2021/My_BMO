#!/usr/bin/env python3
"""Privacy-safe Stage 8 validation for a read-only live Messages mount.

The supplied directory must be the iPhone's ``/var/mobile/Library/SMS``
directory exposed through a read-only mount. SQLite never opens the supplied
database directly. The DB/WAL/SHM trio is copied into a disposable local
directory, checked for source stability, and parsed there. Output contains
only aggregate diagnostics and fixed error codes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, Iterable

from ..relay import (
    AttachmentAvailability,
    IMessageParserError,
    MessageEvent,
    MessagesReader,
)
from ..relay.reader import open_read_only_database


TRIO_NAMES = ("sms.db", "sms.db-wal", "sms.db-shm")
MAX_SCAN_LIMIT = 1_000
MAX_ATTACHMENT_FILES = 4
MAX_ATTACHMENT_FILE_BYTES = 16 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 32 * 1024 * 1024


class LiveValidationError(RuntimeError):
    """A privacy-safe Stage 8 validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _trio_paths(messages_root: Path) -> tuple[Path, ...]:
    paths = tuple(messages_root / name for name in TRIO_NAMES)
    if not all(path.is_file() for path in paths):
        raise LiveValidationError("messages_trio_unreadable")
    return paths


def _fingerprint(
    paths: Iterable[Path],
) -> tuple[tuple[int, int, int, int, int, int, int, str], ...]:
    observations = []
    for path in paths:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise LiveValidationError("messages_trio_unreadable")
        observations.append(
            (
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_size,
                info.st_atime_ns,
                info.st_mtime_ns,
                info.st_ctime_ns,
                _sha256(path),
            )
        )
    return tuple(observations)


def _copy_trio(source_paths: tuple[Path, ...], destination: Path) -> Path:
    destination.mkdir(mode=0o700)
    for source, name in zip(source_paths, TRIO_NAMES, strict=True):
        shutil.copyfile(source, destination / name)
    return destination / "sms.db"


def _query_plan_uses_rowid_range(connection: sqlite3.Connection) -> bool:
    rows = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT ROWID FROM message NOT INDEXED
        WHERE ROWID > ? AND service = 'iMessage'
        ORDER BY ROWID ASC
        LIMIT ?
        """,
        (0, 1),
    ).fetchall()
    details = " ".join(str(row[3]).upper() for row in rows)
    return "INTEGER PRIMARY KEY" in details and "ROWID>?" in details


def _recent_i_message_start(connection: sqlite3.Connection, limit: int) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MIN(ROWID), 1)
        FROM (
            SELECT ROWID FROM message NOT INDEXED
            WHERE service = 'iMessage'
            ORDER BY ROWID DESC
            LIMIT ?
        )
        """,
        (limit,),
    ).fetchone()
    return max(0, int(row[0]) - 1)


def _source_direction_counts(
    connection: sqlite3.Connection,
    *,
    after_rowid: int,
    limit: int,
) -> dict[str, int]:
    counts = Counter(
        "outgoing" if int(row[0]) else "incoming"
        for row in connection.execute(
            """
            SELECT is_from_me
            FROM message NOT INDEXED
            WHERE ROWID > ? AND service = 'iMessage'
            ORDER BY ROWID ASC
            LIMIT ?
            """,
            (after_rowid, limit),
        )
    )
    return dict(sorted(counts.items()))


def _attachment_paths(events: Iterable[object]) -> tuple[Path, ...]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        for attachment in event.attachments:
            if attachment.availability is not AttachmentAvailability.AVAILABLE:
                continue
            candidates = (
                [Path(component.source_path) for component in attachment.components]
                if attachment.components
                else ([Path(attachment.source_path)] if attachment.source_path else [])
            )
            for candidate in candidates:
                if candidate not in seen:
                    paths.append(candidate)
                    seen.add(candidate)
    return tuple(paths)


def _verify_attachment_reads(paths: Iterable[Path]) -> dict[str, int | bool]:
    verified_files = 0
    verified_bytes = 0
    skipped_large = 0
    skipped_limit = 0
    read_errors = 0
    unchanged = True

    for path in paths:
        if verified_files >= MAX_ATTACHMENT_FILES:
            skipped_limit += 1
            continue
        try:
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                read_errors += 1
                unchanged = False
                continue
            if before.st_size > MAX_ATTACHMENT_FILE_BYTES:
                skipped_large += 1
                continue
            if verified_bytes + before.st_size > MAX_ATTACHMENT_TOTAL_BYTES:
                skipped_limit += 1
                continue
            first_digest = _sha256(path)
            middle = path.stat()
            second_digest = _sha256(path)
            after = path.stat()
        except OSError:
            read_errors += 1
            unchanged = False
            continue

        metadata = (
            _file_metadata(before),
            _file_metadata(middle),
            _file_metadata(after),
        )
        if len(set(metadata)) != 1 or first_digest != second_digest:
            unchanged = False
        verified_files += 1
        verified_bytes += before.st_size

    return {
        "verified_files": verified_files,
        "verified_source_bytes": verified_bytes,
        "skipped_large": skipped_large,
        "skipped_limit": skipped_limit,
        "read_errors": read_errors,
        "unchanged_during_reads": unchanged,
    }


def _file_metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_atime_ns,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def validate_live_readonly(messages_root: Path, *, scan_limit: int = 100) -> dict[str, Any]:
    """Validate a read-only live mount without opening its SQLite database."""

    if isinstance(scan_limit, bool) or not 1 <= scan_limit <= MAX_SCAN_LIMIT:
        raise LiveValidationError("invalid_scan_limit")
    root = messages_root.expanduser().resolve(strict=False)
    source_paths = _trio_paths(root)
    before = _fingerprint(source_paths)

    with tempfile.TemporaryDirectory(prefix="imessage-stage8-") as temporary:
        copied_database = _copy_trio(source_paths, Path(temporary) / "SMS")
        after_copy = _fingerprint(source_paths)
        if before != after_copy:
            return {
                "status": "inconclusive_source_changed",
                "source": {
                    "database_opened_directly": False,
                    "trio_readable": True,
                    "trio_stable_during_copy": False,
                },
            }

        try:
            with open_read_only_database(copied_database) as connection:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
                schema_version = int(
                    connection.execute("PRAGMA schema_version").fetchone()[0]
                )
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode").fetchone()[0]
                ).lower()
                query_only = bool(
                    connection.execute("PRAGMA query_only").fetchone()[0]
                )
                rowid_range_plan = _query_plan_uses_rowid_range(connection)
                after_rowid = _recent_i_message_start(connection, scan_limit)
                source_directions = _source_direction_counts(
                    connection,
                    after_rowid=after_rowid,
                    limit=scan_limit,
                )

            batch = MessagesReader(copied_database, messages_root=root).scan(
                after_rowid=after_rowid,
                limit=scan_limit,
            )
        except (IMessageParserError, OSError, sqlite3.Error) as exc:
            raise LiveValidationError("copied_database_unreadable") from exc

        event_counts = Counter(event.event_kind.value for event in batch.events)
        direction_counts = Counter(event.direction.value for event in batch.events)
        issue_counts = Counter(issue.code for issue in batch.issues)
        attachments = [
            attachment
            for event in batch.events
            if isinstance(event, MessageEvent)
            for attachment in event.attachments
        ]
        availability_counts = Counter(
            attachment.availability.value for attachment in attachments
        )
        media_counts = Counter(
            attachment.media_category.value for attachment in attachments
        )
        attachment_read_report = _verify_attachment_reads(
            _attachment_paths(batch.events)
        )

    after = _fingerprint(source_paths)
    trio_stable = before == after
    attachments_unchanged = bool(
        attachment_read_report["unchanged_during_reads"]
    )
    accepted = (
        quick_check == "ok"
        and journal_mode == "wal"
        and query_only
        and rowid_range_plan
        and trio_stable
        and attachments_unchanged
    )
    return {
        "status": "pass" if accepted else "failed",
        "source": {
            "database_opened_directly": False,
            "trio_readable": True,
            "trio_stable_during_copy": True,
            "trio_stable_during_validation": trio_stable,
        },
        "database": {
            "quick_check": quick_check,
            "schema_version": schema_version,
            "journal_mode": journal_mode,
            "query_only": query_only,
            "rowid_range_query_plan": rowid_range_plan,
            "validation_python_sqlite_version": sqlite3.sqlite_version,
        },
        "scan": {
            "limit": scan_limit,
            "rows_examined": batch.scanned_row_count,
            "source_directions": source_directions,
            "events": dict(sorted(event_counts.items())),
            "directions": dict(sorted(direction_counts.items())),
            "ordinary_outgoing_events_omitted": not any(
                isinstance(event, MessageEvent) and event.direction.value == "outgoing"
                for event in batch.events
            ),
            "issues": dict(sorted(issue_counts.items())),
        },
        "attachments": {
            "referenced": len(attachments),
            "availability": dict(sorted(availability_counts.items())),
            "media": dict(sorted(media_counts.items())),
            **attachment_read_report,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "messages_root",
        type=Path,
        help="read-only mount of /var/mobile/Library/SMS",
    )
    parser.add_argument("--scan-limit", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_live_readonly(args.messages_root, scan_limit=args.scan_limit)
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted"}, indent=2, sort_keys=True))
        return 130
    except LiveValidationError as exc:
        report = {"status": "failed", "error_code": exc.code}
    except Exception:
        report = {"status": "failed", "error_code": "unexpected_validation_error"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
