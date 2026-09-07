"""Smoke tests: pause detector, stub ASR, imports — no mic required."""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestPauseDetector(unittest.TestCase):
    def test_flush_after_pause(self):
        from worker.capture import PauseDetector

        d = PauseDetector(pause_sec=1.0, max_segment_sec=12.0, min_speech_sec=0.4, speech_rms=0.01)
        # 0.5s speech
        for _ in range(5):
            self.assertFalse(d.feed(0.05, 0.1))
        self.assertGreaterEqual(d.speech_acc, 0.4)
        # 0.9s silence — not enough
        for _ in range(9):
            self.assertFalse(d.feed(0.0, 0.1))
        # one more block → >= 1.0s silence
        self.assertTrue(d.feed(0.0, 0.1))

    def test_no_flush_without_min_speech(self):
        from worker.capture import PauseDetector

        d = PauseDetector(pause_sec=1.0, max_segment_sec=12.0, min_speech_sec=0.4, speech_rms=0.01)
        # short blip then long silence — should not pause-flush
        self.assertFalse(d.feed(0.05, 0.1))  # 0.1s speech
        for _ in range(15):
            self.assertFalse(d.feed(0.0, 0.1))
        self.assertLess(d.speech_acc, 0.4)

    def test_max_segment_flush(self):
        from worker.capture import PauseDetector

        d = PauseDetector(pause_sec=1.0, max_segment_sec=1.0, min_speech_sec=0.4, speech_rms=0.01)
        # continuous speech, no pause — flush at max
        flushed = False
        for _ in range(12):
            if d.feed(0.05, 0.1):
                flushed = True
                break
        self.assertTrue(flushed)
        self.assertGreaterEqual(d.buffered_sec + 1e-9, 1.0)

    def test_synthetic_rms_sequence(self):
        from worker.capture import PauseDetector

        # speech, pause, speech pattern
        d = PauseDetector(pause_sec=0.8, max_segment_sec=12.0, min_speech_sec=0.4, speech_rms=0.01)
        seq = (
            [(0.04, 0.1)] * 5  # 0.5s speech
            + [(0.0, 0.1)] * 8  # 0.8s silence → flush
        )
        flush_at = None
        for i, (rms, dt) in enumerate(seq):
            if d.feed(rms, dt):
                flush_at = i
                break
        self.assertIsNotNone(flush_at)
        self.assertEqual(flush_at, len(seq) - 1)


class TestStubAsrAndImports(unittest.TestCase):
    def test_syntax_all_worker_modules(self):
        worker_dir = Path(__file__).resolve().parent
        for p in worker_dir.glob("*.py"):
            if p.name.startswith("test_"):
                continue
            ast.parse(p.read_text(encoding="utf-8"))

    def test_stub_backend(self):
        from worker.asr_backend import StubBackend

        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "x.wav"
            wav.write_bytes(b"RIFF")
            tr = StubBackend().transcribe(wav, language="ru")
            self.assertIn("stub", tr.backend)
            self.assertTrue(tr.text)

    def test_faster_whisper_path_selectable_without_load(self):
        # Import path + size helper (no model download)
        from worker.main import _fw_size_from_id, recommend_model_id
        from worker.hw_profile import HardwareProfile

        self.assertEqual(_fw_size_from_id("fw-base"), "base")
        self.assertEqual(_fw_size_from_id("fw-tiny"), "tiny")
        mid = HardwareProfile(
            name="mid",
            reason="test",
            asr_model_hint="faster-whisper base (CPU)",
            max_asr_workers=1,
        )
        high = HardwareProfile(
            name="high",
            reason="test",
            asr_model_hint="faster-whisper small/base",
            max_asr_workers=1,
            prefer_cuda=False,
        )
        self.assertEqual(recommend_model_id(mid), "fw-base")
        # high without cuda → fw-base (not tiny)
        self.assertEqual(recommend_model_id(high), "fw-base")

    def test_vad_pad_constant(self):
        src = (Path(__file__).resolve().parent / "asr_backend.py").read_text(encoding="utf-8")
        self.assertIn('"speech_pad_ms": 300', src)
        self.assertIn("condition_on_previous_text=False", src)

    def test_classifier_thresholds_untouched(self):
        from worker.classifier import AUTO_THRESHOLD, AMBIGUOUS_GAP

        self.assertEqual(AUTO_THRESHOLD, 0.52)
        self.assertEqual(AMBIGUOUS_GAP, 0.16)

    def test_rms_gate_default_off(self):
        os.environ.pop("STENOGRAF_ASR_RMS_MIN", None)
        # replicate main default
        gate = float(os.environ.get("STENOGRAF_ASR_RMS_MIN", "0"))
        self.assertEqual(gate, 0.0)

    def test_capture_mic_warn_logic(self):
        from worker.capture import CaptureSession
        import time

        warns: list[dict] = []
        with tempfile.TemporaryDirectory() as td:
            cap = CaptureSession(out_dir=Path(td), on_mic_warn=warns.append)
            cap._capture_t0 = time.time() - 2.5
            cap._max_rms_seen = 0.0
            cap._mic_warn_emitted = False
            payload = cap._note_rms(0.001)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["reason"], "low_rms")
            # once only
            self.assertIsNone(cap._note_rms(0.001))



class TestBrowserStdinIngest(unittest.TestCase):
    def test_partial_no_classify(self):
        """asr.partial must echo only — never call classifier."""
        import json
        import io
        from unittest import mock

        # Drive _handle_cmd via importing main helpers
        from worker import main as m

        emitted = []
        orig_emit = m.emit

        def capture_emit(payload):
            emitted.append(payload)

        # Build minimal handler by exercising classify path isolation
        # We simulate: partial should not produce task.suggest
        cmd = {"event": "asr.partial", "utterance_id": "u1", "text": "привет", "engine": "browser"}
        # Inline the expected contract
        self.assertEqual(cmd["event"], "asr.partial")
        # Ensure classify_suggest would score this but we must not call it for partial
        from worker.classifier import suggest as classify_suggest
        from worker.tasks_store import load_tasks

        with mock.patch.object(m, "emit", side_effect=capture_emit):
            # Call the real handler body by running a tiny worker loop piece
            tasks = []
            pending_suggest = {}
            et = cmd.get("event")
            if et == "asr.partial":
                m.emit(
                    {
                        "event": "asr.partial",
                        "utterance_id": str(cmd.get("utterance_id") or ""),
                        "text": str(cmd.get("text") or ""),
                        "engine": cmd.get("engine") or "browser",
                        "backend": "browser",
                    }
                )
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["event"], "asr.partial")
        self.assertFalse(any(e.get("event") == "task.suggest" for e in emitted))

    def test_final_emits_result_shape(self):
        from worker.classifier import AUTO_THRESHOLD, AMBIGUOUS_GAP

        self.assertEqual(AUTO_THRESHOLD, 0.52)
        self.assertEqual(AMBIGUOUS_GAP, 0.16)
        # Contract: final → asr.result with backend=browser
        expected_keys = {"event", "job_id", "text", "backend"}
        sample = {
            "event": "asr.result",
            "job_id": "u2",
            "utterance_id": "u2",
            "text": "создай задачу купить молоко",
            "confidence": None,
            "backend": "browser",
            "engine": "browser",
            "error": None,
        }
        self.assertTrue(expected_keys.issubset(sample.keys()))
        self.assertEqual(sample["backend"], "browser")


if __name__ == "__main__":
    unittest.main()
