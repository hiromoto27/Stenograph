"""Worker entrypoint: hardware profile + capture → disk → ASR queue."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from worker.asr_backend import describe_backend, select_backend
from worker.asr_queue import AsrJob, AsrQueue, AsrResult
from worker.capture import CaptureSession
from worker.hw_profile import detect_profile
from worker.models_catalog import (
    download_with_resume,
    load_index,
    merge_with_defaults,
    models_root,
    save_index,
)


def _configure_stdio() -> None:
    """Windows cp1251 consoles break on non-ASCII JSON stdout."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def emit(payload: dict) -> None:
    """Print one JSON event as ASCII-escaped JSON (safe for Windows pipes/UI)."""
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stenograf"
    return Path.home() / ".stenograf"


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Stenograph native worker")
    parser.add_argument("--device", type=int, default=None, help="Input device id")
    parser.add_argument("--list-mics", action="store_true")
    parser.add_argument("--segment-sec", type=float, default=5.0)
    parser.add_argument("--seconds", type=float, default=20.0, help="Demo run duration")
    parser.add_argument(
        "--download-model",
        metavar="ID",
        help="Download model id from catalog (e.g. whisper-base) then exit",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "stub", "faster-whisper", "whisper.cpp"),
        default="auto",
        help="Force ASR backend (default: auto by hardware profile)",
    )
    args = parser.parse_args(argv)

    profile = detect_profile()
    emit({"event": "hw.profile", "profile": profile.__dict__})

    entries = merge_with_defaults(load_index())
    save_index(entries)
    emit(
        {
            "event": "models.list",
            "root": str(models_root()),
            "count": len(entries),
            "ids": [e.id for e in entries],
            "models": [
                {
                    "id": e.id,
                    "filename": e.filename,
                    "url": e.url,
                    "sha256": e.sha256,
                    "size_bytes": e.size_bytes,
                    "profile": e.profile,
                    "engine": getattr(e, "engine", ""),
                    "lang": getattr(e, "lang", "ru"),
                    "notes": getattr(e, "notes", ""),
                }
                for e in entries
            ],
        }
    )

    if args.download_model:
        entry = next((e for e in entries if e.id == args.download_model), None)
        if not entry:
            emit({"event": "models.download", "id": args.download_model, "error": "unknown model id", "done": True})
            return 1

        def progress(done: int, total: int | None) -> None:
            pct = round(100.0 * done / total, 1) if total and total > 0 else None
            emit(
                {
                    "event": "models.download",
                    "id": entry.id,
                    "downloaded": done,
                    "total": total,
                    "percent": pct,
                }
            )

        try:
            path = download_with_resume(entry, progress_cb=progress)
        except Exception as exc:  # noqa: BLE001
            emit({"event": "models.download", "id": entry.id, "error": str(exc), "done": True})
            return 1
        emit({"event": "models.download", "id": entry.id, "path": str(path), "done": True})
        return 0

    capture = CaptureSession(
        out_dir=data_root() / "audio_queue",
        device_id=args.device,
        segment_sec=args.segment_sec,
    )

    if args.list_mics:
        emit({"event": "mic.list", "devices": capture.list_input_devices()})
        return 0

    if args.backend == "stub":
        from worker.asr_backend import StubBackend

        backend = StubBackend()
    elif args.backend == "faster-whisper":
        from worker.asr_backend import FasterWhisperBackend

        size = "tiny" if profile.name == "low" else ("small" if profile.name == "high" else "base")
        device = "cuda" if getattr(profile, "prefer_cuda", False) else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        backend = FasterWhisperBackend(
            model_size=size,
            device=device,
            compute_type=compute,
            allow_cpu_fallback=True,
        )
    elif args.backend == "whisper.cpp":
        from worker.asr_backend import WhisperCppOpenVinoBackend, _find_whisper_cpp, _pick_model_file

        binary = _find_whisper_cpp()
        model = _pick_model_file(profile)
        if not binary or not model:
            emit(
                {
                    "event": "asr.backend",
                    "backend": "error",
                    "error": "whisper.cpp binary/model not found; set STENOGRAF_WHISPER_CPP / models dir",
                }
            )
            return 1
        backend = WhisperCppOpenVinoBackend(binary, model)
    else:
        backend = select_backend(profile)

    emit({"event": "asr.backend", **describe_backend(backend)})

    def run_job(job: AsrJob) -> AsrResult:
        try:
            tr = backend.transcribe(job.wav_path, language=job.language)
            return AsrResult(
                job_id=job.id,
                text=tr.text,
                confidence=tr.confidence,
                backend=tr.backend,
            )
        except Exception as exc:  # noqa: BLE001
            return AsrResult(
                job_id=job.id,
                text="",
                confidence=None,
                backend=getattr(backend, "name", "error"),
                error=str(exc),
            )

    asr = AsrQueue(worker_fn=run_job)
    asr.start()

    def on_chunk(ev) -> None:
        emit(
            {
                "event": "audio.chunk",
                "path": str(ev.path),
                "device_id": ev.device_id,
                "rms": ev.rms,
                "started_at": ev.started_at,
            }
        )
        job = asr.enqueue(ev.path, language="ru")
        emit({"event": "asr.job", "id": job.id, "pending": asr.pending()})

    capture.on_chunk = on_chunk
    capture.start()
    emit({"event": "capture.started", "device_id": args.device})

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            result = asr.poll_result(timeout=0.5)
            if result:
                emit(
                    {
                        "event": "asr.result",
                        "job_id": result.job_id,
                        "text": result.text,
                        "confidence": result.confidence,
                        "backend": result.backend,
                        "error": result.error,
                    }
                )
    finally:
        capture.stop()
        asr.stop()
        emit({"event": "capture.stopped"})

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
