# Stenograph worker (MVP)

Native Windows worker: **mic → disk segments → ASR queue**.
UI (Flet) is separate — see `README_UI.md`.

## Run (dev)

```bat
pip install -r requirements-worker.txt
set PYTHONPATH=.
python -m worker.main --list-mics
python -m worker.main --seconds 15 --segment-sec 3
```

Force backend:

```bat
python -m worker.main --backend faster-whisper --seconds 20
python -m worker.main --backend whisper.cpp --seconds 20
python -m worker.main --backend stub --seconds 10
```

## ASR backends

Auto-select (`--backend auto`):

1. **whisper.cpp + OpenVINO** (mid/high) if `STENOGRAF_WHISPER_CPP` (or `whisper-cli` on PATH) and a `ggml-*.bin` under `%LOCALAPPDATA%\Stenograf\models` exist.
2. Else **faster-whisper** (CPU/int8) if installed.
3. Else **stub**.

Env:

- `STENOGRAF_WHISPER_CPP` — path to whisper.cpp CLI
- `STENOGRAF_WHISPER_MODEL` — explicit ggml model path

## Events (JSON lines on stdout)

`hw.profile` · `models.list` · `asr.backend` · `mic.list` · `audio.chunk` · `asr.job` · `asr.result` · `capture.started` · `capture.stopped`

Example `asr.result`:

```json
{"event":"asr.result","job_id":"…","text":"…","confidence":0.82,"backend":"faster-whisper:base","error":null}
```

## Invariants

- Capture never waits for ASR.
- Models live under `%LOCALAPPDATA%\Stenograf\models` + `index.json` (sha256 on downloads).
- Embeddings/LLM must not run while ASR queue is busy (UI/other services).


## Model catalog / download

Default catalog (HF `ggerganov/whisper.cpp`) ships with url+sha256 for tiny/base/small (+ q5_1).

```bat
python -m worker.main --download-model whisper-base
```

Emits `models.download` progress events; stores under `%LOCALAPPDATA%\Stenograf\models`.


### Profiles

- **high** (e.g. 32GB + RTX 4060 Ti): `faster-whisper` CUDA, model small/base; OpenVINO not required.
- **mid** (Zenbook Arc): whisper.cpp OpenVINO if available, else faster-whisper CPU.
- **low**: tiny/base CPU.


## Catalog sources (open)

| Engine | Source | Зачем |
|--------|--------|--------|
| whisper.cpp ggml | HF `ggerganov/whisper.cpp` | OpenVINO / CLI STT |
| faster-whisper | HF `Systran/faster-whisper-*` | CUDA/CPU STT (библиотека качает сама) |
| vosk | Alphacephei `vosk-model-small-ru` | Fallback на слабых ПК |
| silero-vad | GitHub `snakers4/silero-vad` | VAD перед ASR |

Не тащим англ-only Distil-Whisper и прочий шум — только то, что нужно для RU-встреч.

## Next

1. Fill real model URLs/sha256 in catalog + downloader UX.
2. Wire OpenVINO device flags for Intel Arc.
3. Dedicated IPC if stdout JSON becomes limiting.
