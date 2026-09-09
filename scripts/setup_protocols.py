"""Prepare a local Ollama model; never install or start Ollama silently."""
import os
from pathlib import Path
import shutil
import subprocess


def main():
    options = [shutil.which('ollama')]
    for envvar in ('LOCALAPPDATA', 'ProgramFiles'):
        base = os.environ.get(envvar)
        if base:
            options += [str(Path(base) / 'Programs/Ollama/ollama.exe'), str(Path(base) / 'Ollama/ollama.exe')]
    exe = next((path for path in options if path and Path(path).is_file()), None)
    if not exe:
        print('Сначала установите Ollama: https://ollama.com/download/windows')
        print('Откройте установленный Ollama, затем повторите запуск этого файла.')
        return 1
    from stenograph.config import Settings, data_root
    from stenograph.hardware import detect, recommend
    from PySide6.QtCore import QCoreApplication, QLockFile
    app = QCoreApplication([])
    folder = data_root()
    lock = QLockFile(str(folder / 'app.lock'))
    if not lock.tryLock(0):
        raise RuntimeError('Закройте СтеноГраф через меню трея, затем повторите подготовку.')
    try:
        model = recommend(detect(folder))['llm']
        print('Загрузка локальной модели ' + model + '. Требуется интернет. Окно не закрывайте.', flush=True)
        subprocess.run([exe, 'pull', model], check=True)
        settings = Settings.load(folder)
        settings.llm_model = model
        settings.llm_backend = "ollama"
        settings.save(folder)
        print('ГОТОВО. Модель протоколов выбрана. Ollama должен оставаться запущенным.')
    finally:
        lock.unlock()
        del app
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Подготовка протоколов не завершена:', exc)
        raise SystemExit(1)
