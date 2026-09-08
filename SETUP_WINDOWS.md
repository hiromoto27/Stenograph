# Stenograph — чеклист первого прогона (Windows / Zenbook Arc)

Цель: mic → протокол → DOCX/HTML. Сначала можно на **stub** / **faster-whisper**, OpenVINO — следом.

Машины: Zenbook Arc → профиль **mid** (OpenVINO опционально); ПК **32 ГБ + RTX 4060 Ti** → **high** (`faster-whisper` CUDA, base/small). Для CUDA: `pip install torch` с CUDA-сборкой до/вместе с faster-whisper.

## 0. Репо

```bat
git clone https://github.com/hiromoto27/Stenograph.git
cd Stenograph
```

Python 3.11+ (рекомендуется), в PATH.

## 1. Worker

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-worker.txt
set PYTHONPATH=.
python -m worker.main --list-mics
```

Ожидаем JSON `mic.list` с устройствами.

Демо stub (без моделей):

```bat
python -m worker.main --backend stub --seconds 12 --segment-sec 3
```

Живой CPU ASR:

```bat
python -m worker.main --backend faster-whisper --seconds 30 --segment-sec 5 --device 0
```

Первый запуск `faster-whisper` скачает модель (tiny/base) — нужен интернет один раз.

## 2. UI (Flet) — шаги от Разработчик 2

```bat
pip install -r requirements-ui.txt
set PYTHONPATH=.
python -m ui.main
```

В UI: обновить микрофоны → Старт → смотреть очередь ASR и протокол → DOCX/HTML.

## 3. Модели (каталог)

Каталог по умолчанию: `%LOCALAPPDATA%\Stenograf\models` + `index.json` (создаётся worker’ом).

Положить `ggml-*.bin` сюда (или задать `STENOGRAF_WHISPER_MODEL`).

Аудиосегменты: `%LOCALAPPDATA%\Stenograf\audio_queue`.

## 4. OpenVINO / whisper.cpp (mid Arc, опционально)

1. Собрать/скачать `whisper.cpp` CLI с OpenVINO под Windows.
2. `set STENOGRAF_WHISPER_CPP=C:\path\to\whisper-cli.exe`
3. Модель ggml в `%LOCALAPPDATA%\Stenograf\models`
4. `python -m worker.main --backend whisper.cpp --seconds 30`

Авто (`--backend auto`): whisper.cpp если бинарник+модель есть и профиль mid/high, иначе faster-whisper, иначе stub.

## 5. Критерии «работает»

- [ ] `--list-mics` видит нужный микрофон
- [ ] Запись не падает при отставании ASR
- [ ] В протоколе русский текст (не только stub)
- [ ] Экспорт DOCX и HTML открываются, оглавление/якоря на месте
- [ ] Файлы лежат в `%LOCALAPPDATA%\Stenograf\exports`
- [ ] В UI виден `asr.backend` (и `confidence`, если есть)

## 6. Если что-то ломается

- Нет звука / пустой протокол: проверь `--device`, RMS в `audio.chunk`
- Долго на stub: норма, текст-заглушка
- `faster-whisper` тяжёлый: `--backend` + профиль low → tiny
- UI не видит события: оба пакета из корня репо, `PYTHONPATH=.`


## Если профиль mid при 32ГБ + NVIDIA

1. `git pull` — нужен свежий `hw_profile.py`.
2. В том же терминале: `nvidia-smi` (если «не найдено» — добавь CUDA/Driver в PATH).
3. Удали устаревший индекс каталога при странном списке из 5 моделей:
   `del %LOCALAPPDATA%\Stenograf\models\index.json`
4. HF ReadTimeout: `set HF_HUB_DOWNLOAD_TIMEOUT=300` и повтори, либо качай ggml:
   `python -m worker.main --download-model whisper-base`


## 7. Сборка exe (`flet build windows`)

CLAUDE_CODE_PLAN.md, спринт F. Модели остаются вне exe — `models_root()`
(`worker/models_catalog.py`) всегда резолвится через `%LOCALAPPDATA%`,
поэтому обновление exe эту папку не трогает (её вообще нет рядом с exe).

```bat
pip install -r requirements-worker.txt -r requirements-ui.txt flet-cli==0.86.5
flet build windows . --module-name ui.main --yes --product "Стенограф" --org stenograph
```

`--module-name ui.main` обязателен: точка входа — `ui/main.py`, а не
корневой `main.py`, который `flet build` ищет по умолчанию.
`python_app_path` = `.` (корень репо), так что `worker/` попадает в
сборку рядом с `ui/` — это нужно для дочернего процесса воркера.

**Не проверено на реальной Windows-машине в этой сессии** (сборка требует
Flutter + Windows SDK, недоступные в песочнице): worker в dev-режиме
запускается как **отдельный процесс** (`ui/worker_client.py` зовёт
`sys.executable -m worker.main`) с IPC через stdin/stdout. Flet
бандлит переносимый интерпретатор Python вместе с приложением, и на
практике такие подпроцессы у Flet-приложений работают — но перед
релизом стоит собрать exe и вручную проверить, что кнопка «Записать»
поднимает воркер и события идут в UI, а не тихо падает.

## STT (Whisper / Browser)

- **Default engine:** `whisper` (local, полностью офлайн после скачивания модели). Optional UI: Ещё → `browser` (тот же движок, что в превью Grok — Edge/WebView2 + `webkitSpeechRecognition`, `ru-RU`, `interimResults`).
- **Browser нужен интернет.** Web Speech API в Windows/Edge отправляет звук в облачный сервис распознавания Microsoft — это **не** офлайн-путь, в отличие от Whisper. Если сеть недоступна, распознавание падает с `network` и UI сам переключается на Whisper (см. `_FALLBACK_ERRORS` в `ui/browser_stt.py`).
- **Browser needs:** `pip install "flet-webview-all>=0.1.8"` + разрешение на микрофон (Windows Settings → Privacy → Microphone, тот же уровень, что уже нужен `sounddevice` для Whisper-пути). Если WebView недоступен или mic `not-allowed` — UI переключается на Whisper, без тихого зависания.
- **VAD:** on by default with speech pad (~300 ms). Empty transcript → one retry without VAD. Force off: `STENOGRAF_VAD=0`.
- **RMS:** does **not** drop quiet speech (gate default off). Low mic → `mic.warn` / UI hint only. Optional hard gate: `STENOGRAF_ASR_RMS_MIN=0.005` (not recommended as default).
- **Worker flag:** `--stt-engine browser` or `STENOGRAF_STT_ENGINE=browser` — capture/VU only, no local Whisper enqueue (UI owns finals via `asr.final`).

### Быстрый запуск: проверка engine=browser

`ui/browser_stt.py` использует управляющий элемент `FletWebviewAll` из
`flet-webview-all>=0.1.8` (не `WebView` — под этим именем в пакете
ничего нет) и передаёт текст из JS в Python через именованный канал
`javascript_channels=["StenografBridge"]`, а не через
`window.chrome.webview.postMessage` — это API нативного WebView2, а не
то, что подставляет обёртка `webview_all` у Flutter. Обе детали
проверены здесь по исходникам пакета и его README (см. коммит), но
**не проверены на реальном WebView2/Windows** — в песочнице нет
дисплея.

```bat
pip install -r requirements-worker.txt -r requirements-ui.txt
pip install "flet-webview-all>=0.1.8"
set PYTHONPATH=.
python -m ui.main
```

1. Ещё → «Движок STT» → **Browser / Edge Web Speech**.
   Если статус тут же пишет «Browser недоступен… переключился на
   Whisper» — пакет не встал или нет WebView2 Runtime (обычно уже
   стоит на Windows 10 1809+/11; иначе поставить с
   `https://developer.microsoft.com/microsoft-edge/webview2/`).
2. Студия → «Записать», разрешить доступ к микрофону, если Windows
   спросит отдельно.
3. Скажите что-нибудь по-русски: над лентой должна появиться курсивная
   промежуточная строка (частичный результат), а после паузы — обычная
   строка в ленте с пометкой `browser`.
4. Отключите сеть и повторите — движок должен сам откатиться на
   Whisper со статусом про `network`, а не зависнуть молча.
5. Если ничего не приходит и статус не показывает ошибку — включите
   `debugging_enabled=True` в `FletWebviewAll(...)` (`ui/browser_stt.py`)
   и вызовите `await wv.open_devtools()`, чтобы увидеть консоль
   страницы (там будет видно, добралось ли сообщение до
   `window.StenografBridge`).

Когда проверите на реальной машине — напишите, что сработало и что
нет, тогда решим, стоит ли делать `browser` движком по умолчанию.
