"""Utterance archive — LOGIC.md §14: 400 utterances, JSON export/import,
snapshot excludes anything still recording/unclarified (only finalized,
already-classified utterances ever get appended here).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from worker.tasks_store import data_root, load_tasks, save_tasks

MAX_UTTERANCES = 400


def archive_path() -> Path:
    return data_root() / "archive.json"


def load_archive() -> list[dict[str, Any]]:
    path = archive_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("archive") if isinstance(data, dict) else data
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    except Exception:
        return []


def save_archive(rows: list[dict[str, Any]]) -> None:
    path = archive_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    capped = rows[-MAX_UTTERANCES:]
    path.write_text(json.dumps({"archive": capped}, ensure_ascii=False, indent=2), encoding="utf-8")


def append_utterance(
    *,
    job_id: str,
    text: str,
    meeting_id: str | None = None,
    kind: str = "speech",
    kind_score: float = 0.0,
    task_id: str = "",
    task_title: str = "",
) -> None:
    rows = load_archive()
    rows.append(
        {
            "job_id": job_id,
            "text": text,
            "ts": time.time(),
            "meeting_id": meeting_id or "",
            "kind": kind,
            "kind_score": kind_score,
            "task_id": task_id,
            "task_title": task_title,
        }
    )
    save_archive(rows)


def set_task(job_id: str, task_id: str, task_title: str) -> None:
    """Back-fill task assignment onto an already-archived utterance."""
    rows = load_archive()
    changed = False
    for row in rows:
        if row.get("job_id") == job_id:
            row["task_id"] = task_id
            row["task_title"] = task_title
            changed = True
    if changed:
        save_archive(rows)


def export_json(dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {"tasks": load_tasks(), "archive": load_archive()}
    dest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def import_json(src: Path) -> dict[str, int]:
    src = Path(src)
    data = json.loads(src.read_text(encoding="utf-8"))
    tasks = data.get("tasks") if isinstance(data, dict) else None
    archive = data.get("archive") if isinstance(data, dict) else None
    if isinstance(tasks, list):
        save_tasks(tasks)
    if isinstance(archive, list):
        save_archive([r for r in archive if isinstance(r, dict)])
    return {
        "tasks": len(tasks) if isinstance(tasks, list) else 0,
        "archive": len(archive) if isinstance(archive, list) else 0,
    }
