from PySide6.QtCore import QThread, Signal

from .db import fingerprint
from .intelligence import EmbeddedLLM, LocalLLM, batches, merge_reports


class BackgroundCall(QThread):
    completed = Signal(object)
    error = Signal(str)

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    def run(self):
        try:
            self.completed.emit(self.callback())
        except Exception as exc:
            self.error.emit(str(exc))


class Analyze(QThread):
    completed = Signal(int)
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, db, mid, model, backend="ollama", gguf_path="", threads=4):
        super().__init__()
        self.db, self.mid, self.model = db, mid, model
        self.backend, self.gguf_path, self.threads = backend, gguf_path, threads

    def run(self):
        client = None
        try:
            segments = self.db.segments(self.mid)
            if not segments:
                raise ValueError("Сначала запишите речь или импортируйте текст")
            original_hash = fingerprint(segments)
            client = EmbeddedLLM(self.gguf_path, self.threads) if self.backend == "embedded" else LocalLLM(self.model)
            client.check()
            parts = list(batches(segments))
            results = []
            for i, part in enumerate(parts, 1):
                if self.isInterruptionRequested():
                    return
                self.progress.emit(f"Создаю протокол: часть {i} из {len(parts)}…")
                results.append(client.extract(part))
            if self.isInterruptionRequested():
                return
            # No partial reports: every transcript part must succeed before committing.
            if fingerprint(self.db.segments(self.mid)) != original_hash:
                raise ValueError("Расшифровка изменилась во время анализа. Запустите создание протокола повторно.")
            self.db.save_report(self.mid, merge_reports(results), original_hash)
            self.completed.emit(self.mid)
        except Exception as exc:
            self.error.emit(f"Протокол не создан: {exc}")
        finally:
            if client:
                client.close()
