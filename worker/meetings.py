"""Meetings — LOGIC.md §8. meeting_id on utterances; protocol pause (~8s)
is a *different* number from the STT pause (~1s, worker/capture.py).

The «Протокол» button must always work (LOGIC.md §8), meeting or not —
this module only adds the meeting_id tag and the pause_suggest nudge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time
import uuid

PROTOCOL_PAUSE_SEC = 8.0  # LOGIC.md §8 — distinct from capture.py pause_sec (~1s)


@dataclass
class Meeting:
    meeting_id: str
    title: str
    started_at: float
    ended_at: float | None = None
    utterance_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "title": self.title,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "utterance_count": len(self.utterance_ids),
        }


class MeetingTracker:
    """Tracks the current (at most one) open meeting and the protocol-pause gap."""

    def __init__(self, pause_sec: float = PROTOCOL_PAUSE_SEC) -> None:
        self.pause_sec = float(pause_sec)
        self.current: Meeting | None = None
        self.history: list[Meeting] = []
        self._last_utterance_at: float | None = None
        self._pause_suggested = False

    @property
    def meeting_id(self) -> str | None:
        return self.current.meeting_id if self.current else None

    def start(self, title: str = "") -> Meeting:
        if self.current is not None:
            self.end()
        meeting = Meeting(
            meeting_id=f"m-{uuid.uuid4().hex[:8]}",
            title=title.strip() or "Встреча",
            started_at=time.time(),
        )
        self.current = meeting
        self._last_utterance_at = None
        self._pause_suggested = False
        return meeting

    def end(self) -> Meeting | None:
        if self.current is None:
            return None
        meeting = self.current
        meeting.ended_at = time.time()
        self.history.append(meeting)
        self.current = None
        self._last_utterance_at = None
        self._pause_suggested = False
        return meeting

    def note_utterance(self, utterance_id: str) -> None:
        """Attach the utterance to the open meeting (if any) and reset the pause clock."""
        self._last_utterance_at = time.time()
        self._pause_suggested = False
        if self.current is not None:
            self.current.utterance_ids.append(utterance_id)

    def check_pause(self, now: float | None = None) -> bool:
        """True once per silence gap when the protocol pause (8s) has been crossed.

        Only fires while a meeting is open and at least one utterance has landed —
        an empty meeting has nothing to suggest packaging for.
        """
        if self.current is None or self._last_utterance_at is None or self._pause_suggested:
            return False
        now = now if now is not None else time.time()
        if now - self._last_utterance_at >= self.pause_sec:
            self._pause_suggested = True
            return True
        return False
