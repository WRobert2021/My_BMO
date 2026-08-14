"""Contracts for shared strict and atomic JSON primitives."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from bmo.jsonio import (
    DuplicateJSONKeyError,
    atomic_write_json,
    first_json_object,
    load_json,
    loads_json,
)


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_keys_and_non_finite_numbers_are_rejected(self) -> None:
        with self.assertRaises(DuplicateJSONKeyError):
            loads_json('{"enabled":true,"enabled":false}')
        with self.assertRaisesRegex(ValueError, "non-finite"):
            loads_json('{"value":NaN}')

    def test_file_loader_uses_the_same_strict_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            path.write_text('{"name":"BMO"}', encoding="utf-8")
            with path.open("r", encoding="utf-8") as handle:
                self.assertEqual(load_json(handle), {"name": "BMO"})

    def test_first_embedded_object_is_not_confused_by_later_json(self) -> None:
        self.assertEqual(
            first_json_object(
                'prefix {"action":"get_time"} suffix {"action":"chat"}'
            ),
            {"action": "get_time"},
        )
        self.assertEqual(
            first_json_object('{"message":"a } brace","ready":true}'),
            {"message": "a } brace", "ready": True},
        )

    def test_ambiguous_or_non_finite_embedded_object_is_rejected(self) -> None:
        self.assertIsNone(first_json_object('{"a":1,"a":2}'))
        self.assertIsNone(first_json_object('{"value":NaN}'))

    def test_incomplete_outer_object_does_not_expose_nested_action(self) -> None:
        self.assertIsNone(
            first_json_object(
                'prefix {"wrapper":{"action":"get_time"}'
            )
        )

    def test_excessive_json_nesting_is_rejected_cleanly(self) -> None:
        embedded = '{"nested":' * 65 + "null" + "}" * 65
        deeply_nested = "[" * 20000 + "0" + "]" * 20000

        self.assertIsNone(first_json_object(embedded))
        with self.assertRaisesRegex(ValueError, "nesting is too deep"):
            loads_json(deeply_nested)


class AtomicJsonTests(unittest.TestCase):
    def test_replace_failure_preserves_destination_and_removes_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            path.write_text('{"old":true}\n', encoding="utf-8")
            replace = Mock(side_effect=OSError("read only"))

            with self.assertRaisesRegex(OSError, "read only"):
                atomic_write_json(path, {"new": True}, replace=replace)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"old": True},
            )
            self.assertEqual(list(path.parent.glob(".value.json.*.tmp")), [])

    def test_success_flushes_then_replaces_with_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            atomic_write_json(path, {"ready": True}, replace=os.replace)

            self.assertEqual(json.loads(path.read_text()), {"ready": True})
            self.assertTrue(path.read_bytes().endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
