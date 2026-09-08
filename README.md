# Стенограф (Stenograph)

Локальный Windows-диктофон: речь → протокол → задачи.

**Продукт для Windows:** `ui/` + `worker/` (Python, Flet). Запуск:

```bat
python -m ui.main
```

Сборка exe: `flet build windows` — см. [CLAUDE_CODE_PLAN.md](./CLAUDE_CODE_PLAN.md) и [SETUP_WINDOWS.md](./SETUP_WINDOWS.md).

## Документы

- [DESIGN.md](./DESIGN.md) — UI / токены
- [LOGIC.md](./LOGIC.md) — классификатор, kind, пороги (эталон)
- [SETUP_WINDOWS.md](./SETUP_WINDOWS.md) — первый прогон на Zenbook / Arc

Также: [MVP.md](./MVP.md), [README_WORKER.md](./README_WORKER.md), [README_UI.md](./README_UI.md).

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

Данные: `%LOCALAPPDATA%\Stenograf\` (`audio_queue`, `models`, `exports`, `tasks.json`, `archive.json`).

## Статус

- [x] Worker: capture → диск → очередь ASR
- [x] ASR: whisper.cpp/OpenVINO (если есть) → faster-whisper → stub; VAD on by default (`STENOGRAF_VAD=0` off)
- [x] Flet UI: mic, очередь, протокол, backend/confidence
- [x] Экспорт DOCX/HTML
- [x] Классификатор / «Куда отнести?» — `task.suggest` (intent + cosine + feedback)
- [x] Встречи: `meeting_id`, пауза протокола 8с отдельно от STT-паузы ~1с
- [x] Карта связей: essence, авто-рёбра, drag-link, hide по клику
- [x] Протокол: секции по kind, плейсхолдеры шаблона, пакет документов, .ics
- [x] Реальный список задач/сроков в UI (синхронизирован с воркером, не заглушки)
- [x] Архив реплик (400, JSON экспорт/импорт), поиск по архиву — на воркере, с полным профилем задач
- [x] `flet build windows` настроен (CI + SETUP_WINDOWS.md) — **не проверен на реальной Windows-машине**
- [ ] Первый стабильный прогон на целевом Zenbook
