"""Worker entrypoint: hardware profile + capture → disk → ASR queue."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from worker.asr_queue import AsrQueue
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
    args = parser.parse_args(argv)

    profile = detect_profile()
    print(json.dumps({"event": "hw.profile", "profile": profile.__dict__}, ensure_ascii=False))

    entries = load_index()
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
        )
    )

    capture = CaptureSession(
        out_dir=data_root() / "audio_queue",
        device_id=args.device,
        segment_sec=args.segment_sec,
    )

    if args.list_mics:
        print(json.dumps({"event": "mic.list", "devices": capture.list_input_devices()}, ensure_ascii=False))
        return 0

    asr = AsrQueue()
    asr.start()

    def on_chunk(ev) -> None:
        # Invariant: only enqueue — never run STT here.
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
            )
        )
        job = asr.enqueue(ev.path, language="ru")
        print(json.dumps({"event": "asr.job", "id": job.id, "pending": asr.pending()}, ensure_ascii=False))

    capture.on_chunk = on_chunk
    capture.start()
    print(json.dumps({"event": "capture.started", "device_id": args.device}, ensure_ascii=False))

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
                            "backend": result.backend,
                            "error": result.error,
                        },
                        ensure_ascii=False,
                    )
                )
    finally:
        capture.stop()
        asr.stop()
        print(json.dumps({"event": "capture.stopped"}, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    # Allow `python -m worker.main` from repo root with PYTHONPATH=.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
