"""Microphone capture → disk segments. Never blocks on ASR.

Pause-based segmentation (LOGIC.md §8/§13): flush on silence pause
(~1s) or max segment length — not fixed 5s walls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Callable
import math
import os
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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class AudioChunkEvent:
    path: Path
    device_id: int | None
    started_at: float
    rms: float | None = None
    duration_sec: float | None = None


@dataclass
class PauseDetector:
    """Pure pause/segment logic — unit-testable with synthetic RMS sequences.

    Flush when silence lasts ``pause_sec`` after at least ``min_speech_sec`` of
    speech, OR when buffered length hits ``max_segment_sec``.
    """

    pause_sec: float = 1.0
    max_segment_sec: float = 12.0
    min_speech_sec: float = 0.4
    speech_rms: float = 0.008
    speech_acc: float = 0.0
    silence_acc: float = 0.0
    buffered_sec: float = 0.0

    def reset(self) -> None:
        self.speech_acc = 0.0
        self.silence_acc = 0.0
        self.buffered_sec = 0.0

    def feed(self, rms: float, block_sec: float) -> bool:
        """Ingest one block; return True if the segment should flush."""
        if block_sec <= 0:
            return False
        self.buffered_sec += block_sec
        if float(rms) >= self.speech_rms:
            self.speech_acc += block_sec
            self.silence_acc = 0.0
        else:
            self.silence_acc += block_sec

        if self.buffered_sec + 1e-9 >= self.max_segment_sec and self.speech_acc + 1e-9 >= self.min_speech_sec:
            return True
        if (
            self.speech_acc + 1e-9 >= self.min_speech_sec
            and self.silence_acc + 1e-9 >= self.pause_sec
        ):
            return True
        # Max length with no/min speech: still flush to avoid infinite buffer of silence
        if self.buffered_sec + 1e-9 >= self.max_segment_sec:
            return True
        return False

    @property
    def has_speech(self) -> bool:
        return self.speech_acc >= self.min_speech_sec


class CaptureSession:
    """
    Writes pause-bounded WAV segments to disk.
    Emits on_level / on_listening every block while buffering;
    on_chunk only after a flush. Optional callbacks must not run STT inline.
    """

    def __init__(
        self,
        out_dir: Path,
        device_id: int | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        segment_sec: float | None = None,
        block_sec: float = 0.08,
        pause_sec: float | None = None,
        max_segment_sec: float | None = None,
        min_speech_sec: float | None = None,
        speech_rms: float | None = None,
        on_chunk: Callable[[AudioChunkEvent], None] | None = None,
        on_level: Callable[[float], None] | None = None,
        on_listening: Callable[[float, float], None] | None = None,
        on_mic_warn: Callable[[dict], None] | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.channels = channels
        # segment_sec kept as max-length alias for CLI compat (--segment-sec)
        max_seg = (
            max_segment_sec
            if max_segment_sec is not None
            else (segment_sec if segment_sec is not None else _env_float("STENOGRAF_MAX_SEG_SEC", 12.0))
        )
        pause = pause_sec if pause_sec is not None else _env_float("STENOGRAF_PAUSE_SEC", 1.0)
        # Clamp pause into product range 0.8–1.2 unless explicitly extreme via env
        if pause_sec is None:
            pause = max(0.8, min(1.2, pause))
        min_sp = min_speech_sec if min_speech_sec is not None else _env_float("STENOGRAF_MIN_SPEECH_SEC", 0.4)
        sp_rms = speech_rms if speech_rms is not None else _env_float("STENOGRAF_SPEECH_RMS", 0.008)
        self.segment_sec = float(max_seg)  # backward-compat attribute
        self.max_segment_sec = float(max_seg)
        self.pause_sec = float(pause)
        self.min_speech_sec = float(min_sp)
        self.speech_rms = float(sp_rms)
        self.block_sec = block_sec
        self.on_chunk = on_chunk
        self.on_level = on_level
        self.on_listening = on_listening
        self.on_mic_warn = on_mic_warn
        self._stop = Event()
        self._thread: Thread | None = None
        self._max_rms_seen = 0.0
        self._capture_t0: float | None = None
        self._mic_warn_emitted = False

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
        self._max_rms_seen = 0.0
        self._capture_t0 = time.time()
        self._mic_warn_emitted = False
        self._thread = Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _emit_level(self, rms: float) -> None:
        if self.on_level:
            self.on_level(float(rms))

    def _emit_listening(self, rms: float, buffered_sec: float) -> None:
        if self.on_listening:
            self.on_listening(float(rms), float(buffered_sec))

    def _note_rms(self, rms: float) -> dict | None:
        """Track peak RMS; return mic.warn payload once after ~2s if peak too low."""
        self._max_rms_seen = max(self._max_rms_seen, float(rms))
        if self._mic_warn_emitted or self._capture_t0 is None:
            return None
        if time.time() - self._capture_t0 < 2.0:
            return None
        self._mic_warn_emitted = True
        if self._max_rms_seen < 0.01:
            return {
                "event": "mic.warn",
                "reason": "low_rms",
                "hint": "не тот вход?",
                "max_rms": self._max_rms_seen,
            }
        return None

    def _new_detector(self) -> PauseDetector:
        return PauseDetector(
            pause_sec=self.pause_sec,
            max_segment_sec=self.max_segment_sec,
            min_speech_sec=self.min_speech_sec,
            speech_rms=self.speech_rms,
        )

    def _flush_segment(self, parts: list, started: float, np) -> None:
        if not parts:
            return
        full = np.concatenate(parts, axis=0)
        seg_rms = float(np.sqrt(np.mean(np.square(full)))) if full.size else 0.0
        duration = float(full.shape[0]) / float(self.sample_rate) if full.size else 0.0
        path = self.out_dir / f"seg_{int(started * 1000)}.wav"
        self._write_wav(path, full)
        ev = AudioChunkEvent(
            path=path,
            device_id=self.device_id,
            started_at=started,
            rms=seg_rms,
            duration_sec=duration,
        )
        if self.on_chunk:
            self.on_chunk(ev)

    def _run(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
            import numpy as np  # type: ignore
        except ImportError:
            self._run_silence_stub()
            return

        frames_block = max(256, int(self.sample_rate * self.block_sec))
        block_sec = frames_block / float(self.sample_rate)
        detector = self._new_detector()
        parts: list = []
        started = time.time()

        # Prefer InputStream for continuous block reads; fall back to sd.rec.
        use_stream = True
        stream = None
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device_id,
                blocksize=frames_block,
            )
            stream.start()
        except Exception:
            use_stream = False
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                stream = None

        try:
            while not self._stop.is_set():
                if use_stream and stream is not None:
                    recording, _overflowed = stream.read(frames_block)
                else:
                    recording = sd.rec(
                        frames_block,
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
                warn = self._note_rms(rms)
                if warn and self.on_mic_warn:
                    self.on_mic_warn(warn)
                parts.append(recording)
                should_flush = detector.feed(rms, block_sec)
                self._emit_listening(rms, detector.buffered_sec)
                if should_flush:
                    # Drop pure-silence flushes (no min speech) to avoid empty ASR jobs
                    if detector.has_speech:
                        self._flush_segment(parts, started, np)
                    parts = []
                    detector.reset()
                    started = time.time()
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            # Flush trailing speech on stop
            if parts:
                try:
                    import numpy as np  # type: ignore

                    if detector.has_speech:
                        self._flush_segment(parts, started, np)
                except Exception:
                    pass

    def _run_silence_stub(self) -> None:
        """Dev fallback without sounddevice: empty WAVs so queue/IPC can be tested."""
        detector = self._new_detector()
        started = time.time()
        ticks_buf = 0
        while not self._stop.is_set():
            if self._stop.wait(self.block_sec):
                break
            rms = 0.0
            self._emit_level(rms)
            warn = self._note_rms(rms)
            if warn and self.on_mic_warn:
                self.on_mic_warn(warn)
            ticks_buf += 1
            should_flush = detector.feed(rms, self.block_sec)
            self._emit_listening(rms, detector.buffered_sec)
            if should_flush:
                # silence-only: still emit a tiny stub chunk occasionally for IPC tests
                path = self.out_dir / f"seg_{int(started * 1000)}.wav"
                nframes = max(1, int(self.sample_rate * max(detector.buffered_sec, 0.1)))
                nframes = min(nframes, int(self.sample_rate * self.max_segment_sec))
                with wave.open(str(path), "wb") as wf:
                    wf.setnchannels(self.channels)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(b"\x00\x00" * nframes * self.channels)
                if self.on_chunk:
                    self.on_chunk(
                        AudioChunkEvent(
                            path=path,
                            device_id=self.device_id,
                            started_at=started,
                            rms=0.0,
                            duration_sec=detector.buffered_sec,
                        )
                    )
                detector.reset()
                started = time.time()
                ticks_buf = 0

    def _write_wav(self, path: Path, recording) -> None:
        import numpy as np  # type: ignore

        pcm = np.clip(recording, -1.0, 1.0)
        pcm_i16 = (pcm * 32767.0).astype("int16")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_i16.tobytes())
