# Stenograph Flet UI

Dark **Studio** shell (Grok mockups) + worker JSON IPC.

## Run

```bat
pip install -r requirements-ui.txt
set PYTHONPATH=.
set STENOGRAF_FORCE_CPU=1
python -m ui.main
```

Optional browser STT (Windows):

```bat
pip install flet-webview-all
```

## Tabs

- **Студия** — mic, VU ring, record, transcript, DOCX/HTML, «слушаю…»
- **Карта / Сроки / Протокол / Гайды** — stubs
- **Ещё** — engine (whisper|browser), hw profile, models catalog

## Modules

- `ui/studio_app.py` — shell
- `ui/worker_client.py` — spawn worker, JSON lines
- `ui/export_protocol.py` — DOCX/HTML
- `ui/browser_stt.py` + `ui/assets/browser_stt.html` — optional Web Speech host
- `ui/mvp_legacy.py` — previous flat MVP (optional)

## «Куда отнести?»

Listens for worker `task.suggest` after `asr.result` / `asr.final`.
User actions send `task.assign` / `task.create` / `task.skip` on worker stdin.

## Движок STT

- whisper (default): worker ASR.
- browser: Edge WebView2 + Web Speech ru-RU (needs flet-webview-all).
  UI sends `asr.partial` / `asr.final` on worker stdin. VU stays on sounddevice.
- Worker `asr.listening` → UI shows «слушаю…».
