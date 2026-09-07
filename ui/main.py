"""Flet UI for Stenograph MVP — mic picker, ASR queue, protocol, models, export."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import flet as ft

from ui.export_protocol import ProtocolLine, default_export_dir, export_docx, export_html
from ui.worker_client import WorkerClient


def main(page: ft.Page) -> None:
    page.title = "Stenograf"
    page.window.width = 1000
    page.window.height = 780
    page.padding = 16

    mics: list[dict[str, Any]] = []
    protocol_entries: list[ProtocolLine] = []
    model_rows: list[dict[str, Any]] = []
    queue_pending = 0
    queue_done = 0
    hw_label = ft.Text("Профиль железа: —", size=12)
    backend_label = ft.Text("ASR backend: —", size=12)
    models_root_label = ft.Text("Модели: —", size=12)
    status = ft.Text("Worker: остановлен", size=12)
    protocol_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    models_view = ft.ListView(height=200, spacing=4)
    queue_text = ft.Text("Очередь ASR: pending 0 · готово 0", size=13)
    download_progress = ft.ProgressBar(value=0, visible=False)

    mic_dd = ft.Dropdown(
        label="Микрофон",
        options=[],
        width=420,
        dense=True,
    )

    def append_protocol(prefix: str, text: str, *, job_id: str = "", backend: str = "") -> None:
        entry = ProtocolLine(text=text, job_id=job_id or prefix, backend=backend)
        protocol_entries.append(entry)
        line = f"[{prefix}] {text}" if prefix else text
        protocol_view.controls.append(ft.Text(line, selectable=True, size=13))
        page.update()

    def refresh_queue_label() -> None:
        queue_text.value = f"Очередь ASR: pending {queue_pending} · готово {queue_done}"

    def render_models() -> None:
        models_view.controls.clear()
        if not model_rows:
            models_view.controls.append(ft.Text("Каталог пуст — обнови список или дождись models.list", size=12))
            page.update()
            return

        # Group by engine
        order = ["whisper.cpp", "faster-whisper", "vosk", "silero-vad"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in model_rows:
            eng = str(row.get("engine") or "other")
            groups.setdefault(eng, []).append(row)
        for eng in order + sorted(k for k in groups if k not in order):
            rows = groups.get(eng)
            if not rows:
                continue
            models_view.controls.append(
                ft.Text(eng, size=13, weight=ft.FontWeight.W_600)
            )
            for row in rows:
                mid = str(row.get("id") or "?")
                profile = str(row.get("profile") or "")
                filename = str(row.get("filename") or "")
                notes = str(row.get("notes") or "")
                has_url = bool(row.get("url"))
                has_sha = bool(row.get("sha256"))
                local = row.get("local_present")
                can_download = eng != "faster-whisper" and has_url and has_sha

                bits = [mid]
                if profile:
                    bits.append(f"profile={profile}")
                if filename and eng != "faster-whisper":
                    bits.append(filename)
                elif filename and eng == "faster-whisper":
                    bits.append(filename)
                if local is True:
                    bits.append("локально ✓")
                elif local is False:
                    bits.append("нет файла")
                if eng == "faster-whisper":
                    bits.append("качает library сама")
                elif can_download:
                    bits.append("готово к скачиванию")
                else:
                    bits.append("нет url/sha256")
                if notes:
                    bits.append(notes)

                def make_dl(model_id: str):
                    def _(_: ft.ControlEvent) -> None:
                        download_model(model_id)

                    return _

                models_view.controls.append(
                    ft.Row(
                        [
                            ft.Text(" · ".join(bits), size=12, expand=True),
                            ft.OutlinedButton(
                                "Скачать",
                                on_click=make_dl(mid),
                                disabled=not can_download,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                )
        page.update()


    def load_models_from_disk() -> None:
        nonlocal model_rows
        try:
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from worker.models_catalog import load_index, models_root  # type: ignore

            entries = load_index()
            root = models_root()
            model_rows = []
            for e in entries:
                # faster-whisper uses HF id as filename — not a local file path
                engine = getattr(e, "engine", "") or ""
                if engine == "faster-whisper":
                    present = None
                else:
                    present = (root / e.filename).exists() if e.filename else False
                model_rows.append(
                    {
                        "id": e.id,
                        "filename": e.filename,
                        "url": e.url,
                        "sha256": e.sha256,
                        "size_bytes": e.size_bytes,
                        "profile": e.profile,
                        "engine": engine,
                        "notes": getattr(e, "notes", "") or "",
                        "local_present": present,
                    }
                )
            models_root_label.value = f"Модели: {root} · {len(model_rows)} шт."
            render_models()
            status.value = "Каталог моделей обновлён с диска"
        except Exception as exc:  # noqa: BLE001
            status.value = f"Каталог моделей: {exc}"
        page.update()

    def download_model(model_id: str) -> None:
        """Spawn worker --download-model so UI gets models.download events."""
        import os
        import subprocess
        import threading

        if not (repo_root / "worker" / "main.py").exists():
            status.value = "Нет worker/ — скачивание недоступно"
            page.update()
            return

        # Pre-check catalog for url/sha256 so button feedback is clear
        try:
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from worker.models_catalog import load_index  # type: ignore

            entry = next((e for e in load_index() if e.id == model_id), None)
            if entry and (not entry.url or not entry.sha256):
                status.value = f"{model_id}: пустые url/sha256 в каталоге"
                page.update()
                return
        except Exception:
            pass

        download_progress.visible = True
        download_progress.value = None
        status.value = f"Скачивание {model_id}…"
        page.update()

        def _run() -> None:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "worker.main", "--download-model", model_id],
                    cwd=str(repo_root),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            on_event(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                code = proc.wait()
                if code != 0:
                    status.value = f"Скачивание {model_id}: worker exit {code}"
                    download_progress.visible = False
                    page.update()
            except Exception as exc:  # noqa: BLE001
                download_progress.visible = False
                status.value = f"Ошибка скачивания: {exc}"
                page.update()

        threading.Thread(target=_run, daemon=True).start()

    def on_event(event: dict[str, Any]) -> None:
        nonlocal queue_pending, queue_done, mics, model_rows
        et = event.get("event")
        if et == "hw.profile":
            prof = event.get("profile") or {}
            if isinstance(prof, dict):
                name = prof.get("name") or "?"
                hint = prof.get("asr_model_hint") or ""
                reason = prof.get("reason") or ""
                workers = prof.get("max_asr_workers")
                bits = [str(name)]
                if hint:
                    bits.append(f"model={hint}")
                if workers is not None:
                    bits.append(f"workers={workers}")
                if reason:
                    bits.append(str(reason))
                hw_label.value = "Профиль железа: " + " · ".join(bits)
            else:
                hw_label.value = f"Профиль железа: {prof}"
        elif et == "mic.list":
            mics = event.get("devices") or []
            mic_dd.options = [
                ft.dropdown.Option(
                    key=str(d.get("id", i)),
                    text=str(d.get("name") or f"Mic {i}"),
                )
                for i, d in enumerate(mics)
            ]
            if mic_dd.options and not mic_dd.value:
                mic_dd.value = mic_dd.options[0].key
        elif et == "audio.chunk":
            rms = event.get("rms")
            path = event.get("path") or ""
            if rms is not None:
                status.value = (
                    f"Worker: запись… rms={rms:.3f}"
                    if isinstance(rms, (int, float))
                    else f"Worker: запись… {path}"
                )
        elif et == "asr.backend":
            name = event.get("backend") or event.get("name") or "?"
            detail = event.get("detail") or event.get("reason") or ""
            backend_label.value = f"ASR backend: {name}" + (f" · {detail}" if detail else "")
        elif et == "asr.job":
            pending = event.get("pending")
            if isinstance(pending, int):
                queue_pending = pending
            else:
                queue_pending += 1
            refresh_queue_label()
        elif et == "asr.result":
            queue_done += 1
            pending = event.get("pending")
            if isinstance(pending, int):
                queue_pending = pending
            elif queue_pending > 0:
                queue_pending -= 1
            refresh_queue_label()
            err = event.get("error")
            text = event.get("text") or ""
            job_id = str(event.get("job_id") or "")
            backend = event.get("backend") or ""
            if err:
                append_protocol(
                    job_id or "err",
                    f"ERROR ({backend}): {err}",
                    job_id=job_id,
                    backend=str(backend),
                )
            elif text:
                conf = event.get("confidence")
                prefix = job_id
                if backend:
                    prefix = f"{job_id} · {backend}" if job_id else str(backend)
                if conf is not None:
                    prefix = f"{prefix} · conf={conf}" if prefix else f"conf={conf}"
                append_protocol(prefix, text, job_id=job_id, backend=str(backend))
        elif et == "models.list":
            root = event.get("root") or ""
            ids = event.get("ids") or []
            models = event.get("models") or []
            count = event.get("count")
            n = count if count is not None else (len(models) or len(ids))
            models_root_label.value = f"Модели: {root or '—'} · {n} шт."
            if models:
                model_rows = []
                for mrow in models:
                    if not isinstance(mrow, dict):
                        continue
                    model_rows.append(
                        {
                            "id": mrow.get("id"),
                            "filename": mrow.get("filename") or "",
                            "url": mrow.get("url") or "",
                            "sha256": mrow.get("sha256") or "",
                            "size_bytes": mrow.get("size_bytes"),
                            "profile": mrow.get("profile") or "",
                            "engine": mrow.get("engine") or "",
                            "notes": mrow.get("notes") or "",
                            "local_present": mrow.get("local_present"),
                        }
                    )
                render_models()
            else:
                load_models_from_disk()
                if not model_rows and ids:
                    model_rows = [
                        {"id": i, "url": "", "sha256": "", "profile": "", "filename": "", "engine": ""}
                        for i in ids
                    ]
                    render_models()
        elif et == "models.download":
            mid = event.get("id") or "?"
            download_progress.visible = True
            if event.get("done"):
                download_progress.visible = False
                download_progress.value = 0
                path_done = event.get("path") or ""
                status.value = f"Скачано {mid}: {path_done}" if path_done else f"Скачано {mid}"
                load_models_from_disk()
            elif event.get("error"):
                download_progress.visible = False
                status.value = f"Ошибка скачивания {mid}: {event.get('error')}"
            else:
                percent = event.get("percent")
                downloaded = event.get("downloaded")
                total = event.get("total")
                if isinstance(percent, (int, float)):
                    download_progress.value = max(0.0, min(1.0, float(percent) / 100.0))
                    status.value = f"Скачивание {mid}: {float(percent):.0f}%"
                    if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
                        status.value += f" ({downloaded}/{total})"
                elif isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
                    download_progress.value = float(downloaded) / float(total)
                    pct = 100.0 * float(downloaded) / float(total)
                    status.value = f"Скачивание {mid}: {pct:.0f}% ({downloaded}/{total})"
                else:
                    download_progress.value = None
                    status.value = f"Скачивание {mid}…"
        page.update()

    repo_root = Path(__file__).resolve().parents[1]
    client = WorkerClient(worker_cwd=repo_root, on_event=on_event)

    def start_click(_: ft.ControlEvent) -> None:
        status.value = "Worker: запись…"
        page.update()
        client.start(mic_id=mic_dd.value, segment_sec=3.0)

    def stop_click(_: ft.ControlEvent) -> None:
        client.stop()
        status.value = "Worker: остановлен"
        page.update()

    def refresh_mics(_: ft.ControlEvent) -> None:
        if not (repo_root / "worker" / "main.py").exists():
            mic_dd.options = [
                ft.dropdown.Option(key="default", text="Микрофон по умолчанию (нет worker)"),
            ]
            mic_dd.value = "default"
            status.value = "Нет worker/ в cwd — демо-режим UI"
            page.update()
            return
        status.value = "Запрос списка микрофонов…"
        page.update()
        import os
        import subprocess

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            out = subprocess.check_output(
                [sys.executable, "-m", "worker.main", "--list-mics"],
                cwd=str(repo_root),
                env=env,
                text=True,
                timeout=30,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        on_event(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            status.value = "Микрофоны обновлены"
        except Exception as exc:  # noqa: BLE001
            status.value = f"Ошибка mic list: {exc}"
        page.update()

    def do_export(kind: str) -> None:
        if not protocol_entries:
            status.value = "Экспорт: протокол пуст"
            page.update()
            return
        out_dir = default_export_dir()
        try:
            if kind == "DOCX":
                path = export_docx(protocol_entries, out_dir / "protocol-latest.docx")
            else:
                path = export_html(protocol_entries, out_dir / "protocol-latest.html")
            status.value = f"Экспорт {kind}: {path}"
        except Exception as exc:  # noqa: BLE001
            status.value = f"Экспорт {kind} ошибка: {exc}"
        page.update()

    page.add(
        ft.Column(
            [
                ft.Text("Stenograf — MVP UI", size=22, weight=ft.FontWeight.BOLD),
                hw_label,
                backend_label,
                models_root_label,
                status,
                download_progress,
                ft.Row(
                    [
                        mic_dd,
                        ft.OutlinedButton("Обновить mic", on_click=refresh_mics),
                    ],
                    wrap=True,
                ),
                ft.Row(
                    [
                        ft.FilledButton("Старт", on_click=start_click),
                        ft.OutlinedButton("Стоп", on_click=stop_click),
                        ft.OutlinedButton("DOCX", on_click=lambda e: do_export("DOCX")),
                        ft.OutlinedButton("HTML", on_click=lambda e: do_export("HTML")),
                    ],
                    wrap=True,
                ),
                queue_text,
                ft.Row(
                    [
                        ft.Text("Каталог моделей", size=16, weight=ft.FontWeight.W_600),
                        ft.OutlinedButton("Обновить каталог", on_click=lambda e: load_models_from_disk()),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(
                    content=models_view,
                    border=ft.Border.all(1, ft.Colors.OUTLINE),
                    border_radius=8,
                    padding=8,
                ),
                ft.Text("Протокол", size=16, weight=ft.FontWeight.W_600),
                ft.Container(
                    content=protocol_view,
                    border=ft.Border.all(1, ft.Colors.OUTLINE),
                    border_radius=8,
                    padding=8,
                    expand=True,
                ),
            ],
            expand=True,
        )
    )
    refresh_mics(None)  # type: ignore[arg-type]
    load_models_from_disk()


if __name__ == "__main__":
    ft.run(main)
