"""Smoke tests for worker/essence.py + worker/graph.py — LOGIC.md §10."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.essence import task_essence
from worker.graph import build_edges, circle_layout


class TestEssence(unittest.TestCase):
    def test_short_title_used_as_is(self) -> None:
        self.assertEqual(task_essence({"title": "Ремонт кухни"}), "Ремонт кухни")

    def test_strips_filler_words(self) -> None:
        out = task_essence({"title": "короче, ремонт кухни типа"})
        self.assertNotIn("короче", out.lower())
        self.assertNotIn("типа", out.lower())

    def test_long_title_falls_back_to_keywords(self) -> None:
        long_title = "Очень длинное название задачи которое явно превышает лимит символов для узла карты"
        out = task_essence({"title": long_title, "positive": {"кухн": 5.0, "ремонт": 3.0, "плитк": 1.0}})
        self.assertLessEqual(len(out), 42)
        self.assertTrue(out)

    def test_no_title_no_positive_falls_back_to_id(self) -> None:
        self.assertEqual(task_essence({"task_id": "t-1"}), "t-1")


class TestGraph(unittest.TestCase):
    def _tasks(self):
        return [
            {"task_id": "a", "title": "A", "positive": {"кухн": 3.0, "ремонт": 2.0}, "links": [], "hidden_pairs": []},
            {"task_id": "b", "title": "B", "positive": {"кухн": 2.0, "ремонт": 1.0}, "links": [], "hidden_pairs": []},
            {"task_id": "c", "title": "C", "positive": {"отчет": 3.0}, "links": [], "hidden_pairs": []},
        ]

    def test_similar_tasks_get_auto_edge(self) -> None:
        edges = build_edges(self._tasks())
        pair = {(e["a"], e["b"]) for e in edges}
        self.assertIn(("a", "b"), pair)
        self.assertNotIn(("a", "c"), pair)
        self.assertNotIn(("b", "c"), pair)

    def test_manual_link_always_present(self) -> None:
        tasks = self._tasks()
        tasks[2]["links"] = ["a"]  # c manually linked to a despite low similarity
        tasks[0]["links"] = ["c"]
        edges = build_edges(tasks)
        manual = [e for e in edges if e["kind"] == "manual"]
        self.assertEqual(len(manual), 1)
        self.assertEqual((manual[0]["a"], manual[0]["b"]), ("a", "c"))

    def test_hidden_pair_suppresses_auto_edge(self) -> None:
        tasks = self._tasks()
        tasks[0]["hidden_pairs"] = ["b"]
        tasks[1]["hidden_pairs"] = ["a"]
        edges = build_edges(tasks)
        pair = {(e["a"], e["b"]) for e in edges}
        self.assertNotIn(("a", "b"), pair)

    def test_manual_link_survives_hidden_pair_conflict(self) -> None:
        # a user can still hide an edge they manually created — manual wins the
        # dict key first, so a hidden_pairs entry for the same pair is a no-op.
        tasks = self._tasks()
        tasks[0]["links"] = ["b"]
        tasks[1]["links"] = ["a"]
        edges = build_edges(tasks)
        pair = {(e["a"], e["b"]): e for e in edges}
        self.assertIn(("a", "b"), pair)
        self.assertEqual(pair[("a", "b")]["kind"], "manual")

    def test_circle_layout_spaces_tasks_around_center(self) -> None:
        tasks = self._tasks()
        pos = circle_layout(tasks, radius=100.0, center=(0.0, 0.0))
        self.assertEqual(len(pos), 3)
        for x, y in pos.values():
            dist = (x ** 2 + y ** 2) ** 0.5
            self.assertAlmostEqual(dist, 100.0, places=6)

    def test_circle_layout_empty(self) -> None:
        self.assertEqual(circle_layout([]), {})


if __name__ == "__main__":
    unittest.main()
