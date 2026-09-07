"""Task essence for the map node — LOGIC.md §10: «без короче/типа», не простыня."""

from __future__ import annotations

import re
from typing import Any

# Filler words to strip — same spirit as src/lib/essence.ts in the sandbox preview.
_FILLERS = (
    "короче", "типа", "как бы", "в общем", "в общем-то", "ну", "вот",
    "значит", "собственно", "это самое", "получается", "грубо говоря",
)
_FILLER_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in _FILLERS) + r")\b", re.I)
_WS_RE = re.compile(r"\s+")

MAX_LEN = 42


def _strip_fillers(text: str) -> str:
    out = _FILLER_RE.sub("", text)
    out = out.replace(" ,", ",").strip(" ,.-")
    return _WS_RE.sub(" ", out).strip()


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def task_essence(task: dict[str, Any], *, top_n: int = 3) -> str:
    """Short phrase for the map node — the title if it's already tight, else the
    strongest positive-profile keywords (LOGIC.md §6 dict[str,float])."""
    title = _strip_fillers(str(task.get("title") or ""))
    if title and len(title) <= MAX_LEN:
        return _capitalize(title)

    pos = task.get("positive") or {}
    if isinstance(pos, dict) and pos:
        ranked = sorted(pos.items(), key=lambda kv: -float(kv[1] or 0))
        keywords = [str(k) for k, _ in ranked[:top_n] if len(str(k)) >= 3]
        if keywords:
            phrase = " · ".join(keywords)
            return _capitalize(phrase[:MAX_LEN].rstrip(" ·"))

    if title:
        return _capitalize(title[: MAX_LEN - 1].rstrip() + "…")

    return str(task.get("task_id") or "?")
