# Stenograph Flet UI (MVP)

UI shell for Windows MVP. Consumes worker JSON-line events on stdout:

`hw.profile` · `models.list` · `mic.list` · `audio.chunk` · `asr.job` · `asr.result`

## Screens (MVP)

- Mic picker (+ refresh via `worker.main --list-mics`)
- Start / Stop recording (spawns `python -m worker.main`)
- ASR queue counters
- Live protocol from `asr.result`
- DOCX / HTML export stubs (post-process later)

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
  ui/              # Разработчик 2 (this)
  requirements-ui.txt
  README_UI.md
```

Interim IPC only — later replace with a dedicated channel if needed.

## Export

`ui/export_protocol.py` — offline DOCX (`python-docx`) and interactive HTML (TOC + anchors).
Default output: `%LOCALAPPDATA%\Stenograf\exports` on Windows, else `~/.local/share/Stenograf/exports`.
