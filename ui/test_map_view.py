"""Smoke tests for ui/map_view.py — LOGIC.md §10 (Flet map tab)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import flet as ft

from ui.map_view import MapView, circle_positions


class TestCirclePositions(unittest.TestCase):
    def test_equally_spaced_around_center(self) -> None:
        pos = circle_positions(["a", "b", "c", "d"], radius=100.0, center=(0.0, 0.0))
        self.assertEqual(len(pos), 4)
        for x, y in pos.values():
            self.assertAlmostEqual((x**2 + y**2) ** 0.5, 100.0, places=6)

    def test_empty(self) -> None:
        self.assertEqual(circle_positions([], radius=100.0), {})


class TestMapView(unittest.TestCase):
    def _view(self) -> MapView:
        return MapView(on_link=lambda a, b: None, on_hide_pair=lambda a, b: None)

    def test_set_state_builds_hub_nodes_and_edges(self) -> None:
        mv = self._view()
        nodes = [
            {"task_id": "a", "title": "A", "essence": "A"},
            {"task_id": "b", "title": "B", "essence": "B"},
        ]
        edges = [{"a": "a", "b": "b", "weight": 0.5, "kind": "auto"}]
        mv.set_state(nodes, edges)
        # hub (1) + edges (1) + nodes (2) = 4 stack children
        self.assertEqual(len(mv.stack.controls), 4)

    def test_edge_referencing_unknown_node_is_skipped(self) -> None:
        mv = self._view()
        nodes = [{"task_id": "a", "title": "A", "essence": "A"}]
        edges = [{"a": "a", "b": "ghost", "weight": 0.9, "kind": "auto"}]
        mv.set_state(nodes, edges)
        # hub (1) + node (1), the dangling edge is dropped
        self.assertEqual(len(mv.stack.controls), 2)

    def test_zoom_is_clamped(self) -> None:
        mv = self._view()
        mv.set_state([{"task_id": "a", "title": "A"}], [])
        for _ in range(20):
            mv.zoom(0.1)
        self.assertLessEqual(mv.scale, 1.6)
        for _ in range(40):
            mv.zoom(-0.1)
        self.assertGreaterEqual(mv.scale, 0.6)

    def test_reset_restores_default_scale(self) -> None:
        mv = self._view()
        mv.set_state([{"task_id": "a", "title": "A"}], [])
        mv.zoom(0.5)
        mv.reset()
        self.assertEqual(mv.scale, 1.0)


if __name__ == "__main__":
    unittest.main()
