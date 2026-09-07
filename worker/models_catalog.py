"""Local model catalog under %LOCALAPPDATA%\\Stenograf\\models + index.json."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
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


def models_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stenograf" / "models"
    return Path.home() / ".stenograf" / "models"


def index_path() -> Path:
    return models_root() / "index.json"


def load_index() -> list[ModelEntry]:
    path = index_path()
    if not path.exists():
        return default_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ModelEntry(**row) for row in data.get("models", [])]


def default_index() -> list[ModelEntry]:
    # Placeholders — replace URLs/sha256 with real whisper.cpp ggml artifacts.
    return [
        ModelEntry(
            id="whisper-tiny",
            filename="ggml-tiny.bin",
            url="",
            sha256="",
            size_bytes=None,
            profile="low",
        ),
        ModelEntry(
            id="whisper-base",
            filename="ggml-base.bin",
            url="",
            sha256="",
            size_bytes=None,
            profile="mid",
        ),
        ModelEntry(
            id="whisper-small",
            filename="ggml-small.bin",
            url="",
            sha256="",
            size_bytes=None,
            profile="mid",
        ),
    ]


def save_index(entries: Iterable[ModelEntry]) -> None:
    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "models": [e.__dict__ for e in entries],
    }
    index_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_with_resume(entry: ModelEntry) -> Path:
    """Download below capture/ASR priority — caller should schedule accordingly."""
    if not entry.url or not entry.sha256:
        raise ValueError(f"Model {entry.id} missing url/sha256 in catalog")

    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / entry.filename
    part = dest.with_suffix(dest.suffix + ".part")

    existing = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    req = Request(entry.url, headers=headers)
    with urlopen(req) as resp, part.open("ab" if existing else "wb") as out:
        while True:
            block = resp.read(1024 * 256)
            if not block:
                break
            out.write(block)

    digest = sha256_file(part)
    if digest.lower() != entry.sha256.lower():
        part.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch for {entry.id}: got {digest}")

    part.replace(dest)
    return dest
