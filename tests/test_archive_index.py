from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from storage import archive_index


class ArchiveIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.index_path = Path(self.directory.name) / "data" / "archive_index.json"
        self.original = [{"id": "old", "title": "기존 글", "article_key": "1:2"}]
        archive_index.save_archive_index(self.original, self.index_path)
        self.original_bytes = self.index_path.read_bytes()

    def assert_original_preserved(self) -> None:
        self.assertEqual(self.index_path.read_bytes(), self.original_bytes)
        self.assertEqual(archive_index.load_archive_index(self.index_path), self.original)
        self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])

    def test_success_keeps_unicode_and_existing_index_shape(self) -> None:
        posts = self.original + [{"id": "new", "title": "새 글"}]
        archive_index.save_archive_index(posts, self.index_path)
        self.assertEqual(json.loads(self.index_path.read_text(encoding="utf-8")), {"posts": posts})
        self.assertIn("새 글", self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(archive_index.load_archive_index(self.index_path), posts)
        self.assertEqual(list(self.index_path.parent.iterdir()), [self.index_path])

    def test_failed_replace_preserves_existing_index_and_removes_temporary_file(self) -> None:
        def failed_replace(source: Path, destination: Path) -> None:
            self.assertEqual(Path(source).parent, self.index_path.parent)
            self.assertEqual(Path(destination), self.index_path)
            self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8"))["posts"], [])
            raise OSError("synthetic replacement failure")

        with patch.object(archive_index.os, "replace", side_effect=failed_replace):
            with self.assertRaisesRegex(OSError, "synthetic replacement failure"):
                archive_index.save_archive_index([], self.index_path)
        self.assert_original_preserved()

    def test_failed_flush_preserves_existing_index_and_removes_temporary_file(self) -> None:
        with patch.object(archive_index.os, "fsync", side_effect=OSError("synthetic flush failure")):
            with self.assertRaisesRegex(OSError, "synthetic flush failure"):
                archive_index.save_archive_index([], self.index_path)
        self.assert_original_preserved()

    def test_partial_temporary_write_preserves_existing_index(self) -> None:
        real_temporary_file = archive_index.tempfile.NamedTemporaryFile

        @contextmanager
        def interrupted_temporary_file(**kwargs):
            with real_temporary_file(**kwargs) as temporary_file:
                real_write = temporary_file.write

                def interrupted_write(value: str) -> None:
                    real_write(value[:5])
                    raise OSError("synthetic interrupted write")

                with patch.object(temporary_file, "write", side_effect=interrupted_write):
                    yield temporary_file

        with patch.object(archive_index.tempfile, "NamedTemporaryFile", interrupted_temporary_file):
            with self.assertRaisesRegex(OSError, "synthetic interrupted write"):
                archive_index.save_archive_index([], self.index_path)
        self.assert_original_preserved()

    def test_serialization_failure_preserves_existing_index(self) -> None:
        with self.assertRaises(TypeError):
            archive_index.save_archive_index([{"unsupported": object()}], self.index_path)
        self.assert_original_preserved()

    def test_initial_creation_and_legacy_list_index_remain_supported(self) -> None:
        new_path = self.index_path.parent / "nested" / "new.json"
        self.assertEqual(archive_index.load_archive_index(new_path), [])
        self.assertEqual(json.loads(new_path.read_text(encoding="utf-8")), {"posts": []})
        self.index_path.write_text(json.dumps(self.original), encoding="utf-8")
        self.assertEqual(archive_index.load_archive_index(self.index_path), self.original)

    def test_upsert_and_remove_preserve_public_helpers(self) -> None:
        replacement = {"id": "old", "title": "바뀐 글", "article_key": "1:2"}
        self.assertEqual(archive_index.upsert_archive_entry(replacement, self.index_path), [replacement])
        self.assertTrue(archive_index.has_article_key("1:2", self.index_path))
        self.assertEqual(archive_index.remove_archive_entry("old", self.index_path), [])
        self.assertEqual(archive_index.load_archive_index(self.index_path), [])


if __name__ == "__main__":
    unittest.main()
