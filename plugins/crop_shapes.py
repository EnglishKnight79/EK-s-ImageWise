"""Crop Shapes - crop the selected photo to a shape taken from a folder of pictures.

How to use
  1. Put your shape pictures in a folder (the default is  <home>/EKImageWise/shapes ) or type / browse to any
     other folder. Sub-folders are included.
  2. Click a shape in the list. The selected photo is cropped to it; everything outside the shape becomes
     transparent. Click "None" to remove the shape.
  3. Use Shape size and Rotate to scale and turn the shape. Move or resize the crop box in the Crop pane to
     choose which part of the photo shows through.

What a shape picture can be (PNG, WebP, TIFF, BMP or JPG)
  * a picture with transparency: the visible part is the shape, or
  * a plain picture: a dark shape on a light background, or a light shape on a dark background
    (it works out which). If it gets it the wrong way round, tick "Invert shape".

The shape settings belong to each photo, so every photo in a composition can have its own shape.
Switching this plugin off (or removing it) removes crop shapes from the app.
"""
from pathlib import Path

from PIL import Image

from imagewise.engine import shapes
from imagewise.plugins.api import Plugin

THUMB = 56
MAX_LISTED = 400  # shapes shown in the list


def default_folder() -> str:
    return str(Path.home() / "EKImageWise" / "shapes")


