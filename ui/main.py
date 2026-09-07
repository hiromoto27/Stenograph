"""Flet UI for Stenograph MVP — mic picker, ASR queue, protocol view, export stubs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import flet as ft

from ui.worker_client import WorkerClient


def main(page: ft.Page) -> None:
    page.title = "Stenograf"
    page.window.width = 960
    page.window.height = 720
    page.padding = 16

    mics: list[dict[str, Any]] = []
    protocol_lines: list[str] = []
    queue_jobs = 0
    queue_done = 0
    hw_label = ft.Text("Профиль железа: —", size=12)
    status = ft.Text("Worker: остановлен", size=12)
    protocol_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    queue_text = ft.Text("Очередь ASR: 0 / 0", size=13)

    mic_dd = ft.Dropdown(
        label="Микрофон",
        options=[],
        width=420,
        dense=True,
    )

    def append_protocol(ts: str, text: str) -> None:
        line = f"[{ts}] {text}" if ts else text
        protocol_lines.append(line)
        protocol_view.controls.append(ft.Text(line, selectable=True, size=13))
        page.update()

    def on_event(event: dict[str, Any]) -> None:
        nonlocal queue_jobs, queue_done, mics
        et = event.get("type") or event.get("event")
        if et == "hw.profile":
            tier = event.get("tier") or event.get("profile") or "?"
            hw_label.value = f"Профиль железа: {tier}"
        elif et == "mic.list":
            mics = event.get("devices") or event.get("mics") or []
            mic_dd.options = [
                ft.dropdown.Option(
                    key=str(d.get("id", i)),
                    text=str(d.get("name") or d.get("label") or f"Mic {i}"),
                )
                for i, d in enumerate(mics)
            ]
            if mic_dd.options and not mic_dd.value:
                mic_dd.value = mic_dd.options[0].key
        elif et == "asr.job":
            queue_jobs += 1
            queue_text.value = f"Очередь ASR: {queue_done} готово / {queue_jobs} всего"
        elif et == "asr.result":
            queue_done += 1
            queue_text.value = f"Очередь ASR: {queue_done} готово / {queue_jobs} всего"
            text = event.get("text") or event.get("transcript") or ""
            ts = str(event.get("t0") or event.get("ts") or "")
            if text:
                append_protocol(ts, text)
        elif et == "models.list":
            status.value = f"Модели: {len(event.get('models') or [])} в каталоге"
        page.update()

    # Repo root: parent of ui/ when laid out as Stenograph/ui/
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
        """Ask worker for mic list via a short list-only run if available."""
        # Demo / offline fallback so UI is usable without worker present
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
        # One-shot: worker --list-mics should emit mic.list then exit
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
        except Exception as exc:  # noqa: BLE001 — surface to UI
            status.value = f"Ошибка mic list: {exc}"
        page.update()

    def export_stub(kind: str) -> None:
        status.value = f"Экспорт {kind}: post-process из protocol (TODO после стыковки)"
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
                        ft.OutlinedButton("DOCX", on_click=lambda e: export_stub("DOCX")),
                        ft.OutlinedButton("HTML", on_click=lambda e: export_stub("HTML")),
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
