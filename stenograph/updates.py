"""Explicit GitHub source updates. No network requests occur until check/apply is called."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile

APP_ID = 'stenograph-local'
MANIFEST = 'release.json'
LIMIT = 100 * 1024 * 1024
RESERVED = {'.git', '.venv', 'models', 'data', 'audio', 'screenshots', 'runtime.guard', 'settings.json'}


def repo_slug(url):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?', url.strip())
    if not match:
        raise ValueError('Укажите HTTPS-адрес репозитория github.com без пароля и параметров.')
    return match.group(1)


def safe_relative(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
            or any(part.casefold() in RESERVED or part.casefold().startswith('.venv-old-')
                   or part.endswith((' ', '.')) or re.search(r'[<>"|?*\x00-\x1f]', part)
                   or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part, re.I)
                   for part in path.parts)
            or str(path) != name or path.parts[0].startswith('.update-')):
        raise ValueError('Недопустимый путь обновления: ' + name)
    return path


def validate_manifest(manifest):
    if manifest.get('app_id') != APP_ID or not re.fullmatch(r'\d+\.\d+\.\d+', manifest.get('version', '')):
        raise ValueError('В репозитории нет подходящего выпуска СтеноГрафа.')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files or len(files) > 2000:
        raise ValueError('Некорректный список файлов выпуска.')
    folded = set()
    for name, digest in files.items():
        safe_relative(name)
        if name.casefold() in folded or name.casefold() == MANIFEST or not re.fullmatch(r'[a-f0-9]{64}', str(digest)):
            raise ValueError('Некорректный или повторяющийся файл в выпуске.')
        folded.add(name.casefold())
    for required in ('pyproject.toml', 'stenograph/__main__.py', 'stenograph/app.py'):
        if required not in files:
            raise ValueError('В выпуске отсутствует ' + required)
    return manifest


def download(url, limit=LIMIT):
    request = urllib.request.Request(url, headers={'User-Agent': 'Stenograph-Updater/0.2'})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Обновление превышает допустимый размер.')
    return data


def check_release(repository, branch, subdir=''):
    slug = repo_slug(repository)
    if not branch or branch.startswith('-'):
        raise ValueError('Укажите ветку обновлений.')
    ref = urllib.parse.quote(branch, safe='')
    commit = json.loads(download(f'https://api.github.com/repos/{slug}/commits/{ref}', 2_000_000))['sha']
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Некорректный номер коммита.')
    prefix = str(safe_relative(subdir)) + '/' if subdir else ''
    path = urllib.parse.quote(prefix + MANIFEST, safe='/')
    try:
        data = json.loads(download(f'https://api.github.com/repos/{slug}/contents/{path}?ref={commit}', 2_000_000))
        manifest = validate_manifest(json.loads(base64.b64decode(data['content'])))
    except (KeyError, ValueError) as exc:
        raise ValueError('В выбранной ветке нет готового выпуска с release.json.') from exc
    return {'sha': commit, 'manifest': manifest, 'repository': repository, 'subdir': subdir}


def unpack_release(payload, release, staging):
    manifest = validate_manifest(release['manifest'])
    staging = Path(staging)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(item.file_size for item in archive.infolist()) > LIMIT * 2:
            raise ValueError('Распакованное обновление слишком велико.')
        roots = {PurePosixPath(item.filename).parts[0] for item in archive.infolist() if item.filename}
        if len(roots) != 1:
            raise ValueError('Неверная структура архива.')
        prefix = next(iter(roots)) + '/' + (release['subdir'].strip('/') + '/' if release['subdir'] else '')
        for name, expected in manifest['files'].items():
            safe_relative(name)
            item = archive.getinfo(prefix + name)
            if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Символические ссылки в обновлениях не допускаются.')
            content = archive.read(item)
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('Контрольная сумма не совпала: ' + name)
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    (staging / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_files(staging, target, backup, prepare_dependencies):
    staging, target, backup = Path(staging), Path(target).resolve(), Path(backup)
    new = validate_manifest(json.loads((staging / MANIFEST).read_text(encoding='utf-8')))
    if not (target / MANIFEST).is_file():
        raise ValueError('Для первого перехода установите версию 0.2 из архива; затем обновляйтесь этой кнопкой.')
    old = validate_manifest(json.loads((target / MANIFEST).read_text(encoding='utf-8')))
    names = set(new['files']) | set(old['files']) | {MANIFEST}
    for name in names:
        safe_relative(name)
        destination = target / name
        parts = [destination, *destination.parents]
        redirected = any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                         for p in parts if p != target and p.is_relative_to(target))
        if redirected or not destination.resolve().is_relative_to(target):
            raise ValueError('Небезопасный путь назначения: ' + name)
        if destination.exists():
            if not destination.is_file():
                raise ValueError('Путь занят каталогом: ' + name)
            if name != MANIFEST:
                expected = old['files'].get(name)
                if expected is None or digest(destination) != expected:
                    raise ValueError('Файл изменён вручную. Сохраните изменения перед обновлением: ' + name)
    backup.mkdir(parents=True, exist_ok=False)
    existing = set()
    for name in names:
        source = target / name
        if source.is_file():
            existing.add(name)
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    try:
        for name in names:
            destination = target / name
            if name in new['files'] or name.casefold() == MANIFEST:
                source = staging / name
                if name != MANIFEST and digest(source) != new['files'][name]:
                    raise ValueError('Подготовленные файлы повреждены: ' + name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=destination.parent, prefix='.update-')
                os.close(fd)
                try:
                    shutil.copyfile(source, tmp)
                    os.replace(tmp, destination)
                finally:
                    Path(tmp).unlink(missing_ok=True)
            else:
                destination.unlink(missing_ok=True)
        prepare_dependencies()
    except Exception:
        for name in names:
            destination = target / name
            if name in existing:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / name, destination)
            else:
                destination.unlink(missing_ok=True)
        raise
