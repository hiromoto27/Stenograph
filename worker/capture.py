"""Microphone capture → disk segments. Never blocks on ASR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable
import time
import wave


@dataclass
class AudioChunkEvent:
    path: Path
    device_id: int | None
    started_at: float
    rms: float | None = None


class CaptureSession:
    """
    Writes fixed-length WAV segments to disk.
    Optional on_chunk callback should only enqueue ASR — never run STT inline.
    """

    def __init__(
        self,
        out_dir: Path,
        device_id: int | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        segment_sec: float = 5.0,
        on_chunk: Callable[[AudioChunkEvent], None] | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.segment_sec = segment_sec
        self.on_chunk = on_chunk
        self._stop = Event()
        self._thread: Thread | None = None

    def list_input_devices(self) -> list[dict]:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            return [{"id": None, "name": "(sounddevice not installed)", "channels": 1}]

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

    def _run(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            self._run_silence_stub()
            return

        frames_per_seg = int(self.sample_rate * self.segment_sec)
        while not self._stop.is_set():
            started = time.time()
            recording = sd.rec(
                frames_per_seg,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device_id,
            )
            sd.wait()
            if self._stop.is_set():
                break
            rms = float(np.sqrt(np.mean(np.square(recording)))) if recording.size else 0.0
            path = self.out_dir / f"seg_{int(started * 1000)}.wav"
            self._write_wav(path, recording)
            ev = AudioChunkEvent(path=path, device_id=self.device_id, started_at=started, rms=rms)
            if self.on_chunk:
                self.on_chunk(ev)

    def _run_silence_stub(self) -> None:
        """Dev fallback without sounddevice: empty WAVs so queue/IPC can be tested."""
        import struct

        while not self._stop.is_set():
            started = time.time()
            time.sleep(min(0.5, self.segment_sec))
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
            # drain remaining segment time
            elapsed = time.time() - started
            rem = self.segment_sec - elapsed
            if rem > 0:
                self._stop.wait(rem)

    def _write_wav(self, path: Path, recording) -> None:
        import numpy as np  # type: ignore

        pcm = np.clip(recording, -1.0, 1.0)
        pcm_i16 = (pcm * 32767.0).astype("int16")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_i16.tobytes())
