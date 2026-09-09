from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget, QStyle,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

from .audio import Capture, Transcriber, devices, recover_audio
from .config import Settings
from .db import Database, fingerprint
from .exports import guide_html, mindmap_data, report_html, standalone
from .hardware import catalogue, compatibility, detect, recommend
from .jobs import Analyze, BackgroundCall
from .widgets import MindMap, TaskDialog, NoteDialog, ReminderDialog, LinksDialog
from .maintenance import cleanup_audio


def button(text, callback, primary=False):
    value = QPushButton(text)
    if primary:
        value.setObjectName("primary")
    value.clicked.connect(callback)
    return value


def label(text, kind="", wrap=False):
    value = QLabel(text)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setObjectName(kind)
    value.setWordWrap(wrap)
    return value


def table(headers):
    value = QTableWidget(0, len(headers))
    value.setHorizontalHeaderLabels(headers)
    value.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    value.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    value.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    value.setAlternatingRowColors(True)
    value.verticalHeader().hide()
    value.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    value.horizontalHeader().setStretchLastSection(True)
    return value


def fill_table(widget, rows):
    widget.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            widget.setItem(r, c, QTableWidgetItem(str(text or "")))
    widget.resizeRowsToContents()


def clock(seconds):
    value = int(seconds)
    return f"{value//3600:02}:{value//60%60:02}:{value%60:02}"


