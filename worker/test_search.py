"""Smoke tests for worker/search.py — LOGIC.md §12."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.search import search_archive


class TestSearchArchive(unittest.TestCase):
    def _lines(self):
        return [
            {"text": "Нужно купить плитку для кухни", "task_id": "t1"},
            {"text": "Отчёт руководству готов", "task_id": "t2"},
            {"text": "Случайная реплика ни о чём", "task_id": ""},
        ]

    def test_empty_query_returns_nothing(self) -> None:
        self.assertEqual(search_archive("", self._lines()), [])

    def test_matches_ranked_by_stem_overlap(self) -> None:
        out = search_archive("кухня плитка", self._lines())
        self.assertTrue(out)
        self.assertIn("кухни", out[0]["text"])

    def test_no_match_excluded(self) -> None:
        out = search_archive("совершенно другой запрос без пересечений", self._lines())
        texts = [r["text"] for r in out]
        self.assertNotIn("Случайная реплика ни о чём", texts)

    def test_task_bonus_applied(self) -> None:
        tasks = [{"task_id": "t1", "title": "Ремонт кухни", "positive": {"кухн": 1.0}}]
        with_task = search_archive("кухня", self._lines(), tasks)[0]
        without_task = search_archive("кухня", self._lines(), [])[0]
        self.assertGreater(with_task["score"], without_task["score"])

    def test_top_20_cap(self) -> None:
        lines = [{"text": f"кухня номер {i}", "task_id": ""} for i in range(30)]
        out = search_archive("кухня", lines)
        self.assertEqual(len(out), 20)


if __name__ == "__main__":
    unittest.main()
