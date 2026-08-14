import json
import math
import tempfile
import unittest
from pathlib import Path

from bmo.archive import InteractionArchiveManager


class InteractionArchiveTests(unittest.TestCase):
    def test_interaction_creates_dated_category_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = InteractionArchiveManager(directory).begin("PTT")
            self.assertIsNotNone(archive)
            assert archive is not None

            for category in ("input", "output", "web", "images"):
                self.assertTrue((archive.path / category).is_dir())
            relative_parts = archive.path.relative_to(directory).parts
            self.assertEqual(len(relative_parts), 4)
            self.assertEqual(
                [len(part) for part in relative_parts[:3]],
                [4, 2, 2],
            )
            self.assertTrue(all(part.isdigit() for part in relative_parts[:3]))

    def test_records_text_json_events_and_final_status(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = InteractionArchiveManager(directory).begin("WAKE_WORD")
            assert archive is not None
            archive.write_text("input", "transcript.txt", "hello\n")
            archive.append_text("output", "assistant.txt", "hi")
            archive.append_json(
                "web",
                "searches.jsonl",
                {"query": "weather", "result": [Path("result.txt")]},
            )
            archive.finish("completed")

            self.assertEqual(
                (archive.path / "input" / "transcript.txt").read_text(),
                "hello\n",
            )
            self.assertEqual(
                (archive.path / "output" / "assistant.txt").read_text(),
                "hi\n",
            )
            search_record = json.loads(
                (archive.path / "web" / "searches.jsonl").read_text()
            )
            self.assertEqual(search_record["result"], ["result.txt"])
            manifest = json.loads((archive.path / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertIn("finished_at", manifest)

    def test_archive_paths_are_contained_and_non_finite_values_are_strict_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = InteractionArchiveManager(directory).begin("PTT")
            assert archive is not None

            for filename in ("../manifest.json", "nested/tools.jsonl", ".."):
                with self.subTest(filename=filename), self.assertRaisesRegex(
                    ValueError,
                    "leaf name",
                ):
                    archive.append_json("output", filename, {})

            archive.append_json(
                "output",
                "numbers.jsonl",
                {
                    "timestamp": "spoofed",
                    "nan": math.nan,
                    "positive": math.inf,
                    "negative": -math.inf,
                },
            )
            record = json.loads(
                (archive.path / "output" / "numbers.jsonl").read_text()
            )
            self.assertEqual(
                (record["nan"], record["positive"], record["negative"]),
                ("nan", "inf", "-inf"),
            )
            self.assertNotEqual(record["timestamp"], "spoofed")
            for suffix in ("../../outside.jpg", ".tar.gz", "."):
                with self.subTest(suffix=suffix), self.assertRaisesRegex(
                    ValueError,
                    "suffix",
                ):
                    archive.image_path(suffix)

    def test_disabled_manager_does_not_create_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = InteractionArchiveManager(directory, enabled=False)
            self.assertIsNone(manager.begin("PTT"))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
