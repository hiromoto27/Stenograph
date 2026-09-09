import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from stenograph.db import Database, fingerprint
from stenograph.exports import mindmap_data
from stenograph.maintenance import cleanup_audio
from stenograph.runtime_guard import RuntimeGuard
from stenograph.updates import digest, install_files, safe_relative, unpack_release


def report():
    return {k: [] for k in ('summary', 'decisions', 'questions', 'topics', 'tasks', 'steps')}


def test_audio_deadline_restart_pending_and_path_guards(tmp_path):
    db = Database(tmp_path / 'knowledge.sqlite3')
    mid = db.new_meeting('Встреча')
    audio = tmp_path / 'audio' / str(mid)
    audio.mkdir(parents=True)
    path = audio / 'done.wav'
    path.write_bytes(b'audio')
    db.add_chunk(mid, 'mic', path, 0, 10)
    chunk = db.rows('SELECT * FROM chunks')[0]
    db.complete_chunk(chunk, [(0, 10, 'Текст', 'Текст')])
    assert cleanup_audio(db, tmp_path, at='2100-01-01T00:00:00+00:00') == (0, [])
    db.save_report(mid, report(), fingerprint(db.segments(mid)))
    row = db.rows('SELECT * FROM chunks')[0]
    deadline = datetime.fromisoformat(row['delete_after'])
    assert 3590 < (deadline-datetime.now(timezone.utc)).total_seconds() <= 3600
    assert cleanup_audio(db, tmp_path, at=(deadline-timedelta(seconds=1)).isoformat()) == (0, [])
    pending = audio / 'pending.wav'
    pending.write_bytes(b'pending')
    db.add_chunk(mid, 'mic', pending, 10, 10)
    assert cleanup_audio(db, tmp_path, {mid}, at=deadline.isoformat()) == (0, [])
    assert cleanup_audio(Database(db.path), tmp_path, at=deadline.isoformat()) == (1, [])
    assert not path.exists() and pending.exists() and db.segments(mid)
    assert cleanup_audio(db, tmp_path, at=deadline.isoformat()) == (0, [])
    outside = tmp_path / 'do-not-delete.wav'
    outside.write_bytes(b'keep')
    db.add_chunk(mid, 'mic', outside, 20, 10)
    db.execute("UPDATE chunks SET state='done',delete_after=? WHERE path=?", (deadline.isoformat(), str(outside)))
    assert cleanup_audio(db, tmp_path, at=deadline.isoformat())[1]
    assert outside.exists()


def test_notes_links_regeneration_search_move_and_cascade(tmp_path):
    db = Database(tmp_path / 'db')
    mid = db.new_meeting('Встреча')
    a = db.save_note(None, None, 'Раздел', 'Тема', 'Альфа')
    b = db.save_note(None, mid, 'Раздел', 'Другая', 'Бета')
    c = db.save_note(None, None, 'Раздел', 'Третья', 'Гамма')
    link = db.save_link(None, a, b, 'дополняет')
    db.save_report(mid, report(), fingerprint([]))
    assert db.search('Альфа')
    db.save_note(a, mid, 'Другой раздел', 'Другая тема', 'Дельта')
    assert not db.search('Альфа')
    assert db.search('Дельта')[0]['meeting_id'] == mid
    db.save_link(link, b, c, 'уточняет')
    assert db.rows('SELECT * FROM map_links')[0]['target_id'] == c
    with pytest.raises(ValueError):
        db.save_link(None, a, a, 'ошибка')
    with pytest.raises(ValueError):
        db.save_link(None, b, c, 'дубликат')
    groups = mindmap_data(Database(db.path))
    facts = [f for g in groups.values() for t in g['topics'].values() for f in t['facts']]
    assert sum(len(f['links']) for f in facts) == 1
    db.delete_note(c)
    assert not db.rows('SELECT * FROM map_links')
    assert len(db.rows('SELECT * FROM map_notes')) == 2


def test_deleted_generated_task_not_resurrected_and_reminder_snooze(tmp_path):
    db = Database(tmp_path/'db')
    mid = db.new_meeting('Встреча')
    db.add_text(mid, 'Нужно позвонить')
    sid = db.segments(mid)[0]['id']
    body = report()
    body['tasks'] = [{'title': 'Позвонить', 'context': 'Тема', 'owner': '', 'source_id': sid,
                      'quote': 'Нужно позвонить', 'deadline_text': ''}]
    db.save_report(mid, body, fingerprint(db.segments(mid)))
    tid = db.rows('SELECT * FROM tasks')[0]['id']
    db.delete_task(tid)
    db.save_report(mid, body, fingerprint(db.segments(mid)))
    assert not db.rows('SELECT * FROM tasks')
    assert not db.rows("SELECT * FROM documents WHERE kind='task'")
    tid = db.save_task(None, mid, 'Другая', 'Контекст', '', None, '2000-01-01T00:00:00+00:00', 'open')
    assert db.due_reminders()
    db.snooze_task(tid, 15)
    assert not db.due_reminders()
    db.finish_task(tid)
    assert db.rows('SELECT * FROM tasks')[0]['state'] == 'done'


