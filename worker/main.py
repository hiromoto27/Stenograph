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
from worker.capture import CaptureSession, db_to_level, rms_to_db
from worker.hw_profile import detect_profile
from worker.classifier import apply_feedback, suggest as classify_suggest
from worker.tasks_store import create_task, load_tasks, save_tasks
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


def recommend_model_id(profile) -> str:
    """Catalog id suggested for this hardware (matches UI ★ badge)."""
    from worker.asr_backend import cuda_runtime_available

    if getattr(profile, "prefer_openvino", False) and not getattr(profile, "prefer_cuda", False):
        return "whisper-base"
    if profile.name == "low":
        return "fw-tiny"
    if profile.name == "high" and getattr(profile, "prefer_cuda", False) and cuda_runtime_available():
        return "fw-small"
    if profile.name == "high":
        return "fw-base"
    if getattr(profile, "prefer_cuda", False):
        return "fw-base"
    return "fw-base"


def _fw_size_from_id(model_id: str) -> str:
    mid = model_id.lower()
    for size in ("large-v3", "large", "medium", "small", "base", "tiny"):
        if size in mid:
            if size.startswith("large"):
                return "small"  # keep MVP practical on local boxes
            if size == "medium":
                return "small"
            return size
    return "base"


def backend_for_model_id(model_id: str, profile, entries):
    """Build ASR backend for an explicit catalog model id."""
    from worker.asr_backend import (
        FasterWhisperBackend,
        WhisperCppOpenVinoBackend,
        _find_whisper_cpp,
        cuda_runtime_available,
        select_backend,
    )
    from worker.models_catalog import models_root

    by_id = {e.id: e for e in entries}
    entry = by_id.get(model_id)
    if entry is None:
        emit({"event": "asr.model", "model_id": model_id, "warning": "unknown model id; using auto"})
        return select_backend(profile), None

    engine = (getattr(entry, "engine", "") or "").lower()
    want_cuda = getattr(profile, "prefer_cuda", False) and cuda_runtime_available()
    device = "cuda" if want_cuda else "cpu"
    compute = "float16" if device == "cuda" else "int8"

    if engine == "faster-whisper" or model_id.startswith("fw-"):
        size = _fw_size_from_id(model_id)
        backend = FasterWhisperBackend(
            model_size=size,
            device=device,
            compute_type=compute,
            allow_cpu_fallback=True,
        )
        return backend, model_id

    if engine == "whisper.cpp" or model_id.startswith("whisper-"):
        root = models_root()
        path = root / entry.filename
        binary = _find_whisper_cpp()
        if binary and path.exists():
            return WhisperCppOpenVinoBackend(binary, path), model_id
        # No local ggml / binary — map to faster-whisper size of same tier
        size = _fw_size_from_id(model_id)
        emit(
            {
                "event": "asr.model",
                "model_id": model_id,
                "warning": f"ggml/binary missing; falling back to faster-whisper {size}",
            }
        )
        backend = FasterWhisperBackend(
            model_size=size,
            device=device,
            compute_type=compute,
            allow_cpu_fallback=True,
        )
        return backend, model_id

    emit({"event": "asr.model", "model_id": model_id, "warning": f"engine {engine!r} not selectable; auto"})
    return select_backend(profile), None



