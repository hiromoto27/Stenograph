from __future__ import annotations

import textwrap
from datetime import datetime, timezone

from PySide6.QtCore import QDateTime, QTime, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout,
    QGraphicsScene, QGraphicsView, QLabel, QLineEdit, QPlainTextEdit,
    QHBoxLayout, QVBoxLayout, QPushButton, QMessageBox, QListWidget,
)


STYLE = """
QWidget { background:#101724; color:#e6ecf7; font-family:'Segoe UI'; font-size:13px; }
QMainWindow, QDialog { background:#101724; }
QLabel#brand { font-size:24px; font-weight:700; color:#f5f7ff; padding:12px 4px; }
QLabel#heading { font-size:26px; font-weight:600; padding-bottom:6px; }
QLabel#muted { color:#96a8c0; }
QLabel#badge { color:#7be0ba; background:#193d37; border-radius:10px; padding:7px 12px; }
QPushButton { background:#26334b; border:1px solid #374662; border-radius:7px; padding:9px 14px; }
QPushButton:hover { background:#354561; }
QPushButton:disabled { color:#64748b; background:#1a2435; }
QPushButton#primary { background:#7264e9; border-color:#8c7bf2; color:white; font-weight:600; }
QPushButton#stop { background:#703749; border-color:#9f4f62; }
QLineEdit,QPlainTextEdit,QTextBrowser,QComboBox,QSpinBox,QDateTimeEdit {
 background:#182235; border:1px solid #34445f; border-radius:7px; padding:7px; selection-background-color:#665ad8; }
QComboBox QAbstractItemView { background:#1c2a40; selection-background-color:#665ad8; }
QListWidget { background:#111d2d; border:0; border-radius:8px; padding:6px; }
QListWidget::item { padding:13px 10px; border-radius:6px; }
QListWidget::item:selected { background:#30335c; color:#dfdcff; }
QTableWidget,QTreeWidget { background:#172235; alternate-background-color:#1b2940; border:1px solid #2d3c54; gridline-color:#2a3851; }
QHeaderView::section { background:#23314a; color:#a8b8d1; padding:9px; border:0; }
QTabWidget::pane { border:1px solid #2e3d57; border-radius:7px; }
QTabBar::tab { background:#172235; padding:12px 17px; color:#9baec8; }
QTabBar::tab:selected { color:#eeeaff; background:#33305b; }
QProgressBar { background:#243047; border:0; border-radius:3px; max-height:8px; }
QProgressBar::chunk { background:#71d8bd; border-radius:3px; }
QScrollBar:vertical { background:#152034; width:11px; }
QScrollBar::handle:vertical { background:#435571; border-radius:4px; min-height:30px; }
QGroupBox { border:1px solid #34445f; border-radius:8px; margin-top:15px; padding:14px; }
QGroupBox::title { subcontrol-origin:margin; padding:0 8px; color:#b8c8df; }
QToolTip { color:#142031; background:#ecf1f9; border:0; }
"""


