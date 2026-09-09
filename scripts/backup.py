import argparse
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile

from stenograph.config import data_root
from stenograph.db import Database


def main():
    parser = argparse.ArgumentParser(description="Копия базы, настроек, аудио и скриншотов")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    app = QCoreApplication([])
    root = data_root()
    lock = QLockFile(str(root / "app.lock"))
    if not lock.tryLock(0):
        raise SystemExit("Закройте СтеноГраф через меню трея перед резервным копированием.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.sqlite3"
            Database(root / "knowledge.sqlite3").backup(db_path)
            with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
                archive.write(db_path, "knowledge.sqlite3")
                for folder in ("audio", "screenshots"):
                    for path in (root / folder).rglob("*"):
                        if path.is_file():
                            archive.write(path, path.relative_to(root))
                if (root / "settings.json").exists():
                    archive.write(root / "settings.json", "settings.json")
        print(f"Резервная копия: {args.output.resolve()}")
    finally:
        lock.unlock()
        del app


if __name__ == "__main__":
    main()
