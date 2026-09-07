"""Local model catalog under %LOCALAPPDATA%\\Stenograf\\models + index.json."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen


@dataclass
class ModelEntry:
    id: str
    filename: str
    url: str
    sha256: str
    size_bytes: int | None
    profile: str  # low|mid|high|any
    engine: str = "whisper.cpp"  # whisper.cpp | vosk | silero-vad | faster-whisper
    lang: str = "ru"
    notes: str = ""


def models_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stenograf" / "models"
    return Path.home() / ".stenograf" / "models"


def index_path() -> Path:
    return models_root() / "index.json"


def _entry_from_dict(row: dict) -> ModelEntry:
    allowed = {f.name for f in fields(ModelEntry)}
    return ModelEntry(**{k: v for k, v in row.items() if k in allowed})


def load_index() -> list[ModelEntry]:
    path = index_path()
    if not path.exists():
        return default_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_entry_from_dict(row) for row in data.get("models", [])]


def default_index() -> list[ModelEntry]:
    """Open-source models suitable for local RU meeting STT / VAD.

    Sources:
      - HF ggerganov/whisper.cpp (ggml) — whisper.cpp / OpenVINO path
      - Alphacephei Vosk — weak-PC fallback STT
      - Silero VAD — speech activity detection
      - Systran faster-whisper — CUDA/CPU path (managed by library; listed for UI)
    """
    hf = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
    return [
        # --- whisper.cpp ggml (downloadable, sha256 = HF LFS oid) ---
        ModelEntry(
            id="whisper-tiny",
            filename="ggml-tiny.bin",
            url=f"{hf}/ggml-tiny.bin",
            sha256="be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
            size_bytes=77691713,
            profile="low",
            engine="whisper.cpp",
            notes="Быстрый CPU / слабые ПК",
        ),
        ModelEntry(
            id="whisper-tiny-q5_1",
            filename="ggml-tiny-q5_1.bin",
            url=f"{hf}/ggml-tiny-q5_1.bin",
            sha256="818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7",
            size_bytes=32152673,
            profile="low",
            engine="whisper.cpp",
            notes="Квантованный tiny",
        ),
        ModelEntry(
            id="whisper-base",
            filename="ggml-base.bin",
            url=f"{hf}/ggml-base.bin",
            sha256="60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
            size_bytes=147951465,
            profile="mid",
            engine="whisper.cpp",
            notes="Баланс качество/скорость (Arc / CPU)",
        ),
        ModelEntry(
            id="whisper-base-q5_1",
            filename="ggml-base-q5_1.bin",
            url=f"{hf}/ggml-base-q5_1.bin",
            sha256="422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
            size_bytes=59707625,
            profile="mid",
            engine="whisper.cpp",
        ),
        ModelEntry(
            id="whisper-small",
            filename="ggml-small.bin",
            url=f"{hf}/ggml-small.bin",
            sha256="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
            size_bytes=487601967,
            profile="mid",
            engine="whisper.cpp",
            notes="Лучше RU на mid",
        ),
        ModelEntry(
            id="whisper-medium-q5_0",
            filename="ggml-medium-q5_0.bin",
            url=f"{hf}/ggml-medium-q5_0.bin",
            sha256="19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
            size_bytes=539212467,
            profile="high",
            engine="whisper.cpp",
            notes="Качество выше, тяжелее",
        ),
        ModelEntry(
            id="whisper-large-v3-turbo-q5_0",
            filename="ggml-large-v3-turbo-q5_0.bin",
            url=f"{hf}/ggml-large-v3-turbo-q5_0.bin",
            sha256="394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
            size_bytes=574041195,
            profile="high",
            engine="whisper.cpp",
            notes="High / GPU: качество встреч, ~0.5GB",
        ),
        # --- Vosk RU fallback ---
        ModelEntry(
            id="vosk-small-ru",
            filename="vosk-model-small-ru-0.22.zip",
            url="https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
            sha256="961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4",
            size_bytes=46236750,
            profile="low",
            engine="vosk",
            notes="Офлайн STT fallback на слабых ПК (Alphacephei)",
        ),
        # --- Silero VAD ---
        ModelEntry(
            id="silero-vad",
            filename="silero_vad.onnx",
            url="https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
            sha256="1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
            size_bytes=2327524,
            profile="any",
            engine="silero-vad",
            notes="VAD: отсев тишины перед ASR",
        ),
        # --- faster-whisper (CUDA/CPU): managed by library, no direct file URL ---
        ModelEntry(
            id="fw-tiny",
            filename="Systran/faster-whisper-tiny",
            url="",
            sha256="",
            size_bytes=None,
            profile="low",
            engine="faster-whisper",
            notes="CT2 tiny — тянет faster-whisper сам (HF Systran)",
        ),
        ModelEntry(
            id="fw-base",
            filename="Systran/faster-whisper-base",
            url="",
            sha256="",
            size_bytes=None,
            profile="mid",
            engine="faster-whisper",
            notes="CT2 base — рекомендуем для mid CPU / mid CUDA",
        ),
        ModelEntry(
            id="fw-small",
            filename="Systran/faster-whisper-small",
            url="",
            sha256="",
            size_bytes=None,
            profile="high",
            engine="faster-whisper",
            notes="CT2 small — high / RTX 4060 Ti CUDA",
        ),
    ]


def save_index(entries: Iterable[ModelEntry]) -> None:
    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {"models": [asdict(e) for e in entries], "source": "stenograf-default+user"}
    index_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_with_defaults(entries: list[ModelEntry]) -> list[ModelEntry]:
    """Refresh known ids from defaults when url/sha missing; append new default ids."""
    defaults = {e.id: e for e in default_index()}
    merged: list[ModelEntry] = []
    seen: set[str] = set()
    for e in entries:
        d = defaults.get(e.id)
        if d and (not e.url or not e.sha256) and d.url and d.sha256:
            e = d
        elif d:
            # keep user overrides but fill engine/notes if empty
            if not getattr(e, "engine", None):
                e.engine = d.engine
            if not getattr(e, "notes", None):
                e.notes = d.notes
        merged.append(e)
        seen.add(e.id)
    for mid, d in defaults.items():
        if mid not in seen:
            merged.append(d)
    return merged


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_with_resume(
    entry: ModelEntry,
    progress_cb=None,
) -> Path:
    """Download below capture/ASR priority — caller should schedule accordingly.

    progress_cb(downloaded_bytes, total_bytes|None) optional.
    """
    if entry.engine == "faster-whisper":
        raise ValueError(
            f"{entry.id} managed by faster-whisper (HF {entry.filename}); no direct file download"
        )
    if not entry.url or not entry.sha256:
        raise ValueError(f"Model {entry.id} missing url/sha256 in catalog")

    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / entry.filename
    part = dest.with_suffix(dest.suffix + ".part")

    existing = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    headers["User-Agent"] = "Stenograf/0.1"
    req = Request(entry.url, headers=headers)
    with urlopen(req) as resp, part.open("ab" if existing else "wb") as out:
        while True:
            block = resp.read(1024 * 256)
            if not block:
                break
            out.write(block)
            if progress_cb:
                downloaded = part.stat().st_size
                progress_cb(downloaded, entry.size_bytes)

    digest = sha256_file(part)
    if digest.lower() != entry.sha256.lower():
        part.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch for {entry.id}: got {digest}")

    part.replace(dest)
    return dest
