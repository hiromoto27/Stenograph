"""Smoke tests for worker/meetings.py — LOGIC.md §8."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.meetings import PROTOCOL_PAUSE_SEC, MeetingTracker


class TestMeetingTracker(unittest.TestCase):
    def test_start_assigns_id_and_open_meeting(self) -> None:
        mt = MeetingTracker()
        self.assertIsNone(mt.meeting_id)
        meeting = mt.start("Планёрка")
        self.assertEqual(mt.meeting_id, meeting.meeting_id)
        self.assertEqual(meeting.title, "Планёрка")
        self.assertIsNone(meeting.ended_at)

    def test_end_closes_and_moves_to_history(self) -> None:
        mt = MeetingTracker()
        mt.start("X")
        ended = mt.end()
        self.assertIsNotNone(ended)
        self.assertIsNotNone(ended.ended_at)
        self.assertIsNone(mt.meeting_id)
        self.assertIn(ended, mt.history)

    def test_start_without_title_defaults(self) -> None:
        mt = MeetingTracker()
        meeting = mt.start("")
        self.assertEqual(meeting.title, "Встреча")

    def test_note_utterance_tags_current_meeting(self) -> None:
        mt = MeetingTracker()
        mt.start("Y")
        mt.note_utterance("u1")
        mt.note_utterance("u2")
        self.assertEqual(mt.current.utterance_ids, ["u1", "u2"])

    def test_note_utterance_without_meeting_is_noop(self) -> None:
        mt = MeetingTracker()
        mt.note_utterance("u1")  # must not raise
        self.assertIsNone(mt.current)

    def test_check_pause_fires_once_per_gap(self) -> None:
        mt = MeetingTracker(pause_sec=8.0)
        self.assertEqual(mt.pause_sec, PROTOCOL_PAUSE_SEC)
        mt.start("Z")
        mt.note_utterance("u1")
        t0 = mt._last_utterance_at
        self.assertFalse(mt.check_pause(now=t0 + 7.9))
        self.assertTrue(mt.check_pause(now=t0 + 8.0))
        # already suggested for this gap — no repeat until a new utterance resets it
        self.assertFalse(mt.check_pause(now=t0 + 20.0))
        mt.note_utterance("u2")
        self.assertFalse(mt.check_pause(now=mt._last_utterance_at + 0.1))

    def test_check_pause_requires_open_meeting_with_utterance(self) -> None:
        mt = MeetingTracker(pause_sec=8.0)
        self.assertFalse(mt.check_pause(now=1000.0))
        mt.start("no utterances yet")
        self.assertFalse(mt.check_pause(now=1000.0))

    def test_restarting_open_meeting_closes_previous(self) -> None:
        mt = MeetingTracker()
        first = mt.start("A")
        second = mt.start("B")
        self.assertNotEqual(first.meeting_id, second.meeting_id)
        self.assertIn(first, mt.history)
        self.assertIsNotNone(first.ended_at)


if __name__ == "__main__":
    unittest.main()
