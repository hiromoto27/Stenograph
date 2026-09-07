# Stenograph — чеклист первого прогона (Windows / Zenbook Arc)

Цель: mic → протокол → DOCX/HTML. Сначала можно на **stub** / **faster-whisper**, OpenVINO — следом.

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
