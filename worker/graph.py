"""Map edges — LOGIC.md §10: auto-edges by similarity + map_links − hidden_pairs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from worker.tokens import cosine

AUTO_EDGE_THRESHOLD = 0.18


def _pos_bag(task: dict[str, Any]) -> Counter[str]:
    return Counter({str(k): float(v) for k, v in dict(task.get("positive") or {}).items()})


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def build_edges(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manual links (LOGIC.md §10 drag-link) + auto-edges by cosine similarity,
    minus hidden_pairs (clicked-away edges). One entry per unordered pair.
    """
    by_id = {t["task_id"]: t for t in tasks}
    hidden: set[tuple[str, str]] = set()
    manual: set[tuple[str, str]] = set()
    for t in tasks:
        tid = t["task_id"]
        for other in t.get("hidden_pairs") or []:
            if other in by_id:
                hidden.add(_pair_key(tid, other))
        for other in t.get("links") or []:
            if other in by_id:
                manual.add(_pair_key(tid, other))

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for key in manual:
        a, b = key
        edges[key] = {"a": a, "b": b, "weight": 1.0, "kind": "manual"}

    ids = [t["task_id"] for t in tasks]
    bags = {tid: _pos_bag(by_id[tid]) for tid in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            key = _pair_key(a, b)
            if key in edges or key in hidden:
                continue
            weight = cosine(bags[a], bags[b])
            if weight >= AUTO_EDGE_THRESHOLD:
                edges[key] = {"a": key[0], "b": key[1], "weight": round(weight, 4), "kind": "auto"}

    return sorted(edges.values(), key=lambda e: -e["weight"])


def circle_layout(tasks: list[dict[str, Any]], *, radius: float = 200.0, center: tuple[float, float] = (0.0, 0.0)) -> dict[str, tuple[float, float]]:
    """LOGIC.md §10 — hub in the center, tasks spaced evenly around a circle."""
    import math

    cx, cy = center
    n = len(tasks)
    positions: dict[str, tuple[float, float]] = {}
    for i, t in enumerate(tasks):
        angle = (2 * math.pi * i / n) - (math.pi / 2) if n else 0.0
        positions[t["task_id"]] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    return positions
