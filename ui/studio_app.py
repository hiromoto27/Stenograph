"""Stenograf Studio shell — dark UI per Grok mockups, wired to worker IPC."""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime
import math
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import flet as ft

from ui.guides import GUIDES
from ui.export_protocol import (
    ProtocolLine,
    default_export_dir,
    export_docx,
    export_html,
    export_package,
    list_packages,
    package_preview,
)
from ui.map_view import MapView
from ui.theme import ACCENT, ACCENT_FG, BG, BORDER, MUTED, OK, REC, REC_FG, SURFACE, SURFACE2, SURFACE3, TEXT, page_theme
from ui.browser_stt import (
    build_webview,
    resolve_stt_engine,
    should_fallback_to_whisper,
    webview_available,
)
from ui.worker_client import WorkerClient

TABS = ("Студия", "Карта", "Сроки", "Протокол", "Гайды", "Ещё")


def settings_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "Stenograf"
    else:
        root = Path.home() / ".stenograf"
    root.mkdir(parents=True, exist_ok=True)
    return root / "ui_settings.json"


def load_ui_settings() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ui_settings(**kwargs: Any) -> None:
    data = load_ui_settings()
    data.update({k: v for k, v in kwargs.items() if v is not None})
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _db_from_rms(rms: float) -> float:
    if rms <= 1e-12:
        return -60.0
    # Boost quiet mics: treat ~0.02 RMS as near 0 dB display
    boosted = max(rms * 8.0, 1e-12)
    return max(-60.0, min(0.0, 20.0 * math.log10(boosted)))


