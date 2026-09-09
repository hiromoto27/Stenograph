import sys
import types
import wave

import pytest

from stenograph.audio import Capture
from stenograph.db import Database
from stenograph.intelligence import LocalLLM
from stenograph.jobs import Analyze


def test_capture_stop_flushes_final_short_chunk(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    mid = db.new_meeting("Остановка посреди фрагмента")
    capture = Capture(db, tmp_path, mid, "Микрофон", 0, 10, 0)

    class FakeStream:
        calls = 0

        def read(self, frames, exception_on_overflow):
            self.calls += 1
            if self.calls == 2:
                capture.stop()
            return bytes(frames * 2)

        def stop_stream(self):
            pass

        def close(self):
            pass

    class FakeAudio:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_device_info_by_index(self, index):
            return {"maxInputChannels": 1, "defaultSampleRate": 16000}

        def open(self, **kwargs):
            return FakeStream()

    monkeypatch.setitem(sys.modules, "pyaudiowpatch", types.SimpleNamespace(PyAudio=FakeAudio, paInt16=8))
    capture.run()
    chunks = db.rows("SELECT * FROM chunks")
    assert len(chunks) == 1
    assert chunks[0]["duration"] == pytest.approx(0.2)
    with wave.open(chunks[0]["path"]) as recorded:
        assert recorded.getnframes() == 3200


def test_analysis_failure_on_later_batch_leaves_no_partial_report(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    mid = db.new_meeting("Длинная встреча")
    db.add_text(mid, "\n".join(["Решили обсудить задачу. " * 70 for _ in range(8)]))
    calls = []

    def extract(self, segments):
        calls.append(segments)
        if len(calls) == 2:
            raise ValueError("Ошибка второго фрагмента")
        return {key: [] for key in ["summary", "decisions", "questions", "tasks", "steps", "topics"]}

    monkeypatch.setattr(LocalLLM, "check", lambda self: None)
    monkeypatch.setattr(LocalLLM, "extract", extract)
    worker = Analyze(db, mid, "qwen3:4b")
    worker.run()
    assert len(calls) == 2
    assert db.latest_report(mid) is None
    assert db.rows("SELECT * FROM tasks") == []
