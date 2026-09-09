import sys

from .config import data_root, enforce_offline


def main():
    enforce_offline()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .app import MainWindow
    from .widgets import STYLE

    app = QApplication(sys.argv)
    app.setApplicationName("Stenograph")
    app.setOrganizationName("Stenograph")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    root = data_root()
    lock = QLockFile(str(root / "app.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "СтеноГраф", "Приложение уже запущено. Проверьте значок в трее.")
        return 1
    from .runtime_guard import RuntimeGuard
    guard = RuntimeGuard(root)
    if not guard.acquire():
        QMessageBox.information(None, "СтеноГраф", "Идёт обновление. Дождитесь его завершения.")
        lock.unlock()
        return 1
    try:
        window = MainWindow(root)
        window.show()
        return app.exec()
    finally:
        lock.unlock()
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
