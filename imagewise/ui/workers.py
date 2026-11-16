"""Background threads so slow jobs never freeze the window."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal



class TaskWorker(QThread):
    """Runs any function on a background thread (used by plugins through host.run_task)."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            logging.getLogger("imagewise").exception("Background task failed")
            # exceptions meant for the user (user_message = True, or ValueError) are shown as they are
            friendly = getattr(exc, "user_message", False) or isinstance(exc, ValueError)
            self.failed.emit(str(exc) if friendly else f"{type(exc).__name__}: {exc}")


class ExportWorker(QThread):
    """Builds and saves the final image off the UI thread (poster exports can take a while)."""

    done = Signal()
    failed = Signal(str)

    def __init__(self, doc, path: str, parent=None):
        super().__init__(parent)
        self._doc = doc
        self._path = path

    def run(self):
        try:
            self._doc.export(self._path)
            self.done.emit()
        except MemoryError:
            self.failed.emit("Not enough memory to build this image. Lower the DPI or the output size and try again.")
        except Exception as exc:
            self.failed.emit(str(exc))


class ViewWorker(QThread):
    """Renders a sharp picture of just the visible part of the preview (used when zoomed in)."""

    done = Signal(object, object, int)  # image, region, job id
    failed = Signal(str, int)

    def __init__(self, doc, region, out_w: int, job_id: int, parent=None):
        super().__init__(parent)
        self._doc, self._region, self._out_w, self._id = doc, region, out_w, job_id

    def run(self):
        try:
            self.done.emit(self._doc.render_view(self._region, self._out_w), self._region, self._id)
        except Exception as exc:
            self.failed.emit(str(exc), self._id)
