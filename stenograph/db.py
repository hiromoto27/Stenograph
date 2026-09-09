from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(segments) -> str:
    return hashlib.sha256(json.dumps([dict(s) for s in segments], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def norm(text: str) -> str:
    return " ".join(text.casefold().split())


class Database:
    """Short-lived connections: UI, audio and inference threads never share a connection."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise RuntimeError("База создана более новой версией СтеноГрафа. Обновите приложение.")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meetings(
                  id INTEGER PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks(
                  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id),
                  source TEXT NOT NULL, path TEXT UNIQUE NOT NULL, offset REAL NOT NULL,
                  duration REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending', error TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS chunks_queue ON chunks(state,id);
                CREATE TABLE IF NOT EXISTS segments(
                  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id),
                  chunk_id INTEGER REFERENCES chunks(id), source TEXT NOT NULL,
                  start REAL NOT NULL, end REAL NOT NULL, original TEXT NOT NULL, text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS segments_meeting ON segments(meeting_id,start);
                CREATE TABLE IF NOT EXISTS reports(
                  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id),
                  created TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                  id INTEGER PRIMARY KEY, meeting_id INTEGER REFERENCES meetings(id),
                  title TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
                  due TEXT, reminder TEXT, state TEXT NOT NULL DEFAULT 'draft', notified TEXT,
                  source_id INTEGER REFERENCES segments(id), quote TEXT NOT NULL DEFAULT '',
                  dedup TEXT UNIQUE NOT NULL);
                CREATE INDEX IF NOT EXISTS tasks_reminder ON tasks(state,reminder,notified);
                CREATE TABLE IF NOT EXISTS terms(
                  wrong TEXT PRIMARY KEY, correct TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS corrections(
                  id INTEGER PRIMARY KEY, segment_id INTEGER REFERENCES segments(id),
                  before_text TEXT NOT NULL, after_text TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shots(
                  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id),
                  path TEXT NOT NULL, caption TEXT NOT NULL, at_seconds REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(
                  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id INTEGER NOT NULL,
                  meeting_id INTEGER REFERENCES meetings(id), title TEXT NOT NULL, body TEXT NOT NULL,
                  topic TEXT NOT NULL DEFAULT '', UNIQUE(kind,ref_id));
                CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
                  title, body, topic, content='documents', content_rowid='id', tokenize='unicode61');
                CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
                  INSERT INTO search_fts(rowid,title,body,topic) VALUES(new.id,new.title,new.body,new.topic); END;
                CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
                  INSERT INTO search_fts(search_fts,rowid,title,body,topic)
                  VALUES('delete',old.id,old.title,old.body,old.topic); END;
                CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
                  INSERT INTO search_fts(search_fts,rowid,title,body,topic)
                  VALUES('delete',old.id,old.title,old.body,old.topic);
                  INSERT INTO search_fts(rowid,title,body,topic) VALUES(new.id,new.title,new.body,new.topic); END;
                CREATE TABLE IF NOT EXISTS deleted_tasks(dedup TEXT PRIMARY KEY, deleted TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS map_notes(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id INTEGER REFERENCES meetings(id),
                  group_name TEXT NOT NULL, topic_name TEXT NOT NULL, body TEXT NOT NULL,
                  created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS map_links(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_id INTEGER NOT NULL REFERENCES map_notes(id) ON DELETE CASCADE,
                  target_id INTEGER NOT NULL REFERENCES map_notes(id) ON DELETE CASCADE,
                  label TEXT NOT NULL, CHECK(source_id <> target_id), UNIQUE(source_id,target_id));
            """)

            columns = {r[1] for r in db.execute("PRAGMA table_info(chunks)")}
            for name in ("delete_after", "purged_at", "purge_error"):
                if name not in columns:
                    db.execute(f"ALTER TABLE chunks ADD COLUMN {name} TEXT")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).lastrowid

    @staticmethod
    def index(db, kind, ref, meeting, title, body, topic=""):
        db.execute("""INSERT INTO documents(kind,ref_id,meeting_id,title,body,topic) VALUES(?,?,?,?,?,?)
           ON CONFLICT(kind,ref_id) DO UPDATE SET meeting_id=excluded.meeting_id,title=excluded.title,body=excluded.body,topic=excluded.topic""",
                   (kind, ref, meeting, title, body, topic))

    def new_meeting(self, title):
        with self.connect() as db:
            mid = db.execute("INSERT INTO meetings(title,created) VALUES(?,?)", (title.strip() or "Новая встреча", now_iso())).lastrowid
            self.index(db, "meeting", mid, mid, title, "")
        return mid

    def meetings(self):
        return self.rows("SELECT * FROM meetings ORDER BY id DESC")

    def segments(self, mid):
        return self.rows("SELECT * FROM segments WHERE meeting_id=? ORDER BY start,id", (mid,))

    def add_chunk(self, mid, source, path, offset, duration):
        return self.execute("INSERT OR IGNORE INTO chunks(meeting_id,source,path,offset,duration) VALUES(?,?,?,?,?)",
                            (mid, source, str(path), offset, duration))

    def complete_chunk(self, chunk, segments):
        with self.connect() as db:
            # A chunk's transcript and done state commit together, even across a crash/retry.
            if db.execute("SELECT state FROM chunks WHERE id=?", (chunk["id"],)).fetchone()[0] == "done":
                return
            for start, end, original, corrected in segments:
                sid = db.execute("""INSERT INTO segments(meeting_id,chunk_id,source,start,end,original,text)
                    VALUES(?,?,?,?,?,?,?)""", (chunk["meeting_id"], chunk["id"], chunk["source"], start, end, original, corrected)).lastrowid
                self.index(db, "segment", sid, chunk["meeting_id"], chunk["source"], corrected)
            db.execute("UPDATE chunks SET state='done',error='' WHERE id=?", (chunk["id"],))

    def add_text(self, mid, text):
        paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
        with self.connect() as db:
            for i, paragraph in enumerate(paragraphs):
                # Bound imported rows so one source cannot overflow the LLM context.
                for off in range(0, len(paragraph), 2000):
                    part = paragraph[off:off+2000]
                    sid = db.execute("""INSERT INTO segments(meeting_id,source,start,end,original,text)
                        VALUES(?,?,?,?,?,?)""", (mid, "Импорт текста", i, i, part, part)).lastrowid
                    self.index(db, "segment", sid, mid, "Импорт текста", part)

    def correct_segment(self, sid, text):
        if not text.strip():
            raise ValueError("Текст не должен быть пустым")
        with self.connect() as db:
            row = db.execute("SELECT * FROM segments WHERE id=?", (sid,)).fetchone()
            db.execute("INSERT INTO corrections(segment_id,before_text,after_text,created) VALUES(?,?,?,?)",
                       (sid, row["text"], text.strip(), now_iso()))
            db.execute("UPDATE segments SET text=? WHERE id=?", (text.strip(), sid))
            self.index(db, "segment", sid, row["meeting_id"], row["source"], text.strip())

    def save_report(self, mid, body, source_fingerprint):
        with self.connect() as db:
            rid = db.execute("INSERT INTO reports(meeting_id,created,fingerprint,body) VALUES(?,?,?,?)",
                             (mid, now_iso(), source_fingerprint, json.dumps(body, ensure_ascii=False))).lastrowid
            # Index only current report. Previous versions remain available in reports.
            topic_names = " ".join(t["name"] for t in body["topics"])
            self.index(db, "report", mid, mid, "Протокол", json.dumps(body, ensure_ascii=False), topic_names)
            cleanup_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
            db.execute("UPDATE chunks SET delete_after=?,purge_error=NULL WHERE meeting_id=? AND state='done' AND purged_at IS NULL",
                       (cleanup_at, mid))
            for task in body["tasks"]:
                key = hashlib.sha256(f"{mid}|{norm(task['title'])}|{task['source_id']}".encode()).hexdigest()
                if db.execute("SELECT 1 FROM deleted_tasks WHERE dedup=?", (key,)).fetchone():
                    continue
                cur = db.execute("""INSERT OR IGNORE INTO tasks(meeting_id,title,context,owner,source_id,quote,dedup)
                    VALUES(?,?,?,?,?,?,?)""", (mid, task["title"], task["context"], task["owner"], task["source_id"], task["quote"], key))
                if cur.rowcount:
                    self.index(db, "task", cur.lastrowid, mid, task["title"], task["context"] + " " + task["quote"])
            return rid

    def latest_report(self, mid):
        rows = self.rows("SELECT * FROM reports WHERE meeting_id=? ORDER BY id DESC LIMIT 1", (mid,))
        if not rows:
            return None
        row = rows[0]
        row["body"] = json.loads(row["body"])
        return row

    def save_task(self, task_id, mid, title, context, owner, due, reminder, state):
        if not title.strip() or state not in {"draft", "open", "done", "dismissed"}:
            raise ValueError("Укажите название и допустимый статус задачи")
        for value in (due, reminder):
            if value and datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("Время должно содержать часовой пояс")
        with self.connect() as db:
            if task_id:
                old = db.execute("SELECT reminder FROM tasks WHERE id=?", (task_id,)).fetchone()
                db.execute("UPDATE tasks SET title=?,context=?,owner=?,due=?,reminder=?,state=? WHERE id=?",
                           (title, context, owner, due, reminder, state, task_id))
                if old[0] != reminder:
                    db.execute("UPDATE tasks SET notified=NULL WHERE id=?", (task_id,))
            else:
                import uuid
                task_id = db.execute("""INSERT INTO tasks(meeting_id,title,context,owner,due,reminder,state,dedup)
                    VALUES(?,?,?,?,?,?,?,?)""", (mid, title, context, owner, due, reminder, state, uuid.uuid4().hex)).lastrowid
            self.index(db, "task", task_id, mid, title, context)
        return task_id

    def delete_task(self, task_id):
        with self.connect() as db:
            task = db.execute("SELECT dedup FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return
            db.execute("INSERT OR IGNORE INTO deleted_tasks(dedup,deleted) VALUES(?,?)", (task[0], now_iso()))
            db.execute("DELETE FROM documents WHERE kind='task' AND ref_id=?", (task_id,))
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def snooze_task(self, task_id, minutes=15):
        reminder = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        self.execute("UPDATE tasks SET reminder=?,notified=NULL WHERE id=? AND state='open'", (reminder, task_id))

    def finish_task(self, task_id):
        self.execute("UPDATE tasks SET state='done',notified=? WHERE id=?", (now_iso(), task_id))

    def save_link(self, link_id, source_id, target_id, label):
        if source_id == target_id or not label.strip():
            raise ValueError("Выберите два разных элемента и подпишите связь.")
        with self.connect() as db:
            if len(db.execute("SELECT id FROM map_notes WHERE id IN (?,?)", (source_id, target_id)).fetchall()) != 2:
                raise ValueError("Один из элементов уже удалён.")
            try:
                if link_id:
                    cursor = db.execute("UPDATE map_links SET source_id=?,target_id=?,label=? WHERE id=?",
                                        (source_id, target_id, label.strip(), link_id))
                    if not cursor.rowcount:
                        raise ValueError("Связь уже удалена.")
                else:
                    link_id = db.execute("INSERT INTO map_links(source_id,target_id,label) VALUES(?,?,?)",
                                         (source_id, target_id, label.strip())).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError("Между этими элементами уже есть связь. Отредактируйте её.") from exc
        return link_id

    def delete_link(self, link_id):
        self.execute("DELETE FROM map_links WHERE id=?", (link_id,))

    def save_note(self, note_id, mid, group, topic, body):
        group, topic, body = group.strip(), topic.strip(), body.strip()
        if not group or not topic or not body:
            raise ValueError("Заполните раздел, тему и содержание элемента.")
        with self.connect() as db:
            if note_id:
                if not db.execute("SELECT 1 FROM map_notes WHERE id=?", (note_id,)).fetchone():
                    raise ValueError("Элемент уже удалён.")
                db.execute("UPDATE map_notes SET meeting_id=?,group_name=?,topic_name=?,body=?,updated=? WHERE id=?",
                           (mid, group, topic, body, now_iso(), note_id))
            else:
                note_id = db.execute("INSERT INTO map_notes(meeting_id,group_name,topic_name,body,created,updated) VALUES(?,?,?,?,?,?)",
                                     (mid, group, topic, body, now_iso(), now_iso())).lastrowid
            self.index(db, "note", note_id, mid, topic, body, group + " " + topic)
        return note_id

    def delete_note(self, note_id):
        with self.connect() as db:
            db.execute("DELETE FROM documents WHERE kind='note' AND ref_id=?", (note_id,))
            db.execute("DELETE FROM map_notes WHERE id=?", (note_id,))

    def due_reminders(self, at=None):
        return self.rows("""SELECT * FROM tasks WHERE state='open' AND reminder IS NOT NULL AND notified IS NULL
               AND julianday(reminder)<=julianday(?) ORDER BY reminder""", (at or now_iso(),))

    def mark_notified(self, task_id):
        self.execute("UPDATE tasks SET notified=? WHERE id=?", (now_iso(), task_id))

    def search(self, query, phrase=False):
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if not tokens:
            return []
        expression = ('"' + " ".join(tokens) + '"') if phrase else " AND ".join('"' + t + '"*' for t in tokens)
        return self.rows("""SELECT d.*,bm25(search_fts) AS rank FROM search_fts
            JOIN documents d ON d.id=search_fts.rowid WHERE search_fts MATCH ? ORDER BY rank LIMIT 100""", (expression,))

    def add_shot(self, mid, path, caption, at):
        with self.connect() as db:
            sid = db.execute("INSERT INTO shots(meeting_id,path,caption,at_seconds) VALUES(?,?,?,?)",
                             (mid, str(path), caption, at)).lastrowid
            self.index(db, "shot", sid, mid, "Скриншот", caption)

    def backup(self, target):
        with self.connect() as src, sqlite3.connect(target) as dst:
            src.backup(dst)
