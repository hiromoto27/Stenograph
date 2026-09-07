"""ASR job queue. Invariant: capture never waits on this queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Callable
import time
import uuid


@dataclass
class AsrJob:
    id: str
    wav_path: Path
    language: str = "ru"
    created_at: float = field(default_factory=time.time)


@dataclass
class AsrResult:
    job_id: str
    text: str
    confidence: float | None
    backend: str
    error: str | None = None


class AsrQueue:
    def __init__(self, worker_fn: Callable[[AsrJob], AsrResult] | None = None) -> None:
        self._q: Queue[AsrJob] = Queue()
        self._results: Queue[AsrResult] = Queue()
        self._stop = Event()
        self._worker_fn = worker_fn or stub_asr
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="asr-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def enqueue(self, wav_path: Path, language: str = "ru") -> AsrJob:
        job = AsrJob(id=str(uuid.uuid4()), wav_path=wav_path, language=language)
        self._q.put(job)
        return job

    def pending(self) -> int:
        return self._q.qsize()

    def poll_result(self, timeout: float = 0.0) -> AsrResult | None:
        try:
            return self._results.get(timeout=timeout)
        except Empty:
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.2)
            except Empty:
                continue
            try:
                result = self._worker_fn(job)
            except Exception as exc:  # noqa: BLE001
                result = AsrResult(
                    job_id=job.id,
                    text="",
                    confidence=None,
                    backend="error",
                    error=str(exc),
                )
            self._results.put(result)
            self._q.task_done()


def stub_asr(job: AsrJob) -> AsrResult:
    """Placeholder until whisper.cpp OpenVINO is wired."""
    return AsrResult(
        job_id=job.id,
        text=f"[stub ASR] {job.wav_path.name}",
        confidence=None,
        backend="stub",
    )
