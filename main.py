"""EK's Image Wise - entry point.  Run:  python main.py   [image files to open]"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from imagewise import paths
from imagewise.version import APP_ID, APP_NAME, VERSION


def setup_logging() -> logging.Logger:
    """Write a log file (a packaged app has no console, so this is how problems get diagnosed)."""
    handler: logging.Handler
    try:
        paths.log_dir().mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(paths.log_dir() / "ekiw.log", maxBytes=500_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("imagewise")
    log.info("%s %s starting (packaged=%s, python %s)", APP_NAME, VERSION, paths.frozen(), sys.version.split()[0])
    return log


def install_excepthook(log: logging.Logger) -> None:
    """Log every unexpected error, and tell the user where the log is (instead of silently failing)."""
    shown = {"count": 0}

    def hook(exc_type, exc, tb):
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
        if shown["count"] < 3:  # don't bury the user in dialogs if something repeats
            shown["count"] += 1
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(None, APP_NAME, f"Something went wrong:\n\n{exc}\n\n"
                                     f"Details were saved to:\n{paths.log_dir() / 'ekiw.log'}")
            except Exception:
                pass

    sys.excepthook = hook


def set_windows_app_id() -> None:
    """Windows: give the app its own identity so the taskbar shows OUR icon (not Python's)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def app_icon_path():
    """Icon_1.png from the app's main folder if it is there, otherwise the built-in icon."""
    for candidate in (paths.root_file("Icon_1.png"), paths.asset("ekiw.png")):
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    log = setup_logging()
    install_excepthook(log)
    set_windows_app_id()

    import time

    from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    from imagewise.ui import theme
    from imagewise.ui.main_window import MainWindow

    class App(QApplication):
        fileOpened = Signal(str)

        def event(self, e):  # macOS: files dropped on the Dock icon / "Open With" arrive as events
            if e.type() == QEvent.FileOpen:
                self.fileOpened.emit(e.file())
                return True
            return super().event(e)

    app = App(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    icon = app_icon_path()
    if icon is not None:  # window, taskbar (Windows) and Dock (Mac) icon
        app.setWindowIcon(QIcon(str(icon)))
    saved = QSettings("EK", "ImageWise").value("theme", theme.DEFAULT, type=str)
    theme.apply(app, saved if saved in theme.THEMES else theme.DEFAULT)

    # splash screen: splash.png in the app's main folder (skipped if the file is not there)
    started = time.time()
    splash = None
    splash_file = paths.root_file("splash.png")
    if splash_file.is_file():
        pixmap = QPixmap(str(splash_file))
        if not pixmap.isNull():
            if pixmap.width() > 900:
                pixmap = pixmap.scaledToWidth(900, Qt.SmoothTransformation)
            splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
            splash.show()
            app.processEvents()  # draw it now, before the (slower) window and plugins load

    win = MainWindow()
    app.fileOpened.connect(win.open_image)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    def show_main():
        win.show()
        if splash is not None:
            splash.finish(win)
        if args:  # python main.py photo.jpg [more.jpg ...]
            win.open_image(args[0])
            if len(args) > 1:
                win.add_photos(args[1:])

    # keep the splash on screen for at least a moment so it can be seen
    wait_ms = max(0, 1500 - int((time.time() - started) * 1000)) if splash is not None else 0
    QTimer.singleShot(wait_ms, show_main)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
