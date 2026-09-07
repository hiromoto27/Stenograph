"""Spawn worker and parse JSON-line events from stdout; optional stdin commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

EventHandler = Callable[[dict[str, Any]], None]


class WorkerClient:
    """Interim IPC: worker emits JSON lines on stdout; UI may send JSON on stdin."""

    def __init__(
        self,
        worker_cwd: Path | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.worker_cwd = worker_cwd or Path.cwd()
        self.on_event = on_event
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(
        self,
        *,
        mic_id: str | None = None,
        seconds: float | None = None,
        segment_sec: float = 3.0,
        model_id: str | None = None,
        stt_engine: str | None = None,
    ) -> None:
        if self.running:
            return
        cmd = [sys.executable, "-m", "worker.main", "--segment-sec", str(segment_sec)]
        if mic_id:
            cmd.extend(["--device", str(int(mic_id)) if str(mic_id).isdigit() else mic_id])
        if seconds is not None:
            cmd.extend(["--seconds", str(seconds)])
        if model_id:
            cmd.extend(["--model-id", str(model_id)])
        if stt_engine:
            cmd.extend(["--stt-engine", str(stt_engine)])
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.worker_cwd) + os.pathsep + env.get("PYTHONPATH", "")
        if model_id:
            env["STENOGRAF_MODEL_ID"] = str(model_id)
        if stt_engine:
            env["STENOGRAF_STT_ENGINE"] = str(stt_engine)
        self._stop.clear()
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.worker_cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def send(self, event: dict[str, Any]) -> None:
        """Send a JSON command to worker stdin (task.assign / create / skip / …)."""
        if not self._proc or not self._proc.stdin or self._proc.poll() is not None:
            return
        line = json.dumps(event, ensure_ascii=True) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except OSError:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if self.on_event:
                self.on_event(event)
