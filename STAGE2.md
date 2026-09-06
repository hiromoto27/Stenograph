# Этап 2 — локальный STT

1. Ещё → скачать Whisper tiny (~75 МБ, Xenova/whisper-tiny).
2. Студия → движок «Авто» или «Только Whisper».
3. Запись кладёт чанки 12 с в IndexedDB (`stenograph-audio`).
4. После стоп очередь разбирается локально, без сервера.

Код: `src/lib/whisper-local.ts`, `src/lib/audio-queue.ts`.
