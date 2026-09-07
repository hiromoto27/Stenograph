"""Flet UI for Stenograph MVP — mic picker, ASR queue, protocol view, export stubs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import flet as ft

from ui.export_protocol import ProtocolLine, export_docx, export_html, default_export_dir
from ui.worker_client import WorkerClient


def main(page: ft.Page) -> None:
    page.title = "Stenograf"
    page.window.width = 960
    page.window.height = 720
    page.padding = 16

    mics: list[dict[str, Any]] = []
    protocol_entries: list[ProtocolLine] = []
    queue_pending = 0
    queue_done = 0
    hw_label = ft.Text("Профиль железа: —", size=12)
    status = ft.Text("Worker: остановлен", size=12)
    protocol_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    queue_text = ft.Text("Очередь ASR: pending 0 · готово 0", size=13)

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

    def on_event(event: dict[str, Any]) -> None:
        nonlocal queue_pending, queue_done, mics
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
                status.value = f"Worker: запись… rms={rms:.3f}" if isinstance(rms, (int, float)) else f"Worker: запись… {path}"
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
                append_protocol(job_id or "err", f"ERROR ({backend}): {err}", job_id=job_id, backend=str(backend))
            elif text:
                prefix = job_id
                if backend:
                    prefix = f"{job_id} · {backend}" if job_id else str(backend)
                append_protocol(prefix, text, job_id=job_id, backend=str(backend))
        elif et == "models.list":
            models = event.get("models") or []
            status.value = f"Модели: {len(models)} в каталоге"
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
        import sys

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
                status,
                ft.Row(
                    [
                        mic_dd,
                        ft.OutlinedButton("Обновить", on_click=refresh_mics),
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
                ft.Text("Протокол", size=16, weight=ft.FontWeight.W_600),
                ft.Container(
                    content=protocol_view,
                    border=ft.border.all(1, ft.Colors.OUTLINE),
                    border_radius=8,
                    padding=8,
                    expand=True,
                ),
            ],
            expand=True,
        )
    )
    refresh_mics(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    ft.app(target=main)
