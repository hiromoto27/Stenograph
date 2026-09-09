"""One-click speech preparation; preserve an already selected valid model."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(root / 'scripts/prepare_models.py'), '--size', 'base',
                    '--output', str(root / 'models')], check=True)
    from PySide6.QtCore import QCoreApplication, QLockFile
    from stenograph.config import Settings, data_root
    app = QCoreApplication([])
    folder = data_root()
    lock = QLockFile(str(folder / 'app.lock'))
    if not lock.tryLock(0):
        raise RuntimeError('Модель скачана. Закройте СтеноГраф через меню трея и повторите подготовку для сохранения настройки.')
    try:
        settings = Settings.load(folder)
        if not settings.model_path or not (Path(settings.model_path) / 'model.bin').is_file():
            settings.model_path = str(root / 'models/faster-whisper-base')
            settings.save(folder)
        print('ГОТОВО. Модель речи выбрана. Теперь откройте Запустить.cmd.')
    finally:
        lock.unlock()
        del app


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Подготовка речи не завершена:', exc)
        raise SystemExit(1)