class TaskDialog(QDialog):
    def __init__(self, parent, task=None):
        super().__init__(parent)
        self.setWindowTitle("Задача и напоминание")
        self.resize(660, 610)
        task = task or {}
        layout = QFormLayout(self)
        self.title = QLineEdit(task.get("title", ""))
        self.owner = QLineEdit(task.get("owner", ""))
        self.context = QPlainTextEdit(task.get("context", ""))
        self.context.setMaximumHeight(110)
        self.context.setPlaceholderText("О чём нужно вспомнить? Краткий контекст встречи или темы.")
        self.state = QComboBox()
        for name, code in [("Черновик", "draft"), ("В работе", "open"), ("Выполнена", "done"), ("Отклонена", "dismissed")]:
            self.state.addItem(name, code)
        self.state.setCurrentIndex(max(0, self.state.findData(task.get("state", "open"))))
        self.due_check, self.reminder_check = QCheckBox("Указать срок"), QCheckBox("Напомнить")
        self.due, self.reminder = QDateTimeEdit(), QDateTimeEdit()
        for box, edit, key in [(self.due_check, self.due, "due"), (self.reminder_check, self.reminder, "reminder")]:
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd.MM.yyyy HH:mm")
            edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
            if task.get(key):
                edit.setDateTime(QDateTime.fromString(task[key], Qt.DateFormat.ISODate).toLocalTime())
                box.setChecked(True)
            edit.setEnabled(box.isChecked())
            box.toggled.connect(edit.setEnabled)
        layout.addRow("Название", self.title)
        layout.addRow("Исполнитель", self.owner)
        layout.addRow("Краткое содержание", self.context)
        layout.addRow("Статус", self.state)
        layout.addRow(self.due_check, self.due)
        layout.addRow(self.reminder_check, self.reminder)
        presets = QHBoxLayout()
        for title, minutes in [("Через 15 минут", 15), ("Через час", 60), ("Завтра в 09:00", None), ("За 15 мин до срока", -15)]:
            btn = QPushButton(title)
            btn.clicked.connect(lambda checked=False, m=minutes: self.preset_reminder(m))
            presets.addWidget(btn)
        layout.addRow(presets)
        self.reminder_summary = QLabel()
        self.reminder_summary.setWordWrap(True)
        layout.addRow(self.reminder_summary)
        self.reminder.dateTimeChanged.connect(self.update_summary)
        self.reminder_check.toggled.connect(self.update_summary)
        self.state.currentIndexChanged.connect(self.update_summary)
        self.update_summary()

        note = QLabel("Время — в часовом поясе Windows. Уведомления приходят, пока приложение запущено, в том числе в трее.")
        note.setWordWrap(True)
        layout.addRow(note)
        if task.get("quote"):
            evidence = QLabel(f"Основание · #{task['source_id']}: {task['quote']}")
            evidence.setWordWrap(True)
            evidence.setTextFormat(Qt.TextFormat.PlainText)
            layout.addRow(evidence)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def preset_reminder(self, minutes):
        now = QDateTime.currentDateTime()
        if minutes is None:
            value = QDateTime(now.date().addDays(1), QTime(9, 0))
        elif minutes == -15:
            if not self.due_check.isChecked():
                QMessageBox.information(self, "Срок задачи", "Сначала включите срок и выберите дату выполнения.")
                return
            value = self.due.dateTime().addSecs(-900)
        else:
            value = now.addSecs(minutes * 60)
        self.reminder_check.setChecked(True)
        self.reminder.setDateTime(value)
        if self.state.currentData() == "draft":
            self.state.setCurrentIndex(self.state.findData("open"))

    def update_summary(self, *_):
        if not self.reminder_check.isChecked():
            text = "Напоминание выключено."
        elif self.state.currentData() != "open":
            text = "Для уведомления установите статус «В работе»."
        else:
            value = self.reminder.dateTime()
            text = "Напомнить: " + value.toString("dd.MM.yyyy в HH:mm") + " · местное время"
            if value <= QDateTime.currentDateTime():
                text += " · время прошло, уведомление появится сразу"
        self.reminder_summary.setText(text)

    def validate_and_accept(self):
        if not self.title.text().strip():
            QMessageBox.information(self, "Задача", "Введите название задачи.")
            return
        if self.reminder_check.isChecked() and self.state.currentData() == "draft":
            QMessageBox.information(self, "Напоминание", "Чтобы получать напоминания, выберите статус «В работе».")
            return
        self.accept()

    def values(self):
        def iso(edit):
            return datetime.fromtimestamp(edit.dateTime().toSecsSinceEpoch(), timezone.utc).isoformat(timespec="seconds")
        return dict(title=self.title.text().strip(), context=self.context.toPlainText(), owner=self.owner.text(),
                    state=self.state.currentData(), due=iso(self.due) if self.due_check.isChecked() else None,
                    reminder=iso(self.reminder) if self.reminder_check.isChecked() else None)


