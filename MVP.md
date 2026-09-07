# Stenograph MVP (Windows-first)

Обновлено после согласования в комнате планирования (2026-09-07).
Старые ориентиры на Tauri/PWA как целевой Windows-shell **устарели** — см. ниже.

## Цель MVP
Локальный диктофон на Windows: микрофон → запись на диск → очередь ASR → текстовый протокол.
Всё on-device. Интернет нужен только для первичной загрузки моделей.

Целевая машина: ASUS Zenbook 14 UX3405C (16 ГБ, Intel Arc). Язык STT: `ru`.

## Стек (зафиксировано)
- **UI shell:** Flet (один shell; Tauri/Electron/PWA в MVP не плодим).
- **Worker:** отдельный native/Python worker; UI не считает STT.
- **Audio:** sounddevice + выбор устройства (`query_devices`), сегменты на диск.
- **VAD:** Silero; webrtcvad как fallback.
- **STT:** whisper.cpp с **OpenVINO first** на Arc; fallback faster-whisper CPU/int8; на слабых ПК — меньшая модель / Vosk-класс fallback.
- **Модели:** не в бандле exe; `%LOCALAPPDATA%\Stenograf\models` + `index.json` (имя, URL, sha256, размер, профиль).
- **Данные MVP:** SQLite (встречи, реплики, протоколы) + аудио-сегменты на диске.
- **Экспорт (сразу после протокола):** DOCX + интерактивный HTML (оглавление, якоря); также Markdown/JSON по возможности.

## Инварианты
1. **Запись никогда не ждёт ASR.** Capture пишет чанки на диск независимо от очереди распознавания.
2. **Автопрофиль железа** при старте: `low | mid | high` → выбор модели ASR и лимитов параллелизма.
3. На mid/Arc: embeddings/LLM **не** крутить во время активной STT-очереди (только idle / пустая очередь).
4. Continuous-режим только с явным согласием + красный индикатор.
5. Модели скачиваются с resume + проверка sha256; очередь загрузки ниже приоритета записи/ASR.

## Контракт IPC (MVP)
- `audio.chunk` — сегмент записан (path, ts, device_id, rms)
- `asr.job` / `asr.result` — задача и результат (text, conf, language=ru)
- `meeting.protocol` — собранный протокол (plain + timestamps)
- `hw.profile` — выбранный профиль и обоснование
- `models.list` / `models.download` — каталог и прогресс
- `mic.list` / `mic.select` — устройства ввода

## Скоуп MVP (делаем)
1. Flet: студия (mic picker, start/pause/stop, индикатор очереди ASR, протокол).
2. Worker: сегменты на диск, один ASR-worker, `language=ru`, ресемпл 48→16 kHz.
3. Каталог моделей + скачивание + sha256.
4. Автопрофиль железа + рекомендации.
5. Экспорт протокола в DOCX и интерактивный HTML (фон, без сети).

## Вне MVP (позже)
- Задачи/напоминания, self-learning классификация, mind-map + RAG
- Гайды со скринами/видео (отдельный пайплайн, не realtime встречи)
- Словарь/codebook сжатия знаний — только после статистики повторов
- Android/tray/background recording, ZIP встречи, синки устройств

## Профили железа (черновик)
| Профиль | Когда | ASR |
|--------|--------|-----|
| low | ≤8 ГБ / слабый CPU | tiny/base, CPU; очередь может отставать |
| mid | ~16 ГБ + Arc (целевая) | small/base, whisper.cpp OpenVINO |
| high | много VRAM/RAM | medium / large-v3-turbo |

## Хранение
- Аудио: сегменты (позже Opus); опция удалить сырьё после подтверждённого транскрипта.
- Текст: SQLite + FTS позже.
- Сжатие codebook — не с дня 1 (сначала сырой текст + zstd по блокам).

## Источники
- Репо: https://github.com/hiromoto27/Stenograph
- PROJECT.md / шара Grok — продуктовый бэклог; этот файл — рабочий план MVP.
- Превью React/PWA в репо — справочно, не целевой Windows-shell.

## Порядок работ
1. Этот документ + выравнивание PROJECT.md (пометки устаревшего).
2. Каркас Flet + worker + IPC-заглушки.
3. Запись + mic picker + очередь на диск.
4. whisper.cpp OpenVINO + catalog/sha256.
5. Протокол + DOCX/HTML экспорт.
