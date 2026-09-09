import importlib.util
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def installer():
    path = Path(__file__).resolve().parents[1] / 'scripts/install.py'
    spec = importlib.util.spec_from_file_location('installer_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def info(path='python.exe', minor=12):
    return dict(executable=str(path), major=3, minor=minor, bits=64, machine='AMD64',
                implementation='CPython', free_threaded=False, version=f'3.{minor}.0')


def test_launcher_output_keeps_paths_with_spaces_separate(installer):
    output = ' -V:3.13 * C:\\Program Files\\Python313\\python.exe\n -3.12-64 C:\\Users\\Hiro\\Python312\\python.exe\n'
    assert list(installer.launcher_paths(output)) == [
        r'C:\Program Files\Python313\python.exe', r'C:\Users\Hiro\Python312\python.exe']


def test_two_launchers_invoked_individually_and_failure_is_skipped(installer, tmp_path, monkeypatch):
    folders = [tmp_path / 'Windows', tmp_path / 'WindowsApps']
    for folder in folders:
        folder.mkdir()
        (folder / 'py.exe').touch()
    monkeypatch.setattr(installer.os, 'get_exec_path', lambda: [str(x) for x in folders])
    monkeypatch.setattr(installer, 'registry_paths', lambda: iter(()))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == str(folders[0] / 'py.exe'):
            raise FileNotFoundError('stale launcher')
        return subprocess.CompletedProcess(command, 0, ' -V:3.12 * C:\\Python 312\\python.exe\n', '')

    monkeypatch.setattr(installer.subprocess, 'run', run)
    assert r'C:\Python 312\python.exe' in list(installer.candidates())
    assert calls == [[str(folders[0] / 'py.exe'), '-0p'], [str(folders[1] / 'py.exe'), '-0p']]


def test_unsupported_default_falls_back_to_supported_python(installer, tmp_path, monkeypatch):
    paths = [tmp_path / 'Python 314.exe', tmp_path / 'Python 312.exe']
    for path in paths:
        path.touch()
    monkeypatch.setattr(installer, 'probe', lambda p: info(p, 14 if '314' in str(p) else 12))
    assert installer.select_python([str(p) for p in paths], lambda _: None) == str(paths[1])
    assert installer.select_python([str(paths[0])], lambda _: None) is None


def test_damaged_environment_is_preserved_and_paths_remain_single_arguments(installer, tmp_path, monkeypatch):
    root = tmp_path / 'Folder with spaces'
    old = root / '.venv'
    old.mkdir(parents=True)
    (old / 'keep.txt').write_text('previous environment')
    monkeypatch.setattr(installer, 'ROOT', root)
    monkeypatch.setattr(installer, 'probe', lambda p: info(p) if Path(p).is_file() else None)
    calls = []

    def run(command):
        calls.append(command)
        if 'venv' in command:
            target = root / '.venv/Scripts/python.exe'
            target.parent.mkdir(parents=True)
            target.touch()

    interpreter = r'C:\Program Files\Python312\python.exe'
    installer.install(interpreter, lambda _: None, run)
    assert calls[0] == [interpreter, '-m', 'venv', str(root / '.venv')]
    assert len(list(root.glob('.venv-old-*/keep.txt'))) == 1
    assert calls[1][-1] == str(root)


def test_environment_creation_failure_never_claims_python_missing(installer, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    monkeypatch.setattr(installer, 'probe', lambda _: None)
    with pytest.raises(RuntimeError, match='Окружение не создано'):
        installer.install('python.exe', lambda _: None, lambda _: None)
