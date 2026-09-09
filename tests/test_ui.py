import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stenograph.app import MainWindow
from stenograph.db import fingerprint
from stenograph.widgets import STYLE, TaskDialog


def test_desktop_flow_without_network_or_models(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow(tmp_path, scan_hardware=False)
    window.mid = window.db.new_meeting("Проверка интерфейса")
    window.db.add_text(window.mid, "Сергей создаст инструкцию для отдела.")
    source = window.db.segments(window.mid)[0]
    fact = {"text": "Подготовить инструкцию", "source_id": source["id"], "quote": source["text"]}
    report = {"summary": [fact], "decisions": [], "questions": [], "tasks": [], "steps": [],
              "topics": [{"group": "Работа", "name": "Инструкции", "facts": [fact]}]}
    window.db.save_report(window.mid, report, fingerprint([source]))
    window.refresh_meetings()
    assert window.transcript.rowCount() == 1
    assert "Подготовить инструкцию" in window.protocol.toPlainText()
    window.query.setText("инструкц")
    window.search()
    assert window.search_results.rowCount() >= 1
    window.nav.setCurrentRow(3)
    assert len(window.map.scene().items()) > 3
    window.go_source(window.mid, source["id"])
    assert window.transcript.currentRow() == 0
    dialog = TaskDialog(window)
    dialog.title.setText("Задача")
    dialog.reminder_check.setChecked(True)
    assert "+00:00" in dialog.values()["reminder"]
    window.timer.stop()
    window.tray.hide()
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_manual_links_dialog_and_reminder_actions(tmp_path):
    from stenograph.widgets import LinksDialog, ReminderDialog
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path, scan_hardware=False)
    a = window.db.save_note(None, None, 'Общее', 'Архитектура', 'Хранить офлайн')
    b = window.db.save_note(None, None, 'Общее', 'Резервирование', 'Делать копии')
    dialog = LinksDialog(window, window.db)
    dialog.source.setCurrentIndex(dialog.source.findData(a))
    dialog.target.setCurrentIndex(dialog.target.findData(b))
    dialog.caption.setText('требует')
    dialog.save_link()
    assert window.db.rows('SELECT * FROM map_links')[0]['label'] == 'требует'
    dialog.caption.setText('дополняет')
    dialog.save_link()
    assert len(window.db.rows('SELECT * FROM map_links')) == 1
    window.refresh_map()
    assert any(item.data(0) == ('link', dialog.link_id) for item in window.map.scene().items())
    task = TaskDialog(window)
    task.preset_reminder(None)
    assert task.reminder.dateTime().time().hour() == 9
    assert task.state.currentData() == 'open'
    actions = []
    reminder = ReminderDialog({'title': 'Проверить', 'context': 'Краткая тема'}, window)
    reminder.action.connect(lambda action, minutes: actions.append((action, minutes)))
    reminder.choose('snooze', 15)
    assert actions == [('snooze', 15)]
    window.timer.stop()
    window.tray.hide()
    window.hide()
    window.deleteLater()
    app.processEvents()
