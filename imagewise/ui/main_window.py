"""Main window: crop and preview panes side by side on the left, controls on the right."""
from __future__ import annotations

import json
import random
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from PIL import Image

from imagewise import paths
from imagewise.engine import effects, shapes
from imagewise.engine.document import Document, SUPPORTED_EXPORT
from imagewise.engine.gradient import Gradient
from imagewise.engine.history import History, Snapshot
from imagewise.engine.photo import Photo
from imagewise.version import APP_NAME, VERSION
from imagewise.ui.canvas import ImageCanvas
from imagewise.ui.category_box import CategoryBox
from imagewise.ui import theme
from imagewise.ui.photos_panel import PhotosPanel
from imagewise.ui.plugin_manager import PluginManager
from imagewise.ui.wheel_guard import WheelGuard
from imagewise.ui.workers import ExportWorker, ViewWorker

PREVIEW_MAX_SIDE = 1600
LIVE_MAX_SIDE = 800  # quicker, rougher preview while a photo is being dragged
UNDO_STYLE = ("QPushButton { background-color: #c0392b; color: white; font-weight: bold; padding: 4px 14px; }"
              "QPushButton:disabled { background-color: #5d3a36; color: #a99; }")
REDO_STYLE = ("QPushButton { background-color: #27ae60; color: white; font-weight: bold; padding: 4px 14px; }"
              "QPushButton:disabled { background-color: #355a43; color: #9a9; }")
APP_ROOT = paths.app_root()  # folder containing plugins/ (the project folder, or inside the installed app)
OPEN_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;All files (*)"
EXPORT_FILTER = "PNG (*.png);;JPEG (*.jpg *.jpeg);;TIFF (*.tif *.tiff);;WebP (*.webp)"