def _level_from_db(db: float) -> float:
    # Preview-aligned: (db+60)/60; slight display boost applied in VU paint
    norm = (db + 60.0) / 60.0
    return max(0.0, min(1.0, norm))


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
    current_meeting_id: str | None = None
    wizard_step = 0
    compact_mode = False
    protocol_by_id: dict[str, ProtocolLine] = {}
    asr_engine = str(load_ui_settings().get("asr_engine") or "whisper")
    listen_label = ft.Text("", size=12, color=MUTED)
    partial_box = ft.Text("", size=13, italic=True, color=MUTED, visible=False)
    browser_start = None
    browser_stop = None
    browser_host = None

    # --- header labels ---
    hw_label = ft.Text("Профиль: —", size=11, color=MUTED)
    backend_label = ft.Text("ASR: —", size=11, color=MUTED)
    status = ft.Text("", size=12, color=MUTED)
    meeting_label = ft.Text("Встреча не начата", size=12, color=MUTED)
    rec_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor=REC, visible=False)
    rec_label = ft.Text("Идёт запись", size=12, color=REC, visible=False)
    db_label = ft.Text("-60 дБ", size=12, color=MUTED)
    VU_BARS = 64
    VU_H = 40
    vu_history: deque[float] = deque([0.0] * VU_BARS, maxlen=VU_BARS)
    vu_cells = [
        ft.Container(width=4, height=2, bgcolor=MUTED, border_radius=1)
        for _ in range(VU_BARS)
    ]
    vu_row = ft.Row(vu_cells, spacing=1, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.END, height=VU_H + 4)
    recording = False
    peak_level = 0.0

    def paint_vu() -> None:
        active = recording
        for i, cell in enumerate(vu_cells):
            lvl = vu_history[i] if i < len(vu_history) else 0.0
            # visible height boost (~preview *3.2 feel on normalized level)
            h = max(2, int(min(1.0, lvl * 1.35) * VU_H))
            cell.height = h
            cell.bgcolor = REC if active and lvl > 0.02 else (SURFACE3 if lvl > 0.02 else BORDER)

    queue_text = ft.Text("Очередь ASR: pending 0 · готово 0", size=12, color=MUTED)
    transcript = ft.ListView(expand=True, spacing=6, auto_scroll=True)
    models_view = ft.ListView(expand=True, spacing=4)
    download_progress = ft.ProgressBar(value=0, visible=False, color=ACCENT, bgcolor=BORDER)

    # --- «Куда отнести?» ---
    classify_text = ft.Text("", size=14, italic=True, color=TEXT)
    classify_hint = ft.Text("Куда отнести?", size=12, color=MUTED)
    classify_candidates = ft.Column(spacing=6)
    new_task_field = ft.TextField(label="Новая задача", dense=True, bgcolor=SURFACE2, expand=True)
    classify_panel = ft.Container(
        visible=False,
        bgcolor=SURFACE,
        border=ft.Border.all(1, BORDER),
        border_radius=12,
        padding=12,
        content=ft.Column([classify_hint, classify_text, classify_candidates], spacing=8),
    )

    def _dismiss_pause_nudge(_: ft.ControlEvent) -> None:
        pause_nudge.visible = False
        page.update()

    pause_nudge = ft.Container(
        visible=False,
        bgcolor=SURFACE2,
        border=ft.Border.all(1, WARN),
        border_radius=12,
        padding=10,
        content=ft.Row(
            [
                ft.Text("Пауза 8 с — собрать протокол?", size=12, color=TEXT, expand=True),
                ft.OutlinedButton("Протокол", on_click=lambda e: (do_export("PACKAGE"), _dismiss_pause_nudge(e))),
                ft.IconButton(ft.Icons.CLOSE, icon_size=14, icon_color=MUTED, on_click=_dismiss_pause_nudge),
            ]
        ),
    )
    search_results_col = ft.Column(spacing=6)

    def _dismiss_search(_: ft.ControlEvent | None = None) -> None:
        search_panel.visible = False
        page.update()

    search_panel = ft.Container(
        visible=False,
        bgcolor=SURFACE,
        border=ft.Border.all(1, BORDER),
        border_radius=12,
        padding=12,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Поиск по архиву", size=13, weight=ft.FontWeight.W_600, color=TEXT, expand=True),
                        ft.IconButton(ft.Icons.CLOSE, icon_size=14, icon_color=MUTED, on_click=_dismiss_search),
                    ]
                ),
                search_results_col,
            ],
            spacing=8,
        ),
    )

    def render_search_results(results: list[dict[str, Any]]) -> None:
        search_results_col.controls.clear()
        if not results:
            search_results_col.controls.append(ft.Text("Ничего не найдено", size=12, color=MUTED))
        for r in results:
            pct = int(round(float(r.get("score") or 0) * 100))
            search_results_col.controls.append(
                ft.Container(
                    content=ft.Text(f"{pct}% — {r.get('text')}", size=12, color=TEXT),
                    bgcolor=SURFACE2,
                    padding=8,
                    border_radius=8,
                )
            )
        search_panel.visible = True
        page.update()

    def do_search(e: ft.ControlEvent) -> None:
        # LOGIC.md §12 — searched server-side over the persisted archive
        # (worker/archive_store.py), which carries full task profiles the UI's
        # thin tasks_sidebar mirror doesn't (needed for the +0.15 task bonus).
        query = (e.control.value or "").strip()
        if not query:
            search_panel.visible = False
            page.update()
            return
        client.send({"event": "archive.search", "query": query})

    pending_utterance: dict[str, Any] = {}
    # Mirror of worker's tasks_store — populated from "tasks.list" events only;
    # never fabricate ids/rows locally, or they'd diverge from the real backend.
    tasks_sidebar: list[dict[str, Any]] = []

    tasks_list_col = ft.Column(spacing=8)
    sidebar_new_field = ft.TextField(label="Новая задача", bgcolor=SURFACE2, dense=True, expand=True)

    def refresh_tasks_sidebar() -> None:
        tasks_list_col.controls.clear()
        for t in tasks_sidebar:
            hits = int(t.get("hits") or 0)
            misses = int(t.get("misses") or 0)
            level = t.get("level") or "Новичок"
            tasks_list_col.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(t["title"], size=13, color=TEXT),
                            ft.Text(f"{hits} реплик · {level}", size=11, color=MUTED),
                        ],
                        spacing=2,
                    ),
                    bgcolor=SURFACE2,
                    padding=10,
                    border_radius=8,
                )
            )

    def add_sidebar_task(_: ft.ControlEvent | None = None) -> None:
        title = (sidebar_new_field.value or "").strip()
        if not title:
            set_status("Введите название новой задачи")
            return
        sidebar_new_field.value = ""
        client.send({"event": "task.create", "utterance_id": "", "title": title})
        set_status(f"Создана задача: {title}")
        page.update()



    mic_dd = ft.Dropdown(label="Микрофон", options=[], width=320, dense=True, bgcolor=SURFACE2)
    model_dd = ft.Dropdown(label="Модель ASR", options=[], width=360, dense=True, bgcolor=SURFACE2)
    model_rec_label = ft.Text("Рекомендация: —", size=11, color=MUTED)
    selected_model_id: str | None = None
    recommended_model_id: str | None = None
    ui_settings = load_ui_settings()
    wizard_active = not bool(ui_settings.get("onboarded"))

    topic_field = ft.TextField(
        label="Тема встречи",
        hint_text="Тема встречи",
        expand=True,
        bgcolor=SURFACE2,
        border_color=BORDER,
    )

    body = ft.Container(expand=True, bgcolor=BG, padding=20)
    nav_row = ft.Row(spacing=4, alignment=ft.MainAxisAlignment.SPACE_AROUND, expand=True)
    bottom_nav = ft.Container(
        bgcolor=SURFACE,
        padding=ft.Padding.symmetric(vertical=10, horizontal=8),
        border=ft.Border(top=ft.BorderSide(1, BORDER)),
        content=nav_row,
    )

    def set_status(msg: str) -> None:
        status.value = msg
        page.update()

    KIND_LABEL = {"decision": "Решение", "risk": "Риск", "blocker": "Блокер"}
    KIND_COLOR = {"decision": OK, "risk": WARN, "blocker": REC}

    def append_protocol(prefix: str, text: str, *, job_id: str = "", backend: str = "") -> None:
        entry = ProtocolLine(text=text, job_id=job_id or prefix, backend=backend, meeting_id=current_meeting_id or "")
        protocol_entries.append(entry)
        if job_id:
            protocol_by_id[job_id] = entry
        line = f"[{prefix}] {text}" if prefix else text
        row_id = f"row-{job_id or len(protocol_entries)}"
        kind_badge = ft.Text("", size=10, visible=False)
        text_ctl = ft.Text(line, selectable=True, size=13, color=TEXT, expand=True)
        entry._badge = kind_badge  # type: ignore[attr-defined]

        def _delete_line(_: ft.ControlEvent) -> None:
            if entry in protocol_entries:
                protocol_entries.remove(entry)
            for c in list(transcript.controls):
                if getattr(c, "data", None) == row_id:
                    transcript.controls.remove(c)
            page.update()

        row = ft.Container(
            data=row_id,
            content=ft.Row(
                [kind_badge, text_ctl, ft.IconButton(ft.Icons.CLOSE, icon_size=14, icon_color=MUTED, on_click=_delete_line, tooltip="Удалить строку")],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE2,
            padding=10,
            border_radius=8,
        )
        transcript.controls.append(row)
        page.update()

    def apply_kind(job_id: str, kind: str, kind_score: float) -> None:
        entry = protocol_by_id.get(job_id)
        if entry is None or kind == "speech":
            return
        entry.kind = kind
        entry.kind_score = kind_score
        badge = getattr(entry, "_badge", None)
        if badge is not None:
            badge.value = KIND_LABEL.get(kind, kind)
            badge.color = KIND_COLOR.get(kind, MUTED)
            badge.visible = True
            page.update()

    def apply_task_assignment(job_id: str, task_id: str) -> None:
        entry = protocol_by_id.get(job_id)
        if entry is None or not task_id:
            return
        entry.task_id = task_id
        title = next((t["title"] for t in tasks_sidebar if t["task_id"] == task_id), task_id)
        entry.task_title = title

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
            refresh_model_dropdown()
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
        nonlocal queue_pending, queue_done, model_rows, current_meeting_id
        et = event.get("event")
        if et == "hw.profile":
            nonlocal recommended_model_id
            prof = event.get("profile") or {}
            if isinstance(prof, dict):
                name = prof.get("name") or "?"
                hint = prof.get("asr_model_hint") or ""
                reason = prof.get("reason") or ""
                hw_label.value = f"Профиль: {name}" + (f" · {hint}" if hint else "") + (f" · {reason}" if reason else "")
                # Map profile → recommended catalog id
                n = str(name).lower()
                force_cpu = (os.environ.get("STENOGRAF_FORCE_CPU") or "").strip() in {"1", "true", "yes"}
                if force_cpu or n == "low":
                    recommended_model_id = "fw-base" if any(r.get("id") == "fw-base" for r in model_rows) else "whisper-base"
                elif n == "high":
                    recommended_model_id = "fw-small" if any(r.get("id") == "fw-small" for r in model_rows) else "whisper-small"
                else:
                    recommended_model_id = "whisper-base"
                # Prefer explicit recommend from worker if present
                if event.get("recommend_model_id"):
                    recommended_model_id = str(event.get("recommend_model_id"))
                elif prof.get("recommend_model_id"):
                    recommended_model_id = str(prof.get("recommend_model_id"))
                model_rec_label.value = f"Рекомендация: {recommended_model_id} ({name})"
                refresh_model_dropdown()
            else:
                hw_label.value = f"Профиль: {prof}"
        elif et == "mic.list":
            devices = event.get("devices") or []
            mic_dd.options = [
                ft.dropdown.Option(key=str(d.get("id", i)), text=str(d.get("name") or f"Mic {i}"))
                for i, d in enumerate(devices)
            ]
            saved = str(ui_settings.get("device_id") or "")
            keys = [str(o.key) for o in mic_dd.options]
            if saved and saved in keys:
                mic_dd.value = saved
            elif mic_dd.options and not mic_dd.value:
                mic_dd.value = mic_dd.options[0].key
            set_status("Микрофоны обновлены")
        elif et in ("audio.chunk", "mic.level"):
            nonlocal peak_level
            rms = event.get("rms")
            db = event.get("db")
            level = event.get("level")
            if isinstance(rms, (int, float)) and not isinstance(db, (int, float)):
                db = _db_from_rms(float(rms))
            if isinstance(db, (int, float)):
                db_label.value = f"{float(db):.0f} дБ"
                if not isinstance(level, (int, float)):
                    level = _level_from_db(float(db))
            if isinstance(level, (int, float)):
                lvl = max(0.0, min(1.0, float(level)))
                peak_level = max(lvl, peak_level * 0.82)
                vu_history.append(peak_level)
                paint_vu()
        elif et == "asr.listening":
            buf = event.get("buffered_sec")
            rms = event.get("rms")
            if isinstance(buf, (int, float)) and float(buf) > 0:
                bits = ["слушаю…"]
                bits.append(f"{float(buf):.1f} с")
                if isinstance(rms, (int, float)):
                    bits.append(f"rms={float(rms):.3f}")
                listen_label.value = " · ".join(bits)
            else:
                listen_label.value = ""
        elif et == "mic.warn":
            reason = event.get("reason") or event.get("code") or "low_rms"
            set_status(f"Микрофон: похоже не тот вход ({reason}). RMS < 0.01 — смените устройство.")
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
                # classification via worker task.suggest (LOGIC.md)
        elif et == "task.suggest":
            uid = str(event.get("utterance_id") or event.get("job_id") or "")
            text_value = str(event.get("text") or "")
            cands = event.get("candidates") or []
            apply_kind(uid, str(event.get("kind") or "speech"), float(event.get("kind_score") or 0.0))
            if event.get("auto") and cands:
                set_status(f"Авто → {cands[0].get('title')} ({cands[0].get('score')})")
            elif event.get("intent") and event["intent"].get("type") == "create_task":
                show_suggest(uid, text_value, cands)
                if event["intent"].get("title"):
                    new_task_field.value = event["intent"]["title"]
            else:
                show_suggest(uid, text_value, cands)
                if event.get("ambiguous") and event.get("reason"):
                    classify_hint.value = f"Куда отнести? ({event.get('reason')})"
                else:
                    classify_hint.value = "Куда отнести?"
            page.update()
        elif et == "task.assigned":
            apply_task_assignment(str(event.get("utterance_id") or ""), str(event.get("task_id") or ""))
            if event.get("auto"):
                set_status(f"Авто-назначено → {event.get('task_id')} · score={event.get('score')}")
            classify_panel.visible = False
            page.update()
        elif et == "task.created":
            task = event.get("task") or {}
            set_status(f"Задача создана: {task.get('title')}")
            client.send({"event": "tasks.reload"})  # pick up the canonical row (hits/level)
            page.update()
        elif et == "tasks.list":
            tasks_sidebar.clear()
            tasks_sidebar.extend(event.get("tasks") or [])
            refresh_tasks_sidebar()
            if active_tab == "Сроки":
                body.content = deadlines_view()
            page.update()
        elif et == "meeting.start":
            current_meeting_id = event.get("meeting_id")
            meeting_label.value = f"Встреча «{event.get('title') or 'без темы'}» идёт"
            meeting_label.color = OK
            meeting_btn.text = "Завершить встречу"
            pause_nudge.visible = False
            page.update()
        elif et == "meeting.end":
            current_meeting_id = None
            meeting_label.value = "Встреча не начата"
            meeting_label.color = MUTED
            meeting_btn.text = "Начать встречу"
            pause_nudge.visible = False
            page.update()
        elif et == "meeting.pause_suggest":
            pause_nudge.visible = True
            page.update()
        elif et == "map.state":
            map_view.set_state(event.get("nodes") or [], event.get("edges") or [])
        elif et == "ics.exported":
            set_status(f"Экспортировано: {event.get('path')}")
            page.update()
        elif et == "archive.search_result":
            render_search_results(event.get("results") or [])
        elif et == "archive.exported":
            set_status(f"JSON снимок: {event.get('path')}")
            page.update()
        elif et == "archive.imported":
            set_status(f"Импортировано: задач {event.get('tasks')}, реплик {event.get('archive')}")
            client.send({"event": "map.request"})
            page.update()
        elif et == "archive.import_error":
            set_status(f"Ошибка импорта: {event.get('error')}")
            page.update()
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

    def _map_link(task_a: str, task_b: str) -> None:
        client.send({"event": "task.link", "task_a": task_a, "task_b": task_b})
        set_status(f"Связаны: {task_a} ↔ {task_b}")

    def _map_hide_pair(task_a: str, task_b: str) -> None:
        client.send({"event": "task.hide_pair", "task_a": task_a, "task_b": task_b})
        set_status(f"Связь скрыта: {task_a} ↔ {task_b}")

    map_view = MapView(on_link=_map_link, on_hide_pair=_map_hide_pair)

    def refresh_model_dropdown() -> None:
        nonlocal selected_model_id
        # Prefer downloadable / local engines for explicit pick; include faster-whisper ids
        opts = []
        for row in model_rows:
            mid = str(row.get("id") or "")
            if not mid:
                continue
            eng = str(row.get("engine") or "")
            mark = ""
            if mid == recommended_model_id:
                mark = " ★ рек."
            local = row.get("local_present")
            loc = " ✓" if local is True else ("" if local is None else "")
            label = f"{mid} [{eng}]{loc}{mark}"
            opts.append(ft.dropdown.Option(key=mid, text=label))
        model_dd.options = opts
        saved_model = str(ui_settings.get("model_id") or "")
        keys = [str(o.key) for o in opts]
        if saved_model and saved_model in keys:
            model_dd.value = saved_model
            selected_model_id = saved_model
        elif recommended_model_id and recommended_model_id in keys and not model_dd.value:
            model_dd.value = recommended_model_id
            selected_model_id = recommended_model_id
        elif opts and not model_dd.value:
            model_dd.value = opts[0].key
            selected_model_id = opts[0].key
        page.update()

    def on_model_pick(e: ft.ControlEvent) -> None:
        nonlocal selected_model_id
        selected_model_id = model_dd.value
        save_ui_settings(model_id=selected_model_id, device_id=mic_dd.value)
        client.send({"event": "asr.model", "model_id": selected_model_id})
        set_status(f"Модель: {selected_model_id}")

    model_dd.on_change = on_model_pick

    def on_mic_pick(e: ft.ControlEvent) -> None:
        save_ui_settings(device_id=mic_dd.value, model_id=model_dd.value or selected_model_id)
        set_status(f"Микрофон сохранён: {mic_dd.value}")

    mic_dd.on_change = on_mic_pick

    engine_dd = ft.Dropdown(
        label="Движок STT",
        width=280,
        dense=True,
        bgcolor=SURFACE2,
        value=asr_engine if asr_engine in ("whisper", "browser") else "whisper",
        options=[
            ft.dropdown.Option(key="whisper", text="Whisper (офлайн worker)"),
            ft.dropdown.Option(key="browser", text="Browser / Edge Web Speech"),
        ],
    )

    def on_engine_pick(_: ft.ControlEvent) -> None:
        nonlocal asr_engine
        preferred = engine_dd.value or "whisper"
        effective, reason = resolve_stt_engine(preferred)
        asr_engine = effective
        engine_dd.value = effective
        save_ui_settings(asr_engine=asr_engine)
        set_status(reason or f"Движок: {asr_engine}")
        page.update()

    engine_dd.on_change = on_engine_pick

    def on_browser_message(msg: dict) -> None:
        nonlocal asr_engine
        mtype = msg.get("type")
        uid = str(msg.get("utterance_id") or f"b-{int(__import__('time').time())}")
        text_value = str(msg.get("text") or "").strip()
        if mtype == "partial" and text_value:
            partial_box.value = text_value
            partial_box.visible = True
            client.send({"event": "asr.partial", "utterance_id": uid, "text": text_value, "engine": "browser"})
            page.update()
        elif mtype == "final" and text_value:
            partial_box.value = ""
            partial_box.visible = False
            append_protocol("browser", text_value, job_id=uid, backend="browser")
            client.send({"event": "asr.final", "utterance_id": uid, "text": text_value, "engine": "browser"})
            page.update()
        elif mtype == "error":
            err = str(msg.get("error") or "")
            if should_fallback_to_whisper(err):
                asr_engine = "whisper"
                engine_dd.value = "whisper"
                save_ui_settings(asr_engine="whisper")
                set_status(f"Browser: {err} — фолбэк на Whisper (перезапустите Запись)")
            else:
                set_status(f"Browser STT: {err}")

    browser_host, browser_start, browser_stop = build_webview(on_browser_message)




    def show_suggest(utterance_id: str, text_value: str, candidates: list[dict[str, Any]]) -> None:
        pending_utterance.clear()
        pending_utterance.update({"utterance_id": utterance_id, "text": text_value})
        classify_text.value = f"«{text_value}»"
        classify_candidates.controls.clear()
        for c in candidates:
            score = float(c.get("score") or 0)
            title = str(c.get("title") or c.get("task_id") or "?")
            tid = str(c.get("task_id") or "")
            pct = int(round(score * 100))
            fill = max(0.08, min(1.0, score))

            def make_assign(task_id: str):
                def _(_: ft.ControlEvent) -> None:
                    classify_assign(task_id)
                return _

            bar = ft.Stack(
                [
                    ft.Container(bgcolor=BORDER, border_radius=8, height=36, expand=True),
                    ft.Container(
                        bgcolor="#3f3f46",
                        border_radius=8,
                        height=36,
                        width=None,
                        # approximate fill via opacity row
                    ),
                    ft.Container(
                        content=ft.Text(f"{title} — {pct}%", size=13, color=TEXT),
                        alignment=ft.Alignment.CENTER,
                        height=36,
                        expand=True,
                    ),
                ],
                height=36,
                expand=True,
            )
            # Simpler clickable row with progress
            classify_candidates.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.ProgressBar(value=fill, width=120, color=ACCENT, bgcolor=BORDER),
                            ft.Text(f"{title} — {pct}%", size=13, color=TEXT, expand=True),
                        ]
                    ),
                    bgcolor=SURFACE2,
                    padding=8,
                    border_radius=8,
                    on_click=make_assign(tid),
                )
            )
        classify_panel.visible = True
        page.update()

    def classify_assign(task_id: str) -> None:
        uid = pending_utterance.get("utterance_id") or ""
        client.send({"event": "task.assign", "utterance_id": uid, "task_id": task_id})
        classify_panel.visible = False
        set_status(f"Отнесено → {task_id}")
        page.update()

    def classify_create() -> None:
        title = (new_task_field.value or "").strip()
        if not title:
            set_status("Введите название новой задачи")
            return
        uid = pending_utterance.get("utterance_id") or ""
        client.send({"event": "task.create", "utterance_id": uid, "title": title})
        new_task_field.value = ""
        classify_panel.visible = False
        set_status(f"Создана задача: {title}")
        page.update()

    def classify_skip() -> None:
        uid = pending_utterance.get("utterance_id") or ""
        client.send({"event": "task.skip", "utterance_id": uid})
        classify_panel.visible = False
        set_status("Не отнесено")
        page.update()

    # Wire classify panel AFTER handlers exist (avoid orphan fields / late binding issues)
    def _on_new_task_submit(e: ft.ControlEvent) -> None:
        classify_create()

    new_task_field.on_submit = _on_new_task_submit
    sidebar_new_field.on_submit = add_sidebar_task
    classify_panel.content = ft.Column(
        [
            classify_hint,
            classify_text,
            classify_candidates,
            ft.Row(
                [
                    ft.OutlinedButton("Не относить никуда", on_click=lambda e: classify_skip()),
                    new_task_field,
                    ft.FilledButton(
                        "Создать",
                        bgcolor=ACCENT,
                        color=ACCENT_FG,
                        on_click=lambda e: classify_create(),
                    ),
                ],
                wrap=True,
            ),
        ],
        spacing=8,
    )

    def start_rec(_: ft.ControlEvent) -> None:
        nonlocal meeting_open, recording, asr_engine
        meeting_open = True
        mid = model_dd.value or selected_model_id
        recording = True
        rec_dot.visible = True
        rec_label.visible = True
        preferred = asr_engine
        effective, reason = resolve_stt_engine(preferred, has_webview=bool(browser_start))
        if effective != preferred:
            asr_engine = effective
            engine_dd.value = effective
            save_ui_settings(asr_engine=effective, device_id=mic_dd.value, model_id=mid)
            set_status(reason)
        else:
            save_ui_settings(device_id=mic_dd.value, model_id=mid)
            set_status(f"Запись… модель={mid or 'auto'} · {effective}")
        client.start(mic_id=mic_dd.value, segment_sec=3.0, model_id=mid, seconds=0, stt_engine=effective)
        if effective == "browser" and browser_start:
            browser_start(f"b-{int(__import__('time').time())}")
            set_status("Browser STT + VU (sounddevice)")
        page.update()

    def stop_rec(_: ft.ControlEvent) -> None:
        nonlocal recording
        recording = False
        if browser_stop:
            browser_stop()
        client.stop()
        rec_dot.visible = False
        rec_label.visible = False
        listen_label.value = ""
        partial_box.visible = False
        paint_vu()
        set_status("Остановлено")
        page.update()

    def start_meeting(e: ft.ControlEvent) -> None:
        title = (topic_field.value or "").strip()
        if not client.running:
            start_rec(e)
        client.send({"event": "meeting.start", "title": title})

    def end_meeting(_: ft.ControlEvent) -> None:
        client.send({"event": "meeting.end"})

    def toggle_meeting(e: ft.ControlEvent) -> None:
        if current_meeting_id:
            end_meeting(e)
        else:
            start_meeting(e)

    meeting_btn = ft.FilledButton(
        "Начать встречу",
        bgcolor=ACCENT,
        color=ACCENT_FG,
        on_click=toggle_meeting,
    )

    def do_export(kind: str) -> None:
        if not protocol_entries:
            set_status("Протокол пуст")
            return
        out = default_export_dir()
        title = (topic_field.value or "").strip() or "Протокол встречи"
        try:
            if kind == "DOCX":
                path = export_docx(protocol_entries, out / "protocol-latest.docx", title=title)
                set_status(f"Экспорт DOCX: {path}")
            elif kind == "HTML":
                path = export_html(protocol_entries, out / "protocol-latest.html", title=title)
                set_status(f"Экспорт HTML: {path}")
            else:  # PACKAGE — LOGIC.md §9: протокол + действия + выжимка + черновик гайда
                paths = export_package(protocol_entries, title=title)
                set_status(f"Пакет собран: {paths['protocol_md'].parent}")
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
                        "Реплик пока нет. Нажмите «Записать» или откройте встречу.",
                        color=MUTED,
                        size=13,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            border=ft.Border.all(1, BORDER),
            border_radius=16,
            padding=12,
            expand=True,
            bgcolor=SURFACE,
        )
        return ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("Студия", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                        ft.Text(
                            "Сначала откройте встречу — реплики лягут в неё. Пауза 8 с предлагает протокол.",
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
                                    vu_row,
                                ],
                                spacing=8,
                            ),
                            bgcolor=SURFACE,
                            border=ft.Border.all(1, BORDER),
                            border_radius=16,
                            padding=16,
                        ),
                        ft.Row([topic_field, meeting_btn]),
                        meeting_label,
                        pause_nudge,
                        ft.Row(
                            [
                                mic_dd,
                                ft.OutlinedButton("Обновить", on_click=refresh_mics),
                            ]
                        ),
                        ft.Row(
                            [
                                model_dd,
                                model_rec_label,
                            ],
                            wrap=True,
                        ),
                        ft.Row(
                            [
                                ft.FilledButton(
                                    content=ft.Row(
                                        [ft.Icon(ft.Icons.MIC, size=16, color=REC_FG), ft.Text("Записать", color=REC_FG)],
                                        spacing=6,
                                        tight=True,
                                    ),
                                    bgcolor=REC,
                                    color=REC_FG,
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                                    on_click=start_rec,
                                ),
                                ft.OutlinedButton(
                                    "Стоп",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                                    on_click=stop_rec,
                                ),
                                ft.OutlinedButton(
                                    "Протокол",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                                    on_click=lambda e: do_export("DOCX"),
                                ),
                                ft.OutlinedButton(
                                    "HTML",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                                    on_click=lambda e: do_export("HTML"),
                                ),
                                ft.OutlinedButton(
                                    "Пакет",
                                    tooltip="Протокол + действия + выжимка + черновик гайда",
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)),
                                    on_click=lambda e: do_export("PACKAGE"),
                                ),
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                        queue_text,
                        listen_label,
                        partial_box,
                        status,
                        classify_panel,
                        transcript_box,
                    ],
                    expand=True,
                    spacing=10,
                ),
                ft.Container(
                    width=280,
                    bgcolor=SURFACE,
                    border=ft.Border.all(1, BORDER),
                    border_radius=16,
                    padding=12,
                    content=ft.Column(
                        [
                            ft.Text("Задачи", size=18, weight=ft.FontWeight.W_600, color=TEXT),
                            ft.Text("Профили ключевых слов — следующий слой", size=11, color=MUTED),
                            ft.Row(
                                [
                                    sidebar_new_field,
                                    ft.FilledButton("+", bgcolor=ACCENT, color=ACCENT_FG, on_click=add_sidebar_task),
                                ],
                                spacing=6,
                            ),
                            tasks_list_col,
                        ],
                        spacing=10,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                ),
            ],
            expand=True,
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    file_picker = ft.FilePicker()

    def export_json_click(_: ft.ControlEvent) -> None:
        client.send({"event": "archive.export"})
        set_status("Экспорт JSON…")

    async def _pick_and_import(_: ft.ControlEvent) -> None:
        files = await file_picker.pick_files(dialog_title="Импорт JSON", allowed_extensions=["json"])
        if not files:
            return
        client.send({"event": "archive.import", "path": files[0].path})
        set_status(f"Импорт: {files[0].path}")

    def import_json_click(e: ft.ControlEvent) -> None:
        page.run_task(_pick_and_import, e)

    def settings_view() -> ft.Control:
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Настройки", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                        ft.Container(expand=True),
                        ft.OutlinedButton("Мастер настройки", on_click=wizard_restart),
                    ]
                ),
                ft.Text("Движок: Whisper (worker) или Browser/Edge Web Speech (WebView2).", size=12, color=MUTED),
                engine_dd,
                ft.Text(
                    "Browser нужен flet-webview-all + Edge WebView2. VU всегда с sounddevice.",
                    size=11,
                    color=MUTED,
                ),
                hw_label,
                backend_label,
                ft.Row(
                    [
                        ft.Text("Данные", size=16, weight=ft.FontWeight.W_600, color=TEXT),
                        ft.Container(expand=True),
                        ft.OutlinedButton("Экспорт JSON", on_click=export_json_click),
                        ft.OutlinedButton("Импорт JSON", on_click=import_json_click),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(
                    "Снимок задач + до 400 реплик архива (LOGIC.md §14) — %LOCALAPPDATA%\\Stenograf\\exports",
                    size=11,
                    color=MUTED,
                ),
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
                    border_radius=16,
                    padding=10,
                    expand=True,
                    bgcolor=SURFACE,
                ),
            ],
            expand=True,
            spacing=10,
        )

    def snooze_task_row(task_id: str, minutes: float = 15.0) -> None:
        client.send({"event": "task.snooze", "task_id": task_id, "minutes": minutes})
        set_status(f"Отложено на {int(minutes)} мин")

    def export_ics_click(_: ft.ControlEvent) -> None:
        client.send({"event": "ics.export"})
        set_status("Экспорт .ics…")

    def deadlines_view() -> ft.Control:
        # LOGIC.md §11 — remind_at/due_at/repeat_min/reminded; список + месяц.
        with_dates = [t for t in tasks_sidebar if t.get("remind_at") or t.get("due_at")]
        by_month: dict[str, list[dict[str, Any]]] = {}
        for t in with_dates:
            ts = t.get("due_at") or t.get("remind_at")
            try:
                label = datetime.fromtimestamp(float(ts)).strftime("%B %Y")
            except (TypeError, ValueError, OSError):
                label = "Без даты"
            by_month.setdefault(label, []).append(t)

        rows: list[ft.Control] = []
        if not with_dates:
            rows.append(ft.Text("Нет напоминаний. Задайте remind_at/due_at задаче.", size=13, color=MUTED))
        for month, items in by_month.items():
            rows.append(ft.Text(month, size=13, weight=ft.FontWeight.W_600, color=MUTED))
            for t in items:
                ts = t.get("due_at") or t.get("remind_at")
                try:
                    when = datetime.fromtimestamp(float(ts)).strftime("%d.%m %H:%M")
                except (TypeError, ValueError, OSError):
                    when = "—"
                tid = str(t.get("task_id") or "")
                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(when, size=12, color=MUTED, width=90),
                                ft.Text(t.get("title") or tid, size=13, color=TEXT, expand=True),
                                ft.OutlinedButton("Отложить +15м", on_click=lambda e, tid=tid: snooze_task_row(tid)),
                            ]
                        ),
                        bgcolor=SURFACE2,
                        padding=10,
                        border_radius=8,
                    )
                )

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Сроки", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                        ft.Container(expand=True),
                        ft.OutlinedButton("Экспорт .ics", on_click=export_ics_click),
                    ]
                ),
                ft.Column(rows, spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            expand=True,
            spacing=12,
        )

    def open_package_folder(path: Path) -> None:
        page.launch_url(path.resolve().as_uri())

    def protocol_view() -> ft.Control:
        # LOGIC.md §9 — browse собранные пакеты; сборка кнопкой «Пакет» — в Студии.
        packages = list_packages()
        rows: list[ft.Control] = []
        if not packages:
            rows.append(ft.Text("Пакетов ещё нет. Соберите «Пакет» в Студии.", size=13, color=MUTED))
        for pkg in packages[:50]:
            title, date = package_preview(pkg)
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [ft.Text(title, size=13, color=TEXT), ft.Text(date, size=11, color=MUTED)],
                                spacing=2,
                                expand=True,
                            ),
                            ft.OutlinedButton("Открыть папку", on_click=lambda e, p=pkg: open_package_folder(p)),
                        ]
                    ),
                    bgcolor=SURFACE2,
                    padding=10,
                    border_radius=8,
                )
            )
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Протокол", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                        ft.Container(expand=True),
                        ft.OutlinedButton("Обновить", on_click=lambda e: render_body()),
                    ]
                ),
                ft.Text("Собранные пакеты: протокол + действия + выжимка + черновик гайда.", size=12, color=MUTED),
                ft.Column(rows, spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            expand=True,
            spacing=12,
        )

    def guides_view() -> ft.Control:
        tiles = [
            ft.ExpansionTile(
                title=ft.Text(g.title, size=14, weight=ft.FontWeight.W_600, color=TEXT),
                subtitle=ft.Text(g.subtitle, size=11, color=MUTED),
                bgcolor=SURFACE2,
                collapsed_bgcolor=SURFACE2,
                text_color=TEXT,
                collapsed_text_color=TEXT,
                icon_color=MUTED,
                collapsed_icon_color=MUTED,
                controls=[
                    ft.Container(
                        content=ft.Text(f"{i}. {step}", size=12, color=TEXT),
                        padding=ft.Padding.only(left=16, right=16, bottom=8),
                    )
                    for i, step in enumerate(g.steps, start=1)
                ],
            )
            for g in GUIDES
        ]
        return ft.Column(
            [
                ft.Text("Гайды", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                ft.Text("Как пользоваться Стенографом, по разделам.", size=12, color=MUTED),
                ft.Column(tiles, spacing=8, scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            expand=True,
            spacing=12,
        )

    def wizard_next(_: ft.ControlEvent) -> None:
        nonlocal wizard_step
        wizard_step = min(wizard_step + 1, 2)
        render_body()

    def wizard_finish(_: ft.ControlEvent | None = None) -> None:
        nonlocal wizard_active
        wizard_active = False
        save_ui_settings(onboarded=True)
        bottom_nav.visible = True
        render_body()

    def wizard_restart(_: ft.ControlEvent) -> None:
        nonlocal wizard_active, wizard_step
        wizard_active = True
        wizard_step = 0
        bottom_nav.visible = False
        render_body()

    def wizard_view() -> ft.Control:
        # DESIGN.md §5 «Мастер»: один шаг — одна мысль, кнопка на всю ширину.
        dots = ft.Row(
            [
                ft.Container(width=8, height=8, border_radius=4, bgcolor=ACCENT if i == wizard_step else BORDER)
                for i in range(3)
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        if wizard_step == 0:
            step_content: ft.Control = ft.Column(
                [
                    ft.Text("Стенограф", size=32, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                    ft.Text(
                        "Локальный диктофон: речь → задачи → протокол. Всё остаётся на этом компьютере.",
                        size=14,
                        color=MUTED,
                    ),
                ],
                spacing=12,
            )
            primary_label, on_primary = "Далее", wizard_next
        elif wizard_step == 1:
            step_content = ft.Column(
                [
                    ft.Text("Выберите микрофон", size=28, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                    mic_dd,
                    ft.OutlinedButton("Обновить список", on_click=refresh_mics),
                ],
                spacing=12,
            )
            primary_label, on_primary = "Далее", wizard_next
        else:
            step_content = ft.Column(
                [
                    ft.Text("Модель распознавания", size=28, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                    model_dd,
                    model_rec_label,
                    download_progress,
                ],
                spacing=12,
            )
            primary_label, on_primary = "Начать", wizard_finish

        return ft.Column(
            [
                dots,
                ft.Container(content=step_content, expand=True, alignment=ft.Alignment.CENTER),
                ft.FilledButton(primary_label, bgcolor=ACCENT, color=ACCENT_FG, on_click=on_primary),
                ft.TextButton("Пропустить", on_click=wizard_finish),
            ],
            spacing=20,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def compact_toggle(_: ft.ControlEvent) -> None:
        nonlocal compact_mode
        compact_mode = not compact_mode
        bottom_nav.visible = not compact_mode and not wizard_active
        render_body()

    def compact_view() -> ft.Control:
        # DESIGN.md §5 «Compact»: точка rec (уже в шапке) + «слушаю» + RMS + Протокол + Развернуть.
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column([listen_label, db_label], spacing=2, expand=True),
                    ft.OutlinedButton("Протокол", on_click=lambda e: do_export("PACKAGE")),
                    ft.OutlinedButton("Развернуть", on_click=compact_toggle),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE,
            border=ft.Border.all(1, BORDER),
            border_radius=16,
            padding=16,
        )

    def render_body() -> None:
        if wizard_active:
            body.content = wizard_view()
            page.update()
            return
        if compact_mode:
            body.content = compact_view()
            page.update()
            return
        if active_tab == "Студия":
            body.content = studio_view()
        elif active_tab == "Ещё":
            body.content = settings_view()
        elif active_tab == "Карта":
            body.content = map_view.control()
            if client.running:
                client.send({"event": "map.request"})
        elif active_tab == "Сроки":
            body.content = deadlines_view()
        elif active_tab == "Протокол":
            body.content = protocol_view()
        elif active_tab == "Гайды":
            body.content = guides_view()
        page.update()

    def switch_tab(name: str):
        def _(_: ft.ControlEvent) -> None:
            nonlocal active_tab
            active_tab = name
            rebuild_nav()
            render_body()

        return _

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

    def rebuild_nav() -> None:
        nav_row.controls.clear()
        for name in TABS:
            selected = name == active_tab
            nav_row.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(name, size=11, weight=ft.FontWeight.W_600 if selected else None,
                                    color=TEXT if selected else MUTED),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=0,
                    ),
                    padding=ft.Padding.symmetric(vertical=8, horizontal=10),
                    border_radius=10,
                    bgcolor=SURFACE3 if selected else None,
                    on_click=switch_tab(name),
                    expand=True,
                )
            )

    header = ft.Container(
        bgcolor=BG,
        padding=ft.Padding.symmetric(vertical=14, horizontal=20),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    content=ft.Icon(ft.Icons.MIC, color=TEXT, size=18),
                                    width=36,
                                    height=36,
                                    bgcolor=SURFACE2,
                                    border_radius=18,
                                    alignment=ft.Alignment.CENTER,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("Стенограф", size=22, weight=ft.FontWeight.W_600, color=TEXT, font_family="Georgia"),
                                        ft.Text("Диктофон · карта · напоминания", size=11, color=MUTED),
                                    ],
                                    spacing=0,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Container(expand=True),
                        ft.TextField(
                            hint_text="Поиск по архиву",
                            width=260,
                            dense=True,
                            bgcolor=SURFACE,
                            border_color=BORDER,
                            border_radius=20,
                            on_submit=do_search,
                        ),
                        ft.IconButton(
                            ft.Icons.UNFOLD_LESS,
                            icon_size=18,
                            icon_color=MUTED,
                            tooltip="Compact",
                            on_click=compact_toggle,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([rec_dot, rec_label, hw_label, backend_label], spacing=12),
            ],
            spacing=8,
        ),
    )

    rebuild_nav()
    bottom_nav.visible = not wizard_active
    render_body()
    controls = [header, search_panel, body, bottom_nav]
    if browser_host is not None:
        controls.append(ft.Container(content=browser_host, width=1, height=1, opacity=0.01))
    page.overlay.append(file_picker)
    page.add(ft.Column(controls, expand=True, spacing=0))
    refresh_tasks_sidebar()
    refresh_mics()
    load_models_from_disk()


if __name__ == "__main__":
    ft.run(main)
