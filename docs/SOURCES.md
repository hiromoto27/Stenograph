# Компоненты и источники

Проверено по официальным материалам 08.09.2026. Значения RAM/VRAM в каталоге — инженерные ориентиры этого проекта, **не официальные гарантированные минимальные требования**.

| Компонент | Официальный источник | Использование |
|---|---|---|
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | Локальная модель CTranslate2, int8, VAD, требования NVIDIA |
| PyAudioWPatch | https://github.com/s0d3s/PyAudioWPatch | WASAPI loopback, перечисление устройств, Windows wheels |
| Ollama structured outputs | https://docs.ollama.com/capabilities/structured-outputs | Передача JSON Schema и проверка структурированных ответов |
| Ollama FAQ | https://docs.ollama.com/faq | Контекст, локальное исполнение, отдельные настройки сервера и обновлений |
| Qwen3 4B | https://huggingface.co/Qwen/Qwen3-4B | Открытые веса и карточка модели |
| Qwen3 1.7B | https://huggingface.co/Qwen/Qwen3-1.7B | Экономный вариант; проверить карточку перед распространением |
| Qwen3 8B | https://huggingface.co/Qwen/Qwen3-8B | Более тяжёлый вариант; проверить карточку перед распространением |
| Qt tray | https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html | Системный трей и уведомления |
| Vosk models | https://alphacephei.com/vosk/models | Кандидат для слабых ПК; лицензия зависит от конкретной модели |
| whisper.cpp | https://github.com/ggml-org/whisper.cpp | Кандидат для альтернативного нативного backend |
| Tesseract | https://github.com/tesseract-ocr/tesseract | Кандидат для OCR скриншотов |

Разные кодовые пакеты и веса распространяются на своих лицензиях. Метка свободного доступа не означает отсутствие лицензионных обязательств при распространении сборки.
