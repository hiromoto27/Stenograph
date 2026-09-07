"""Persistent task profiles — LOGIC.md §6/14 under %LOCALAPPDATA%/Stenograf."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stenograf"
    return Path.home() / ".stenograf"


def tasks_path() -> Path:
    return data_root() / "tasks.json"


def as_weight_dict(raw: Any) -> dict[str, float]:
    """Normalize positive/negative to dict[str,float]. list→dict: each token count 1.0."""
    if isinstance(raw, dict):
        out: dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(raw, list):
        out = {}
        for item in raw:
            s = str(item)
            out[s] = out.get(s, 0.0) + 1.0
        return out
    return {}


DEFAULT_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "t-kitchen",
        "title": "Ремонт кухни",
        "notes": "",
        "positive": {"кухн": 1.0, "ремонт": 1.0},
        "negative": {},
        "hits": 0,
        "misses": 0,
        "links": [],
    },
    {
        "task_id": "t-buy",
        "title": "Закупка материалов",
        "notes": "",
        "positive": {"закуп": 1.0, "материал": 1.0},
        "negative": {},
        "hits": 0,
        "misses": 0,
        "links": [],
    },
    {
        "task_id": "t-report",
        "title": "Отчёт руководству",
        "notes": "",
        "positive": {"отчет": 1.0, "отчёт": 1.0, "руковод": 1.0},
        "negative": {},
        "hits": 0,
        "misses": 0,
        "links": [],
    },
]


def _normalize_task(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(t["task_id"]),
        "title": str(t.get("title") or t["task_id"]),
        "notes": str(t.get("notes") or ""),
        "positive": as_weight_dict(t.get("positive")),
        "negative": as_weight_dict(t.get("negative")),
        "hits": int(t.get("hits") or 0),
        "misses": int(t.get("misses") or 0),
        "links": list(t.get("links") or []),
        "remind_at": t.get("remind_at"),
    }


def load_tasks() -> list[dict[str, Any]]:
    path = tasks_path()
    if not path.exists():
        save_tasks([dict(t) for t in DEFAULT_TASKS])
        return [_normalize_task(t) for t in DEFAULT_TASKS]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks = data.get("tasks") if isinstance(data, dict) else data
        if not isinstance(tasks, list) or not tasks:
            return [_normalize_task(t) for t in DEFAULT_TASKS]
        out = []
        for t in tasks:
            if not isinstance(t, dict) or not t.get("task_id"):
                continue
            out.append(_normalize_task(t))
        return out or [_normalize_task(t) for t in DEFAULT_TASKS]
    except Exception:
        return [_normalize_task(t) for t in DEFAULT_TASKS]


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    path = tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for t in tasks:
        if not isinstance(t, dict) or not t.get("task_id"):
            continue
        row = dict(t)
        row["positive"] = as_weight_dict(row.get("positive"))
        row["negative"] = as_weight_dict(row.get("negative"))
        normalized.append(row)
    path.write_text(json.dumps({"tasks": normalized}, ensure_ascii=False, indent=2), encoding="utf-8")


def create_task(tasks: list[dict[str, Any]], title: str) -> dict[str, Any]:
    tid = f"t-{uuid.uuid4().hex[:8]}"
    task = {
        "task_id": tid,
        "title": title.strip() or "Новая задача",
        "notes": "",
        "positive": {},
        "negative": {},
        "hits": 0,
        "misses": 0,
        "links": [],
        "remind_at": None,
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def level_label(hits: int, misses: int) -> str:
    total = hits + misses
    if total < 3:
        return "Новичок"
    rate = 100.0 * hits / total
    if rate >= 85:
        return "Эксперт"
    if rate >= 70:
        return "Уверенный"
    if rate >= 50:
        return "Учится"
    return "Новичок"