class MindMap(QGraphicsView):
    selected = Signal(int, int)
    edit_note = Signal(int)
    edit_link = Signal(int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#111b2a"))

    def node(self, x, y, text, color, data=None, width=240):
        label = self.scene().addText(textwrap.fill(text, max(22, width // 8)), QFont("Segoe UI", 11))
        label.setTextWidth(width - 24)
        label.setDefaultTextColor(QColor("#e9eef9"))
        height = max(58, label.boundingRect().height() + 22)
        rect = self.scene().addRect(x, y, width, height, QPen(QColor(color)), QBrush(QColor("#1e2c42")))
        rect.setZValue(-1)
        label.setPos(x + 12, y + 8)
        if data:
            rect.setData(0, data)
            label.setData(0, data)
            label.setToolTip("Двойной щелчок — исходная реплика")
        return (x, y, width, height)

    def edge(self, a, b, color):
        self.scene().addLine(a[0]+a[2], a[1]+a[3]/2, b[0], b[1]+b[3]/2, QPen(QColor(color), 1.5)).setZValue(-2)

    def load(self, groups):
        self.scene().clear()
        self.resetTransform()
        if not groups:
            self.node(0, 0, "После создания протокола здесь появятся разделы, темы и факты.", "#7465e8", width=420)
            return
        y = 0
        manual_nodes, links = {}, []
        for group in groups.values():
            group_node = self.node(0, y, group["name"], "#9b8afc", width=210)
            for topic in group["topics"].values():
                topic_node = self.node(285, y, topic["name"], "#6dace4")
                self.edge(group_node, topic_node, "#665bbb")
                topic_start = y
                for fact in topic["facts"]:
                    text = ("[Моя заметка] " if fact.get("manual") else "") + ("[Обновить протокол] " if fact.get("stale") else "") + fact["text"]
                    data = ("note", fact["note_id"]) if fact.get("manual") else (fact["meeting_id"], fact["source_id"])
                    fact_node = self.node(610, y, text, "#e2b56c" if fact.get("stale") else "#70cead",
                                          data, width=330)
                    self.edge(topic_node, fact_node, "#356d71")
                    if fact.get("manual"):
                        manual_nodes[fact['note_id']] = fact_node
                        links.extend(fact.get('links', []))
                    y += fact_node[3] + 18
                y = max(y, topic_start + topic_node[3] + 30)
            y = max(y, group_node[1] + group_node[3] + 40)
            y += 32
        for index, link in enumerate(links):
            a, b = manual_nodes[link['source_id']], manual_nodes[link['target_id']]
            ax, ay, bx, by = a[0]+a[2], a[1]+a[3]/2, b[0]+b[2], b[1]+b[3]/2
            lane = max(ax, bx) + 45 + index * 28
            path = QPainterPath()
            path.moveTo(ax, ay)
            path.lineTo(lane, ay)
            path.lineTo(lane, by)
            path.lineTo(bx, by)
            item = self.scene().addPath(path, QPen(QColor('#e2b56c'), 2))
            item.setData(0, ('link', link['id']))
            item.setToolTip(link['label'] + ' · двойной щелчок — изменить связь')
            self.scene().addLine(bx+9, by-5, bx, by, QPen(QColor('#e2b56c'), 2))
            self.scene().addLine(bx+9, by+5, bx, by, QPen(QColor('#e2b56c'), 2))
            caption = self.scene().addText(link['label'])
            caption.setDefaultTextColor(QColor('#e2b56c'))
            caption.setPos(lane+5, (ay+by)/2)
            caption.setData(0, ('link', link['id']))
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-30, -30, 30, 30))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scale = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            if 0.2 < self.transform().m11() * scale < 3:
                self.scale(scale, scale)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(0):
            data = item.data(0)
            if data[0] == "note":
                self.edit_note.emit(data[1])
            elif data[0] == "link":
                self.edit_link.emit(data[1])
            else:
                self.selected.emit(*data)
        super().mouseDoubleClickEvent(event)


class NoteDialog(QDialog):
    def __init__(self, parent, meetings, current_mid=None, note=None):
        super().__init__(parent)
        self.setWindowTitle("Элемент mind-карты")
        self.resize(610, 440)
        note = note or {}
        layout = QFormLayout(self)
        self.scope = QComboBox()
        self.scope.addItem("Общая база знаний", None)
        for meeting in meetings:
            self.scope.addItem(meeting["title"], meeting["id"])
        self.scope.setCurrentIndex(max(0, self.scope.findData(note.get("meeting_id", current_mid))))
        self.group = QLineEdit(note.get("group_name", "Мои знания"))
        self.topic = QLineEdit(note.get("topic_name", ""))
        self.body = QPlainTextEdit(note.get("body", ""))
        layout.addRow("Привязать к", self.scope)
        layout.addRow("Раздел", self.group)
        layout.addRow("Тема", self.topic)
        layout.addRow("Содержание", self.body)
        self.remove = False
        self.extend = False
        if note.get("id"):
            child = QPushButton("Достроить: добавить связанный элемент…")
            child.clicked.connect(self.extend_note)
            layout.addRow(child)
            delete = QPushButton("Удалить элемент…")
            delete.clicked.connect(self.delete_note)
            layout.addRow(delete)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.save_note)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def save_note(self):
        if not self.group.text().strip() or not self.topic.text().strip() or not self.body.toPlainText().strip():
            QMessageBox.information(self, "Элемент карты", "Заполните раздел, тему и содержание.")
            return
        self.accept()

    def extend_note(self):
        self.extend = True
        self.save_note()

    def delete_note(self):
        if QMessageBox.question(self, "Удалить элемент?", "Удалить эту ручную заметку из карты и поиска вместе с её связями? Другие заметки сохранятся.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.remove = True
            self.accept()


class ReminderDialog(QDialog):
    action = Signal(str, int)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Напоминание · СтеноГраф")
        self.resize(540, 280)
        layout = QVBoxLayout(self)
        title = QLabel(task["title"])
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setObjectName("heading")
        layout.addWidget(title)
        context = QLabel(task["context"] or "Откройте задачу, чтобы добавить краткое содержание.")
        context.setTextFormat(Qt.TextFormat.PlainText)
        context.setWordWrap(True)
        layout.addWidget(context)
        row = QHBoxLayout()
        for text, code, minutes in [("Через 15 мин", "snooze", 15), ("Через час", "snooze", 60),
                                    ("Выполнено", "done", 0), ("Понятно", "ack", 0)]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, c=code, m=minutes: self.choose(c, m))
            row.addWidget(btn)
        layout.addLayout(row)
        self.chosen = False

    def choose(self, code, minutes):
        self.chosen = True
        self.action.emit(code, minutes)
        self.accept()

    def reject(self):
        # Closing the window acknowledges this notification; task and deadline are retained.
        if not self.chosen:
            self.action.emit("ack", 0)
        super().reject()


class LinksDialog(QDialog):
    def __init__(self, parent, db, selected=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle('Связи между ручными элементами')
        self.resize(720, 540)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Направленная связь: от элемента → к элементу. Можно связывать разные темы и встречи.'))
        self.links = QListWidget()
        self.links.currentRowChanged.connect(self.select_link)
        layout.addWidget(self.links)
        form = QFormLayout()
        self.source, self.target = QComboBox(), QComboBox()
        for note in db.rows('SELECT * FROM map_notes ORDER BY id'):
            title = f"#{note['id']} · {note['topic_name']} · {note['body'][:65]}"
            self.source.addItem(title, note['id'])
            self.target.addItem(title, note['id'])
        self.caption = QLineEdit('дополняет')
        form.addRow('От элемента', self.source)
        form.addRow('К элементу', self.target)
        form.addRow('Подпись связи', self.caption)
        layout.addLayout(form)
        row = QHBoxLayout()
        for text, callback in [('Новая связь', self.new_link), ('Сохранить связь', self.save_link),
                               ('Удалить связь…', self.delete_link), ('Закрыть', self.accept)]:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            row.addWidget(btn)
        layout.addLayout(row)
        self.reload(selected)

    def reload(self, selected=None):
        self.links.clear()
        self.rows = self.db.rows('SELECT * FROM map_links ORDER BY id')
        for link in self.rows:
            self.links.addItem(f"#{link['source_id']} → #{link['target_id']} · {link['label']}")
        self.new_link()
        for index, link in enumerate(self.rows):
            if link['id'] == selected:
                self.links.setCurrentRow(index)

    def new_link(self):
        self.link_id = None
        self.links.setCurrentRow(-1)
        self.caption.setText('дополняет')
        if self.target.count() > 1:
            self.target.setCurrentIndex((self.source.currentIndex()+1) % self.target.count())

    def select_link(self, row):
        if row < 0:
            return
        link = self.rows[row]
        self.link_id = link['id']
        self.source.setCurrentIndex(self.source.findData(link['source_id']))
        self.target.setCurrentIndex(self.target.findData(link['target_id']))
        self.caption.setText(link['label'])

    def save_link(self):
        try:
            link_id = self.db.save_link(self.link_id, self.source.currentData(), self.target.currentData(), self.caption.text())
            self.reload(link_id)
        except ValueError as exc:
            QMessageBox.information(self, 'Связь', str(exc))

    def delete_link(self):
        if self.link_id and QMessageBox.question(self, 'Удалить связь?', 'Элементы останутся; удалить только связь?',
                                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.db.delete_link(self.link_id)
            self.reload()
