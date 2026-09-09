from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get("STENOGRAPH_DATA_DIR")
    root = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "Stenograph"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Settings:
    model_path: str = ""
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ru"
    chunk_seconds: int = 10
    cpu_threads: int = 4
    llm_model: str = "qwen3:4b"
    llm_backend: str = "ollama"
    gguf_path: str = ""
    update_repository: str = "https://github.com/hiromoto27/Stenograph.git"
    update_branch: str = "main"
    update_subdir: str = ""
    mic_name: str = ""
    loopback_name: str = ""

    @classmethod
    def load(cls, root: Path) -> "Settings":
        path = root / "settings.json"
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        value = cls(**values)
        value.chunk_seconds = max(3, min(30, int(value.chunk_seconds)))
        value.cpu_threads = max(1, min(32, int(value.cpu_threads)))
        return value

    def save(self, root: Path) -> None:
        temp = root / "settings.json.tmp"
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(root / "settings.json")


def enforce_offline() -> None:
    # Downloads exist only in the separate, explicitly invoked preparation script.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
