"""Loads plugins, shows their panels in the sidebar and acts as the `host` they talk to."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from imagewise.engine import background, effects, shapes
from imagewise.plugins.api import API_VERSION
from imagewise.plugins.loader import PluginRecord, load_all, plugin_dirs, user_plugin_dir
from imagewise.ui.category_box import CategoryBox
from imagewise.ui.workers import TaskWorker


def _safe(name: str) -> str:
    return re.sub(r"\W+", "_", name)


class PluginManager:
    """Also the `host` object that plugins receive (see imagewise/plugins/api.py)."""

    api_version = API_VERSION

    def __init__(self, window, layout: QVBoxLayout, settings: QSettings, app_root: Path):
        self.window = window
        self.layout = layout
        self.settings = settings
        self.app_root = app_root
        self.records: list[PluginRecord] = []
        self._boxes: list[QWidget] = []
        self._cats: list[CategoryBox] = []
        self._available = False  # True once an image is open
        self._tasks: set = set()  # running background tasks (kept alive until they finish)

    # ================= what plugins can use =================
    @property
    def document(self):
        return self.window.doc

    def request_refresh(self):
        self.window.plugin_refresh()

    def message(self, text: str):
        self.window.statusBar().showMessage(str(text), 6000)

    def run_task(self, fn, on_done=None, on_error=None):
        """Run fn() on a background thread; on_done(result) / on_error(message) run on the UI thread."""
        worker = TaskWorker(fn)
        if on_done is not None:
            worker.done.connect(on_done, Qt.QueuedConnection)
        if on_error is not None:
            worker.failed.connect(on_error, Qt.QueuedConnection)
        worker.finished.connect(lambda w=worker: self._task_finished(w))
        self._tasks.add(worker)
        worker.start()

    def _task_finished(self, worker):
        self._tasks.discard(worker)
        worker.deleteLater()

    def set_canvas_items(self, owner, items):
        self.window.set_canvas_items(owner, items)

    def select_canvas_item(self, owner, index):
        self.window.select_canvas_item(owner, index)

    def block_canvas_size(self, blocked):
        """While a plugin (Pattern / Poster) sets the canvas size, the Canvas size controls are greyed out."""
        self.window.cat_size.set_blocked(bool(blocked))

    def set_photos_interactive(self, on):
        self.window.set_photos_interactive(bool(on))

    def data_dir(self, name: str) -> Path:
        path = Path.home() / "EKImageWise" / "data" / _safe(name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ================= lifecycle =================
    def load(self):
        """(Re)load every plugin and rebuild the sidebar boxes."""
        self.save_state()
        self._clear()
        try:
            user_plugin_dir().mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.records = load_all(self, plugin_dirs(self.app_root))
        disabled = self._disabled()
        loaded = 0
        for rec in self.records:
            plugin = rec.plugin
            if plugin is None:
                continue
            loaded += 1
            plugin.enabled = rec.name not in disabled
            self._restore_state(rec)
            self._add_box(rec)
            if plugin.has_effect():
                effects.register(plugin)
            if plugin.has_generator():
                effects.register_generator(plugin)
        if loaded == 0:
            note = QLabel("No plugins installed.\nPlugins > Open plugins folder to add some.")
            note.setWordWrap(True)
            self.layout.addWidget(note)
            self._boxes.append(note)
        self.window.plugin_refresh()

    def _clear(self):
        effects.clear()
        shapes.set_active(False)  # each plugin switches its feature back on when it loads
        background.set_active(False)
        self.window.clear_canvas_items()
        self.window.set_photos_interactive(True)
        self.window.cat_size.set_blocked(False)
        for w in self._boxes:
            self.layout.removeWidget(w)
            w.deleteLater()
        self._boxes.clear()
        self._cats.clear()

    def collapse_all(self):
        for cat in self._cats:
            cat.set_expanded(False)

    def set_available(self, on: bool):
        """Plugin settings can only be changed while an image is open."""
        self._available = on
        for cat in self._cats:
            cat.set_available(on)

    # ----- settings of all plugins, for undo / redo -----
    def get_states(self) -> dict:
        states = {}
        for rec in self.records:
            if rec.plugin is not None:
                try:
                    states[rec.name] = rec.plugin.get_state()
                except Exception:
                    pass
        return states

    def set_states(self, states: dict):
        for rec in self.records:
            if rec.plugin is not None and rec.name in states:
                try:
                    rec.plugin.set_state(states[rec.name])
                except Exception as exc:
                    self.message(f"{rec.name}: could not restore settings ({exc})")

    def document_changed(self, document):
        for rec in self.records:
            if rec.plugin is not None:
                try:
                    rec.plugin.on_document_changed(document)
                except Exception as exc:
                    self.message(f"{rec.name}: {exc}")

    # ================= sidebar =================
    def _add_box(self, rec: PluginRecord):
        plugin = rec.plugin
        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        if plugin.description:
            desc = QLabel(plugin.description)
            desc.setWordWrap(True)
            inner.addWidget(desc)
        try:
            panel = plugin.create_panel()
        except Exception as exc:
            panel = None
            rec.error = f"Panel failed: {type(exc).__name__}: {exc}"
        if panel is not None:
            inner.addWidget(panel)
            self.window.protect_wheel(panel)  # wheel only changes a setting after it has been clicked
        elif not rec.error:
            inner.addWidget(QLabel("This plugin has no settings."))
        if rec.error:
            err = QLabel(rec.error)
            err.setWordWrap(True)
            err.setStyleSheet("color: #d9534f;")
            inner.addWidget(err)

        cat = CategoryBox(rec.name, content, checkable=True)  # the tick switches the plugin on or off
        cat.chk_enable.setChecked(plugin.enabled)
        cat.enabledToggled.connect(lambda on, r=rec: self._on_toggled(r, on))
        cat.resetRequested.connect(lambda r=rec: self._reset_plugin(r))
        cat.set_available(self._available)
        cat.expandedChanged.connect(lambda _on: self.window.fit_settings_width())
        cat.lockedChanged.connect(lambda on, p=plugin: self.window.canvas_items_locked(p, on))
        self.layout.addWidget(cat)
        self._boxes.append(cat)
        self._cats.append(cat)

    def _reset_plugin(self, rec: PluginRecord):
        try:
            rec.plugin.reset()
        except Exception as exc:
            self.message(f"{rec.name}: {exc}")
        self.window.plugin_refresh()

    def _on_toggled(self, rec: PluginRecord, on: bool):
        rec.plugin.enabled = on
        disabled = self._disabled()
        (disabled.discard if on else disabled.add)(rec.name)
        self.settings.setValue("plugins/disabled", json.dumps(sorted(disabled)))
        self.window.plugin_refresh()

    def _disabled(self) -> set[str]:
        try:
            return set(json.loads(self.settings.value("plugins/disabled", "[]", type=str)))
        except (ValueError, TypeError):
            return set()

    # ================= remembered settings =================
    def _restore_state(self, rec: PluginRecord):
        raw = self.settings.value(f"plugins/state/{_safe(rec.name)}", "", type=str)
        if not raw:
            return
        try:
            rec.plugin.set_state(json.loads(raw))
        except Exception as exc:
            rec.error = f"Could not restore settings: {exc}"

    def save_state(self):
        for rec in self.records:
            if rec.plugin is None:
                continue
            try:
                self.settings.setValue(f"plugins/state/{_safe(rec.name)}", json.dumps(rec.plugin.get_state()))
            except Exception:
                pass  # a plugin that can't save its settings just starts fresh next time

    # ================= dialog / folders =================
    def open_folder(self):
        folder = user_plugin_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_dialog(self):
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Plugins")
        dlg.resize(560, 480)
        layout = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setHtml(self._summary_html())
        layout.addWidget(view)
        row = QHBoxLayout()
        btn_open = QPushButton("Open plugins folder")
        btn_open.clicked.connect(self.open_folder)
        btn_reload = QPushButton("Reload plugins")
        btn_reload.clicked.connect(lambda: (self.load(), view.setHtml(self._summary_html())))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        row.addWidget(btn_open)
        row.addWidget(btn_reload)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)
        dlg.exec()

    def _summary_html(self) -> str:
        e = html.escape
        parts = ["<h3>Installed plugins</h3>"]
        good = [r for r in self.records if r.plugin is not None]
        bad = [r for r in self.records if r.plugin is None]
        if not good and not bad:
            parts.append("<p>None found.</p>")
        for r in good:
            p = r.plugin
            state = "on" if p.enabled else "off"
            parts.append(f"<p><b>{e(r.name)}</b> v{e(str(p.version))} ({state})"
                         + (f" by {e(p.author)}" if p.author else "")
                         + f"<br>{e(p.description)}<br><small>{e(str(r.path))}</small>"
                         + (f"<br><span style='color:#d9534f'>{e(r.error)}</span>" if r.error else "") + "</p>")
        if bad:
            parts.append("<h3>Could not load</h3>")
            for r in bad:
                parts.append(f"<p><b>{e(r.name)}</b><br><span style='color:#d9534f'>{e(r.error or '')}</span>"
                             f"<br><small>{e(str(r.path))}</small></p>")
        parts.append("<h3>Plugin folders</h3><ul>"
                     + "".join(f"<li>{e(str(d))}</li>" for d in plugin_dirs(self.app_root)) + "</ul>")
        return "".join(parts)