class MainWindow(QMainWindow):
    def __init__(self, root, scan_hardware=True):
        super().__init__()
        self.root = Path(root)
        self.db = Database(self.root / "knowledge.sqlite3")
        self.settings = Settings.load(self.root)
        self.mid = None
        self.captures = []
        self.transcriber = None
        self.analysis = None
        self.record_epoch = None
        self.quitting = False
        self.reminder_dialog = None
        self.maintenance_ticks = 0
        self.setWindowTitle("СтеноГраф · локальное рабочее пространство")
        self.resize(1380, 880)
        self.setMinimumSize(1050, 700)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))

        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QHBoxLayout(outer)
        layout.setContentsMargins(16, 12, 16, 12)
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.addWidget(label("СтеноГраф", "brand"))
        side.addWidget(label("Разговор → знания → действия", "muted", True))
        self.nav = QListWidget()
        self.nav.addItems(["Встречи", "Задачи", "База знаний", "Mind-карта", "Модели и компьютер", "Словарь", "Обновления и помощь"])
        side.addWidget(self.nav)
        side.addWidget(label("●  Всё на компьютере", "badge"))
        side.addWidget(label("0.2 · локальное пространство", "muted"))
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.make_meetings()
        self.make_tasks()
        self.make_search()
        self.make_map()
        self.make_settings()
        self.make_terms()
        self.make_updates()
        self.nav.currentRowChanged.connect(self.change_page)
        self.nav.setCurrentRow(0)
        self.make_tray()
        self.refresh_meetings()
        self.refresh_tasks()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        count, errors = recover_audio(self.db, root)
        if count or errors:
            self.statusBar().showMessage(f"Восстановлено фрагментов: {count}. Ошибок: {len(errors)}")
        if scan_hardware:
            QTimer.singleShot(50, self.scan_pc)
        QTimer.singleShot(100, self.refresh_devices)

    def page(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        layout.addWidget(label(title, "heading"))
        layout.addWidget(label(subtitle, "muted", True))
        self.pages.addWidget(page)
        return layout

    def make_meetings(self):
        layout = self.page("Встречи", "Записывайте разговор, сохраняйте решения и возвращайтесь к источнику.")
        split = QSplitter()
        layout.addWidget(split, 1)
        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 8, 0)
        column.addWidget(button("+ Новая встреча", self.new_meeting, True))
        self.meeting_list = QListWidget()
        self.meeting_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.meeting_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.meeting_list.currentItemChanged.connect(self.select_meeting)
        column.addWidget(self.meeting_list)
        column.addWidget(button("Импорт текста", self.import_text))
        column.addWidget(button("Импорт WAV", self.import_wav))
        split.addWidget(left)
        right = QWidget()
        pane = QVBoxLayout(right)
        pane.setContentsMargins(6, 0, 0, 0)
        self.meeting_title = label("Выберите встречу или создайте новую", "heading", True)
        pane.addWidget(self.meeting_title)
        inputs = QGroupBox("Источники звука")
        form = QFormLayout(inputs)
        self.mic, self.system = QComboBox(), QComboBox()
        self.mic_level, self.system_level = QProgressBar(), QProgressBar()
        for bar in (self.mic_level, self.system_level):
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
        form.addRow("Микрофон", self.mic)
        form.addRow("Уровень микрофона", self.mic_level)
        form.addRow("Звук встречи", self.system)
        form.addRow("Уровень системы", self.system_level)
        form.addRow(button("Обновить устройства", self.refresh_devices))
        pane.addWidget(inputs)
        self.record_controls = inputs
        actions = QHBoxLayout()
        self.record_button = button("● Записать", self.start_recording, True)
        self.stop_button = button("■ Стоп", self.stop_recording)
        self.stop_button.setObjectName("stop")
        self.stop_button.setEnabled(False)
        self.elapsed = label("00:00:00", "muted")
        actions.addWidget(self.record_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(button("Распознать очередь", self.start_transcriber))
        actions.addWidget(self.elapsed)
        pane.addLayout(actions)
        self.queue_label = label("Готово к записи", "muted", True)
        pane.addWidget(self.queue_label)
        self.tabs = QTabWidget()
        self.transcript = table(["ID", "Время", "Источник", "Текст"])
        self.transcript.setColumnHidden(0, True)
        self.transcript.setWordWrap(True)
        self.transcript.cellDoubleClicked.connect(self.edit_segment)
        self.tabs.addTab(self.transcript, "Расшифровка")
        self.protocol = QTextBrowser()
        self.protocol.setOpenExternalLinks(False)
        self.tabs.addTab(self.protocol, "Протокол")
        guides = QWidget()
        guide_layout = QVBoxLayout(guides)
        row = QHBoxLayout()
        self.screen_select = QComboBox()
        for i, screen in enumerate(QApplication.screens()):
            self.screen_select.addItem(f"Экран {i+1} · {screen.name()}", i)
        row.addWidget(self.screen_select)
        row.addWidget(button("Скриншот через 3 сек", self.capture_shot))
        row.addWidget(button("Добавить изображение", self.import_shot))
        guide_layout.addLayout(row)
        guide_layout.addWidget(label("Снимки добавляются с подписью шага. Двойной щелчок открывает изображение.", "muted", True))
        self.shots = table(["Шаг / подпись", "Время"])
        self.shots.cellDoubleClicked.connect(self.open_shot)
        guide_layout.addWidget(self.shots)
        guide_layout.addWidget(button("Экспорт инструкции со скриншотами", self.export_guide))
        self.tabs.addTab(guides, "Инструкция")
        pane.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.analyze_button = button("Создать протокол и задачи", self.analyze, True)
        footer.addWidget(self.analyze_button)
        footer.addWidget(button("Экспорт HTML", self.export_report))
        footer.addWidget(button("Открыть аудио", self.open_audio))
        pane.addLayout(footer)
        split.addWidget(right)
        split.setSizes([230, 850])

    def make_tasks(self):
        layout = self.page("Задачи", "Проверьте предложения из диалога, назначьте срок и включите напоминание.")
        row = QHBoxLayout()
        row.addWidget(button("+ Создать задачу", lambda: self.edit_task(), True))
        row.addWidget(button("Редактировать", self.edit_selected_task))
        row.addWidget(button("Удалить…", self.delete_selected_task))
        self.task_filter = QComboBox()
        for text, state in [("Все задачи", ""), ("В работе", "open"), ("Черновики", "draft"), ("Выполненные", "done")]:
            self.task_filter.addItem(text, state)
        self.task_filter.currentIndexChanged.connect(self.refresh_tasks)
        row.addWidget(self.task_filter)
        row.addStretch()
        layout.addLayout(row)
        self.tasks = table(["ID", "Статус", "Задача", "Исполнитель", "Срок", "Напомнить", "Контекст"])
        self.tasks.setColumnHidden(0, True)
        self.tasks.cellDoubleClicked.connect(lambda *_: self.edit_selected_task())
        layout.addWidget(self.tasks)
        layout.addWidget(label("Напоминания работают при запущенном приложении. Пропущенные во время выключения будут показаны после запуска.", "muted", True))

    def make_search(self):
        layout = self.page("База знаний", "Локальный поиск по расшифровкам, протоколам, задачам, темам и подписям скриншотов.")
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Слово, фраза или тема…")
        self.query.returnPressed.connect(self.search)
        self.phrase = QCheckBox("Точная фраза")
        row.addWidget(self.query, 1)
        row.addWidget(self.phrase)
        row.addWidget(button("Найти", self.search, True))
        layout.addLayout(row)
        self.search_results = table(["Тип", "Название", "Фрагмент"])
        self.search_results.cellDoubleClicked.connect(self.open_search)
        layout.addWidget(self.search_results)
        self.search_items = []

    def make_map(self):
        layout = self.page("Карта знаний", "Раздел → тема → факт. Ctrl + колесо — масштаб; двойной щелчок по факту — источник.")
        row = QHBoxLayout()
        self.map_all = QCheckBox("Все встречи")
        self.map_all.setChecked(True)
        self.map_all.toggled.connect(self.refresh_map)
        row.addWidget(self.map_all)
        row.addWidget(button("+ Добавить элемент", self.add_map_note, True))
        row.addWidget(button("Связи…", self.edit_map_links))
        row.addStretch()
        row.addWidget(button("Обновить", self.refresh_map))
        row.addWidget(button("Экспорт JSON", self.export_map))
        layout.addLayout(row)
        self.map = MindMap()
        self.map.selected.connect(self.go_source)
        self.map.edit_note.connect(self.edit_map_note)
        self.map.edit_link.connect(self.edit_map_links)
        layout.addWidget(self.map)

    def make_settings(self):
        layout = self.page("Модели и компьютер", "Подбор локальных компонентов. Оценки памяти предварительные; скорость проверяется на записи.")
        settings = QGroupBox("Распознавание и анализ")
        form = QFormLayout(settings)
        model_row = QHBoxLayout()
        self.model_path = QLineEdit(self.settings.model_path)
        model_row.addWidget(self.model_path)
        model_row.addWidget(button("Папка…", self.choose_model))
        form.addRow("Модель речи", model_row)
        self.device = QComboBox()
        self.device.addItems(["cpu", "cuda"])
        self.device.setCurrentText(self.settings.device)
        self.llm = QComboBox()
        self.llm.addItems(["qwen3:1.7b", "qwen3:4b", "qwen3:8b"])
        self.llm.setCurrentText(self.settings.llm_model)
        self.threads = QSpinBox()
        self.threads.setRange(1, 32)
        self.threads.setValue(self.settings.cpu_threads)
        self.chunk = QSpinBox()
        self.chunk.setRange(3, 30)
        self.chunk.setSuffix(" сек")
        self.chunk.setValue(self.settings.chunk_seconds)
        self.language = QComboBox()
        for text, code in [("Русский", "ru"), ("English", "en"), ("Автоопределение", "")]:
            self.language.addItem(text, code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.settings.language)))
        form.addRow("Устройство", self.device)
        self.backend = QComboBox()
        self.backend.addItem("Ollama — отдельная локальная программа", "ollama")
        self.backend.addItem("Встроенная модель — без Ollama", "embedded")
        self.backend.setCurrentIndex(max(0, self.backend.findData(self.settings.llm_backend)))
        form.addRow("Где создавать протокол", self.backend)
        form.addRow("Модель Ollama", self.llm)
        gguf_row = QHBoxLayout()
        self.gguf = QLineEdit(self.settings.gguf_path)
        self.gguf.setPlaceholderText("Файл Qwen2.5 Instruct .gguf для встроенного режима")
        gguf_row.addWidget(self.gguf)
        gguf_row.addWidget(button("Файл…", self.choose_gguf))
        form.addRow("Встроенная модель", gguf_row)
        self.backend.currentIndexChanged.connect(self.backend_changed)
        self.backend_changed()
        form.addRow("Потоки CPU", self.threads)
        form.addRow("Фрагмент речи", self.chunk)
        form.addRow("Язык речи", self.language)
        actions = QHBoxLayout()
        actions.addWidget(button("Сохранить настройки", self.save_settings, True))
        actions.addWidget(button("Определить ПК", self.scan_pc))
        actions.addWidget(button("Применить рекомендацию", self.apply_recommendation))
        form.addRow(actions)
        layout.addWidget(settings)
        self.pc_info = label("Характеристики появятся после проверки компьютера.", "muted", True)
        layout.addWidget(self.pc_info)
        self.catalog = table(["Компонент", "Назначение", "Статус", "Этот компьютер"])
        self.catalog.cellClicked.connect(self.show_catalog_item)
        layout.addWidget(self.catalog, 1)
        self.catalog_info = QTextBrowser()
        self.catalog_info.setMaximumHeight(155)
        self.catalog_info.setOpenExternalLinks(True)
        layout.addWidget(self.catalog_info)
        self.hw = None
        self.items = catalogue()
        fill_table(self.catalog, [(x["name"], x["kind"], x["status"], "Нужна проверка ПК") for x in self.items])

    def make_terms(self):
        layout = self.page("Словарь и исправления", "Сохраняйте имена, аббревиатуры и термины. Словарь учитывается в следующих расшифровках.")
        row = QHBoxLayout()
        row.addWidget(button("+ Правило исправления", self.add_term, True))
        row.addWidget(button("Удалить правило", self.delete_term))
        row.addStretch()
        layout.addLayout(row)
        self.terms = table(["Распознано как", "Правильное написание"])
        layout.addWidget(self.terms)
        layout.addWidget(label("Правьте реплики двойным щелчком в расшифровке. История исправлений сохраняется. Правила добавляются явно; веса модели автоматически не меняются.", "muted", True))

    def make_updates(self):
        from . import __version__
        layout = self.page("Обновления и помощь", f"Установлена версия {__version__}. Интернет нужен только для проверки и загрузки обновления.")
        self.release = None
        self.update_job = None
        self.ollama_job = None
        self.repository = QLineEdit(self.settings.update_repository)
        self.update_branch = QLineEdit(self.settings.update_branch)
        form = QFormLayout()
        form.addRow("Репозиторий GitHub", self.repository)
        form.addRow("Ветка", self.update_branch)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.check_update_button = button("Проверить обновления", self.check_updates)
        self.apply_update_button = button("Установить обновление…", self.apply_update, True)
        self.apply_update_button.setEnabled(False)
        row.addWidget(self.check_update_button)
        row.addWidget(self.apply_update_button)
        layout.addLayout(row)
        self.update_status = label("Перед обновлением завершите запись и создание протокола. Данные и модели хранятся отдельно.", wrap=True)
        layout.addWidget(self.update_status)
        self.ollama_button = button("Проверить подключение к Ollama", self.check_ollama)
        layout.addWidget(self.ollama_button)
        self.ollama_status = label("", wrap=True)
        layout.addWidget(self.ollama_status)
        help_view = QTextBrowser()
        help_view.setOpenExternalLinks(True)
        help_view.setHtml((Path(__file__).parent / "resources/help.html").read_text(encoding="utf-8"))
        layout.addWidget(help_view, 1)

    def check_ollama(self):
        from .intelligence import LocalLLM
        model = self.llm.currentText()
        self.ollama_button.setEnabled(False)
        self.ollama_status.setText("Проверяю локальный сервер и выбранную модель…")
        self.ollama_job = BackgroundCall(lambda: LocalLLM(model).check(), self)
        self.ollama_job.completed.connect(lambda _: self.ollama_status.setText("Ollama доступен; модель найдена: " + model))
        self.ollama_job.error.connect(self.ollama_status.setText)
        self.ollama_job.finished.connect(lambda: self.ollama_button.setEnabled(True))
        self.ollama_job.start()

    def check_updates(self):
        from .updates import check_release, repo_slug
        try:
            repo_slug(self.repository.text().strip())
            self.settings.update_repository = self.repository.text().strip()
            self.settings.update_branch = self.update_branch.text().strip()
            self.settings.save(self.root)
        except Exception as exc:
            self.error(str(exc))
            return
        self.release = None
        self.apply_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.update_status.setText("Проверяю выпуск в GitHub…")
        repository, branch, subdir = self.settings.update_repository, self.settings.update_branch, self.settings.update_subdir
        self.update_job = BackgroundCall(lambda: check_release(repository, branch, subdir), self)
        self.update_job.completed.connect(self.update_checked)
        self.update_job.error.connect(lambda message: self.update_status.setText("Проверка не завершена: " + message))
        self.update_job.finished.connect(lambda: self.check_update_button.setEnabled(True))
        self.update_job.start()

    def update_checked(self, release):
        from . import __version__
        self.release = release
        version = release['manifest']['version']
        newer = tuple(map(int, version.split('.'))) > tuple(map(int, __version__.split('.')))
        self.update_status.setText(f"Версия в репозитории: {version}. " + ("Можно установить." if newer else "Новая версия не требуется."))
        self.apply_update_button.setEnabled(newer and not getattr(sys, 'frozen', False) and os.name == 'nt')

    def apply_update(self):
        if not self.release:
            return
        workers = self.captures + [x for x in (self.transcriber, self.analysis) if x]
        if any(w.isRunning() for w in workers):
            self.info("Остановите запись и дождитесь завершения распознавания и протокола.")
            return
        version = self.release['manifest']['version']
        if QMessageBox.question(self, "Обновить СтеноГраф?", f"Установить {version} из {self.release['repository']}?\nПриложение закроется. Обновление скачает исходники и зависимости; предыдущие исходники сохранятся для отката.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            root = Path(__file__).resolve().parent.parent
            helper = root / "scripts/update.py"
            subprocess.Popen([str(Path(sys._base_executable).with_name("python.exe")), str(helper), "--sha", self.release['sha'], "--pause"], cwd=root, creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as exc:
            self.error(str(exc))
            return
        self.quit_app()

    def make_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("СтеноГраф")
        menu = QMenu()
        show = QAction("Открыть", self)
        show.triggered.connect(self.showNormal)
        quit_action = QAction("Завершить", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        if index == 1:
            self.refresh_tasks()
        elif index == 3:
            self.refresh_map()
        elif index == 5:
            self.refresh_terms()

    def info(self, message):
        QMessageBox.information(self, "СтеноГраф", message)

    def error(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Нужна проверка", message)

    def require_meeting(self):
        if self.mid is None:
            self.info("Создайте или выберите встречу.")
            return False
        return True

    def new_meeting(self):
        if any(c.isRunning() for c in self.captures):
            return self.info("Остановите запись перед созданием другой встречи.")
        title, ok = QInputDialog.getText(self, "Новая встреча", "Название:", text="Встреча " + datetime.now().strftime("%d.%m %H:%M"))
        if ok and title.strip():
            self.mid = self.db.new_meeting(title)
            self.refresh_meetings()

    def refresh_meetings(self):
        self.meeting_list.blockSignals(True)
        self.meeting_list.clear()
        for row in self.db.meetings():
            item = QListWidgetItem(row["title"] + "\n" + row["created"][:10])
            item.setToolTip(row["title"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.meeting_list.addItem(item)
            if row["id"] == self.mid:
                self.meeting_list.setCurrentItem(item)
        self.meeting_list.blockSignals(False)
        if self.mid:
            self.refresh_current()

    def select_meeting(self, current, previous=None):
        if current:
            self.mid = current.data(Qt.ItemDataRole.UserRole)
            self.refresh_current()

    def refresh_current(self):
        if self.mid is None:
            return
        meeting = self.db.rows("SELECT * FROM meetings WHERE id=?", (self.mid,))[0]
        self.meeting_title.setText(meeting["title"])
        segments = self.db.segments(self.mid)
        fill_table(self.transcript, [(s["id"], "—" if s["source"] == "Импорт текста" else clock(s["start"]), s["source"], s["text"]) for s in segments])
        self.transcript.scrollToBottom()
        report = self.db.latest_report(self.mid)
        if report:
            stale = report["fingerprint"] != fingerprint(segments)
            banner = "<p><b>Расшифровка изменилась. Создайте протокол повторно.</b></p>" if stale else ""
            self.protocol.setHtml(banner + report_html(meeting["title"], report["body"]))
        else:
            self.protocol.setPlainText("После распознавания нажмите «Создать протокол и задачи». Для анализа подготовьте модель Ollama или выберите встроенный режим в настройках.")
        expiry = self.db.rows("SELECT MIN(delete_after) AS next FROM chunks WHERE meeting_id=? AND purged_at IS NULL AND delete_after IS NOT NULL", (self.mid,))[0]["next"]
        if expiry:
            cleanup_time = datetime.fromisoformat(expiry).astimezone().strftime("%d.%m %H:%M")
            self.protocol.append("<p>Исходное аудио будет удалено после " + cleanup_time + ". Расшифровка сохранится.</p>")
        self.shot_rows = self.db.rows("SELECT * FROM shots WHERE meeting_id=? ORDER BY id", (self.mid,))
        fill_table(self.shots, [(s["caption"], clock(s["at_seconds"])) for s in self.shot_rows])

    def refresh_devices(self):
        if any(c.isRunning() for c in self.captures):
            return
        try:
            found = devices()
            for box in (self.mic, self.system):
                box.clear()
                box.addItem("Не записывать", None)
            for item in found:
                target = self.system if item["loopback"] else self.mic
                target.addItem(f"{item['name']} · {item['api']}", item["index"])
            for box, preferred in [(self.mic, self.settings.mic_name), (self.system, self.settings.loopback_name)]:
                index = box.findText(preferred)
                box.setCurrentIndex(index if index >= 0 else (1 if box is self.mic and box.count() > 1 else 0))
            if not found:
                self.queue_label.setText("Запись доступна на Windows. Здесь можно работать с импортом текста и WAV.")
        except Exception as exc:
            self.error(f"Не удалось получить устройства: {exc}")

    def start_recording(self):
        if not self.require_meeting():
            return
        selected = [("Микрофон", self.mic.currentData()), ("Система", self.system.currentData())]
        if all(index is None for _, index in selected):
            return self.info("Выберите хотя бы один источник звука.")
        if self.analysis and self.analysis.isRunning():
            return self.info("Дождитесь завершения анализа.")
        if not self.save_settings(silent=True):
            return
        offsets = self.db.rows("SELECT MAX(offset+duration) AS last FROM chunks WHERE meeting_id=?", (self.mid,))
        self.record_epoch = time.monotonic() - (offsets[0]["last"] or 0)
        self.captures = []
        for source, index in selected:
            if index is not None:
                worker = Capture(self.db, self.root, self.mid, source, index, self.settings.chunk_seconds, self.record_epoch)
                worker.level.connect(self.set_level)
                worker.error.connect(self.capture_error)
                worker.finished.connect(self.capture_finished)
                self.captures.append(worker)
                worker.start()
        self.record_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.record_controls.setEnabled(False)
        self.meeting_list.setEnabled(False)
        self.analyze_button.setEnabled(False)
        if self.settings.model_path:
            self.start_transcriber()
        else:
            self.queue_label.setText("Идёт запись без расшифровки. Подключите модель в разделе «Модели и компьютер».")

    def set_level(self, source, value):
        (self.mic_level if source == "Микрофон" else self.system_level).setValue(value)

    def capture_error(self, message):
        self.stop_recording()
        self.error(message)

    def stop_recording(self):
        for capture in self.captures:
            capture.stop()
        self.stop_button.setEnabled(False)
        self.queue_label.setText("Завершаю запись и сохраняю последние фрагменты…")

    def capture_finished(self):
        if any(c.isRunning() for c in self.captures):
            return
        self.record_epoch = None
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.record_controls.setEnabled(True)
        self.meeting_list.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.queue_label.setText("Запись сохранена. Ожидайте завершения очереди распознавания.")

    def start_transcriber(self):
        if self.analysis and self.analysis.isRunning():
            return self.info("Дождитесь завершения анализа.")
        if self.transcriber and self.transcriber.isRunning():
            if self.transcriber.stop_event.is_set():
                QTimer.singleShot(400, self.start_transcriber)
            return
        if not self.settings.model_path:
            return self.info("Укажите локальную модель в разделе «Модели и компьютер».")
        self.db.execute("UPDATE chunks SET state='pending',error='' WHERE state='error'")
        self.transcriber = Transcriber(self.db, Settings(**vars(self.settings)))
        self.transcriber.changed.connect(lambda mid: self.refresh_current() if mid == self.mid else None)
        self.transcriber.status.connect(self.queue_label.setText)
        self.transcriber.error.connect(self.error)
        self.transcriber.start()

    def analyze(self):
        if not self.require_meeting():
            return
        if any(c.isRunning() for c in self.captures):
            return self.info("Остановите запись перед составлением протокола.")
        pending = self.db.rows("SELECT COUNT(*) AS n FROM chunks WHERE meeting_id=? AND state!='done'", (self.mid,))[0]["n"]
        if pending:
            return self.info(f"Осталось нераспознанных фрагментов: {pending}. Сначала обработайте очередь.")
        if self.transcriber and self.transcriber.isRunning():
            self.transcriber.stop()
            self.queue_label.setText("Освобождаю модель речи перед анализом…")
            QTimer.singleShot(400, self.analyze)
            return
        if self.analysis and self.analysis.isRunning():
            return
        self.analysis = Analyze(self.db, self.mid, self.settings.llm_model, self.settings.llm_backend,
                                self.settings.gguf_path, self.settings.cpu_threads)
        self.analysis.progress.connect(self.queue_label.setText)
        self.analysis.error.connect(self.error)
        self.analysis.completed.connect(self.analysis_done)
        self.analysis.finished.connect(lambda: self.analyze_button.setEnabled(True))
        self.analyze_button.setEnabled(False)
        self.analysis.start()

    def analysis_done(self, mid):
        if self.mid == mid:
            self.refresh_current()
            self.tabs.setCurrentIndex(1)
        self.refresh_tasks()
        self.queue_label.setText("Протокол и черновики задач готовы. Проверьте выводы по цитатам.")

    def edit_segment(self, row, col):
        sid = int(self.transcript.item(row, 0).text())
        old = self.transcript.item(row, 3).text()
        value, ok = QInputDialog.getMultiLineText(self, "Исправить расшифровку", "Текст реплики:", old)
        if ok and value.strip() and value != old:
            self.db.correct_segment(sid, value)
            self.refresh_current()

    def import_text(self):
        if any(c.isRunning() for c in self.captures):
            return self.info("Остановите запись перед импортом.")
        if not self.require_meeting():
            return
        text, ok = QInputDialog.getMultiLineText(self, "Импорт диалога", "Вставьте текст. Новая строка — новая реплика:")
        if ok and text.strip():
            self.db.add_text(self.mid, text)
            self.refresh_current()

    def import_wav(self):
        if any(c.isRunning() for c in self.captures):
            return self.info("Остановите запись перед импортом.")
        if not self.require_meeting():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Импорт аудио", "", "PCM WAV (*.wav)")
        if not name:
            return
        try:
            # Split on disk instead of loading a whole meeting into memory.
            folder = self.root / "audio" / str(self.mid)
            folder.mkdir(parents=True, exist_ok=True)
            base = self.db.rows("SELECT MAX(offset+duration) AS last FROM chunks WHERE meeting_id=?", (self.mid,))[0]["last"] or 0
            with wave.open(name) as audio:
                if audio.getsampwidth() != 2 or audio.getcomptype() != "NONE":
                    raise ValueError("Нужен несжатый 16-bit PCM WAV.")
                rate, channels = audio.getframerate(), audio.getnchannels()
                offset = 0
                while True:
                    raw = audio.readframes(rate * self.settings.chunk_seconds)
                    if not raw:
                        break
                    path = folder / f"{uuid.uuid4().hex}.wav"
                    with wave.open(str(path), "wb") as out:
                        out.setnchannels(channels)
                        out.setsampwidth(2)
                        out.setframerate(rate)
                        out.writeframes(raw)
                    duration = len(raw) / (2 * channels * rate)
                    self.db.add_chunk(self.mid, "Импорт WAV", path, base + offset, duration)
                    offset += duration
            self.queue_label.setText("Аудио импортировано. Нажмите «Распознать очередь».")
        except Exception as exc:
            self.error(str(exc))

    def refresh_tasks(self, *_):
        self.task_rows = self.db.rows("SELECT * FROM tasks ORDER BY CASE state WHEN 'open' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,due,id DESC")
        if self.task_filter.currentData():
            self.task_rows = [t for t in self.task_rows if t["state"] == self.task_filter.currentData()]
        names = {"draft": "Черновик", "open": "В работе", "done": "Выполнена", "dismissed": "Отклонена"}
        def date(value):
            return datetime.fromisoformat(value).astimezone().strftime("%d.%m %H:%M") if value else "—"
        fill_table(self.tasks, [(t["id"], names[t["state"]], t["title"], t["owner"], date(t["due"]), date(t["reminder"]) + (" · показано" if t["notified"] else ""), t["context"]) for t in self.task_rows])

    def edit_selected_task(self):
        row = self.tasks.currentRow()
        if row >= 0:
            self.edit_task(self.task_rows[row])

    def edit_task(self, task=None):
        dialog = TaskDialog(self, task)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.save_task(task["id"] if task else None, task["meeting_id"] if task else self.mid, **dialog.values())
                self.refresh_tasks()
            except ValueError as exc:
                self.error(str(exc))

    def delete_selected_task(self):
        row = self.tasks.currentRow()
        if row < 0:
            return self.info("Выберите задачу в списке.")
        task = self.task_rows[row]
        question = QMessageBox(self)
        question.setWindowTitle("Удалить задачу?")
        question.setTextFormat(Qt.TextFormat.PlainText)
        question.setText("Удалить задачу «" + task["title"] + "» и её напоминание?")
        question.setInformativeText("Протокол и исходная расшифровка сохранятся.")
        question.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        question.setDefaultButton(QMessageBox.StandardButton.No)
        if question.exec() == QMessageBox.StandardButton.Yes:
            self.db.delete_task(task["id"])
            if self.reminder_dialog and getattr(self.reminder_dialog, "task_id", None) == task["id"]:
                self.reminder_dialog.reject()
            self.refresh_tasks()

    def add_map_note(self):
        self.edit_map_note(None)

    def edit_map_links(self, selected=None):
        LinksDialog(self, self.db, selected).exec()
        self.refresh_map()

    def edit_map_note(self, note_id=None, parent_note=None):
        rows = self.db.rows("SELECT * FROM map_notes WHERE id=?", (note_id,)) if note_id else []
        if note_id and not rows:
            return
        dialog = NoteDialog(self, self.db.meetings(), None if self.map_all.isChecked() else self.mid,
                            rows[0] if rows else ({**parent_note, 'id': None, 'body': ''} if parent_note else None))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.remove:
                self.db.delete_note(note_id)
            else:
                saved_id = self.db.save_note(note_id, dialog.scope.currentData(), dialog.group.text(),
                                            dialog.topic.text(), dialog.body.toPlainText())
                if parent_note:
                    self.db.save_link(None, parent_note['id'], saved_id, 'раскрывает тему')
                if dialog.extend:
                    self.edit_map_note(parent_note=self.db.rows("SELECT * FROM map_notes WHERE id=?", (saved_id,))[0])
            self.refresh_map()

    def search(self):
        self.search_items = self.db.search(self.query.text(), self.phrase.isChecked())
        fill_table(self.search_results, [(s["kind"], s["title"], s["body"][:450]) for s in self.search_items])

    def open_search(self, row, col):
        item = self.search_items[row]
        if item["kind"] == "note":
            self.nav.setCurrentRow(3)
            self.edit_map_note(item["ref_id"])
            return
        if item["meeting_id"]:
            self.go_source(item["meeting_id"], item["ref_id"] if item["kind"] == "segment" else 0)
            if item["kind"] == "report":
                self.tabs.setCurrentIndex(1)
            elif item["kind"] == "shot":
                self.tabs.setCurrentIndex(2)
        elif item["kind"] == "task":
            self.nav.setCurrentRow(1)

    def go_source(self, mid, sid):
        if any(c.isRunning() for c in self.captures):
            return self.info("Сначала остановите текущую запись.")
        self.mid = mid
        self.refresh_meetings()
        self.nav.setCurrentRow(0)
        self.tabs.setCurrentIndex(0)
        for row in range(self.transcript.rowCount()):
            if int(self.transcript.item(row, 0).text()) == sid:
                self.transcript.selectRow(row)
                self.transcript.scrollToItem(self.transcript.item(row, 3))
                break

    def refresh_map(self, *_):
        self.map.load(mindmap_data(self.db, None if self.map_all.isChecked() else self.mid))

    def export_map(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт карты", "mindmap.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(mindmap_data(self.db, None if self.map_all.isChecked() else self.mid), ensure_ascii=False, indent=2), encoding="utf-8")

    def backend_changed(self, *_):
        embedded = self.backend.currentData() == "embedded"
        self.llm.setEnabled(not embedded)
        self.gguf.setEnabled(embedded)

    def choose_gguf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Qwen2.5 Instruct GGUF", "", "GGUF (*.gguf)")
        if path:
            self.gguf.setText(path)
            self.backend.setCurrentIndex(self.backend.findData("embedded"))

    def choose_model(self):
        path = QFileDialog.getExistingDirectory(self, "Папка модели faster-whisper")
        if path:
            self.model_path.setText(path)

    def save_settings(self, checked=False, silent=False):
        if any(c.isRunning() for c in self.captures):
            if not silent:
                self.info("Остановите запись перед изменением настроек.")
            return False
        if self.transcriber and self.transcriber.isRunning():
            # Use the current recognizer until stopped; a restart picks up new settings.
            self.transcriber.stop()
        self.settings.model_path = self.model_path.text().strip()
        self.settings.device = self.device.currentText()
        self.settings.compute_type = "int8_float16" if self.settings.device == "cuda" else "int8"
        self.settings.llm_model = self.llm.currentText()
        self.settings.llm_backend = self.backend.currentData()
        self.settings.gguf_path = self.gguf.text().strip()
        self.settings.language = self.language.currentData()
        self.settings.cpu_threads = self.threads.value()
        self.settings.chunk_seconds = self.chunk.value()
        self.settings.mic_name = self.mic.currentText()
        self.settings.loopback_name = self.system.currentText()
        self.settings.save(self.root)
        if not silent:
            self.info("Настройки сохранены. Для обработки нажмите «Распознать очередь» после остановки предыдущего распознавания.")
        return True

    def scan_pc(self):
        self.hw = detect(self.root)
        advice = recommend(self.hw)
        self.pc_info.setText(f"{self.hw.cpu} • {self.hw.threads} потоков • RAM {self.hw.ram_gb} ГБ (свободно {self.hw.available_gb})\n"
                             f"GPU: {self.hw.gpu} • VRAM {self.hw.vram_gb} ГБ • диск: {self.hw.disk_free_gb} ГБ свободно\n"
                             f"Стартовый профиль: Whisper {advice['stt']} + {advice['llm']}. {advice['note']}")
        fill_table(self.catalog, [(x["name"], x["kind"], x["status"], compatibility(x, self.hw)) for x in self.items])

    def apply_recommendation(self):
        if self.hw is None:
            self.scan_pc()
        advice = recommend(self.hw)
        self.device.setCurrentText(advice["device"])
        self.llm.setCurrentText(advice["llm"])
        self.threads.setValue(advice["cpu_threads"])
        self.chunk.setValue(advice["chunk_seconds"])
        self.save_settings()

    def show_catalog_item(self, row, col):
        import html
        item = self.items[row]
        url = f'<a href="{html.escape(item["url"], quote=True)}">Официальный источник</a>' if item["url"] else "Скрипт в исходниках приложения"
        self.catalog_info.setHtml(f'<b>{html.escape(item["name"])}</b> · {html.escape(item["license"])}<p>{html.escape(item["description"])}</p>'
                                 f'<p>Ориентир: RAM {item["ram_gb"]} ГБ, свободная RAM {item["working_gb"]} ГБ, диск {item["disk_gb"]} ГБ.</p>'
                                 f'<code>{html.escape(item["action"])}</code><p>{url} · Загрузка требует интернета, запускается отдельно.</p>')

    def refresh_terms(self):
        self.term_rows = self.db.rows("SELECT * FROM terms ORDER BY wrong")
        fill_table(self.terms, [(t["wrong"], t["correct"]) for t in self.term_rows])

    def add_term(self):
        wrong, ok = QInputDialog.getText(self, "Словарь", "Ошибочное написание:")
        if not ok or not wrong.strip():
            return
        correct, ok = QInputDialog.getText(self, "Словарь", "Правильное написание:")
        if ok and correct.strip():
            self.db.execute("INSERT INTO terms(wrong,correct) VALUES(?,?) ON CONFLICT(wrong) DO UPDATE SET correct=excluded.correct",
                            (wrong.strip().casefold(), correct.strip()))
            self.refresh_terms()

    def delete_term(self):
        row = self.terms.currentRow()
        if row >= 0:
            self.db.execute("DELETE FROM terms WHERE wrong=?", (self.term_rows[row]["wrong"],))
            self.refresh_terms()

    def capture_shot(self):
        if not self.require_meeting():
            return
        caption, ok = QInputDialog.getText(self, "Шаг инструкции", "Что показано на этом шаге?")
        if not ok:
            return
        mid = self.mid
        screen_index = self.screen_select.currentData()
        at = time.monotonic() - self.record_epoch if self.record_epoch else 0
        self.hide()
        QTimer.singleShot(3000, lambda: self.finish_shot(mid, screen_index, caption, at))

    def finish_shot(self, mid, screen_index, caption, at):
        try:
            screens = QApplication.screens()
            if screen_index is None or screen_index >= len(screens):
                raise ValueError("Экран отключён")
            self.save_shot(screens[screen_index].grabWindow(0), mid, caption, at)
        except Exception as exc:
            self.showNormal()
            self.error(str(exc))
        finally:
            self.showNormal()

    def save_shot(self, pixmap, mid, caption, at):
        folder = self.root / "screenshots" / str(mid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}.png"
        if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
            raise ValueError("Не удалось сохранить изображение")
        self.db.add_shot(mid, path, caption.strip() or "Шаг инструкции", at)
        self.refresh_current()

    def import_shot(self):
        if not self.require_meeting():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Добавить скриншот", "", "Изображения (*.png *.jpg *.jpeg)")
        if path:
            from PySide6.QtGui import QPixmap
            caption, ok = QInputDialog.getText(self, "Шаг инструкции", "Подпись:")
            if ok:
                try:
                    self.save_shot(QPixmap(path), self.mid, caption, 0)
                except ValueError as exc:
                    self.error(str(exc))

    def open_shot(self, row, col):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.shot_rows[row]["path"]))

    def export_guide(self):
        if not self.require_meeting():
            return
        report = self.db.latest_report(self.mid)
        shots = self.db.rows("SELECT * FROM shots WHERE meeting_id=? ORDER BY id", (self.mid,))
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт инструкции", "guide.html", "HTML (*.html)")
        if path:
            Path(path).write_text(guide_html(self.meeting_title.text(), report["body"]["steps"] if report else [], shots), encoding="utf-8")

    def export_report(self):
        if not self.require_meeting():
            return
        report = self.db.latest_report(self.mid)
        if not report:
            return self.info("Сначала создайте протокол.")
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт протокола", "meeting.html", "HTML (*.html)")
        if path:
            title = self.meeting_title.text()
            stale = report["fingerprint"] != fingerprint(self.db.segments(self.mid))
            banner = "<p><b>Расшифровка изменена после создания этого протокола. Нужен повторный анализ.</b></p>" if stale else ""
            Path(path).write_text(standalone(banner + report_html(title, report["body"]), title), encoding="utf-8")

    def open_audio(self):
        if self.require_meeting():
            path = self.root / "audio" / str(self.mid)
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def tick(self):
        if self.record_epoch:
            self.elapsed.setText(clock(time.monotonic() - self.record_epoch))
        self.maintenance_ticks += 1
        if self.maintenance_ticks == 1 or self.maintenance_ticks % 60 == 0:
            protected = {c.mid for c in self.captures if c.isRunning()}
            deleted, errors = cleanup_audio(self.db, self.root, protected)
            if deleted or errors:
                self.statusBar().showMessage(f"Очистка аудио: удалено {deleted}, не удалось {len(errors)}")
        due = self.db.due_reminders()
        if due and not self.reminder_dialog and not self.quitting:
            task = due[0]
            dialog = ReminderDialog(task, self)
            dialog.task_id = task["id"]
            self.reminder_dialog = dialog
            dialog.action.connect(lambda action, minutes, tid=task["id"]: self.reminder_action(tid, action, minutes))
            dialog.finished.connect(self.reminder_closed)
            if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
                self.tray.showMessage(task["title"], task["context"][:250], QSystemTrayIcon.MessageIcon.Information, 10000)
            dialog.show()
        if self.quitting:
            workers = self.captures + [x for x in (self.transcriber, self.analysis, self.update_job, self.ollama_job) if x]
            if not any(w.isRunning() for w in workers):
                self.timer.stop()
                self.tray.hide()
                QApplication.quit()

    def reminder_action(self, task_id, action, minutes):
        if action == "snooze":
            self.db.snooze_task(task_id, minutes)
        elif action == "done":
            self.db.finish_task(task_id)
        else:
            self.db.mark_notified(task_id)
        self.refresh_tasks()

    def reminder_closed(self, *_):
        self.reminder_dialog = None

    def quit_app(self):
        self.quitting = True
        self.stop_recording()
        if self.transcriber:
            self.transcriber.stop()
        if self.analysis:
            self.analysis.requestInterruption()
        self.setEnabled(False)
        self.statusBar().showMessage("Сохраняю данные и завершаю текущие вычисления…")

    def closeEvent(self, event):
        event.ignore()
        if QSystemTrayIcon.isSystemTrayAvailable() and not self.quitting:
            self.hide()
            self.tray.showMessage("СтеноГраф работает в фоне", "Запись и напоминания продолжают работать. Завершение — через меню значка в трее.")
        else:
            self.quit_app()