def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Stenograph native worker")
    parser.add_argument("--device", type=int, default=None, help="Input device id")
    parser.add_argument("--list-mics", action="store_true")
    parser.add_argument("--segment-sec", type=float, default=5.0)
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="Run duration in seconds; 0 = until process stop (UI default)",
    )
    parser.add_argument(
        "--download-model",
        metavar="ID",
        help="Download model id from catalog (e.g. whisper-base) then exit",
    )
    parser.add_argument(
        "--model-id",
        metavar="ID",
        default=None,
        help="Catalog model id (fw-base, whisper-small, …); also STENOGRAF_MODEL_ID",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "stub", "faster-whisper", "whisper.cpp"),
        default="auto",
        help="Force ASR backend (default: auto by hardware profile)",
    )
    args = parser.parse_args(argv)

    profile = detect_profile()
    rec_id = recommend_model_id(profile)
    emit(
        {
            "event": "hw.profile",
            "profile": {**profile.__dict__, "recommend_model_id": rec_id},
            "recommend_model_id": rec_id,
        }
    )

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

    model_id = args.model_id or os.environ.get("STENOGRAF_MODEL_ID") or None
    selected_model_id = None

    if args.backend == "stub":
        from worker.asr_backend import StubBackend

        backend = StubBackend()
    elif model_id:
        backend, selected_model_id = backend_for_model_id(model_id, profile, entries)
    elif args.backend == "faster-whisper":
        from worker.asr_backend import FasterWhisperBackend, cuda_runtime_available

        want_cuda = getattr(profile, "prefer_cuda", False) and cuda_runtime_available()
        if profile.name == "low":
            size = "tiny"
        elif profile.name == "high":
            size = "small" if want_cuda else "base"
        else:
            size = "base"
        device = "cuda" if want_cuda else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        backend = FasterWhisperBackend(
            model_size=size,
            device=device,
            compute_type=compute,
            allow_cpu_fallback=True,
        )
        selected_model_id = f"fw-{size}"
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
        selected_model_id = model_id
    else:
        backend = select_backend(profile)
        selected_model_id = rec_id

    info = describe_backend(backend)
    if selected_model_id:
        info["model_id"] = selected_model_id
    info["recommend_model_id"] = rec_id
    emit({"event": "asr.backend", **info})

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

    def on_level(rms: float) -> None:
        db = rms_to_db(rms)
        emit(
            {
                "event": "mic.level",
                "rms": rms,
                "db": db,
                "level": db_to_level(db),
            }
        )

    def on_chunk(ev) -> None:
        rms = float(ev.rms or 0.0)
        db = rms_to_db(rms)
        # LOGIC.md §13 — не звать на тишине: write WAV but skip ASR if energy gate fails
        try:
            rms_gate = float(os.environ.get("STENOGRAF_ASR_RMS_MIN", "0.005"))
        except ValueError:
            rms_gate = 0.005
        skip_asr = rms < rms_gate
        emit(
            {
                "event": "audio.chunk",
                "path": str(ev.path),
                "device_id": ev.device_id,
                "rms": rms,
                "db": db,
                "level": db_to_level(db),
                "started_at": ev.started_at,
                "skipped_asr": skip_asr,
            }
        )
        if skip_asr:
            return
        job = asr.enqueue(ev.path, language="ru")
        emit({"event": "asr.job", "id": job.id, "pending": asr.pending()})

    capture.on_chunk = on_chunk
    capture.on_level = on_level
    capture.start()
    emit({"event": "capture.started", "device_id": args.device})

    tasks = load_tasks()
    emit({"event": "tasks.list", "tasks": [
        {"task_id": t["task_id"], "title": t["title"], "hits": t.get("hits", 0), "misses": t.get("misses", 0)}
        for t in tasks
    ]})

    pending_suggest: dict[str, dict] = {}
    import threading
    import queue as queue_mod
    cmd_q: queue_mod.Queue = queue_mod.Queue()

    def _stdin_loop() -> None:
        if sys.stdin is None or sys.stdin.closed:
            return
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    cmd_q.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            return

    threading.Thread(target=_stdin_loop, name="stdin-cmds", daemon=True).start()

    def _handle_cmd(cmd: dict) -> None:
        nonlocal tasks
        et = cmd.get("event")
        uid = str(cmd.get("utterance_id") or "")
        meta = pending_suggest.pop(uid, {})
        text_u = str(meta.get("text") or cmd.get("text") or "")
        suggested_ids = [c["task_id"] for c in (meta.get("candidates") or [])]

        if et == "task.assign":
            tid = str(cmd.get("task_id") or "")
            mode = "auto" if meta.get("auto") else "ask"
            apply_feedback(tasks, chosen_id=tid, utterance=text_u, suggested_ids=suggested_ids, mode=mode)
            emit({"event": "task.assigned", "utterance_id": uid, "task_id": tid})
        elif et == "task.create":
            title = str(cmd.get("title") or "Новая задача")
            task = create_task(tasks, title)
            tasks = load_tasks()
            apply_feedback(tasks, chosen_id=task["task_id"], utterance=text_u, suggested_ids=suggested_ids, mode="ask")
            emit({"event": "task.created", "utterance_id": uid, "task": {"task_id": task["task_id"], "title": task["title"]}})
        elif et == "task.skip":
            emit({"event": "task.skipped", "utterance_id": uid})
        elif et == "asr.model":
            emit({"event": "asr.model", "model_id": cmd.get("model_id"), "note": "restart worker to apply"})
        elif et == "tasks.reload":
            tasks = load_tasks()
            emit({"event": "tasks.list", "tasks": [
                {"task_id": t["task_id"], "title": t["title"], "hits": t.get("hits", 0), "misses": t.get("misses", 0)}
                for t in tasks
            ]})

    deadline = None if args.seconds <= 0 else time.time() + args.seconds
    try:
        while deadline is None or time.time() < deadline:
            while True:
                try:
                    _handle_cmd(cmd_q.get_nowait())
                except queue_mod.Empty:
                    break
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
                text = (result.text or "").strip()
                if text and len(text) >= 2 and not result.error:
                    payload = classify_suggest(text, tasks, utterance_id=str(result.job_id))
                    pending_suggest[str(result.job_id)] = payload
                    emit(payload)
                    # Intent create_task: still suggest UI create with title
                    # Auto-assign only when auto and not create intent
                    if payload.get("auto") and payload.get("candidates"):
                        top = payload["candidates"][0]
                        apply_feedback(
                            tasks,
                            chosen_id=top["task_id"],
                            utterance=text,
                            suggested_ids=[c["task_id"] for c in payload["candidates"]],
                            mode="auto",
                        )
                        emit({
                            "event": "task.assigned",
                            "utterance_id": str(result.job_id),
                            "task_id": top["task_id"],
                            "auto": True,
                            "score": top["score"],
                        })
    finally:
        capture.stop()
        asr.stop()
        emit({"event": "capture.stopped"})

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
