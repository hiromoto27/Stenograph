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
from worker.models_catalog import load_index, models_root, save_index


def data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stenograf"
    return Path.home() / ".stenograf"


def main(argv: list[str] | None = None) -> int:
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
    print(json.dumps({"event": "hw.profile", "profile": profile.__dict__}, ensure_ascii=False), flush=True)

    entries = load_index()
    # Always refresh missing url/sha from defaults for known ids
    from worker.models_catalog import default_index, download_with_resume

    defaults = {e.id: e for e in default_index()}
    merged = []
    seen = set()
    for e in entries:
        d = defaults.get(e.id)
        if d and (not e.url or not e.sha256):
            e = d
        merged.append(e)
        seen.add(e.id)
    for mid, d in defaults.items():
        if mid not in seen:
            merged.append(d)
    entries = merged
    save_index(entries)
    print(
        json.dumps(
            {
                "event": "models.list",
                "root": str(models_root()),
                "count": len(entries),
                "ids": [e.id for e in entries],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    if args.download_model:
        from worker.models_catalog import download_with_resume

        entry = next((e for e in entries if e.id == args.download_model), None)
        if not entry:
            raise SystemExit(f"unknown model id: {args.download_model}")

        def progress(done, total):
            print(
                json.dumps(
                    {
                        "event": "models.download",
                        "id": entry.id,
                        "downloaded": done,
                        "total": total,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        path = download_with_resume(entry, progress_cb=progress)
        print(
            json.dumps(
                {"event": "models.download", "id": entry.id, "path": str(path), "done": True},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0


    capture = CaptureSession(
        out_dir=data_root() / "audio_queue",
        device_id=args.device,
        segment_sec=args.segment_sec,
    )

    if args.list_mics:
        print(
            json.dumps({"event": "mic.list", "devices": capture.list_input_devices()}, ensure_ascii=False),
            flush=True,
        )
        return 0

    if args.backend == "stub":
        from worker.asr_backend import StubBackend

        backend = StubBackend()
    elif args.backend == "faster-whisper":
        from worker.asr_backend import FasterWhisperBackend

        size = "tiny" if profile.name == "low" else ("small" if profile.name == "high" else "base")
        backend = FasterWhisperBackend(model_size=size)
    elif args.backend == "whisper.cpp":
        from worker.asr_backend import WhisperCppOpenVinoBackend, _find_whisper_cpp, _pick_model_file

        binary = _find_whisper_cpp()
        model = _pick_model_file(profile)
        if not binary or not model:
            raise SystemExit("whisper.cpp binary/model not found; set STENOGRAF_WHISPER_CPP / models dir")
        backend = WhisperCppOpenVinoBackend(binary, model)
    else:
        backend = select_backend(profile)

    print(json.dumps({"event": "asr.backend", **describe_backend(backend)}, ensure_ascii=False), flush=True)

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
        print(
            json.dumps(
                {
                    "event": "audio.chunk",
                    "path": str(ev.path),
                    "device_id": ev.device_id,
                    "rms": ev.rms,
                    "started_at": ev.started_at,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        job = asr.enqueue(ev.path, language="ru")
        print(
            json.dumps({"event": "asr.job", "id": job.id, "pending": asr.pending()}, ensure_ascii=False),
            flush=True,
        )

    capture.on_chunk = on_chunk
    capture.start()
    print(json.dumps({"event": "capture.started", "device_id": args.device}, ensure_ascii=False), flush=True)

    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            result = asr.poll_result(timeout=0.5)
            if result:
                print(
                    json.dumps(
                        {
                            "event": "asr.result",
                            "job_id": result.job_id,
                            "text": result.text,
                            "confidence": result.confidence,
                            "backend": result.backend,
                            "error": result.error,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        capture.stop()
        asr.stop()
        print(json.dumps({"event": "capture.stopped"}, ensure_ascii=False), flush=True)

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
