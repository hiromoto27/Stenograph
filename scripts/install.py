"""Standard-library Windows installer; can discover a supported Python from a newer one."""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PROBE = "import json,platform,struct,sys,sysconfig; print(json.dumps(dict(executable=sys.executable,version=platform.python_version(),major=sys.version_info.major,minor=sys.version_info.minor,bits=struct.calcsize('P')*8,machine=platform.machine(),implementation=platform.python_implementation(),free_threaded=bool(sysconfig.get_config_var('Py_GIL_DISABLED')))))"


def compatible(info):
    return bool(info and info.get('major') == 3 and info.get('minor') in (11, 12, 13)
                and info.get('bits') == 64 and info.get('machine', '').lower() in ('amd64', 'x86_64')
                and info.get('implementation') == 'CPython' and not info.get('free_threaded'))


def probe(executable):
    try:
        result = subprocess.run([str(executable), '-I', '-c', PROBE], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=15, check=False)
        if result.returncode:
            return None
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def launcher_paths(output):
    """One installed interpreter per line; never join paths into one executable."""
    for line in output.splitlines():
        match = re.match(r'^\s*-\S+\s+(?:\*\s+)?(.+?\.exe)\s*(?:\*)?\s*$', line, re.I)
        if match:
            yield match.group(1).strip()


def registry_paths():
    if sys.platform != 'win32':
        return
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'Software\Python\PythonCore', 0, winreg.KEY_READ | view) as core:
                    for index in range(winreg.QueryInfoKey(core)[0]):
                        version = winreg.EnumKey(core, index)
                        try:
                            with winreg.OpenKey(core, version + r'\InstallPath') as install:
                                yield str(Path(winreg.QueryValueEx(install, '')[0]) / 'python.exe')
                        except OSError:
                            continue
            except OSError:
                continue


def candidates():
    yield str(ROOT / '.venv' / 'Scripts' / 'python.exe')
    yield sys.executable
    yield str(Path(sys.base_prefix) / 'python.exe')
    yield from registry_paths()
    for variable, suffix in [('LOCALAPPDATA', 'Programs/Python/Python*/python.exe'),
                             ('ProgramFiles', 'Python*/python.exe')]:
        base = os.environ.get(variable)
        if base:
            yield from glob.glob(str(Path(base) / suffix))
    launchers = []
    for folder in os.get_exec_path():
        yield str(Path(folder) / 'python.exe')
        launcher = Path(folder) / 'py.exe'
        if launcher.is_file():
            launchers.append(str(launcher))
    for launcher in dict.fromkeys(launchers):
        try:
            result = subprocess.run([launcher, '-0p'], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=15, check=False)
            if result.returncode == 0:
                yield from launcher_paths(result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            continue


def select_python(paths, report):
    seen = set()
    for candidate in paths:
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen:
            continue
        seen.add(key)
        # Store aliases for python.exe may open the Store instead of an interpreter.
        if '\\microsoft\\windowsapps\\' in candidate.lower():
            continue
        if not Path(candidate).is_file():
            continue
        info = probe(candidate)
        if info:
            report('Найден Python {version}, {bits}-bit, {machine}: {executable}'.format(**info))
            if compatible(info):
                return info['executable']
    return None


def install(selected, report, run):
    env_dir = ROOT / '.venv'
    env_python = env_dir / 'Scripts' / 'python.exe'
    if env_dir.exists() and not compatible(probe(env_python)):
        preserved = ROOT / ('.venv-old-' + time.strftime('%Y%m%d-%H%M%S'))
        report('Предыдущее окружение непригодно. Сохраняю его как ' + preserved.name)
        env_dir.rename(preserved)
    if not env_python.is_file():
        report('[1/2] Создаю окружение приложения…')
        run([selected, '-m', 'venv', str(env_dir)])
    else:
        report('[1/2] Использую существующее окружение приложения.')
    if not compatible(probe(env_python)):
        raise RuntimeError('Окружение не создано или его Python не запускается. Смотрите исходную ошибку выше.')
    report('[2/2] Устанавливаю зависимости. Первый запуск требует интернета; окно не закрывайте.')
    run([str(env_python), '-m', 'pip', 'install', '--disable-pip-version-check', '-e', str(ROOT)])
    report('\nГОТОВО. Для распознавания запустите «Подготовить-речь.cmd», затем «Запустить.cmd».')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--python', help='Точный путь к установленному python.exe')
    args = parser.parse_args()
    if args.probe:
        return 0 if sys.version_info >= (3, 8) else 1
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    logfile = ROOT / 'install.log'
    with logfile.open('w', encoding='utf-8') as log:
        def report(message):
            print(message, flush=True)
            log.write(message + '\n')
            log.flush()

        def run(command):
            env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
            with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace') as process:
                for line in process.stdout:
                    report(line.rstrip())
                code = process.wait()
            if code:
                raise RuntimeError('Команда завершилась с кодом {}. Причина приведена выше.'.format(code))

        try:
            report('СтеноГраф — установка\nПапка: ' + str(ROOT))
            if sys.platform != 'win32':
                raise RuntimeError('Этот установщик предназначен для Windows.')
            selected = select_python([args.python] if args.python else candidates(), report)
            if not selected:
                raise RuntimeError('Не найден обычный Python 3.11–3.13 x64. Если установлен Python 3.14+, '
                                   '32-bit или ARM64, установите рядом Python 3.12 x64. Текущий Python удалять не нужно.')
            install(selected, report, run)
            return 0
        except (OSError, RuntimeError) as exc:
            report('\nУСТАНОВКА НЕ ЗАВЕРШЕНА: ' + str(exc))
            report('Если нужна помощь, пришлите файл install.log из папки приложения.')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
