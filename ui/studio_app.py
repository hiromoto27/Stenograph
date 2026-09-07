"""Stenograf Studio shell — dark UI per Grok mockups, wired to worker IPC."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import flet as ft

from ui.export_protocol import ProtocolLine, default_export_dir, export_docx, export_html
from ui.theme import ACCENT, ACCENT_FG, BG, BORDER, MUTED, SURFACE, SURFACE2, TEXT, page_theme
from ui.worker_client import WorkerClient

TABS = ("Студия", "Карта", "Сроки", "Протокол", "Гайды", "Ещё")


def _db_from_rms(rms: float) -> float:
    if rms <= 1e-9:
        return -60.0
    return max(-60.0, min(0.0, 20.0 * math.log10(rms)))


def main(page: ft.Page) -> None:
    page.title = "Стенограф"
    page.window.width = 1180
    page.window.height = 820
    page_theme(page)

    repo_root = Path(__file__).resolve().parents[1]
    active_tab = "Студия"
    protocol_entries: list[ProtocolLine] = []
    model_rows: list[dict[str, Any]] = []
    queue_pending = 0
    queue_done = 0
    meeting_open = False

    # --- header labels ---
    hw_label = ft.Text("Профиль: —", size=11, color=MUTED)
    backend_label = ft.Text("ASR: —", size=11, color=MUTED)
    status = ft.Text("", size=12, color=MUTED)
    db_label = ft.Text("-60 дБ", size=12, color=MUTED)
    level_bar = ft.ProgressBar(value=0, height=6, color=ACCENT, bgcolor=BORDER)
    queue_text = ft.Text("Очередь ASR: pending 0 · готово 0", size=12, color=MUTED)
    transcript = ft.ListView(expand=True, spacing=6, auto_scroll=True)
    models_view = ft.ListView(expand=True, spacing=4)
    download_progress = ft.ProgressBar(value=0, visible=False, color=ACCENT, bgcolor=BORDER)

    mic_dd = ft.Dropdown(label="Микрофон", options=[], width=320, dense=True, bgcolor=SURFACE2)
    topic_field = ft.TextField(
        label="Тема встречи",
        hint_text="Тема встречи",
        expand=True,
        bgcolor=SURFACE2,
        border_color=BORDER,
    )

    body = ft.Container(expand=True, bgcolor=BG, padding=16)
    nav_row = ft.Row(spacing=8)

    def set_status(msg: str) -> None:
        status.value = msg
        page.update()

    def append_protocol(prefix: str, text: str, *, job_id: str = "", backend: str = "") -> None:
        entry = ProtocolLine(text=text, job_id=job_id or prefix, backend=backend)
        protocol_entries.append(entry)
        line = f"[{prefix}] {text}" if prefix else text
        transcript.controls.append(
            ft.Container(
                content=ft.Text(line, selectable=True, size=13, color=TEXT),
                bgcolor=SURFACE2,
                padding=10,
                border_radius=8,
            )
        )
        page.update()

    def refresh_queue() -> None:
        queue_text.value = f"Очередь ASR: pending {queue_pending} · готово {queue_done}"

    def load_models_from_disk() -> None:
        nonlocal model_rows
        try:
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from worker.models_catalog import load_index, models_root  # type: ignore

            root = models_root()
            model_rows = []
            for e in load_index():
                engine = getattr(e, "engine", "") or ""
                present = None if engine == "faster-whisper" else (root / e.filename).exists()
                model_rows.append(
                    {
                        "id": e.id,
                        "filename": e.filename,
                        "url": e.url,
                        "sha256": e.sha256,
                        "profile": e.profile,
                        "engine": engine,
                        "notes": getattr(e, "notes", "") or "",
                        "local_present": present,
                    }
                )
            render_models()
        except Exception as exc:  # noqa: BLE001
            set_status(f"Каталог: {exc}")

    def download_model(model_id: str) -> None:
        if not (repo_root / "worker" / "main.py").exists():
            set_status("Нет worker/")
            return
        download_progress.visible = True
        download_progress.value = None
        set_status(f"Скачивание {model_id}…")

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
                assert proc.stdout
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            on_event(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                if proc.wait() != 0:
                    set_status(f"Скачивание {model_id}: exit {proc.returncode}")
                    download_progress.visible = False
                    page.update()
            except Exception as exc:  # noqa: BLE001
                download_progress.visible = False
                set_status(f"Ошибка скачивания: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def render_models() -> None:
        models_view.controls.clear()
        order = ["whisper.cpp", "faster-whisper", "vosk", "silero-vad"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in model_rows:
            groups.setdefault(str(row.get("engine") or "other"), []).append(row)
        for eng in order + sorted(k for k in groups if k not in order):
            rows = groups.get(eng) or []
            if not rows:
                continue
            models_view.controls.append(ft.Text(eng, size=13, weight=ft.FontWeight.W_600, color=TEXT))
            for row in rows:
                mid = str(row.get("id") or "?")
                can_dl = eng != "faster-whisper" and bool(row.get("url")) and bool(row.get("sha256"))
                bits = [mid, f"profile={row.get('profile') or ''}"]
                if row.get("local_present") is True:
                    bits.append("локально ✓")
                elif row.get("local_present") is False:
                    bits.append("нет файла")
                if row.get("notes"):
                    bits.append(str(row["notes"]))

                def make_dl(mid_: str):
                    return lambda _: download_model(mid_)

                models_view.controls.append(
                    ft.Row(
                        [
                            ft.Text(" · ".join(bits), size=12, color=MUTED, expand=True),
                            ft.OutlinedButton("Скачать", on_click=make_dl(mid), disabled=not can_dl),
                        ]
                    )
                )
        page.update()

    def on_event(event: dict[str, Any]) -> None:
        nonlocal queue_pending, queue_done, model_rows
        et = event.get("event")
        if et == "hw.profile":
            prof = event.get("profile") or {}
            if isinstance(prof, dict):
                name = prof.get("name") or "?"
                hint = prof.get("asr_model_hint") or ""
                reason = prof.get("reason") or ""
                hw_label.value = f"Профиль: {name}" + (f" · {hint}" if hint else "") + (f" · {reason}" if reason else "")
            else:
                hw_label.value = f"Профиль: {prof}"
        elif et == "mic.list":
            devices = event.get("devices") or []
            mic_dd.options = [
                ft.dropdown.Option(key=str(d.get("id", i)), text=str(d.get("name") or f"Mic {i}"))
                for i, d in enumerate(devices)
            ]
            if mic_dd.options and not mic_dd.value:
                mic_dd.value = mic_dd.options[0].key
            set_status("Микрофоны обновлены")
        elif et == "audio.chunk":
            rms = event.get("rms")
            if isinstance(rms, (int, float)):
                db = _db_from_rms(float(rms))
                db_label.value = f"{db:.0f} дБ"
                level_bar.value = (db + 60.0) / 60.0
        elif et == "asr.backend":
            name = event.get("backend") or "?"
            bits = [str(name)]
            for key in ("device", "model_size", "compute_type"):
                if event.get(key):
                    bits.append(f"{key}={event.get(key)}")
            if event.get("warning"):
                bits.append(str(event.get("warning")))
            backend_label.value = "ASR: " + " · ".join(bits)
        elif et == "asr.job":
            pending = event.get("pending")
            queue_pending = pending if isinstance(pending, int) else queue_pending + 1
            refresh_queue()
        elif et == "asr.result":
            queue_done += 1
            pending = event.get("pending")
            if isinstance(pending, int):
                queue_pending = pending
            elif queue_pending > 0:
                queue_pending -= 1
            refresh_queue()
            err = event.get("error")
            text = event.get("text") or ""
            job_id = str(event.get("job_id") or "")
            backend = event.get("backend") or ""
            if err:
                append_protocol(job_id or "err", f"ERROR ({backend}): {err}", job_id=job_id, backend=str(backend))
            elif text:
                conf = event.get("confidence")
                prefix = f"{job_id} · {backend}" if backend else job_id
                if conf is not None:
                    prefix = f"{prefix} · conf={conf}" if prefix else f"conf={conf}"
                append_protocol(prefix, text, job_id=job_id, backend=str(backend))
        elif et == "models.list":
            models = event.get("models") or []
            if models:
                model_rows = [m for m in models if isinstance(m, dict)]
                render_models()
            else:
                load_models_from_disk()
        elif et == "models.download":
            mid = event.get("id") or "?"
            download_progress.visible = True
            if event.get("done"):
                download_progress.visible = False
                set_status(f"Скачано {mid}: {event.get('path') or ''}")
                load_models_from_disk()
            elif event.get("error"):
                download_progress.visible = False
                set_status(f"Ошибка {mid}: {event.get('error')}")
            else:
                percent = event.get("percent")
                if isinstance(percent, (int, float)):
                    download_progress.value = max(0.0, min(1.0, float(percent) / 100.0))
                    set_status(f"Скачивание {mid}: {float(percent):.0f}%")
                else:
                    download_progress.value = None
                    set_status(f"Скачивание {mid}…")
        page.update()

    client = WorkerClient(worker_cwd=repo_root, on_event=on_event)

    def refresh_mics(_: ft.ControlEvent | None = None) -> None:
        if not (repo_root / "worker" / "main.py").exists():
            mic_dd.options = [ft.dropdown.Option(key="default", text="Микрофон по умолчанию")]
            mic_dd.value = "default"
            set_status("Демо без worker/")
            return
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
        except Exception as exc:  # noqa: BLE001
            set_status(f"mic list: {exc}")

    def start_rec(_: ft.ControlEvent) -> None:
        nonlocal meeting_open
        meeting_open = True
        set_status("Запись…")
        client.start(mic_id=mic_dd.value, segment_sec=3.0)

    def stop_rec(_: ft.ControlEvent) -> None:
        client.stop()
        set_status("Остановлено")

    def do_export(kind: str) -> None:
        if not protocol_entries:
            set_status("Протокол пуст")
            return
        out = default_export_dir()
        try:
            path = (
                export_docx(protocol_entries, out / "protocol-latest.docx")
                if kind == "DOCX"
                else export_html(protocol_entries, out / "protocol-latest.html")
            )
            set_status(f"Экспорт {kind}: {path}")
        except Exception as exc:  # noqa: BLE001
            set_status(f"Экспорт ошибка: {exc}")

    def stub_view(title: str, hint: str) -> ft.Control:
        return ft.Column(
            [
                ft.Text(title, size=28, weight=ft.FontWeight.W_600, color=TEXT),
                ft.Text(hint, size=13, color=MUTED),
                ft.Container(
                    content=ft.Text("Раздел в работе — каркас под макет", color=MUTED),
                    border=ft.Border.all(1, BORDER),
                    border_radius=12,
                    padding=24,
                    expand=True,
                ),
            ],
            expand=True,
            spacing=12,
        )

    def studio_view() -> ft.Control:
        empty = not transcript.controls
        transcript_box = ft.Container(
            content=transcript
            if not empty
            else ft.Column(
                [
                    ft.Text("ТРАНСКРИПТ", size=11, color=MUTED),
                    ft.Text(
                        "Реплик пока нет. Нажмите «Записать».",
                        color=MUTED,
                        size=13,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            border=ft.Border.all(1, BORDER),
            border_radius=12,
            padding=12,
            expand=True,
            bgcolor=SURFACE,
        )
        return ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("Студия", size=28, weight=ft.FontWeight.W_600, color=TEXT),
                        ft.Text(
                            "Сначала откройте встречу — реплики лягут в неё.",
                            size=12,
                            color=MUTED,
                        ),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text("Уровень сигнала", color=TEXT),
                                            ft.Container(expand=True),
                                            db_label,
                                        ]
                                    ),
                                    level_bar,
                                ],
                                spacing=8,
                            ),
                            bgcolor=SURFACE,
                            border=ft.Border.all(1, BORDER),
                            border_radius=12,
                            padding=16,
                        ),
                        ft.Row(
                            [
                                topic_field,
                                ft.FilledButton(
                                    "Начать встречу",
                                    bgcolor=ACCENT,
                                    color=ACCENT_FG,
                                    on_click=lambda e: set_status(
                                        f"Встреча: {topic_field.value or 'без темы'}"
                                    ),
                                ),
                            ]
                        ),
                        ft.Row(
                            [
                                mic_dd,
                                ft.OutlinedButton("Обновить", on_click=refresh_mics),
                            ]
                        ),
                        ft.Row(
                            [
                                ft.FilledButton("Записать", bgcolor=ACCENT, color=ACCENT_FG, on_click=start_rec),
                                ft.OutlinedButton("Стоп", on_click=stop_rec),
                                ft.OutlinedButton("Протокол DOCX", on_click=lambda e: do_export("DOCX")),
                                ft.OutlinedButton("HTML", on_click=lambda e: do_export("HTML")),
                            ],
                            wrap=True,
                        ),
                        queue_text,
                        download_progress,
                        status,
                        transcript_box,
                    ],
                    expand=True,
                    spacing=10,
                ),
                ft.Container(
                    width=280,
                    bgcolor=SURFACE,
                    border=ft.Border.all(1, BORDER),
                    border_radius=12,
                    padding=12,
                    content=ft.Column(
                        [
                            ft.Text("Задачи", size=18, weight=ft.FontWeight.W_600, color=TEXT),
                            ft.Text("Профили ключевых слов — следующий слой", size=11, color=MUTED),
                            ft.TextField(label="Новая задача", bgcolor=SURFACE2, dense=True),
                            ft.Text("Пока заглушка сайдбара", size=12, color=MUTED),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            expand=True,
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def settings_view() -> ft.Control:
        return ft.Column(
            [
                ft.Text("Настройки", size=28, weight=ft.FontWeight.W_600, color=TEXT),
                ft.Text("Native: профиль железа + каталог моделей (не WASM/Web Speech).", size=12, color=MUTED),
                hw_label,
                backend_label,
                ft.Row(
                    [
                        ft.Text("Каталог моделей", size=16, weight=ft.FontWeight.W_600, color=TEXT),
                        ft.OutlinedButton("Обновить", on_click=lambda e: load_models_from_disk()),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                download_progress,
                ft.Container(
                    content=models_view,
                    border=ft.Border.all(1, BORDER),
                    border_radius=12,
                    padding=10,
                    expand=True,
                    bgcolor=SURFACE,
                ),
            ],
            expand=True,
            spacing=10,
        )

    def render_body() -> None:
        if active_tab == "Студия":
            body.content = studio_view()
        elif active_tab == "Ещё":
            body.content = settings_view()
        elif active_tab == "Карта":
            body.content = stub_view("Карта связей", "Перетащите задачу — связь. Panzoom позже.")
        elif active_tab == "Сроки":
            body.content = stub_view("Напоминания", "Календарь + .ics — каркас.")
        elif active_tab == "Протокол":
            body.content = stub_view("Протокол", "Сборка из транскрипта; DOCX/HTML уже в Студии.")
        elif active_tab == "Гайды":
            body.content = stub_view("Инструкции", "Гайды со скринами — после Студии.")
        page.update()

    def switch_tab(name: str):
        def _(_: ft.ControlEvent) -> None:
            nonlocal active_tab
            active_tab = name
            rebuild_nav()
            render_body()

        return _

    def rebuild_nav() -> None:
        nav_row.controls.clear()
        for name in TABS:
            selected = name == active_tab
            nav_row.controls.append(
                ft.Container(
                    content=ft.Text(name, size=13, color=TEXT if selected else MUTED),
                    padding=ft.Padding.symmetric(vertical=8, horizontal=12),
                    border=ft.Border.all(1, ACCENT if selected else BORDER),
                    border_radius=8,
                    bgcolor=SURFACE2 if selected else None,
                    on_click=switch_tab(name),
                )
            )

    header = ft.Container(
        bgcolor=SURFACE,
        padding=ft.Padding.symmetric(vertical=12, horizontal=16),
        border=ft.Border(bottom=ft.BorderSide(1, BORDER)),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("Стенограф", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                                ft.Text("Диктофон · карта · напоминания", size=11, color=MUTED),
                            ],
                            spacing=0,
                        ),
                        ft.Container(expand=True),
                        ft.TextField(
                            hint_text="Поиск по архиву",
                            width=280,
                            dense=True,
                            bgcolor=SURFACE2,
                            border_color=BORDER,
                        ),
                        nav_row,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([hw_label, backend_label], spacing=16),
            ],
            spacing=8,
        ),
    )

    rebuild_nav()
    render_body()
    page.add(ft.Column([header, body], expand=True, spacing=0))
    refresh_mics()
    load_models_from_disk()


if __name__ == "__main__":
    ft.run(main)
