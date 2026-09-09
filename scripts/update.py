"""Updater helper: runs outside the GUI and waits for its process lock."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from stenograph.config import Settings, data_root
    from stenograph.runtime_guard import RuntimeGuard
    from stenograph.updates import check_release, download, install_files, repo_slug, unpack_release

    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', default='')
    parser.add_argument('--pause', action='store_true')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    root = data_root()
    settings = Settings.load(root)
    print('Проверяю выпуск в репозитории…', flush=True)
    release = check_release(settings.update_repository, settings.update_branch, settings.update_subdir)
    if args.sha and args.sha != release['sha']:
        raise ValueError('Ветка изменилась после проверки. Проверьте обновление заново.')
    current = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
    if tuple(map(int, release['manifest']['version'].split('.'))) <= tuple(map(int, current['version'].split('.'))):
        print('Эта версия уже установлена.')
        return
    if not args.sha:
        if input('Установить версию ' + release['manifest']['version'] + '? Введите ДА: ').strip().casefold() not in ('да', 'yes'):
            return
    payload = download(f"https://codeload.github.com/{repo_slug(settings.update_repository)}/zip/{release['sha']}")
    with tempfile.TemporaryDirectory(prefix='stenograph-update-') as temp:
        unpack_release(payload, release, temp)
        guard = RuntimeGuard(root)
        print('Закройте СтеноГраф через меню трея. Ожидаю завершения…', flush=True)
        for _ in range(120):
            if guard.acquire():
                break
            time.sleep(1)
        else:
            raise RuntimeError('СтеноГраф не закрыт. Обновление не установлено.')
        try:
            def dependencies():
                python = ROOT / '.venv/Scripts/python.exe'
                if not python.is_file():
                    raise RuntimeError('Не найдено окружение .venv. Запустите Установить.cmd.')
                subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-e', str(ROOT)], check=True)
            backup = root / 'update-backups' / uuid.uuid4().hex
            install_files(temp, ROOT, backup, dependencies)
            print('ГОТОВО. Откройте Запустить.cmd. Предыдущие исходники сохранены: ' + str(backup))
        finally:
            guard.release()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Обновление не завершено:', exc)
        print('При ошибке зависимостей повторите Установить.cmd. Исходники восстанавливаются из копии.')
        if '--pause' in sys.argv:
            input('Нажмите Enter, чтобы закрыть окно…')
        raise SystemExit(1)
    if '--pause' in sys.argv:
        input('Нажмите Enter, чтобы закрыть окно…')
