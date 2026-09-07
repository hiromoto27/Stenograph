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

## Next

1. Fill real model URLs/sha256 in catalog + downloader UX.
2. Wire OpenVINO device flags for Intel Arc.
3. Dedicated IPC if stdout JSON becomes limiting.
