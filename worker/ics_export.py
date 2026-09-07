"""Minimal .ics (iCalendar, RFC 5545) writer — LOGIC.md §11. No external deps."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid


def _fold(line: str) -> str:
    """RFC 5545 §3.1 line folding at 75 octets."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out = []
    while line:
        chunk, line = line[:74], line[74:]
        out.append(chunk if not out else " " + chunk)
    return "\r\n".join(out)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _dt_stamp(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def task_to_vevent(task: dict[str, Any]) -> str | None:
    """One VEVENT for a task's due_at (fallback remind_at); None if neither is set."""
    when = task.get("due_at") or task.get("remind_at")
    if not when:
        return None
    try:
        when = float(when)
    except (TypeError, ValueError):
        return None
    uid = f"{task.get('task_id') or uuid.uuid4().hex}@stenograf"
    lines = [
        "BEGIN:VEVENT",
        _fold(f"UID:{uid}"),
        f"DTSTAMP:{_dt_stamp(datetime.now(tz=timezone.utc).timestamp())}",
        f"DTSTART:{_dt_stamp(when)}",
        _fold(f"SUMMARY:{_escape(task.get('title') or task.get('task_id') or 'Задача')}"),
    ]
    notes = task.get("notes")
    if notes:
        lines.append(_fold(f"DESCRIPTION:{_escape(notes)}"))
    repeat_min = task.get("repeat_min")
    if repeat_min:
        try:
            freq_min = int(repeat_min)
            if freq_min > 0:
                lines.append(f"RRULE:FREQ=MINUTELY;INTERVAL={freq_min}")
        except (TypeError, ValueError):
            pass
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def export_ics(tasks: list[dict[str, Any]], dest: Path) -> Path:
    """Export all tasks carrying due_at/remind_at as one .ics calendar."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    events = [v for v in (task_to_vevent(t) for t in tasks) if v]
    body = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Stenograf//ru",
        "CALSCALE:GREGORIAN",
        *events,
        "END:VCALENDAR",
    ]
    dest.write_text("\r\n".join(body) + "\r\n", encoding="utf-8")
    return dest
