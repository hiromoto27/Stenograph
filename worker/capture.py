"""Microphone capture → disk segments. Never blocks on ASR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable
import math
import time
import wave


def rms_to_db(rms: float) -> float:
    if rms <= 1e-12:
        return -60.0
    boosted = max(rms * 8.0, 1e-12)
    return max(-60.0, min(0.0, 20.0 * math.log10(boosted)))


def db_to_level(db: float) -> float:
    norm = (db + 60.0) / 60.0
    return max(0.0, min(1.0, norm ** 0.65))


@dataclass
class AudioChunkEvent:
    path: Path
    device_id: int | None
    started_at: float
    rms: float | None = None


class CaptureSession:
    """
    Writes fixed-length WAV segments to disk.
    Emits on_level ~every block_sec for live VU; on_chunk only after a full segment.
    Optional on_chunk callback should only enqueue ASR — never run STT inline.
    """

    def __init__(
        self,
        out_dir: Path,
        device_id: int | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        segment_sec: float = 5.0,
        block_sec: float = 0.08,
        on_chunk: Callable[[AudioChunkEvent], None] | None = None,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.segment_sec = segment_sec
        self.block_sec = block_sec
        self.on_chunk = on_chunk
        self.on_level = on_level
        self._stop = Event()
        self._thread: Thread | None = None

    def list_input_devices(self) -> list[dict]:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            return [{"id": None, "name": "sounddevice not installed - run: pip install sounddevice", "channels": 0, "error": "missing_sounddevice", "hint": "pip install sounddevice"}]

        devices = []
        for i, d in enumerate(sd.query_devices()):
            if int(d.get("max_input_channels", 0)) > 0:
                devices.append(
                    {
                        "id": i,
                        "name": d.get("name"),
                        "channels": d.get("max_input_channels"),
                        "default_samplerate": d.get("default_samplerate"),
                    }
                )
        if not devices:
            return [{"id": None, "name": "No input devices found", "channels": 0, "error": "no_input_devices"}]
        return devices

    def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _emit_level(self, rms: float) -> None:
        if self.on_level:
            self.on_level(float(rms))

    def _run(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            self._run_silence_stub()
            return

        frames_per_seg = int(self.sample_rate * self.segment_sec)
        frames_block = max(256, int(self.sample_rate * self.block_sec))
        while not self._stop.is_set():
            started = time.time()
            parts: list = []
            got = 0
            while got < frames_per_seg and not self._stop.is_set():
                n = min(frames_block, frames_per_seg - got)
                recording = sd.rec(
                    n,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    device=self.device_id,
                )
                sd.wait()
                if self._stop.is_set():
                    break
                rms = float(np.sqrt(np.mean(np.square(recording)))) if recording.size else 0.0
                self._emit_level(rms)
                parts.append(recording)
                got += n
            if self._stop.is_set() or not parts:
                break
            full = np.concatenate(parts, axis=0)
            if full.shape[0] > frames_per_seg:
                full = full[:frames_per_seg]
            seg_rms = float(np.sqrt(np.mean(np.square(full)))) if full.size else 0.0
            path = self.out_dir / f"seg_{int(started * 1000)}.wav"
            self._write_wav(path, full)
            ev = AudioChunkEvent(path=path, device_id=self.device_id, started_at=started, rms=seg_rms)
            if self.on_chunk:
                self.on_chunk(ev)

    def _run_silence_stub(self) -> None:
        """Dev fallback without sounddevice: empty WAVs so queue/IPC can be tested."""
        import struct

        while not self._stop.is_set():
            started = time.time()
            # emit quiet levels during stub segment
            ticks = max(1, int(self.segment_sec / max(self.block_sec, 0.05)))
            for _ in range(ticks):
                if self._stop.wait(self.block_sec):
                    break
                self._emit_level(0.0)
            path = self.out_dir / f"seg_{int(started * 1000)}.wav"
            nframes = int(self.sample_rate * 0.1)
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"\x00\x00" * nframes * self.channels)
            if self.on_chunk:
                self.on_chunk(
                    AudioChunkEvent(path=path, device_id=self.device_id, started_at=started, rms=0.0)
                )

    def _write_wav(self, path: Path, recording) -> None:
        import numpy as np  # type: ignore

        pcm = np.clip(recording, -1.0, 1.0)
        pcm_i16 = (pcm * 32767.0).astype("int16")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_i16.tobytes())
