# Stenograph Flet UI

Dark **Studio** shell (Grok mockups) + worker JSON IPC.

## Run

```bat
pip install -r requirements-ui.txt
set PYTHONPATH=.
set STENOGRAF_FORCE_CPU=1
python -m ui.main
```

## Tabs

- **Студия** — mic, RMS level, record, transcript, DOCX/HTML
- **Карта / Сроки / Протокол / Гайды** — stubs
- **Ещё** — settings: hw profile + models catalog/download

## Modules

- `ui/studio_app.py` — shell
- `ui/worker_client.py` — spawn worker, JSON lines
- `ui/export_protocol.py` — DOCX/HTML
- `ui/mvp_legacy.py` — previous flat MVP (optional)

Classifier / task graph — later with worker Dev.
