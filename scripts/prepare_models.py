"""Explicit online preparation. The desktop application itself never downloads models."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Скачать модель для последующей работы без интернета")
    parser.add_argument("--size", choices=["base", "small", "large-v3"], default="base")
    parser.add_argument("--output", type=Path, default=Path("models"))
    args = parser.parse_args()
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import snapshot_download

    destination = args.output / f"faster-whisper-{args.size}"
    snapshot_download(repo_id=f"Systran/faster-whisper-{args.size}", local_dir=destination,
                      allow_patterns=["*.bin", "*.json", "*.txt", "README.md"])
    checksums = {}
    for path in destination.glob("*"):
        if path.is_file() and path.name != "checksums.json":
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            checksums[path.name] = digest.hexdigest()
    (destination / "checksums.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
    print(f"Модель подготовлена: {destination.resolve()}")
    print("Выберите эту папку в приложении. Для офлайн-ПК скопируйте всю папку.")


if __name__ == "__main__":
    main()
