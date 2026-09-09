"""Restore only into an empty data directory, rebase local attachment paths."""
import argparse
import json
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    target = args.destination.resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Восстановление допускается только в пустую папку.")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or ":" in info.filename:
                raise ValueError("Небезопасный путь в архиве")
        archive.extractall(target)
    with sqlite3.connect(target / "knowledge.sqlite3") as db:
        for table, folder in [("chunks", "audio"), ("shots", "screenshots")]:
            for row_id, mid, old in db.execute(f"SELECT id,meeting_id,path FROM {table}").fetchall():
                filename = old.replace("\\", "/").rsplit("/", 1)[-1]
                db.execute(f"UPDATE {table} SET path=? WHERE id=?", (str(target / folder / str(mid) / filename), row_id))
    config = target / "settings.json"
    if config.exists():
        value = json.loads(config.read_text(encoding="utf-8"))
        value["model_path"] = ""
        config.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Восстановлено: {target}. Укажите STENOGRAPH_DATA_DIR={target} и заново выберите папку модели.")


if __name__ == "__main__":
    main()
