#!/usr/bin/env python3
"""Privacy-safe, read-only evidence probe for the Stage 1 iMessage snapshots.

This is an exploratory development tool, not the production relay parser. It
never opens a supplied database directly: each DB/WAL/SHM trio is copied to a
temporary directory first. Output intentionally excludes message text, handle
values, GUID values, filenames, and blob contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


TRIO_NAMES = ("sms.db", "sms.db-wal", "sms.db-shm")
TABLE_KEYS = {
    "message": ("ROWID",),
    "attachment": ("ROWID",),
    "handle": ("ROWID",),
    "chat": ("ROWID",),
    "chat_message_join": ("chat_id", "message_id"),
    "chat_handle_join": ("chat_id", "handle_id"),
    "message_attachment_join": ("message_id", "attachment_id"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_trio(snapshot_root: Path) -> dict[str, str]:
    sms_root = snapshot_root / "SMS"
    return {name: sha256(sms_root / name) for name in TRIO_NAMES}


def copy_trio(snapshot_root: Path, destination: Path) -> Path:
    sms_root = snapshot_root / "SMS"
    destination.mkdir(parents=True)
    for name in TRIO_NAMES:
        source = sms_root / name
        if not source.is_file():
            raise FileNotFoundError(f"required snapshot file is missing: {source}")
        shutil.copy2(source, destination / name)
    return destination / "sms.db"


def connect_read_only(database: Path, *, immutable: bool = False) -> sqlite3.Connection:
    parameter = "immutable=1" if immutable else "mode=ro"
    connection = sqlite3.connect(f"{database.as_uri()}?{parameter}", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def safe_table_rows(
    connection: sqlite3.Connection,
    table: str,
    keys: tuple[str, ...],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in connection.execute(f'SELECT * FROM "{table}"'):
        record = dict(row)
        rows[tuple(record[key] for key in keys)] = record
    return rows


def compare_table(
    baseline: sqlite3.Connection,
    current: sqlite3.Connection,
    table: str,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    old = safe_table_rows(baseline, table, keys)
    new = safe_table_rows(current, table, keys)
    changed = []
    for key in sorted(old.keys() & new.keys()):
        columns = sorted(
            column for column in old[key] if old[key][column] != new[key][column]
        )
        if columns:
            changed.append({"key": list(key), "columns": columns})
    return {
        "added_keys": [list(key) for key in sorted(new.keys() - old.keys())],
        "removed_keys": [list(key) for key in sorted(old.keys() - new.keys())],
        "changed": changed,
    }


def database_summary(
    connection: sqlite3.Connection,
    database: Path,
) -> dict[str, Any]:
    check = connection.execute("PRAGMA quick_check").fetchone()[0]
    table_names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    table_counts = {
        name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name in table_names
    }
    message_min, message_max = connection.execute(
        "SELECT MIN(ROWID), MAX(ROWID) FROM message"
    ).fetchone()
    message_rowids = {
        row[0] for row in connection.execute("SELECT ROWID FROM message")
    }
    missing_rowids = (
        sorted(set(range(message_min, message_max + 1)) - message_rowids)
        if message_min is not None and message_max is not None
        else []
    )
    services = {
        str(service): count
        for service, count in connection.execute(
            "SELECT service, COUNT(*) FROM message GROUP BY service ORDER BY service"
        )
    }
    directions = {
        str(direction): count
        for direction, count in connection.execute(
            "SELECT is_from_me, COUNT(*) FROM message "
            "GROUP BY is_from_me ORDER BY is_from_me"
        )
    }
    reactions = [
        {
            "associated_message_type": reaction_type,
            "is_from_me": is_from_me,
            "rows": count,
        }
        for reaction_type, is_from_me, count in connection.execute(
            "SELECT associated_message_type, is_from_me, COUNT(*) "
            "FROM message WHERE associated_message_type != 0 "
            "GROUP BY associated_message_type, is_from_me "
            "ORDER BY associated_message_type, is_from_me"
        )
    ]
    text_shapes = dict(
        connection.execute(
            "SELECT COUNT(*) AS rows, "
            "SUM(text IS NULL) AS null_text, "
            "SUM(text = '') AS empty_text, "
            "SUM(attributedBody IS NOT NULL) AS attributed_body, "
            "SUM(cache_has_attachments != 0) AS with_attachments "
            "FROM message"
        ).fetchone()
    )
    attachment_types = [
        {"uti": uti, "mime_type": mime_type, "rows": count}
        for uti, mime_type, count in connection.execute(
            "SELECT uti, mime_type, COUNT(*) FROM attachment "
            "GROUP BY uti, mime_type ORDER BY uti, mime_type"
        )
    ]
    with connect_read_only(database, immutable=True) as immutable_connection:
        immutable_message_rows = immutable_connection.execute(
            "SELECT COUNT(*) FROM message"
        ).fetchone()[0]
    return {
        "quick_check": check,
        "schema_version": connection.execute("PRAGMA schema_version").fetchone()[0],
        "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
        "table_counts": table_counts,
        "message_min_rowid": message_min,
        "message_max_rowid": message_max,
        "message_missing_rowids": missing_rowids,
        "message_services": services,
        "message_directions": directions,
        "reaction_rows": reactions,
        "text_shapes": text_shapes,
        "attachment_types": attachment_types,
        "immutable_message_rows": immutable_message_rows,
    }


def assert_controlled_corpus(report: dict[str, Any]) -> None:
    baseline = report["baseline"]
    current = report["current"]
    differences = report["differences"]
    assert baseline["quick_check"] == "ok"
    assert current["quick_check"] == "ok"
    assert baseline["table_counts"]["message"] == 6
    assert current["table_counts"]["message"] == 36
    assert current["message_max_rowid"] == 38
    assert current["message_missing_rowids"] == [13, 16]
    assert baseline["table_counts"]["attachment"] == 1
    assert current["table_counts"]["attachment"] == 4
    assert current["table_counts"]["sync_deleted_messages"] == 2
    assert current["immutable_message_rows"] == 22
    assert differences["message"]["changed"] == []
    assert differences["handle"] == {
        "added_keys": [],
        "removed_keys": [],
        "changed": [],
    }
    reaction_counts = Counter(
        (row["associated_message_type"], row["is_from_me"], row["rows"])
        for row in current["reaction_rows"]
    )
    assert reaction_counts == Counter(
        {
            (2000, 0, 1): 1,
            (2001, 0, 2): 1,
            (2001, 1, 2): 1,
            (2002, 0, 1): 1,
            (2003, 0, 1): 1,
            (2004, 0, 1): 1,
            (2005, 0, 1): 1,
            (3001, 0, 1): 1,
            (3001, 1, 1): 1,
        }
    )


def build_report(baseline_root: Path, current_root: Path) -> dict[str, Any]:
    original_before = {
        "baseline": fingerprint_trio(baseline_root),
        "current": fingerprint_trio(current_root),
    }
    with tempfile.TemporaryDirectory(prefix="imessage-schema-probe-") as temp:
        temp_root = Path(temp)
        baseline_db = copy_trio(baseline_root, temp_root / "baseline")
        current_db = copy_trio(current_root, temp_root / "current")
        with (
            connect_read_only(baseline_db) as baseline,
            connect_read_only(current_db) as current,
        ):
            report = {
                "baseline": database_summary(baseline, baseline_db),
                "current": database_summary(current, current_db),
                "differences": {
                    table: compare_table(baseline, current, table, keys)
                    for table, keys in TABLE_KEYS.items()
                },
            }
    original_after = {
        "baseline": fingerprint_trio(baseline_root),
        "current": fingerprint_trio(current_root),
    }
    report["source_fingerprints_unchanged"] = original_before == original_after
    if original_before != original_after:
        raise RuntimeError("a source snapshot fingerprint changed during inspection")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="Stage 0 snapshot root")
    parser.add_argument("current", type=Path, help="controlled-test snapshot root")
    parser.add_argument(
        "--assert-controlled-corpus",
        action="store_true",
        help="fail unless the supplied snapshots match the Stage 1 evidence set",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.baseline.resolve(), args.current.resolve())
    if args.assert_controlled_corpus:
        assert_controlled_corpus(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
