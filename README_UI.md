# Stenograph Flet UI (MVP)

UI shell for Windows MVP. Consumes worker JSON-line events on stdout:

`hw.profile` · `models.list` · `models.download` · `mic.list` · `audio.chunk` · `asr.backend` · `asr.job` · `asr.result`

## Screens (MVP)

- Mic picker (+ refresh via `worker.main --list-mics`)
- Start / Stop recording (spawns `python -m worker.main`)
- ASR backend + queue counters + confidence in protocol
- Models catalog (from `worker.models_catalog` / `models.list`; download when url+sha256 set)
- Live protocol from `asr.result`
- DOCX / HTML export (offline TOC + anchors) → `%LOCALAPPDATA%\Stenograf\exports`

## Run (dev)

Place this `ui/` package next to `worker/` in the Stenograph repo root.

```bat
pip install -r requirements-ui.txt
set PYTHONPATH=.
python -m ui.main
```

## Layout

```
Stenograph/
  worker/          # Разработчик 1
  ui/              # Разработчик 2
  requirements-ui.txt
  README_UI.md
```

Interim IPC: JSON lines on stdout. Download buttons stay disabled until catalog has real url/sha256.

Models are grouped by `engine`. Download is disabled for `faster-whisper` (library pulls HF itself).
