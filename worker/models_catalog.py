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
    # Official ggml weights from ggerganov/whisper.cpp (HF LFS oid = sha256).
    base = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
    return [
        ModelEntry(
            id="whisper-tiny",
            filename="ggml-tiny.bin",
            url=f"{base}/ggml-tiny.bin",
            sha256="be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
            size_bytes=77691713,
            profile="low",
        ),
        ModelEntry(
            id="whisper-tiny-q5_1",
            filename="ggml-tiny-q5_1.bin",
            url=f"{base}/ggml-tiny-q5_1.bin",
            sha256="818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7",
            size_bytes=32152673,
            profile="low",
        ),
        ModelEntry(
            id="whisper-base",
            filename="ggml-base.bin",
            url=f"{base}/ggml-base.bin",
            sha256="60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
            size_bytes=147951465,
            profile="mid",
        ),
        ModelEntry(
            id="whisper-base-q5_1",
            filename="ggml-base-q5_1.bin",
            url=f"{base}/ggml-base-q5_1.bin",
            sha256="422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
            size_bytes=59707625,
            profile="mid",
        ),
        ModelEntry(
            id="whisper-small",
            filename="ggml-small.bin",
            url=f"{base}/ggml-small.bin",
            sha256="1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
            size_bytes=487601967,
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


def download_with_resume(
    entry: ModelEntry,
    progress_cb=None,
) -> Path:
    """Download below capture/ASR priority — caller should schedule accordingly.

    progress_cb(downloaded_bytes, total_bytes|None) optional.
    """
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
            if progress_cb:
                downloaded = part.stat().st_size
                progress_cb(downloaded, entry.size_bytes)

    digest = sha256_file(part)
    if digest.lower() != entry.sha256.lower():
        part.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch for {entry.id}: got {digest}")

    part.replace(dest)
    return dest
