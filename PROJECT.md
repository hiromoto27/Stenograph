# Стенограф

Локальный диктофон для рабочих разговоров на русском.
Слушает микрофон, распознаёт речь, раскладывает фразы по задачам, учится на уточнениях, собирает протокол, показывает связи задач и напоминает о сроках.

Рабочие названия: **Стенограф** (превью Grok), **NeuralDictaphone** (Flet, Windows exe).
Целевая машина: ASUS Zenbook 14 UX3405C, 16 ГБ, Intel Arc. Язык — русский. После установки моделей интернет не обязателен.

## Зачем

Обычный диктофон даёт сплошной текст. Нужно включить микрофон по кнопке или держать постоянно (индикатор + согласие), понять к какой задаче относится реплика, спросить если неясно, собрать протокол, показать карту связей и не потерять срок.

Постоянная запись третьих лиц без согласия недопустима: continuous только с подтверждением и красной точкой.

## Две реализации

| | Превью Grok | NeuralDictaphone (Flet) |
|---|---|---|
| Стек | TypeScript, Vite, React, Zustand | Python, Flet ≥0.80 |
| STT | Web Speech / Whisper tiny в браузере | whisper.cpp + faster-whisper |
| Классификатор | мешок слов + MiniLM | Chroma + мешок слов |
| Данные | localStorage, IndexedDB, Cache API | config.json, sqlite/json, APPDATA/models |
| Запуск | превью чата | python main.py / flet build windows |
| Git | этот репо, срез неполный | отдельный neural-dictaphone |

Exe делает Flet по CLAUDE_CODE_PLAN.md, не Tauri.

## Требования продукта

Запись по запросу и непрерывная, выбор микрофона, пауза → протокол, встречи, локальный STT (ru), очередь чанков, модель один раз по sha256.
Задачи из фраз, напоминания, уточнения, самообучение.
Протоколы, шаблоны, пакет документов, удаление строк.
Карта: суть на узле, pan/zoom, drag-узел → связь, анимация ребра.
Сроки, .ics, гайды со скрином, поиск по архиву, JSON экспорт/импорт.

## Данные

Реплика: id, text, created_at, task_id, confidence, auto_assigned, confirmed, meeting_id, speaker, kind.
Задача: title, notes, due_at, remind_at, repeat_min, positive, negative, links, hits, misses.
Встреча: title, started_at, ended_at, protocol_id.

Превью: localStorage `stenograf-v1`, IndexedDB аудио, Cache API модели.
Flet: data/app.json, audio_queue, `%LOCALAPPDATA%\\Stenograf\\models`.

## Алгоритмы

Токены + один стем, не Porter и не pymorphy3 в браузере.
Ранг задачи: cosine мешка + эмбеддинг, порог ~0.52.
Близкие связанные задачи → уточнение.
Kind: решение/риск/блокер, порог ~0.6.
Пауза STT ~1 с, пауза протокола ~8 с — разные числа.

## Как пользоваться

1. Превью чата Grok.
2. Edge → установить как приложение.
3. Ещё → выгрузить JSON.
4. Exe: CLAUDE_CODE_PLAN.md в neural-dictaphone + flet build windows.

Принципы: локально, модель не в бандле exe, UI не считает STT, на карте только суть.
