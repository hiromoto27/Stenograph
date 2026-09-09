import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from stenograph.db import Database, fingerprint
from stenograph.exports import guide_html, mindmap_data, report_html
from stenograph.hardware import Hardware, compatibility, recommend
from stenograph.intelligence import LocalLLM, Report, apply_terms, batches, merge_reports, validate_evidence


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "knowledge.sqlite3")


@pytest.fixture
def meeting(db):
    mid = db.new_meeting("Планирование сервера печати")
    db.add_text(mid, "Сергей подготовит инструкцию по серверу печати.\nРешили использовать локальное распознавание.")
    return mid


def sample_report(segments):
    first, second = segments[:2]
    evidence = {"text": "Работать локально", "source_id": second["id"], "quote": second["text"]}
    return {"summary": [evidence], "decisions": [evidence], "questions": [],
            "topics": [{"group": "Инфраструктура", "name": "Печать", "facts": [evidence]}],
            "tasks": [{"title": "Подготовить инструкцию", "context": "Сервер печати", "owner": "Сергей",
                       "deadline_text": "", "source_id": first["id"], "quote": first["text"]}], "steps": []}


def test_search_russian_prefix_phrase_and_fts_escaping(db, meeting):
    assert db.search("сервер печат")
    assert db.search("серверу печати", phrase=True)
    assert not db.search("печати серверу", phrase=True)
    assert db.search('"серверу"')
    assert db.search("---") == []
    assert db.search('" OR *') == []


def test_correction_updates_index_and_keeps_original(db, meeting):
    row = db.segments(meeting)[0]
    db.correct_segment(row["id"], "Сергей настроит маршрутизатор.")
    changed = db.segments(meeting)[0]
    assert changed["original"] == row["original"]
    assert changed["text"] != changed["original"]
    assert not db.search("серверу")
    assert db.search("маршрутизатор")
    assert len(db.rows("SELECT * FROM corrections")) == 1


def test_chunk_transaction_is_idempotent(db, meeting, tmp_path):
    path = tmp_path / "one.wav"
    db.add_chunk(meeting, "Микрофон", path, 10, 3)
    db.add_chunk(meeting, "Микрофон", path, 10, 3)
    chunk = db.rows("SELECT * FROM chunks")[0]
    for _ in range(2):
        db.complete_chunk(chunk, [(10, 12, "текст", "исправлено")])
    assert len(db.rows("SELECT * FROM chunks")) == 1
    assert len(db.rows("SELECT * FROM segments WHERE chunk_id IS NOT NULL")) == 1
    assert db.rows("SELECT state FROM chunks")[0]["state"] == "done"


def test_report_validation_rejects_invented_sources_and_quotes(db, meeting):
    segments = db.segments(meeting)
    report = sample_report(segments)
    Report.model_validate(report)
    validate_evidence(report, segments)
    report["tasks"][0]["source_id"] = 999999
    with pytest.raises(ValueError, match="цитат"):
        validate_evidence(report, segments)
    report["tasks"][0]["source_id"] = segments[0]["id"]
    report["tasks"][0]["quote"] = "Такого никто не говорил"
    with pytest.raises(ValueError):
        validate_evidence(report, segments)


def test_report_history_task_dedup_and_confirmed_state(db, meeting):
    segments = db.segments(meeting)
    report = sample_report(segments)
    db.save_report(meeting, report, fingerprint(segments))
    task = db.rows("SELECT * FROM tasks")[0]
    db.save_task(task["id"], meeting, task["title"], task["context"], task["owner"], None, None, "done")
    db.save_report(meeting, report, fingerprint(segments))
    assert len(db.rows("SELECT * FROM reports")) == 2
    assert len(db.rows("SELECT * FROM tasks")) == 1
    assert db.rows("SELECT * FROM tasks")[0]["state"] == "done"
    assert len(db.rows("SELECT * FROM documents WHERE kind='report'")) == 1
    assert db.search("Инфраструктура")


def test_due_reminders_timezones_drafts_completion_and_restart(db, meeting):
    at = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
    past_other_zone = (at - timedelta(minutes=10)).astimezone(timezone(timedelta(hours=3))).isoformat()
    open_id = db.save_task(None, meeting, "Позвонить", "О принтере", "", None, past_other_zone, "open")
    db.save_task(None, meeting, "Черновик", "", "", None, past_other_zone, "draft")
    db.save_task(None, meeting, "Готово", "", "", None, past_other_zone, "done")
    db.save_task(None, meeting, "Будущее", "", "", None, (at + timedelta(days=1)).isoformat(), "open")
    restarted = Database(db.path)
    assert [t["id"] for t in restarted.due_reminders(at.isoformat())] == [open_id]
    restarted.mark_notified(open_id)
    assert restarted.due_reminders(at.isoformat()) == []
    with pytest.raises(ValueError):
        db.save_task(None, meeting, "Без зоны", "", "", None, "2026-09-08T10:00:00", "open")


def test_batched_analysis_covers_all_input_and_merges(db, meeting):
    segments = db.segments(meeting)
    parts = list(batches(segments, limit=180))
    assert [s["id"] for p in parts for s in p] == [s["id"] for s in segments]
    merged = merge_reports([sample_report(segments), sample_report(segments)])
    assert len(merged["tasks"]) == 1
    assert len(merged["topics"][0]["facts"]) == 1


def test_dictionary_boundaries_unicode_and_no_cascade():
    terms = [{"wrong": "1 эс", "correct": "1С"}, {"wrong": "кот", "correct": "тигр"}, {"wrong": "тигр", "correct": "лев"}]
    assert apply_terms("1 ЭС и кот, котлета и тигр", terms) == "1С и тигр, котлета и лев"


def test_local_model_allowlist():
    with pytest.raises(ValueError):
        LocalLLM("qwen3:cloud")
    with pytest.raises(ValueError):
        LocalLLM().request("https://external.example")


def test_html_escapes_dialogue_and_mindmap_has_provenance(db, meeting):
    segments = db.segments(meeting)
    report = sample_report(segments)
    report["summary"][0]["text"] = '<script>alert("x")</script>'
    output = report_html("<b>Название</b>", report)
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    db.save_report(meeting, report, fingerprint(segments))
    fact = next(iter(next(iter(mindmap_data(db).values()))["topics"].values()))["facts"][0]
    assert fact["meeting_id"] == meeting and fact["source_id"] in [s["id"] for s in segments]
    assert "<script>" not in guide_html("<script>", [], [])


def test_backup_contains_committed_wal_data(db, meeting, tmp_path):
    backup = tmp_path / "backup.sqlite3"
    db.backup(backup)
    with sqlite3.connect(backup) as restored:
        assert restored.execute("SELECT count(*) FROM segments").fetchone()[0] == 2


def test_hardware_estimates_are_conservative():
    hw = Hardware("Windows", "CPU", 8, 8, 2, 10, "Unknown", 0, False)
    assert recommend(hw)["device"] == "cpu"
    assert recommend(hw)["llm"] == "qwen3:1.7b"
    item = {"ram_gb": 16, "working_gb": 6, "disk_gb": 5, "vram_gb": 6}
    assert "Недостаточно" in compatibility(item, hw)