def pil_to_pixmap(img) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def spin(minimum=0, maximum=100000, value=0) -> QSpinBox:
    s = QSpinBox()
    s.setRange(minimum, maximum)
    s.setValue(value)
    return s


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EK's Image Wise")
        self.resize(1200, 750)
        self.setAcceptDrops(True)
        self.doc: Document | None = None
        self.settings = QSettings("EK", "ImageWise")
        saved_theme = self.settings.value("theme", theme.DEFAULT, type=str)
        self.theme_name = saved_theme if saved_theme in theme.THEMES else theme.DEFAULT
        # live, draggable items that plugins (Alpha Overlays) show on the preview
        self._canvas_items: dict = {}  # plugin -> [(model, pixmap), ...]
        self._item_owner: list = []  # flat index on the canvas -> (plugin, index inside that plugin)
        self._locked_owners: set = set()
        self._photos_interactive = True  # a plugin (Pattern / Poster) can switch photo dragging off

        # debounce so dragging/typing doesn't re-render on every tick
        self._preview_timer = QTimer(self, singleShot=True, interval=150)
        self._preview_timer.timeout.connect(self._update_preview_canvas)
        # sharp zoomed-in picture of the visible part: requested shortly after zoom/pan settles
        self._detail_timer = QTimer(self, singleShot=True, interval=120)
        self._detail_timer.timeout.connect(self._request_detail)
        self._detail_job = 0
        self._detail_worker = None
        self._detail_pending = None
        self._crop_pm_photo = None  # the photo whose crop-pane picture is already built
        self._worker = None
        self.categories: list[CategoryBox] = []
        # undo / redo: the editing state is compared a few times a second and recorded once it settles
        self._history = History()
        self._hist_pending = None
        self._restoring = False
        self._hist_timer = QTimer(self, interval=300)
        self._hist_timer.timeout.connect(self._poll_history)
        # quick preview while a photo is being dragged
        self._live_timer = QTimer(self, singleShot=True, interval=40)
        self._live_timer.timeout.connect(self._live_preview)

        self._build_menu()
        self._build_ui()
        self._set_enabled(False)
        self.plugin_manager.load()
        self.fit_settings_width()
        geometry, state = self.settings.value("window/geometry"), self.settings.value("window/state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)  # remembers whether the settings panel was docked, floating or on the left

    # ================= UI construction =================
    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        for text, shortcut, slot in (
            ("&Open...", "Ctrl+O", self.open_image),
            ("&Add photo to composition...", "Ctrl+Shift+O", self.add_photos),
            ("&Export...", "Ctrl+E", self.export_image),
            ("&Quit", "Ctrl+Q", self.close),
        ):
            act = QAction(text, self, shortcut=shortcut)
            act.triggered.connect(slot)
            file_menu.addAction(act)

        edit_menu = self.menuBar().addMenu("&Edit")
        for text, shortcut, slot in (("&Undo", "Ctrl+Z", self.undo), ("&Redo", "Ctrl+Y", self.redo)):
            act = QAction(text, self, shortcut=shortcut)
            act.triggered.connect(slot)
            edit_menu.addAction(act)
        alt_redo = QAction(self, shortcut="Ctrl+Shift+Z")  # second, hidden shortcut for Redo
        alt_redo.triggered.connect(self.redo)
        self.addAction(alt_redo)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About", self)
        about.triggered.connect(lambda: self._show_about())
        help_menu.addAction(about)

        plugins_menu = self.menuBar().addMenu("&Plugins")
        for text, slot in (
            ("Plugin manager...", lambda: self.plugin_manager.show_dialog()),
            ("Open plugins folder", lambda: self.plugin_manager.open_folder()),
            ("Reload plugins", lambda: self.plugin_manager.load()),
        ):
            act = QAction(text, self)
            act.triggered.connect(slot)
            plugins_menu.addAction(act)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        # --- left: crop pane and preview pane side by side ---
        left = QVBoxLayout()
        switch = QHBoxLayout()
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setStyleSheet(UNDO_STYLE)
        self.btn_undo.setToolTip("Undo the last change (Ctrl+Z)")
        self.btn_undo.clicked.connect(lambda _=False: self.undo())
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.setStyleSheet(REDO_STYLE)
        self.btn_redo.setToolTip("Redo (Ctrl+Y or Ctrl+Shift+Z)")
        self.btn_redo.clicked.connect(lambda _=False: self.redo())
        switch.addWidget(self.btn_undo)
        switch.addWidget(self.btn_redo)
        switch.addSpacing(16)
        self.btn_crop_view = QPushButton("Crop")
        self.btn_preview = QPushButton("Preview")
        for btn in (self.btn_crop_view, self.btn_preview):
            btn.setCheckable(True)
            btn.setChecked(True)  # both panes are shown by default
            btn.setToolTip("Show or hide this pane")
            switch.addWidget(btn)
        self.btn_crop_view.toggled.connect(self._on_panes_toggled)
        self.btn_preview.toggled.connect(self._on_panes_toggled)
        switch.addStretch()
        switch.addWidget(QLabel("Wheel: zoom   |   Middle / right drag, or Alt + drag: move the view"))
        self.crop_canvas = ImageCanvas()
        self.crop_canvas.set_crop_mode(True)
        self.crop_canvas.cropDragged.connect(self._on_crop_dragged)
        self.canvas = ImageCanvas()  # the preview canvas
        self.canvas.detail_supported = True
        self.canvas.viewChanged.connect(lambda: self._detail_timer.start())
        self.crop_pane = self._make_pane("Crop", self.crop_canvas)
        self.preview_pane = self._make_pane("Preview", self.canvas)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.crop_pane)
        self.splitter.addWidget(self.preview_pane)
        self.splitter.setSizes([500, 500])
        left.addLayout(switch)
        left.addWidget(self.splitter, 1)
        layout.addLayout(left, 1)

        # --- right: controls ---
        right = QVBoxLayout()
        right_w = QWidget()
        right_w.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidget(right_w)
        scroll.setWidgetResizable(True)  # the content always fits the panel's width
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll, self._settings_content = scroll, right_w
        scroll.setMinimumWidth(320)
        # The settings live in a dock: drag its title bar to float it as a separate window
        # (or double-click the title), drag it back to re-dock, or move it to the left side.
        self.dock = QDockWidget("Settings", self)
        self.dock.setObjectName("settingsDock")
        # a "Close all" button sits above the settings: it minimises every category
        panel = QWidget()
        panel_box = QVBoxLayout(panel)
        panel_box.setContentsMargins(0, 0, 0, 0)
        panel_box.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        self.btn_close_all = QPushButton("Close all")
        self.btn_close_all.setToolTip("Minimise every settings category")
        self.btn_close_all.clicked.connect(lambda _=False: self.close_all_categories())
        bar.addWidget(self.btn_close_all)
        bar.addStretch()
        panel_box.addLayout(bar)
        panel_box.addWidget(scroll, 1)
        self.dock.setWidget(panel)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                              | QDockWidget.DockWidgetClosable)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.resizeDocks([self.dock], [390], Qt.Horizontal)
        view_menu = self.menuBar().addMenu("&View")
        show_settings = self.dock.toggleViewAction()
        show_settings.setText("Settings panel")
        view_menu.addAction(show_settings)
        theme_menu = view_menu.addMenu("&Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for name in theme.THEMES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(name == self.theme_name)
            act.triggered.connect(lambda _=False, n=name: self.set_theme(n))
            theme_group.addAction(act)
            theme_menu.addAction(act)
        self._apply_canvas_theme()

        self._sidebar = right

        # ---- Photos: the pictures in the composition ----
        self.photos_panel = PhotosPanel()
        self.photos_panel.addRequested.connect(lambda: self.add_photos())
        self.photos_panel.removeRequested.connect(self._remove_photo)
        self.photos_panel.moveRequested.connect(self._move_photo)
        self.photos_panel.selectionChanged.connect(self._on_photo_selected)
        self.photos_panel.adjusted.connect(self._on_photo_adjusted)
        self.cat_photos = self._add_category("Photos", self.photos_panel, self._reset_photo_placement)
        self.cat_photos.lockedChanged.connect(lambda on: self.canvas.set_locks(photos=on))
        self.canvas.photoSelected.connect(self._on_canvas_photo_selected)
        self.canvas.photoEdited.connect(self._on_canvas_photo_edited)
        self.canvas.photoDragFinished.connect(self._schedule_preview)

        # ---- Crop (the selected photo) ----
        self.crop_group = QWidget()
        cf = QFormLayout(self.crop_group)
        self.sp_left, self.sp_top = spin(), spin()
        self.sp_cw, self.sp_ch = spin(1, 100000, 1), spin(1, 100000, 1)
        for label, w in (("Left", self.sp_left), ("Top", self.sp_top),
                         ("Width", self.sp_cw), ("Height", self.sp_ch)):
            cf.addRow(label, w)
            w.valueChanged.connect(self._on_crop_spin)
        hint = QLabel("Crops the selected photo. Drag on the Crop pane to draw a crop box.")
        hint.setWordWrap(True)
        cf.addRow(hint)
        self.cat_crop = self._add_category("Crop", self.crop_group, self._reset_crop)
        self.cat_crop.lockedChanged.connect(lambda on: self.crop_canvas.set_locks(crop=on))

        # ---- Canvas size / output ----
        self.size_group = QWidget()
        sf = QFormLayout(self.size_group)
        self.sp_w, self.sp_h = spin(1, 100000, 1), spin(1, 100000, 1)
        self.sp_w.valueChanged.connect(lambda v: self._on_size_spin("w", v))
        self.sp_h.valueChanged.connect(lambda v: self._on_size_spin("h", v))
        self.dsp_wcm = self._dspin(0.1, 5000, 10)
        self.dsp_hcm = self._dspin(0.1, 5000, 10)
        self.dsp_wcm.valueChanged.connect(lambda v: self._on_size_cm("w", v))
        self.dsp_hcm.valueChanged.connect(lambda v: self._on_size_cm("h", v))
        self.chk_lock = QCheckBox("Lock aspect ratio")
        self.chk_lock.setChecked(True)
        self.sp_dpi = spin(1, 2400, 300)
        self.sp_dpi.valueChanged.connect(self._on_dpi)
        self.lbl_print = QLabel("-")
        self.lbl_print.setWordWrap(True)
        self.cmb_canvas_bg = QComboBox()
        self.cmb_canvas_bg.addItems(["Transparent", "Solid colour", "Gradient"])
        self.cmb_canvas_bg.currentIndexChanged.connect(self._on_canvas_bg_changed)
        self.btn_canvas_bg = QPushButton("Colour 1...")
        self.btn_canvas_bg.clicked.connect(lambda _=False: self._pick_canvas_color(0))
        self.btn_canvas_bg2 = QPushButton("Colour 2...")
        self.btn_canvas_bg2.clicked.connect(lambda _=False: self._pick_canvas_color(1))
        self.lbl_canvas_angle = QLabel("Gradient angle: 90\u00b0")
        self.sl_canvas_angle = QSlider(Qt.Horizontal)
        self.sl_canvas_angle.setRange(0, 360)
        self.sl_canvas_angle.setValue(90)
        self.sl_canvas_angle.valueChanged.connect(self._on_canvas_bg_changed)
        self.chk_canvas_radial = QCheckBox("Radial (from the centre)")
        self.chk_canvas_radial.toggled.connect(self._on_canvas_bg_changed)
        sf.addRow("Width (px)", self.sp_w)
        sf.addRow("Height (px)", self.sp_h)
        sf.addRow("Width (cm)", self.dsp_wcm)
        sf.addRow("Height (cm)", self.dsp_hcm)
        sf.addRow(self.chk_lock)
        sf.addRow("DPI", self.sp_dpi)
        sf.addRow("Print size", self.lbl_print)
        sf.addRow("Canvas", self.cmb_canvas_bg)
        sf.addRow(self.btn_canvas_bg)
        sf.addRow(self.btn_canvas_bg2)
        sf.addRow(self.lbl_canvas_angle)
        sf.addRow(self.sl_canvas_angle)
        sf.addRow(self.chk_canvas_radial)
        self.cat_size = self._add_category("Canvas size / output", self.size_group, self._reset_size)

        # ---- Plugins (each plugin adds its own category here) ----
        self.plugin_container = QWidget()
        plugin_layout = QVBoxLayout(self.plugin_container)
        plugin_layout.setContentsMargins(0, 0, 0, 0)
        plugin_layout.setSpacing(0)
        right.addWidget(self.plugin_container)
        self.plugin_manager = PluginManager(self, plugin_layout, self.settings, APP_ROOT)
        self.canvas.overlayEdited.connect(self._on_canvas_item_edited)
        self.canvas.overlaySelected.connect(self._on_canvas_item_selected)

        self.btn_export = QPushButton("Export...")
        self.btn_export.clicked.connect(self.export_image)
        right.addWidget(self.btn_export)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        right.addWidget(self.lbl_info)
        right.addStretch()

        # the wheel only changes a setting after that setting has been clicked
        self._wheel_guard = WheelGuard(scroll)
        self._wheel_guard.protect(right_w)

    def _add_category(self, title: str, content: QWidget, on_reset) -> CategoryBox:
        box = CategoryBox(title, content)
        box.resetRequested.connect(on_reset)
        box.expandedChanged.connect(lambda _on: self.fit_settings_width())
        self._sidebar.addWidget(box)
        self.categories.append(box)
        return box

    def close_all_categories(self):
        """Minimise every settings category (built-in ones and plugins)."""
        for cat in self.categories:
            cat.set_expanded(False)
        self.plugin_manager.collapse_all()

    def set_theme(self, name: str):
        """View > Theme: switch between the light and dark look (remembered for next time)."""
        self.theme_name = name
        theme.apply(QApplication.instance(), name)
        self._apply_canvas_theme()
        self.settings.setValue("theme", name)

    def _apply_canvas_theme(self):
        dark = theme.is_dark(self.theme_name)
        self.canvas.set_theme(dark)
        self.crop_canvas.set_theme(dark)

    def fit_settings_width(self):
        """Keep the settings panel wide enough that nothing (titles, Lock, Reset) is ever cut off."""
        QTimer.singleShot(0, self._apply_settings_width)

    def _apply_settings_width(self):
        need = self._settings_content.minimumSizeHint().width() + 26  # + room for the scroll bar
        self._scroll.setMinimumWidth(max(320, need))

    def protect_wheel(self, widget: QWidget):
        """Apply the click-before-scroll protection to widgets created later (plugin panels)."""
        self._wheel_guard.protect(widget)

    def _show_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {VERSION}<br><br>"
            f"Your plugins folder:<br>{paths.user_dir() / 'plugins'}<br><br>"
            f"Log file (send this if something goes wrong):<br>{paths.log_dir() / 'ekiw.log'}")

    def _set_enabled(self, on: bool):
        for cat in self.categories:
            cat.set_available(on)
        self.plugin_manager.set_available(on)
        for w in (self.btn_export, self.btn_crop_view, self.btn_preview):
            w.setEnabled(on)
        self._update_undo_buttons()

    # ================= file actions =================
    def open_image(self, path: str | None = None):
        if not self.centralWidget().isEnabled():  # an export is running
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open image", "", OPEN_FILTER)
        if not path:
            return
        try:
            new_doc = Document.open(path)
        except Exception as exc:  # corrupt / unsupported file
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        if self.doc:  # keep the DPI and canvas background for the next client image (plugins keep their own settings)
            new_doc.dpi = self.doc.dpi
            new_doc.canvas_color = self.doc.canvas_color
            new_doc.canvas_gradient = self.doc.canvas_gradient
        self.doc = new_doc
        self.setWindowTitle(f"EK's Image Wise - {Path(path).name}")
        self._set_enabled(True)
        self.photos_panel.bind(self.doc)
        self._refresh_photo_views()
        self.btn_crop_view.setChecked(True)
        self._sync_controls()
        self.crop_canvas.zoom_fit()
        self.canvas.zoom_fit()
        self.canvas.clear_detail()
        self._detail_job += 1
        self._update_canvas()
        self.plugin_manager.document_changed(self.doc)
        # a new image starts a fresh undo history
        self._history.reset(self._take_snapshot())
        self._hist_pending = None
        self._hist_timer.start()
        self._update_undo_buttons()

    def export_image(self):
        if not self.doc or not self.centralWidget().isEnabled():  # ignore while an export is running
            return
        default = (self.doc.path.stem + "_edit.png") if self.doc.path else "edit.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export image", default, EXPORT_FILTER)
        if not path:
            return
        if Path(path).suffix.lower() not in SUPPORTED_EXPORT:
            path += ".png"
        self._set_busy(True)  # everything is locked while the export runs
        self.statusBar().showMessage("Exporting... large posters can take a minute or two.")
        worker = ExportWorker(self.doc, path, self)
        worker.done.connect(lambda: self._export_finished(path, None), Qt.QueuedConnection)
        worker.failed.connect(lambda msg: self._export_finished(path, msg), Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        self._export_worker = worker
        worker.start()

    def _export_finished(self, path: str, error: str | None):
        self._set_busy(False)
        self.statusBar().clearMessage()
        self._update_undo_buttons()
        if error:
            QMessageBox.critical(self, "Export failed", error)
        else:
            QMessageBox.information(self, "Export complete", f"Saved:\n{path}")

    # drag & drop a file onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if not self.doc:  # nothing open yet: the first file is the image, the rest join it
            self.open_image(paths[0])
            if self.doc and len(paths) > 1:
                self.add_photos(paths[1:])
            return
        box = QMessageBox(self)
        box.setWindowTitle("Add or replace?")
        box.setText(f"{len(paths)} image file(s) dropped. What should happen?")
        add_btn = box.addButton("Add to composition", QMessageBox.AcceptRole)
        replace_btn = box.addButton("Replace current image", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is add_btn:
            self.add_photos(paths)
        elif clicked is replace_btn:
            self.open_image(paths[0])
            if len(paths) > 1:
                self.add_photos(paths[1:])

    # ================= control handlers =================
    def _crop_ratio(self) -> float:
        cw, ch = self.doc.crop_size
        return ch / cw

    def _on_crop_spin(self, _=None):
        if not self.doc:
            return
        l, t = self.sp_left.value(), self.sp_top.value()
        self.doc.set_crop((l, t, l + self.sp_cw.value(), t + self.sp_ch.value()))
        self._after_crop_change()

    def _on_crop_dragged(self, l, t, r, b):
        if not self.doc:
            return
        self.doc.set_crop((l, t, r, b))
        self._after_crop_change()

    def _reset_crop(self):
        if self.doc:
            self.doc.set_crop(None)
            self._after_crop_change()

    def _after_crop_change(self):  # also used after shape changes
        # If the user already chose an output size and aspect is locked, keep width, follow aspect.
        if len(self.doc.photos) == 1 and self.doc.out_size and self.chk_lock.isChecked():
            w = self.doc.out_size[0]
            self.doc.out_size = (w, max(1, round(w * self._crop_ratio())))
        self._sync_controls()
        self._update_crop_canvas()
        self._schedule_preview()

    def _on_size_spin(self, which: str, value: int):
        if not self.doc:
            return
        w0, h0 = self.doc.final_size
        if self.chk_lock.isChecked():
            ratio = h0 / w0  # keep the canvas shape
            if which == "w":
                size = (value, max(1, round(value * ratio)))
            else:
                size = (max(1, round(value / ratio)), value)
        else:
            size = (value, h0) if which == "w" else (w0, value)
        self.doc.out_size = size
        self._sync_controls()
        self._schedule_preview()

    def _on_size_cm(self, which: str, cm: float):
        if self.doc:
            self._on_size_spin(which, max(1, round(cm / 2.54 * self.doc.dpi)))

    def _on_canvas_bg_changed(self, *_):
        """Canvas background: transparent, one colour, or a colour gradient."""
        if not self.doc:
            return
        d = self.doc
        mode = self.cmb_canvas_bg.currentIndex()
        if mode == 0:
            d.canvas_color = d.canvas_gradient = None
        elif mode == 1:
            d.canvas_gradient = None
            d.canvas_color = d.canvas_color or (255, 255, 255)
        else:
            if d.canvas_gradient is None:
                d.canvas_gradient = Gradient.two(d.canvas_color or (255, 255, 255), (30, 60, 160))
            d.canvas_gradient.angle = float(self.sl_canvas_angle.value())
            d.canvas_gradient.radial = self.chk_canvas_radial.isChecked()
        self._sync_controls()
        self._schedule_preview()

    def _pick_canvas_color(self, which: int = 0):
        if not self.doc:
            return
        d = self.doc
        if d.canvas_gradient is not None:
            start = d.canvas_gradient.first if which == 0 else d.canvas_gradient.last
        else:
            start = d.canvas_color or (255, 255, 255)
        colour = QColorDialog.getColor(QColor(*start), self, "Canvas colour")
        if not colour.isValid():
            return
        rgb = (colour.red(), colour.green(), colour.blue())
        if d.canvas_gradient is not None:
            d.canvas_gradient.set_ends(rgb if which == 0 else None, rgb if which == 1 else None)
        else:
            d.canvas_color = rgb
        self._sync_controls()
        self._schedule_preview()

    def _reset_size(self):
        if self.doc:
            self.doc.out_size = None
            self.doc.dpi = 300
            self.doc.canvas_color = None
            self.doc.canvas_gradient = None
            self._sync_controls()
            self._schedule_preview()

    def _on_dpi(self, value: int):
        if self.doc:
            self.doc.dpi = value
            self._sync_controls()

    # ================= small helpers =================
    @staticmethod
    def _dspin(lo, hi, value, suffix=" cm") -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(1)
        sp.setSingleStep(1.0)
        sp.setSuffix(suffix)
        sp.setValue(value)
        return sp

    # ================= syncing =================
    def _sync_controls(self):
        """Push document state into the widgets without triggering their handlers."""
        d = self.doc
        l, t, r, b = d.crop_box
        iw, ih = d.size
        widgets = (self.sp_left, self.sp_top, self.sp_cw, self.sp_ch, self.sp_w, self.sp_h, self.sp_dpi,
                   self.dsp_wcm, self.dsp_hcm, self.cmb_canvas_bg, self.sl_canvas_angle, self.chk_canvas_radial)
        for w in widgets:
            w.blockSignals(True)
        self.sp_left.setRange(0, iw - 1)
        self.sp_top.setRange(0, ih - 1)
        self.sp_cw.setRange(1, iw)
        self.sp_ch.setRange(1, ih)
        self.sp_left.setValue(l)
        self.sp_top.setValue(t)
        self.sp_cw.setValue(r - l)
        self.sp_ch.setValue(b - t)
        fw, fh = d.final_size
        self.sp_w.setValue(fw)
        self.sp_h.setValue(fh)
        self.sp_dpi.setValue(d.dpi)
        self.dsp_wcm.setValue(fw / d.dpi * 2.54)
        self.dsp_hcm.setValue(fh / d.dpi * 2.54)
        grad = d.canvas_gradient
        mode = 2 if grad is not None else (1 if d.canvas_color is not None else 0)
        self.cmb_canvas_bg.setCurrentIndex(mode)
        if grad is not None:
            self.sl_canvas_angle.setValue(int(grad.angle))
            self.chk_canvas_radial.setChecked(bool(grad.radial))
        for w in widgets:
            w.blockSignals(False)
        first = grad.first if grad is not None else d.canvas_color
        self.btn_canvas_bg.setEnabled(mode > 0)
        self.btn_canvas_bg.setStyleSheet(f"border-left: 18px solid rgb({first[0]},{first[1]},{first[2]});" if first else "")
        self.btn_canvas_bg2.setEnabled(mode == 2)
        self.btn_canvas_bg2.setStyleSheet(
            f"border-left: 18px solid rgb({grad.last[0]},{grad.last[1]},{grad.last[2]});" if grad is not None else "")
        self.sl_canvas_angle.setEnabled(mode == 2 and not (grad and grad.radial))
        self.chk_canvas_radial.setEnabled(mode == 2)
        self.lbl_canvas_angle.setText(f"Gradient angle: {int(grad.angle) if grad is not None else 90}\u00b0")
        self.lbl_info.setText(f"Selected photo: {iw} x {ih} px")
        wcm, hcm = d.print_size_cm()
        self.lbl_print.setText(f"{wcm:.1f} x {hcm:.1f} cm\n({wcm / 2.54:.1f} x {hcm / 2.54:.1f} in)")

    def _make_pane(self, title: str, canvas: ImageCanvas) -> QWidget:
        """A canvas with a small header: title, zoom percentage and zoom buttons."""
        pane = QWidget()
        box = QVBoxLayout(pane)
        box.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"<b>{title}</b>"))
        bar.addStretch()
        zoom_label = QLabel("")
        zoom_label.setMinimumWidth(48)
        bar.addWidget(zoom_label)
        for text, tip, action in (("-", "Zoom out", canvas.zoom_out), ("+", "Zoom in", canvas.zoom_in),
                                  ("Fit", "Fit to window", canvas.zoom_fit),
                                  ("1:1", "Actual pixels", canvas.zoom_actual)):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda _=False, f=action: f())
            bar.addWidget(btn)
        canvas.zoomChanged.connect(lambda pct, lbl=zoom_label: lbl.setText(f"{pct:.0f}%"))
        box.addLayout(bar)
        box.addWidget(canvas, 1)
        return pane

    def _on_panes_toggled(self, _=None):
        crop_on, prev_on = self.btn_crop_view.isChecked(), self.btn_preview.isChecked()
        if not crop_on and not prev_on:  # at least one pane must stay visible
            sender = self.sender()
            if sender is not None:
                sender.setChecked(True)
            return
        self.crop_pane.setVisible(crop_on)
        self.preview_pane.setVisible(prev_on)
        if prev_on:
            self._update_preview_canvas()

    def plugin_refresh(self):
        """Called by plugins (and the plugin manager) when the picture should be redrawn."""
        if self.doc:
            self._sync_controls()  # a crop shape (from a plugin) can change the canvas size
            self._update_crop_canvas()
        self._schedule_preview()

    def _shape_dim_pixmap(self, photo):
        """Crop pane helper: a see-through dark layer that dims everything outside the crop shape."""
        shape = photo.active_shape()
        if not shape:
            return None
        proxy = photo.proxy()
        pw, ph_h = proxy.size
        ow, oh = photo.size
        sx, sy = pw / ow, ph_h / oh
        left, top, right, bottom = photo.render_box
        rw, rh = max(1, round((right - left) * sx)), max(1, round((bottom - top) * sy))
        inside = shapes.mask(shape, (rw, rh), (0.0, 0.0, 1.0, 1.0), photo.shape_rotation, photo.shape_invert)
        dim = Image.new("L", (pw, ph_h), 150)
        dim.paste(inside.point([150 - v * 150 // 255 for v in range(256)]), (round(left * sx), round(top * sy)))
        layer = Image.new("RGBA", (pw, ph_h), (0, 0, 0, 0))
        layer.putalpha(dim)
        return pil_to_pixmap(layer)

    def _schedule_preview(self):
        self._preview_timer.start()

    def _update_canvas(self, *_):
        self._update_crop_canvas()
        self._update_preview_canvas()

    def _update_crop_canvas(self):
        if not self.doc:
            self.crop_canvas.set_image(None)
            self._crop_pm_photo = None
            return
        photo = self.doc.active_photo
        if self._crop_pm_photo is not photo:  # build the (large) picture once per photo
            self.crop_canvas.set_image(pil_to_pixmap(photo.proxy()), photo.size)
            self._crop_pm_photo = photo
        self.crop_canvas.set_crop(self.doc.crop_box)
        try:
            self.crop_canvas.set_shape_dim(self._shape_dim_pixmap(photo))
        except Exception:  # a broken shape picture must never break the crop pane
            self.crop_canvas.set_shape_dim(None)

    def _update_preview_canvas(self):
        if not self.doc:
            self.canvas.set_image(None)
            return
        if not self.btn_preview.isChecked():
            return
        try:
            preview = self.doc.render(max_side=PREVIEW_MAX_SIDE, overlays=False)  # canvas draws overlays
        except Exception as exc:  # e.g. too many tiles: keep the old picture and say why
            self.statusBar().showMessage(str(exc), 8000)
            return
        self.canvas.set_image(pil_to_pixmap(preview), self.doc.final_size)
        self.canvas.clear_detail()
        self._detail_job += 1  # a detail render that is still running is now out of date
        self._show_plugin_errors()
        self._detail_timer.start()

    def _show_plugin_errors(self):
        problems = effects.take_errors()
        if problems:
            self.statusBar().showMessage("Plugin problem: " + "; ".join(problems[:2]), 8000)

    # ----- sharp detail when zoomed in -----
    def _request_detail(self):
        if not self.doc or not self.btn_preview.isChecked():
            return
        canvas = self.canvas
        if canvas.zoom <= 1.02:  # fitted view: the overall preview is sharp enough
            canvas.clear_detail()
            return
        visible = canvas.visible_region(margin=0.1)
        if visible is None:
            return
        region, (view_w, _view_h) = visible
        out_w = int(min(4096, max(64, view_w * canvas.devicePixelRatioF())))
        self._detail_job += 1
        job = (self._detail_job, region, out_w)
        if self._detail_worker is not None:  # one at a time; the newest request waits its turn
            self._detail_pending = job
        else:
            self._start_detail(job)

    def _start_detail(self, job):
        job_id, region, out_w = job
        worker = ViewWorker(self.doc, region, out_w, job_id, self)
        worker.done.connect(self._on_detail_done, Qt.QueuedConnection)
        worker.failed.connect(self._on_detail_failed, Qt.QueuedConnection)
        worker.finished.connect(self._on_detail_finished)
        self._detail_worker = worker
        worker.start()

    def _on_detail_done(self, image, region, job_id):
        if job_id == self._detail_job:  # ignore results that are already out of date
            self.canvas.set_detail(pil_to_pixmap(image), region)
            self._show_plugin_errors()

    def _on_detail_failed(self, message, job_id):
        if job_id == self._detail_job:
            self.statusBar().showMessage(f"Zoomed view: {message}", 6000)

    def _on_detail_finished(self):
        worker, self._detail_worker = self._detail_worker, None
        if worker is not None:
            worker.deleteLater()
        if self._detail_pending is not None:
            job, self._detail_pending = self._detail_pending, None
            self._start_detail(job)

    # ================= live items from plugins (Alpha Overlays) =================
    def set_canvas_items(self, owner, items):
        """A plugin gives the preview draggable items: a list of (model, pixmap)."""
        self._canvas_items[owner] = list(items)
        self._flatten_canvas_items()

    def clear_canvas_items(self):
        self._canvas_items.clear()
        self._locked_owners.clear()
        self._flatten_canvas_items()
        self.canvas.set_locks(overlays=False)

    def _flatten_canvas_items(self):
        flat, owners = [], []
        for owner, items in self._canvas_items.items():
            for i, item in enumerate(items):
                flat.append(item)
                owners.append((owner, i))
        self._item_owner = owners
        self.canvas.set_overlays(flat)

    def select_canvas_item(self, owner, index: int):
        for flat_index, (o, i) in enumerate(self._item_owner):
            if o is owner and i == index:
                self.canvas.select_overlay(flat_index)
                return

    def _on_canvas_item_selected(self, flat_index: int):
        for owner in self._canvas_items:
            owner.on_canvas_item_selected(-1)  # deselect everywhere first
        if 0 <= flat_index < len(self._item_owner):
            owner, local = self._item_owner[flat_index]
            owner.on_canvas_item_selected(local)

    def _on_canvas_item_edited(self, flat_index: int):
        if 0 <= flat_index < len(self._item_owner):
            owner, local = self._item_owner[flat_index]
            owner.on_canvas_item_edited(local)

    def canvas_items_locked(self, owner, locked: bool):
        (self._locked_owners.add if locked else self._locked_owners.discard)(owner)
        self.canvas.set_locks(overlays=bool(self._locked_owners))

    def set_photos_interactive(self, on: bool):
        self._photos_interactive = bool(on)
        self._refresh_canvas_photos()

    # ================= photos (the composition) =================
    def add_photos(self, paths=None):
        """Add one or more pictures to the composition (File > Add photo, or the Photos box)."""
        if not self.doc:
            self.open_image()  # nothing open yet: the first picture simply opens
            return
        if not self.centralWidget().isEnabled():
            return
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "Add photos to the composition", "", OPEN_FILTER)
        added = 0
        for path in paths or []:
            try:
                self.doc.add_photo(Photo.open(path))
                added += 1
            except ValueError as exc:  # e.g. the photo limit
                QMessageBox.information(self, "Add photo", str(exc))
                break
            except Exception as exc:  # corrupt / unsupported file
                QMessageBox.warning(self, "Could not add photo", f"{Path(path).name}\n\n{exc}")
        if added:
            self._after_photos_changed()
            self.cat_photos.set_expanded(True)

    def _set_busy(self, busy: bool):
        self.centralWidget().setEnabled(not busy)
        self.dock.setEnabled(not busy)

    def _after_photos_changed(self):
        self._refresh_photo_views()
        self._sync_controls()
        self.crop_canvas.zoom_fit()
        self.btn_preview.setChecked(True)
        self._update_canvas()

    def _refresh_photo_views(self):
        """After the photo list or the selection changed: list, preview selection, crop pane, cut-out box."""
        self.photos_panel.refresh()
        self._refresh_canvas_photos()
        self._crop_pm_photo = None  # the crop pane shows the selected photo
        if self.doc:
            self.plugin_manager.document_changed(self.doc)  # plugins that follow the selected photo

    def _refresh_canvas_photos(self):
        if not self.doc:
            return
        draggable = self._photos_interactive  # a plugin (Pattern / Poster) turns photos into tiles
        self.canvas.set_photos(self.doc.photos if draggable else [])
        self.canvas.select_photo(self.doc.active if draggable else -1)

    def _on_photo_selected(self, index: int):
        if not self.doc or not 0 <= index < len(self.doc.photos) or index == self.doc.active:
            return
        self.doc.active = index
        self._refresh_photo_views()
        self._sync_controls()
        self.crop_canvas.zoom_fit()
        self._update_crop_canvas()

    def _on_canvas_photo_selected(self, index: int):
        if index >= 0:
            self._on_photo_selected(index)

    def _on_canvas_photo_edited(self, index: int):
        """A photo is being dragged / resized in the preview."""
        self.photos_panel.refresh_controls()
        if not self._live_timer.isActive():
            self._live_timer.start()  # redraw at a steady, quick rate while dragging

    def _on_photo_adjusted(self):
        self.canvas.update()
        self._schedule_preview()

    def _live_preview(self):
        if not self.doc or not self.btn_preview.isChecked():
            return
        try:
            img = self.doc.render(max_side=LIVE_MAX_SIDE, overlays=False)
        except Exception:
            return
        self.canvas.set_image(pil_to_pixmap(img), self.doc.final_size)
        self.canvas.clear_detail()

    def _remove_photo(self):
        if not self.doc:
            return
        try:
            self.doc.remove_photo(self.doc.active)
        except ValueError as exc:
            QMessageBox.information(self, "Remove photo", str(exc))
            return
        self._after_photos_changed()

    def _move_photo(self, step: int):
        if self.doc:
            self.doc.move_photo(self.doc.active, step)
            self._refresh_photo_views()
            self._update_preview_canvas()

    # ================= resetting a category =================
    def _reset_photo_placement(self):
        if self.doc:
            self.doc.active_photo.reset_placement(is_base=(self.doc.active == 0))
            self._refresh_photo_views()
            self._update_preview_canvas()

    # ================= undo / redo =================
    def _take_snapshot(self) -> Snapshot:
        key, data = self.doc.snapshot()
        plugins = self.plugin_manager.get_states()
        return Snapshot((key, json.dumps(plugins, sort_keys=True, default=str)), (data, plugins))

    def _poll_history(self):
        """Record the state once it has stopped changing (so a slider drag is ONE undo step)."""
        if not self.doc or self._restoring or not self.centralWidget().isEnabled():
            return
        snap = self._take_snapshot()
        if snap.key == self._history.current_key:
            self._hist_pending = None
        elif snap.key == self._hist_pending:  # unchanged since the last check: it has settled
            self._history.push(snap)
            self._hist_pending = None
            self._update_undo_buttons()
        else:
            self._hist_pending = snap.key

    def _flush_history(self):
        """Record any change that has not been picked up yet (called before undo / redo)."""
        if self.doc:
            snap = self._take_snapshot()
            if snap.key != self._history.current_key:
                self._history.push(snap)
        self._hist_pending = None

    def undo(self):
        if not self.doc or not self.centralWidget().isEnabled():
            return
        self._flush_history()
        snap = self._history.undo()
        if snap is not None:
            self._restore_snapshot(snap)
        self._update_undo_buttons()

    def redo(self):
        if not self.doc or not self.centralWidget().isEnabled():
            return
        snap = self._history.redo()
        if snap is not None:
            self._restore_snapshot(snap)
        self._update_undo_buttons()

    def _restore_snapshot(self, snap: Snapshot):
        self._restoring = True
        try:
            doc_data, plugins = snap.data
            self.doc.restore(doc_data)
            self.plugin_manager.set_states(plugins)
            self._refresh_photo_views()
            self._sync_controls()
            self._update_canvas()
        finally:
            self._restoring = False
        self._hist_pending = None

    def _update_undo_buttons(self):
        ready = self.doc is not None and self.centralWidget().isEnabled()
        self.btn_undo.setEnabled(bool(ready and self._history.can_undo))
        self.btn_redo.setEnabled(bool(ready and self._history.can_redo))

    # ----- closing -----
    def closeEvent(self, event):
        self.plugin_manager.save_state()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        for name in ("_detail_worker", "_worker", "_export_worker"):
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    worker.wait(5000)  # let background jobs finish so Qt doesn't abort
            except RuntimeError:  # already deleted
                pass
        super().closeEvent(event)