@pytest.mark.parametrize('path', ['../x', '/x', 'a/../../b', 'a\\b', '.VENV/x', 'Data/x', 'a/NUL.txt', 'a/CON', 'x.', 'a:foo', 'a//b', 'x '])
def test_update_rejects_unsafe_windows_paths(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def create_release(folder, version, content):
    folder.mkdir()
    files = {}
    for name in ('pyproject.toml', 'stenograph/__main__.py', 'stenograph/app.py'):
        path = folder/name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
        files[name] = digest(path)
    manifest = {'app_id': 'stenograph-local', 'version': version, 'files': files}
    (folder/'release.json').write_text(json.dumps(manifest))
    return manifest


def test_updater_rollback_and_preserves_data(tmp_path):
    target, stage = tmp_path/'app', tmp_path/'stage'
    create_release(target, '0.2.0', 'old')
    create_release(stage, '0.3.0', 'new')
    (target/'personal.txt').write_text('keep')
    (target/'models').mkdir()
    (target/'models/model.bin').write_bytes(b'weights')
    def fail():
        raise RuntimeError('dependency failure')
    with pytest.raises(RuntimeError):
        install_files(stage, target, tmp_path/'backup', fail)
    assert (target/'stenograph/app.py').read_text() == 'old'
    assert (target/'personal.txt').read_text() == 'keep'
    assert (target/'models/model.bin').read_bytes() == b'weights'
    install_files(stage, target, tmp_path/'backup2', lambda: None)
    assert (target/'stenograph/app.py').read_text() == 'new'
    (target/'stenograph/app.py').write_text('custom')
    with pytest.raises(ValueError, match='вручную'):
        install_files(stage, target, tmp_path/'backup3', lambda: None)


def test_archive_checksums_and_guard(tmp_path):
    stage = tmp_path/'stage'
    manifest = create_release(stage, '0.3.0', 'new')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        for path in stage.rglob('*'):
            if path.is_file():
                archive.writestr('root/'+str(path.relative_to(stage)), path.read_bytes())
    release = {'manifest': manifest, 'subdir': ''}
    unpack_release(payload.getvalue(), release, tmp_path/'unpacked')
    manifest['files']['stenograph/app.py'] = '0'*64
    with pytest.raises(ValueError, match='сумма'):
        unpack_release(payload.getvalue(), release, tmp_path/'bad')
    first, second = RuntimeGuard(tmp_path), RuntimeGuard(tmp_path)
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_existing_v1_database_migrates_without_scheduling_old_audio(tmp_path):
    import sqlite3
    path = tmp_path/'db'
    with sqlite3.connect(path) as conn:
        conn.executescript("""CREATE TABLE meetings(id INTEGER PRIMARY KEY,title TEXT NOT NULL,created TEXT NOT NULL);
        INSERT INTO meetings VALUES(1,'Старая встреча','2026-01-01');
        CREATE TABLE chunks(id INTEGER PRIMARY KEY,meeting_id INTEGER NOT NULL,source TEXT NOT NULL,
        path TEXT UNIQUE NOT NULL,offset REAL NOT NULL,duration REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',error TEXT DEFAULT '');
        INSERT INTO chunks VALUES(1,1,'mic','old.wav',0,10,'done',''); PRAGMA user_version=1;""")
    db = Database(path)
    assert db.meetings()[0]['title'] == 'Старая встреча'
    assert db.rows('SELECT * FROM chunks')[0]['delete_after'] is None
    assert db.rows('PRAGMA user_version')[0]['user_version'] == 2


def test_embedded_engine_uses_local_gguf_validates_evidence_and_releases(tmp_path, monkeypatch):
    import sys
    import types
    from stenograph.intelligence import EmbeddedLLM
    path = tmp_path/'model.gguf'
    path.write_bytes(b'fake fixture')
    source = {'id': 1, 'source': 'mic', 'text': 'Работаем локально'}
    body = report()
    body['summary'] = [{'text': 'Работа локально', 'source_id': 1, 'quote': source['text']}]
    calls = []
    class Engine:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def create_chat_completion(self, **kwargs):
            assert kwargs['response_format']['schema']['additionalProperties'] is False
            return {'choices': [{'message': {'content': json.dumps(body)}, 'finish_reason': 'stop'}]}
        def close(self):
            calls.append('closed')
    monkeypatch.setitem(sys.modules, 'llama_cpp', types.SimpleNamespace(Llama=Engine))
    def forbidden(*args, **kwargs):
        raise AssertionError('No HTTP allowed for embedded model')
    monkeypatch.setattr('urllib.request.build_opener', forbidden)
    model = EmbeddedLLM(str(path))
    model.check()
    try:
        assert model.extract([source]) == body
        body['summary'][0]['quote'] = 'Выдуманная цитата'
        with pytest.raises(ValueError):
            model.extract([source])
    finally:
        model.close()
    assert calls[0]['model_path'] == str(path)
    assert calls[-1] == 'closed'


def test_update_rejects_parent_symlink_into_model_directory(tmp_path):
    import shutil
    target, stage = tmp_path/'app', tmp_path/'stage'
    create_release(target, '0.2.0', 'old')
    create_release(stage, '0.3.0', 'new')
    models = target/'models'
    models.mkdir()
    shutil.move(str(target/'stenograph'), str(models/'protected'))
    try:
        (target/'stenograph').symlink_to(models/'protected', target_is_directory=True)
    except OSError:
        pytest.skip('Creating symlinks requires Windows Developer Mode or elevation')
    with pytest.raises(ValueError, match='Небезопасный'):
        install_files(stage, target, tmp_path/'backup', lambda: None)
    assert (models/'protected/app.py').read_text() == 'old'
