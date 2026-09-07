"""Smoke tests for worker/ics_export.py — LOGIC.md §11."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.ics_export import export_ics, task_to_vevent


class TestIcsExport(unittest.TestCase):
    def test_task_without_dates_has_no_vevent(self) -> None:
        self.assertIsNone(task_to_vevent({"task_id": "t1", "title": "X"}))

    def test_task_with_due_at_renders_vevent(self) -> None:
        vevent = task_to_vevent({"task_id": "t1", "title": "Отчёт", "due_at": 1893456000})
        self.assertIsNotNone(vevent)
        self.assertIn("BEGIN:VEVENT", vevent)
        self.assertIn("SUMMARY:Отчёт", vevent)
        self.assertIn("END:VEVENT", vevent)

    def test_export_ics_writes_valid_calendar(self) -> None:
        tasks = [
            {"task_id": "t1", "title": "A", "due_at": 1893456000},
            {"task_id": "t2", "title": "B", "remind_at": 1893456000, "repeat_min": 60},
            {"task_id": "t3", "title": "C"},  # no dates — skipped
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reminders.ics"
            out = export_ics(tasks, dest)
            content = out.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(content.strip().endswith("END:VCALENDAR"))
        self.assertEqual(content.count("BEGIN:VEVENT"), 2)
        self.assertIn("RRULE:FREQ=MINUTELY;INTERVAL=60", content)

    def test_escapes_special_characters(self) -> None:
        vevent = task_to_vevent({"task_id": "t1", "title": "Купить; молоко, хлеб", "due_at": 1893456000})
        self.assertIn("Купить\\; молоко\\, хлеб", vevent)


if __name__ == "__main__":
    unittest.main()
