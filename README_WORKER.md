# Stenograph worker (MVP stubs)

Native Windows worker: **mic → disk segments → ASR queue** (stub backend).
UI (Flet) is separate — see Разработчик 2.

## Run (dev)

```bat
pip install -r requirements-worker.txt
set PYTHONPATH=.
python -m worker.main --list-mics
python -m worker.main --seconds 15 --segment-sec 3
```

Events on stdout (JSON lines): `hw.profile`, `models.list`, `mic.list`, `audio.chunk`, `asr.job`, `asr.result`.

## Invariants

- Capture never waits for ASR.
- Models live under `%LOCALAPPDATA%\Stenograf\models` + `index.json` (sha256 on real downloads).
- OpenVINO whisper.cpp wiring is TODO; current ASR is stub.

## Next

1. Real whisper.cpp OpenVINO backend for mid/Arc profile.
2. IPC channel to Flet (stdio JSON is interim).
3. Fill model URLs/sha256 in catalog.
