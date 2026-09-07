# Стенограф (Stenograph)

Локальный диктофон для Windows: речь → протокол → задачи/карта (позже).
**Целевой MVP-shell: Flet UI + native Python worker** (не браузерное превью).

Документы:
- [MVP.md](./MVP.md) — скоуп и инварианты
- [SETUP_WINDOWS.md](./SETUP_WINDOWS.md) — первый прогон на Zenbook / Arc
- [README_WORKER.md](./README_WORKER.md) — worker / ASR
- [README_UI.md](./README_UI.md) — Flet UI / экспорт

## Быстрый старт (dev)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-worker.txt
pip install -r requirements-ui.txt
set PYTHONPATH=.
python -m worker.main --list-mics
python -m ui.main
```

Данные:
- аудио: `%LOCALAPPDATA%\Stenograf\audio_queue`
- модели: `%LOCALAPPDATA%\Stenograf\models`
- экспорт: `%LOCALAPPDATA%\Stenograf\exports`

## Статус

- [x] Worker: capture → диск → очередь ASR
- [x] ASR: whisper.cpp/OpenVINO (если есть) → faster-whisper → stub
- [x] Flet UI: mic, очередь, протокол, backend/confidence
- [x] Экспорт DOCX/HTML (оглавление, якоря)
- [ ] Первый стабильный прогон на целевом Zenbook
- [ ] Задачи / напоминания / mind-map / RAG / гайды — после MVP

Превью React/PWA и `src-tauri/` в репо — **legacy/справочно**, не целевой Windows-shell.
