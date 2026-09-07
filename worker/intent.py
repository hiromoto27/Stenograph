"""Speech intents — LOGIC.md §2. Intent before classifier."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

_HARD = re.compile(
    r"(?P<verb>сделай|создай|поставь|заведи|добавь|запиши|открой)\s+"
    r"(?:пожалуйста\s+)?(?:новую\s+)?задач[уие]\s*(?P<title>.*)$",
    re.IGNORECASE,
)
_SOFT = re.compile(
    r"(?:^|[\.!?]\s*)(?P<body>[^.!?]*\b(?:необходимо|нужно|надо)\b[^.!?]*)",
    re.IGNORECASE,
)
_MARKERS = re.compile(
    r"^(?:сделай|создай|поставь|заведи|добавь|запиши|открой)\s+"
    r"(?:пожалуйста\s+)?(?:новую\s+)?задач[уие]\s*",
    re.IGNORECASE,
)

_IN_HOURS = re.compile(r"через\s+(\d+)\s*час", re.I)
_IN_MIN = re.compile(r"через\s+(\d+)\s*мин", re.I)
_TOMORROW = re.compile(r"завтра(?:\s+в\s+(\d{1,2})(?::(\d{2}))?)?", re.I)
_AT_CLOCK = re.compile(r"\bв\s+(\d{1,2})(?::(\d{2}))?\b", re.I)


@dataclass
class SpeechIntent:
    kind: str  # none | create_task | remind
    title: str | None = None
    remind_at_iso: str | None = None
    raw: str = ""


def _cap_title(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip(" .,"))
    if not s:
        return ""
    return s[0].upper() + s[1:]


def parse_reminder(text: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now().astimezone()
    t = text or ""
    m = _IN_HOURS.search(t)
    if m:
        return (now + timedelta(hours=int(m.group(1)))).isoformat()
    m = _IN_MIN.search(t)
    if m:
        return (now + timedelta(minutes=int(m.group(1)))).isoformat()
    m = _TOMORROW.search(t)
    if m:
        h = int(m.group(1) or 9)
        mi = int(m.group(2) or 0)
        dt = (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return dt.isoformat()
    if "напомн" in t.lower():
        m = _AT_CLOCK.search(t)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            return dt.isoformat()
    return None


def parse_speech_intent(text: str) -> SpeechIntent:
    raw = (text or "").strip()
    if len(raw) < 2:
        return SpeechIntent(kind="none", raw=raw)

    remind = parse_reminder(raw)
    m = _HARD.search(raw)
    if m:
        title = _cap_title(m.group("title") or "")
        if not title:
            title = "Новая задача"
        return SpeechIntent(kind="create_task", title=title, remind_at_iso=remind, raw=raw)

    m = _SOFT.search(raw)
    if m:
        body = m.group("body")
        body = re.sub(r"\b(?:необходимо|нужно|надо)\b\s*", "", body, flags=re.I)
        title = _cap_title(body)
        if title:
            return SpeechIntent(kind="create_task", title=title, remind_at_iso=remind, raw=raw)

    if remind:
        return SpeechIntent(kind="remind", remind_at_iso=remind, raw=raw)
    return SpeechIntent(kind="none", raw=raw)


def intent_to_dict(intent: SpeechIntent) -> dict[str, Any] | None:
    if intent.kind == "none":
        return None
    d: dict[str, Any] = {"type": intent.kind}
    if intent.title:
        d["title"] = intent.title
    if intent.remind_at_iso:
        d["remind_at"] = intent.remind_at_iso
    return d
