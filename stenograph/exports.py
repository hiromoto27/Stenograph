from __future__ import annotations

import base64
import html
from pathlib import Path

from .db import fingerprint


def evidence_html(items):
    return "<ul>" + "".join(
        f'<li>{html.escape(x["text"])} <small>• реплика #{x["source_id"]}</small>'
        f'<blockquote>{html.escape(x["quote"])}</blockquote></li>' for x in items) + "</ul>"


def report_html(title, report):
    out = f"<h1>{html.escape(title)}</h1><p>Черновик протокола · проверьте выводы по цитатам</p>"
    for key, label in [("summary", "Суть встречи"), ("decisions", "Решения"), ("questions", "Открытые вопросы")]:
        out += f"<h2>{label}</h2>" + (evidence_html(report[key]) if report[key] else "<p>Не выделены.</p>")
    out += "<h2>Задачи</h2><ul>"
    for task in report["tasks"]:
        out += f'<li><b>{html.escape(task["title"])}</b><p>{html.escape(task["context"])}</p>'
        out += f'<p>Исполнитель: {html.escape(task["owner"] or "не указан")} · Срок в диалоге: {html.escape(task["deadline_text"] or "не указан")}</p>'
        out += f'<blockquote>#{task["source_id"]} · {html.escape(task["quote"])}</blockquote></li>'
    return out + "</ul>"


def standalone(body, title):
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(title)}</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:48px auto;padding:0 28px;line-height:1.6;color:#20293d}}
h1{{font-size:34px}}h2{{margin-top:32px;color:#5450bf}}blockquote{{border-left:3px solid #b7b4f0;padding-left:16px;color:#61708b}}
img{{max-width:100%;border:1px solid #ddd;border-radius:10px}}small{{color:#69758d}}li{{margin-bottom:16px}}
@media print{{body{{margin:0}}img{{max-height:70vh}}}}
</style><body>{body}</body></html>'''


def guide_html(title, steps, shots):
    out = f"<h1>{html.escape(title)} — инструкция</h1><p>Черновик по диалогу. Скриншоты с подписями добавлены пользователем.</p>"
    if steps:
        out += "<h2>Порядок действий</h2>" + evidence_html(steps)
    else:
        out += "<p>В диалоге не выделена последовательность действий. Ниже — сохранённые шаги со скриншотами.</p>"
    for i, shot in enumerate(shots, 1):
        path = Path(shot["path"])
        out += f'<h2>Скриншот {i} · {html.escape(shot["caption"])}</h2>'
        if path.is_file():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            out += f'<img alt="{html.escape(shot["caption"], quote=True)}" src="data:image/png;base64,{data}">'
        else:
            out += "<p>Файл скриншота отсутствует.</p>"
    return standalone(out, title)


def mindmap_data(db, mid=None):
    meetings = [m for m in db.meetings() if mid is None or m["id"] == mid]
    groups = {}
    for meeting in meetings:
        report = db.latest_report(meeting["id"])
        if not report:
            continue
        stale = report["fingerprint"] != fingerprint(db.segments(meeting["id"]))
        for topic in report["body"]["topics"]:
            group = groups.setdefault(topic["group"].casefold(), {"name": topic["group"], "topics": {}})
            node = group["topics"].setdefault(topic["name"].casefold(), {"name": topic["name"], "facts": []})
            for fact in topic["facts"]:
                node["facts"].append({**fact, "meeting_id": meeting["id"], "meeting_title": meeting["title"], "stale": stale})
    notes = db.rows("SELECT * FROM map_notes ORDER BY id") if mid is None else db.rows(
        "SELECT * FROM map_notes WHERE meeting_id=? ORDER BY id", (mid,))
    visible = {note['id'] for note in notes}
    links = db.rows("SELECT * FROM map_links ORDER BY id")
    for note in notes:
        group = groups.setdefault(note["group_name"].casefold(), {"name": note["group_name"], "topics": {}})
        node = group["topics"].setdefault(note["topic_name"].casefold(), {"name": note["topic_name"], "facts": []})
        node["facts"].append({"text": note["body"], "note_id": note["id"], "meeting_id": note["meeting_id"],
                              "source_id": None, "manual": True, "stale": False,
                              "links": [link for link in links if link['source_id'] == note['id'] and link['target_id'] in visible]})
    return groups
