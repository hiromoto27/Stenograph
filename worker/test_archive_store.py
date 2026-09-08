"""Smoke tests for worker/archive_store.py — LOGIC.md §14."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import worker.archive_store as archive_store


class TestArchiveStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._root = Path(self._tmp.name)
        patcher = mock.patch("worker.archive_store.data_root", return_value=self._root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_archive_when_no_file(self) -> None:
        self.assertEqual(archive_store.load_archive(), [])

    def test_append_and_load_round_trip(self) -> None:
        archive_store.append_utterance(job_id="j1", text="Привет", kind="speech")
        rows = archive_store.load_archive()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Привет")

    def test_capped_at_400(self) -> None:
        for i in range(405):
            archive_store.append_utterance(job_id=f"j{i}", text=f"line {i}")
        rows = archive_store.load_archive()
        self.assertEqual(len(rows), 400)
        self.assertEqual(rows[-1]["job_id"], "j404")
        self.assertEqual(rows[0]["job_id"], "j5")

    def test_set_task_backfills_assignment(self) -> None:
        archive_store.append_utterance(job_id="j1", text="Купить плитку")
        archive_store.set_task("j1", "t1", "Ремонт кухни")
        rows = archive_store.load_archive()
        self.assertEqual(rows[0]["task_id"], "t1")
        self.assertEqual(rows[0]["task_title"], "Ремонт кухни")

    def test_set_task_unknown_job_id_is_noop(self) -> None:
        archive_store.append_utterance(job_id="j1", text="X")
        archive_store.set_task("unknown", "t1", "Y")
        rows = archive_store.load_archive()
        self.assertEqual(rows[0]["task_id"], "")

    def test_export_import_round_trip(self) -> None:
        with mock.patch("worker.archive_store.load_tasks", return_value=[{"task_id": "t1", "title": "X"}]):
            archive_store.append_utterance(job_id="j1", text="Тест")
            dest = self._root / "exports" / "snapshot.json"
            archive_store.export_json(dest)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(data["tasks"], [{"task_id": "t1", "title": "X"}])
            self.assertEqual(len(data["archive"]), 1)

        with mock.patch("worker.archive_store.save_tasks") as save_tasks_mock:
            counts = archive_store.import_json(dest)
            save_tasks_mock.assert_called_once_with([{"task_id": "t1", "title": "X"}])
        self.assertEqual(counts, {"tasks": 1, "archive": 1})


if __name__ == "__main__":
    unittest.main()