def make_thumb(path) -> Image.Image:
    """A small picture of the shape for the list (light shape on a dark card)."""
    mask = shapes.load_mask(path).copy()
    mask.thumbnail((THUMB - 10, THUMB - 10))
    card = Image.new("RGBA", (THUMB, THUMB), (74, 74, 86, 255))
    shape = Image.new("RGBA", mask.size, (245, 245, 250, 255))
    shape.putalpha(mask)
    card.alpha_composite(shape, ((THUMB - mask.width) // 2, (THUMB - mask.height) // 2))
    return card


class CropShapes(Plugin):
    name = "Crop Shapes"
    version = "1.0"
    author = "EK"
    description = "Crop the selected photo to a shape from your own folder of shape pictures. Scale and rotate it."

    def __init__(self, host):
        super().__init__(host)
        self._enabled = True
        shapes.set_active(True)  # the app only applies crop shapes while this plugin is loaded and on
        self.folder = default_folder()
        self.files = []
        self._ui = None
        self._busy = False

    # ----- switching the plugin off switches crop shapes off -----
    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, on):
        self._enabled = bool(on)
        shapes.set_active(self._enabled)

    # ----- remembered settings (the folder) / undo -----
    def get_state(self):
        return {"folder": self.folder}

    def set_state(self, state):
        folder = state.get("folder") or default_folder()
        if folder != self.folder:
            self.folder = folder
            if self._ui is not None:
                self._ui["path"].setText(folder)
                self._rescan()
        self._sync()

    def reset(self):
        """Remove the shape from the selected photo (the folder is kept)."""
        ph = self._photo()
        if ph is not None:
            ph.reset_shape()
        self._sync()
        self.host.request_refresh()

    def on_document_changed(self, document):
        self._sync()  # another image / photo was selected, or Undo changed things

    def _photo(self):
        doc = self.host.document
        return doc.active_photo if doc is not None else None

    # ======================= the sidebar controls =======================
    def create_panel(self):
        from PySide6.QtCore import QSize, Qt, QUrl
        from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
        from PySide6.QtWidgets import (
            QCheckBox, QColorDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
            QListWidgetItem, QPushButton, QSlider, QVBoxLayout, QWidget,
        )

        def to_icon(img):
            data = img.convert("RGBA").tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()
            return QIcon(QPixmap.fromImage(qimg))

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        ui = self._ui = {}

        # ---- folder ----
        outer.addWidget(QLabel("Folder of shape pictures"))
        path = QLineEdit(self.folder)
        path.setPlaceholderText("Type or paste a folder path")
        row = QHBoxLayout()
        browse, refresh, open_btn = QPushButton("Browse..."), QPushButton("Refresh"), QPushButton("Open")
        for b in (browse, refresh, open_btn):
            row.addWidget(b)
        outer.addWidget(path)
        outer.addLayout(row)
        status = QLabel("")
        status.setWordWrap(True)
        outer.addWidget(status)

        def on_path():
            self.folder = path.text().strip() or default_folder()
            self._rescan()
            self.host.request_refresh()  # (also lets Undo history notice the folder change)

        def on_browse(_=False):
            chosen = QFileDialog.getExistingDirectory(panel, "Choose your folder of shape pictures", self.folder)
            if chosen:
                path.setText(chosen)
                on_path()

        def on_open(_=False):
            Path(self.folder).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))

        path.editingFinished.connect(on_path)
        browse.clicked.connect(on_browse)
        refresh.clicked.connect(lambda _=False: self._rescan())
        open_btn.clicked.connect(on_open)

        # ---- the shapes, as a picture list ----
        shape_list = QListWidget()
        shape_list.setViewMode(QListWidget.IconMode)
        shape_list.setIconSize(QSize(THUMB, THUMB))
        shape_list.setResizeMode(QListWidget.Adjust)
        shape_list.setMovement(QListWidget.Static)
        shape_list.setSpacing(4)
        shape_list.setGridSize(QSize(THUMB + 16, THUMB + 30))
        shape_list.setMinimumHeight(150)
        shape_list.setMaximumHeight(230)
        outer.addWidget(shape_list)

        def on_pick(current, _previous):
            ph = self._photo()
            if self._busy or current is None or ph is None:
                return
            ph.shape = current.data(Qt.UserRole) or None
            self._sync()
            self.host.request_refresh()

        shape_list.currentItemChanged.connect(on_pick)

        # ---- shape settings (stored on the selected photo) ----
        def slider(label_text, lo, hi, fmt, setter):
            label = QLabel(label_text)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)

            def on(v):
                ph = self._photo()
                if ph is not None and not self._busy:
                    setter(ph, v)
                    label.setText(fmt(v))
                    self.host.request_refresh()

            s.valueChanged.connect(on)
            outer.addWidget(label)
            outer.addWidget(s)
            return s, label

        ui["size"], ui["size_lbl"] = slider("Shape size: 100%", 20, 100, lambda v: f"Shape size: {v}%",
                                            lambda ph, v: setattr(ph, "shape_scale", v / 100))
        ui["rot"], ui["rot_lbl"] = slider("Rotate: 0\u00b0", -180, 180, lambda v: f"Rotate: {v}\u00b0",
                                          lambda ph, v: setattr(ph, "shape_rotation", float(v)))

        invert = QCheckBox("Invert shape (swap inside and outside)")
        invert.toggled.connect(lambda on: self._set(lambda ph: setattr(ph, "shape_invert", on)))
        outer.addWidget(invert)

        outline = QCheckBox("Outline")
        outline.toggled.connect(lambda on: self._set(lambda ph: setattr(ph, "outline", on)))
        colour = QPushButton("Outline colour...")

        def on_colour(_=False):
            ph = self._photo()
            if ph is None:
                return
            chosen = QColorDialog.getColor(QColor(*ph.outline_color), panel, "Outline colour")
            if chosen.isValid():
                ph.outline_color = (chosen.red(), chosen.green(), chosen.blue())
                self._sync()
                self.host.request_refresh()

        colour.clicked.connect(on_colour)
        ui["owidth"], ui["owidth_lbl"] = slider("Outline width: 6 px", 1, 80, lambda v: f"Outline width: {v} px",
                                                lambda ph, v: setattr(ph, "outline_width", v))
        # the outline checkbox and colour sit above its width slider
        outer.insertWidget(outer.indexOf(ui["owidth_lbl"]), outline)
        outer.insertWidget(outer.indexOf(ui["owidth_lbl"]), colour)

        hint = QLabel("Move or resize the crop box in the Crop pane to choose which part of the photo "
                      "shows through the shape.")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        ui.update(path=path, status=status, list=shape_list, invert=invert, outline=outline, colour=colour,
                  QListWidgetItem=QListWidgetItem, to_icon=to_icon, Qt=Qt)
        self._rescan()
        return panel

    def _set(self, fn):
        ph = self._photo()
        if ph is not None and not self._busy:
            fn(ph)
            self._sync()
            self.host.request_refresh()

    # ----- the list of shapes -----
    def _rescan(self):
        ui = self._ui
        if ui is None:
            return
        folder = Path(self.folder)
        if self.folder == default_folder() and not folder.exists():
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        self.files = []
        for f in shapes.scan_folder(folder)[:MAX_LISTED]:
            if shapes.usable(f):  # skips blank / unreadable pictures
                self.files.append(f)
        lst, Item, Qt = ui["list"], ui["QListWidgetItem"], ui["Qt"]
        self._busy = True
        lst.clear()
        none = Item("None")
        none.setData(Qt.UserRole, "")
        lst.addItem(none)
        for f in self.files:
            try:
                item = Item(ui["to_icon"](make_thumb(f)), f.stem[:14])
            except Exception:
                continue
            item.setData(Qt.UserRole, str(f))
            item.setToolTip(str(f))
            lst.addItem(item)
        self._busy = False
        if not folder.is_dir():
            ui["status"].setText(f"Folder not found: {self.folder}")
        elif not self.files:
            ui["status"].setText("No shape pictures found in this folder yet. Add PNG files with a shape "
                                 "(transparent background, or dark on light) and press Refresh.")
        else:
            ui["status"].setText(f"{len(self.files)} shape(s) found.")
        self._sync()

    # ----- model -> controls -----
    def _sync(self):
        ui = self._ui
        if ui is None:
            return
        ph = self._photo()
        self._busy = True
        try:
            lst = ui["list"]
            current = (ph.shape or "") if ph is not None else ""
            row = 0
            for i in range(lst.count()):
                if lst.item(i).data(ui["Qt"].UserRole) == current:
                    row = i
                    break
            lst.setCurrentRow(row)
            has = bool(ph is not None and ph.active_shape())
            if ph is not None:
                for key, value, text in (("size", round(ph.shape_scale * 100), f"Shape size: {round(ph.shape_scale * 100)}%"),
                                         ("rot", round(ph.shape_rotation), f"Rotate: {round(ph.shape_rotation)}\u00b0"),
                                         ("owidth", int(ph.outline_width), f"Outline width: {int(ph.outline_width)} px")):
                    ui[key].blockSignals(True)
                    ui[key].setValue(value)
                    ui[key].blockSignals(False)
                    ui[key + "_lbl"].setText(text)
                for key, value in (("invert", ph.shape_invert), ("outline", ph.outline)):
                    ui[key].blockSignals(True)
                    ui[key].setChecked(bool(value))
                    ui[key].blockSignals(False)
                r, g, b = ph.outline_color
                ui["colour"].setStyleSheet(f"border-left: 18px solid rgb({r},{g},{b});")
            for key in ("size", "rot", "invert", "outline"):
                ui[key].setEnabled(has)
            outlined = has and bool(ph is not None and ph.outline)
            ui["colour"].setEnabled(outlined)
            ui["owidth"].setEnabled(outlined)
        finally:
            self._busy = False


PLUGIN = CropShapes
