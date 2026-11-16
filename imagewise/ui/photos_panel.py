"""The Photos category: the list of pictures in the composition and the placement of the selected one.

The list shows the TOP layer first. Rows map to Document.photos indexes (0 = bottom).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from imagewise.engine.photo import MAX_PHOTO_SCALE, MIN_PHOTO_SCALE


class PhotosPanel(QWidget):
    addRequested = Signal()
    removeRequested = Signal()
    moveRequested = Signal(int)  # +1 = up a layer, -1 = down
    selectionChanged = Signal(int)  # Document.photos index
    adjusted = Signal()  # visibility / fill / size / rotation / opacity / position changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self._busy = False  # True while we update widgets from the model

        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.currentRowChanged.connect(self._on_row)

        self.btn_add = QPushButton("Add...")
        self.btn_remove = QPushButton("Remove")
        self.btn_up = QPushButton("Up")
        self.btn_down = QPushButton("Down")
        self.btn_add.clicked.connect(lambda _=False: self.addRequested.emit())
        self.btn_remove.clicked.connect(lambda _=False: self.removeRequested.emit())
        self.btn_up.clicked.connect(lambda _=False: self.moveRequested.emit(1))
        self.btn_down.clicked.connect(lambda _=False: self.moveRequested.emit(-1))
        buttons = QHBoxLayout()
        for b in (self.btn_add, self.btn_remove, self.btn_up, self.btn_down):
            buttons.addWidget(b)

        self.chk_visible = QCheckBox("Visible")
        self.chk_fill = QCheckBox("Fill canvas")
        self.chk_fill.setToolTip("Stretch this photo over the whole canvas. Untick to move, size and rotate it.")
        self.chk_visible.toggled.connect(self._on_visible)
        self.chk_fill.toggled.connect(self._on_fill)
        ticks = QHBoxLayout()
        ticks.addWidget(self.chk_visible)
        ticks.addWidget(self.chk_fill)
        ticks.addStretch()

        self.sl_size, self.lbl_size = self._slider(round(MIN_PHOTO_SCALE * 100), round(MAX_PHOTO_SCALE * 100))
        self.sl_rot, self.lbl_rot = self._slider(-180, 180)
        self.sl_opacity, self.lbl_opacity = self._slider(0, 100)
        self.sl_size.valueChanged.connect(self._on_size)
        self.sl_rot.valueChanged.connect(self._on_rotation)
        self.sl_opacity.valueChanged.connect(self._on_opacity)
        grid = QGridLayout()
        for row, (name, sl, lbl) in enumerate((("Size", self.sl_size, self.lbl_size),
                                               ("Rotate", self.sl_rot, self.lbl_rot),
                                               ("Opacity", self.sl_opacity, self.lbl_opacity))):
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(sl, row, 1)
            grid.addWidget(lbl, row, 2)

        self.btn_centre = QPushButton("Centre")
        self.btn_centre.clicked.connect(self._on_centre)
        tip = QLabel("In Preview: drag the selected photo to move it, drag its corner handle or "
                     "Shift + wheel to resize. Click a photo to select it.")
        tip.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        layout.addLayout(ticks)
        layout.addLayout(grid)
        layout.addWidget(self.btn_centre)
        layout.addWidget(tip)

    @staticmethod
    def _slider(lo: int, hi: int):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        label = QLabel("")
        label.setMinimumWidth(44)
        return slider, label

    # ----- model -> widgets -----
    def bind(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self):
        """Rebuild the list and the controls from the document."""
        if self.doc is None:
            return
        self._busy = True
        n = len(self.doc.photos)
        self.list.clear()
        for k in range(n):  # top layer first
            photo = self.doc.photos[n - 1 - k]
            self.list.addItem(photo.name + ("" if photo.visible else "  (hidden)"))
        self.list.setCurrentRow(n - 1 - self.doc.active)
        self._busy = False
        self.refresh_controls()

    def refresh_controls(self):
        """Update just the controls for the active photo (used while dragging on the canvas)."""
        if self.doc is None:
            return
        ph = self.doc.active_photo
        self._busy = True
        for w in (self.chk_visible, self.chk_fill, self.sl_size, self.sl_rot, self.sl_opacity):
            w.blockSignals(True)
        self.chk_visible.setChecked(ph.visible)
        self.chk_fill.setChecked(ph.fill)
        self.sl_size.setValue(round(ph.scale * 100))
        self.sl_rot.setValue(round(ph.rotation))
        self.sl_opacity.setValue(round(ph.opacity * 100))
        for w in (self.chk_visible, self.chk_fill, self.sl_size, self.sl_rot, self.sl_opacity):
            w.blockSignals(False)
        self.lbl_size.setText(f"{round(ph.scale * 100)}%")
        self.lbl_rot.setText(f"{round(ph.rotation)}\u00b0")
        self.lbl_opacity.setText(f"{round(ph.opacity * 100)}%")
        free = not ph.fill
        for w in (self.sl_size, self.sl_rot, self.btn_centre):
            w.setEnabled(free)  # a photo that fills the canvas has nothing to move, size or rotate
        n = len(self.doc.photos)
        self.btn_remove.setEnabled(n > 1)
        self.btn_up.setEnabled(self.doc.active < n - 1)
        self.btn_down.setEnabled(self.doc.active > 0)
        self._busy = False

    # ----- widgets -> model -----
    def _on_row(self, row: int):
        if self._busy or self.doc is None or row < 0:
            return
        self.selectionChanged.emit(len(self.doc.photos) - 1 - row)

    def _on_visible(self, on: bool):
        self.doc.active_photo.visible = on
        self._changed(rebuild=True)

    def _on_fill(self, on: bool):
        self.doc.active_photo.fill = on
        self._changed()

    def _on_size(self, v: int):
        self.doc.active_photo.scale = v / 100
        self.lbl_size.setText(f"{v}%")
        self._changed()

    def _on_rotation(self, v: int):
        self.doc.active_photo.rotation = float(v)
        self.lbl_rot.setText(f"{v}\u00b0")
        self._changed()

    def _on_opacity(self, v: int):
        self.doc.active_photo.opacity = v / 100
        self.lbl_opacity.setText(f"{v}%")
        self._changed()

    def _on_centre(self):
        ph = self.doc.active_photo
        ph.cx = ph.cy = 0.5
        self._changed()

    def _changed(self, rebuild: bool = False):
        if self._busy or self.doc is None:
            return
        if rebuild:
            self.refresh()
        else:
            self.refresh_controls()
        self.adjusted.emit()
