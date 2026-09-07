"""Map tab — LOGIC.md §10.

Hub in the center, tasks spaced around a circle. Auto-edges by profile
similarity (worker/graph.py) plus manual drag-links, minus hidden_pairs.
Drag a task onto another (~58px) to link them; click an edge to hide it.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import flet as ft

from ui.theme import BG, BORDER, MUTED, OK, SURFACE2, SURFACE3, TEXT

CANVAS_W = 640
CANVAS_H = 460
CENTER = (CANVAS_W / 2.0, CANVAS_H / 2.0)
BASE_RADIUS = 170.0
LINK_DIST_PX = 58.0  # LOGIC.md §10 — drag-to-link threshold
ANIM_MS = 550  # LOGIC.md §10/§7 — new-edge / snap-back animation ~0.55s
NODE_W = 96
NODE_H = 52


def circle_positions(
    node_ids: list[str], *, radius: float, center: tuple[float, float] = CENTER
) -> dict[str, tuple[float, float]]:
    cx, cy = center
    n = len(node_ids)
    out: dict[str, tuple[float, float]] = {}
    for i, tid in enumerate(node_ids):
        angle = (2 * math.pi * i / n) - (math.pi / 2) if n else 0.0
        out[tid] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    return out


class MapView:
    """Stateful Flet control builder for the «Карта» tab."""

    def __init__(
        self,
        *,
        on_link: Callable[[str, str], None],
        on_hide_pair: Callable[[str, str], None],
    ) -> None:
        self.on_link = on_link
        self.on_hide_pair = on_hide_pair
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.scale = 1.0
        self._positions: dict[str, tuple[float, float]] = {}
        self.stack = ft.Stack(width=CANVAS_W, height=CANVAS_H)
        self.hint = ft.Text(
            "Перетащите задачу на задачу — связь. Клик по ребру — скрыть.",
            size=12,
            color=MUTED,
        )

    def set_state(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        self.nodes = nodes
        self.edges = edges
        self._rebuild()

    def zoom(self, delta: float) -> None:
        self.scale = max(0.6, min(1.6, round(self.scale + delta, 2)))
        self._rebuild()

    def reset(self) -> None:
        self.scale = 1.0
        self._rebuild()

    def _rebuild(self) -> None:
        ids = [n["task_id"] for n in self.nodes]
        self._positions = circle_positions(ids, radius=BASE_RADIUS * self.scale)

        controls: list[ft.Control] = [
            ft.Container(
                left=CENTER[0] - 34,
                top=CENTER[1] - 34,
                width=68,
                height=68,
                border_radius=34,
                bgcolor=SURFACE2,
                border=ft.Border.all(1, BORDER),
                alignment=ft.Alignment.CENTER,
                content=ft.Text("Стенограф", size=10, color=MUTED, text_align=ft.TextAlign.CENTER),
            )
        ]
        for edge in self.edges:
            a, b = edge.get("a"), edge.get("b")
            if a not in self._positions or b not in self._positions:
                continue
            controls.append(self._edge_control(a, b, edge))
        for node in self.nodes:
            if node["task_id"] not in self._positions:
                continue
            controls.append(self._node_control(node))

        self.stack.controls = controls
        # No self-update here — the caller's page.update() (studio_app's on_event
        # tail, or a tab switch) applies this once Stack is attached to the page.

    def _edge_control(self, a: str, b: str, edge: dict[str, Any]) -> ft.Control:
        ax, ay = self._positions[a]
        bx, by = self._positions[b]
        dx, dy = bx - ax, by - ay
        length = max(1.0, math.hypot(dx, dy))
        angle = math.atan2(dy, dx)
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        color = OK if edge.get("kind") == "manual" else SURFACE3

        def _hide(_: ft.ControlEvent) -> None:
            self.on_hide_pair(a, b)

        return ft.Container(
            left=mx - length / 2.0,
            top=my - 1,
            width=length,
            height=2,
            bgcolor=color,
            rotate=ft.Rotate(angle=angle, alignment=ft.Alignment.CENTER),
            animate_position=ANIM_MS,
            on_click=_hide,
            tooltip=f"Связь {round(float(edge.get('weight') or 0) * 100)}% — клик скрывает",
        )

    def _node_control(self, node: dict[str, Any]) -> ft.Control:
        tid = node["task_id"]
        x, y = self._positions[tid]
        home_left, home_top = x - NODE_W / 2.0, y - NODE_H / 2.0

        box = ft.Container(
            left=home_left,
            top=home_top,
            width=NODE_W,
            height=NODE_H,
            bgcolor=SURFACE2,
            border=ft.Border.all(1, BORDER),
            border_radius=12,
            padding=6,
            alignment=ft.Alignment.CENTER,
            animate_position=ANIM_MS,
            content=ft.Text(
                node.get("essence") or node.get("title") or tid,
                size=11,
                color=TEXT,
                text_align=ft.TextAlign.CENTER,
                max_lines=3,
            ),
            data=tid,
        )

        def _pan_update(e: ft.DragUpdateEvent) -> None:
            delta = e.local_delta
            if delta is None:
                return
            box.animate_position = None
            box.left = (box.left if box.left is not None else home_left) + delta.x
            box.top = (box.top if box.top is not None else home_top) + delta.y
            box.update()

        def _pan_end(_: ft.ControlEvent) -> None:
            cur_left = box.left if box.left is not None else home_left
            cur_top = box.top if box.top is not None else home_top
            cx, cy = cur_left + NODE_W / 2.0, cur_top + NODE_H / 2.0
            nearest, best_dist = None, None
            for other in self.nodes:
                oid = other["task_id"]
                if oid == tid or oid not in self._positions:
                    continue
                ox, oy = self._positions[oid]
                dist = math.hypot(cx - ox, cy - oy)
                if best_dist is None or dist < best_dist:
                    nearest, best_dist = oid, dist
            box.animate_position = ANIM_MS
            box.left = home_left
            box.top = home_top
            box.update()
            if nearest is not None and best_dist is not None and best_dist <= LINK_DIST_PX:
                self.on_link(tid, nearest)

        return ft.GestureDetector(
            content=box,
            drag_interval=16,
            on_pan_update=_pan_update,
            on_pan_end=_pan_end,
        )

    def control(self) -> ft.Control:
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Карта связей", size=28, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                        ft.Container(expand=True),
                        ft.OutlinedButton("−", width=36, on_click=lambda e: self.zoom(-0.1)),
                        ft.OutlinedButton("+", width=36, on_click=lambda e: self.zoom(0.1)),
                        ft.OutlinedButton("Сброс", on_click=lambda e: self.reset()),
                    ]
                ),
                self.hint,
                ft.Container(
                    content=self.stack,
                    bgcolor=BG,
                    border=ft.Border.all(1, BORDER),
                    border_radius=16,
                    padding=8,
                    width=CANVAS_W + 16,
                    height=CANVAS_H + 16,
                    alignment=ft.Alignment.TOP_LEFT,
                ),
            ],
            spacing=10,
            expand=True,
        )
