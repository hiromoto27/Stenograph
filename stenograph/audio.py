from __future__ import annotations

import json
import math
import platform
import shutil
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal
from scipy.signal import resample_poly

from .config import enforce_offline
from .intelligence import apply_terms


def devices():
    if platform.system() != "Windows":
        return []
    import pyaudiowpatch as pa
    with pa.PyAudio() as audio:
        result = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if info["maxInputChannels"]:
                api = audio.get_host_api_info_by_index(info["hostApi"])["name"]
                result.append({"index": index, "name": info["name"], "api": api,
                               "loopback": bool(info.get("isLoopbackDevice", False))})
        return result


def pcm_to_float(data: bytes, channels: int, rate: int):
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32).reshape(-1, channels).mean(axis=1) / 32768
    if rate != 16000:
        divisor = math.gcd(rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, rate // divisor)
    return np.asarray(samples, dtype=np.float32)


class Capture(QThread):
    level = Signal(str, int)
    error = Signal(str)
    ready = Signal(str)

    def __init__(self, db, root, mid, source, index, seconds, epoch):
        super().__init__()
        self.db, self.root, self.mid, self.source = db, Path(root), mid, source
        self.index, self.seconds, self.epoch = index, seconds, epoch
        self.stop_event = threading.Event()

    def run(self):
        try:
            import pyaudiowpatch as pa
            folder = self.root / "audio" / str(self.mid)
            folder.mkdir(parents=True, exist_ok=True)
            with pa.PyAudio() as audio:
                info = audio.get_device_info_by_index(self.index)
                channels = min(2, int(info["maxInputChannels"]))
                rate = int(info["defaultSampleRate"])
                frames = max(256, rate // 10)
                stream = audio.open(format=pa.paInt16, channels=channels, rate=rate, input=True,
                                    input_device_index=self.index, frames_per_buffer=frames)
                self.ready.emit(self.source)
                try:
                    while not self.stop_event.is_set():
                        if shutil.disk_usage(folder).free < 250 * 1024**2:
                            raise RuntimeError("На диске осталось меньше 250 МБ. Запись остановлена.")
                        path = folder / f"{uuid.uuid4().hex}.wav"
                        offset = time.monotonic() - self.epoch
                        count = 0
                        # Sidecar lets a completed/partial wave be recovered after an unexpected exit.
                        meta = {"meeting_id": self.mid, "source": self.source, "offset": offset, "path": str(path)}
                        path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
                        try:
                            with wave.open(str(path), "wb") as out:
                                out.setnchannels(channels)
                                out.setsampwidth(2)
                                out.setframerate(rate)
                                while count < rate * self.seconds and not self.stop_event.is_set():
                                    # Overflow raises an explicit error instead of silently omitting audio.
                                    raw = stream.read(min(frames, rate * self.seconds - count), exception_on_overflow=True)
                                    out.writeframes(raw)
                                    count += len(raw) // (channels * 2)
                                    sample = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
                                    rms = float(np.sqrt(np.mean(sample * sample))) if len(sample) else 0
                                    dbfs = 20 * math.log10(max(rms, 1e-6))
                                    self.level.emit(self.source, int(max(0, min(100, (dbfs + 60) / 60 * 100))))
                        finally:
                            if count:
                                self.db.add_chunk(self.mid, self.source, path, offset, count / rate)
                                path.with_suffix(".json").unlink(missing_ok=True)
                            else:
                                path.unlink(missing_ok=True)
                                path.with_suffix(".json").unlink(missing_ok=True)
                finally:
                    stream.stop_stream()
                    stream.close()
        except Exception as exc:
            self.error.emit(f"{self.source}: {exc}")
        finally:
            self.level.emit(self.source, 0)

    def stop(self):
        self.stop_event.set()


def recover_audio(db, root):
    recovered = 0
    errors = []
    for meta_path in (Path(root) / "audio").glob("*/*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            path = meta_path.with_suffix(".wav")
            with wave.open(str(path)) as audio:
                duration = audio.getnframes() / audio.getframerate()
            if duration:
                db.add_chunk(meta["meeting_id"], meta["source"], path, meta["offset"], duration)
                recovered += 1
            meta_path.unlink()
        except Exception as exc:
            errors.append(f"{meta_path.name}: {exc}")
    return recovered, errors


class Transcriber(QThread):
    changed = Signal(int)
    status = Signal(str)
    error = Signal(str)

    def __init__(self, db, settings):
        super().__init__()
        self.db, self.settings = db, settings
        self.stop_event = threading.Event()

    def run(self):
        model = None
        try:
            enforce_offline()
            path = Path(self.settings.model_path)
            if not self.settings.model_path or not (path / "model.bin").is_file() or not (path / "tokenizer.json").is_file():
                raise RuntimeError("Укажите папку полной модели faster-whisper: нужны model.bin и tokenizer.json.")
            from faster_whisper import WhisperModel
            self.status.emit("Загрузка локальной модели…")
            model = WhisperModel(str(path.resolve()), device=self.settings.device,
                                 compute_type=self.settings.compute_type, cpu_threads=self.settings.cpu_threads,
                                 local_files_only=True, num_workers=1)
            self.status.emit("Распознавание готово")
            while not self.stop_event.is_set():
                pending = self.db.rows("SELECT * FROM chunks WHERE state='pending' ORDER BY id LIMIT 1")
                if not pending:
                    self.stop_event.wait(0.3)
                    continue
                chunk = pending[0]
                started = time.monotonic()
                try:
                    with wave.open(chunk["path"]) as audio:
                        samples = pcm_to_float(audio.readframes(audio.getnframes()), audio.getnchannels(), audio.getframerate())
                    terms = self.db.rows("SELECT * FROM terms ORDER BY uses DESC,wrong LIMIT 100")
                    prompt = ", ".join(t["correct"] for t in terms)[:1000]
                    result, _ = model.transcribe(samples, language=self.settings.language or None,
                                                 beam_size=1, vad_filter=True, condition_on_previous_text=False,
                                                 initial_prompt=prompt or None)
                    segments = []
                    for segment in result:
                        if segment.text.strip():
                            segments.append((chunk["offset"] + segment.start, chunk["offset"] + segment.end,
                                             segment.text.strip(), apply_terms(segment.text.strip(), terms)))
                    self.db.complete_chunk(chunk, segments)
                    ratio = (time.monotonic() - started) / max(chunk["duration"], 0.01)
                    queued = self.db.rows("SELECT COUNT(*) AS n FROM chunks WHERE state='pending'")[0]["n"]
                    self.status.emit(f"Распознавание: {ratio:.2f}× длительности звука • в очереди {queued}")
                    self.changed.emit(chunk["meeting_id"])
                except Exception as exc:
                    self.db.execute("UPDATE chunks SET state='error',error=? WHERE id=?", (str(exc), chunk["id"]))
                    self.error.emit(f"Фрагмент {chunk['id']}: {exc}. Аудио сохранено, доступен повтор.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            del model
            self.status.emit("Распознавание остановлено")

    def stop(self):
        self.stop_event.set()
