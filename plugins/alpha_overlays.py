"""Alpha Overlays - put up to four alpha pictures (stickers, frames, flourishes) on top of the canvas.

  1. Click "Choose alpha folder..." once (it is remembered). PNG / WebP / TIFF files with transparency.
     Sub-folders are included.
  2. Pick an alpha from a layer's drop-down. In the Preview, drag it to move it, drag its corner handle
     (or Shift + mouse wheel) to resize it. Size, Opacity, Visible and Centre are in the layer's box.
  3. Up / Down change the layer order (the first layer in the list is the top one).

The overlays sit on top of everything else (photos, pattern, filters, text). They keep their place and
settings when you open the next image. The export draws them at full size in exactly the same place.
Switching the plugin off (or deleting this file) removes alpha overlays from the app.
"""
from functools import lru_cache
from pathlib import Path

from PIL import Image

from imagewise.engine.blend import apply_opacity, paste_alpha
from imagewise.plugins.api import Plugin

NUM_SLOTS = 4  # layer order = list order (index 0 = bottom)
ALPHA_EXTS = {".png", ".webp", ".tif", ".tiff"}
MIN_SCALE, MAX_SCALE = 0.02, 2.0
MAX_OVERLAY_PIXELS = 600_000_000  # safety limit for absurdly large exports


def scan_folder(folder):
    """All alpha-capable image files in the folder (and its sub-folders), sorted by name."""
    if not folder or not Path(folder).is_dir():
        return []
    root = Path(folder)
    files = [p for p in root.rglob("*") if p.suffix.lower() in ALPHA_EXTS and p.is_file()]
    return sorted(files, key=lambda p: str(p.relative_to(root)).lower())


@lru_cache(maxsize=12)
def _load_cached(path, mtime):
    img = Image.open(path)
    img.load()
    return img.convert("RGBA")


def load_rgba(path):
    return _load_cached(str(path), Path(path).stat().st_mtime_ns)


class Overlay:
    """One alpha layer. Position and size are FRACTIONS of the canvas, so the preview and a full-size
    export line up and the overlay keeps its place if the canvas size changes."""

    def __init__(self, path=None, cx=0.5, cy=0.5, scale=0.4, opacity=1.0, visible=True):
        self.path = path  # file path (str) or None
        self.cx, self.cy = cx, cy  # centre, fraction of canvas width / height
        self.scale = scale  # overlay width, fraction of canvas width
        self.opacity = opacity  # 0..1
        self.visible = visible

    def to_dict(self):
        return {"path": self.path, "cx": self.cx, "cy": self.cy, "scale": self.scale,
                "opacity": self.opacity, "visible": self.visible}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("path") or None, float(d.get("cx", .5)), float(d.get("cy", .5)),
                   float(d.get("scale", .4)), float(d.get("opacity", 1.0)), bool(d.get("visible", True)))


class AlphaOverlays(Plugin):
    name = "Alpha Overlays"
    version = "1.0"
    author = "EK"
    description = "Up to four draggable alpha pictures from your own folder, with layer order, size and opacity."
    layer = 100  # on top of every other effect
    live_on_canvas = True  # drawn live (and draggable) on the preview; the export draws them at full size

    def __init__(self, host):
        super().__init__(host)
        self.overlays = [Overlay() for _ in range(NUM_SLOTS)]
        self.folder = ""
        self.files = []
        self._ui = None
        self._pixmaps = {}
        self._busy = False

    # ----- the export (previews skip this: the canvas draws the overlays live) -----
    def apply(self, image, ctx):
        items = [ov for ov in list(self.overlays) if ov.visible and ov.path]
        if not items:
            return image
        out = image.copy()
        cw, ch = ctx.whole_canvas(image)
        ox, oy = ctx.origin
        for ov in items:
            try:
                src = load_rgba(ov.path)
            except Exception:
                continue  # file moved / deleted: skip it
            tw = max(1, round(ov.scale * cw))
            th = max(1, round(tw * src.height / src.width))
            if tw * th > MAX_OVERLAY_PIXELS:
                raise ValueError("An overlay is too large at this output size. Reduce its size or the output size.")
            if ctx.preview:
                piece = src.resize((tw, th), Image.BILINEAR, reducing_gap=2.0)
            else:
                piece = src.resize((tw, th), Image.LANCZOS)
            apply_opacity(piece, ov.opacity)
            paste_alpha(out, piece, round(ov.cx * cw - tw / 2 - ox), round(ov.cy * ch - th / 2 - oy))
        return out

    # ----- remembered settings / undo -----
    def get_state(self):
        return {"folder": self.folder, "overlays": [ov.to_dict() for ov in self.overlays]}

    def set_state(self, state):
        items = [Overlay.from_dict(d) for d in state.get("overlays", [])][:NUM_SLOTS]
        while len(items) < NUM_SLOTS:
            items.append(Overlay())
        self.overlays = items
        folder = state.get("folder", "")
        if folder != self.folder:
            self.folder = folder
            self._rescan()
        self._sync_all()
        self._publish()

    def reset(self):
        self.overlays = [Overlay() for _ in range(NUM_SLOTS)]
        self._sync_all()
        self._publish()
        self.host.request_refresh()

    # ----- canvas callbacks (the user dragged / selected an overlay in the preview) -----
    def on_canvas_item_selected(self, index):
        self._highlight(index)

    def on_canvas_item_edited(self, index):
        self._sync_slot(index)

    # ======================= the sidebar controls =======================
    def create_panel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
            QPushButton, QSlider, QVBoxLayout, QWidget,
        )

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        ui = self._ui = {"slots": [], "QMessageBox": QMessageBox}

        def to_pixmap(path):
            """A display-size picture of the alpha for the preview (cached)."""
            key = (str(path), Path(path).stat().st_mtime_ns)
            if key not in self._pixmaps:
                small = load_rgba(path).copy()
                small.thumbnail((1200, 1200))
                data = small.tobytes("raw", "RGBA")
                qimg = QImage(data, small.width, small.height, small.width * 4, QImage.Format_RGBA8888).copy()
                self._pixmaps[key] = QPixmap.fromImage(qimg)
            return self._pixmaps[key]

        ui["to_pixmap"] = to_pixmap

        # ---- folder ----
        folder_label = QLabel("")
        folder_label.setWordWrap(True)
        row = QHBoxLayout()
        choose, refresh = QPushButton("Choose alpha folder..."), QPushButton("Refresh")
        row.addWidget(choose)
        row.addWidget(refresh)
        outer.addWidget(folder_label)
        outer.addLayout(row)
        tip = QLabel("In Preview: drag an overlay to move it, drag its corner handle or use Shift + mouse "
                     "wheel to resize. Layers are listed top first.")
        tip.setWordWrap(True)
        outer.addWidget(tip)
        ui["folder_label"] = folder_label

        def on_choose(_=False):
            chosen = QFileDialog.getExistingDirectory(panel, "Choose your alpha folder", self.folder)
            if chosen:
                self.folder = chosen
                self._rescan()
                self.host.request_refresh()

        choose.clicked.connect(on_choose)
        refresh.clicked.connect(lambda _=False: self._rescan())

        # ---- one box per layer, top layer first ----
        for k in range(NUM_SLOTS):
            outer.addWidget(self._make_slot(k, Qt, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                                            QLabel, QPushButton, QSlider, QVBoxLayout))
        self._rescan()
        self._sync_all()
        self._publish()
        return panel

    def _make_slot(self, k, Qt, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                   QSlider, QVBoxLayout):
        """Build the controls for panel position k (0 = top layer). Engine index = NUM_SLOTS - 1 - k."""
        idx = NUM_SLOTS - 1 - k
        title = f"Layer {k + 1}" + (" (top)" if k == 0 else " (bottom)" if k == NUM_SLOTS - 1 else "")
        box = QGroupBox(title)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(14)
        visible = QCheckBox("Visible")
        centre, up, down = QPushButton("Centre"), QPushButton("Up"), QPushButton("Down")
        up.setEnabled(k > 0)
        down.setEnabled(k < NUM_SLOTS - 1)
        row = QHBoxLayout()
        row.addWidget(visible)
        row.addStretch()
        for b in (centre, up, down):
            b.setMaximumWidth(60)
            row.addWidget(b)
        size_sl, op_sl = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
        size_sl.setRange(round(MIN_SCALE * 100), round(MAX_SCALE * 100))
        op_sl.setRange(0, 100)
        size_lbl, op_lbl = QLabel("40%"), QLabel("100%")
        for lbl in (size_lbl, op_lbl):
            lbl.setMinimumWidth(40)
        grid = QGridLayout()
        for r, (name, sl, lbl) in enumerate((("Size", size_sl, size_lbl), ("Opacity", op_sl, op_lbl))):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(sl, r, 1)
            grid.addWidget(lbl, r, 2)
        lay = QVBoxLayout(box)
        lay.addWidget(combo)
        lay.addLayout(row)
        lay.addLayout(grid)

        def ov():
            return self.overlays[idx]

        def changed():
            self._publish()
            self.host.request_refresh()

        def on_combo(_i):
            if self._busy:
                return
            path = combo.currentData() or None
            if path:
                try:
                    load_rgba(path)  # fail now, not later, if the file is bad
                except Exception as exc:
                    self._ui["QMessageBox"].warning(None, "Could not load alpha", str(exc))
                    path = None
            ov().path = path
            self._sync_slot(idx)
            changed()

        def on_visible(on):
            if not self._busy:
                ov().visible = on
                changed()

        def on_size(v):
            if not self._busy:
                ov().scale = v / 100
                size_lbl.setText(f"{v}%")
                changed()

        def on_opacity(v):
            if not self._busy:
                ov().opacity = v / 100
                op_lbl.setText(f"{v}%")
                changed()

        def on_centre(_=False):
            ov().cx = ov().cy = 0.5
            changed()

        def on_move(step):  # step -1 = up a layer (towards the top), +1 = down
            other = idx - step  # up = higher engine index
            if 0 <= other < NUM_SLOTS:
                self.overlays[idx], self.overlays[other] = self.overlays[other], self.overlays[idx]
                self._sync_all()
                changed()
                self._highlight(other)
                self.host.select_canvas_item(self, other)

        combo.currentIndexChanged.connect(on_combo)
        visible.toggled.connect(on_visible)
        size_sl.valueChanged.connect(on_size)
        op_sl.valueChanged.connect(on_opacity)
        centre.clicked.connect(on_centre)
        up.clicked.connect(lambda _=False: on_move(-1))
        down.clicked.connect(lambda _=False: on_move(1))
        self._ui["slots"].append({"box": box, "title": title, "combo": combo, "visible": visible,
                                  "size": size_sl, "op": op_sl, "size_lbl": size_lbl, "op_lbl": op_lbl, "idx": idx})
        return box

    # ----- folder and list of alphas -----
    def _rescan(self):
        self.files = scan_folder(self.folder)
        ui = self._ui
        if ui is not None:
            if self.folder:
                ui["folder_label"].setText(f"{self.folder}\n{len(self.files)} alpha file(s) found")
            else:
                ui["folder_label"].setText("No alpha folder chosen yet.")
            self._sync_all()

    def _label(self, path):
        try:
            return str(Path(path).relative_to(self.folder)) if self.folder else Path(path).name
        except ValueError:
            return Path(path).name

    # ----- model -> controls -----
    def _sync_all(self):
        if self._ui is None:
            return
        for s in self._ui["slots"]:
            self._sync_slot(s["idx"], rebuild_combo=True)

    def _sync_slot(self, idx, rebuild_combo=False):
        """Update one layer's controls. The drop-down is only rebuilt when asked (not while dragging)."""
        if self._ui is None:
            return
        s = next(x for x in self._ui["slots"] if x["idx"] == idx)
        ov = self.overlays[idx]
        self._busy = True
        try:
            if rebuild_combo:
                combo = s["combo"]
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("(none)", None)
                shown = [str(f) for f in self.files]
                for f in shown:
                    combo.addItem(self._label(f), f)
                if ov.path and ov.path not in shown:  # an alpha from another folder: keep it selectable
                    combo.insertItem(1, Path(ov.path).name, ov.path)
                combo.setCurrentIndex(max(0, combo.findData(ov.path)) if ov.path else 0)
                combo.blockSignals(False)
            for w in (s["visible"], s["size"], s["op"]):
                w.blockSignals(True)
            s["visible"].setChecked(ov.visible)
            s["size"].setValue(round(ov.scale * 100))
            s["op"].setValue(round(ov.opacity * 100))
            for w in (s["visible"], s["size"], s["op"]):
                w.blockSignals(False)
            s["size_lbl"].setText(f"{round(ov.scale * 100)}%")
            s["op_lbl"].setText(f"{round(ov.opacity * 100)}%")
        finally:
            self._busy = False

    def _highlight(self, index):
        if self._ui is None:
            return
        for s in self._ui["slots"]:
            s["box"].setTitle(("\u25cf " if s["idx"] == index else "") + s["title"])

    # ----- the live items on the preview -----
    def _publish(self):
        """Give the preview canvas the overlays to draw (and let the user drag)."""
        if self._ui is None:
            return
        items = []
        for ov in self.overlays:
            pm = None
            if ov.path:
                try:
                    pm = self._ui["to_pixmap"](ov.path)
                except Exception:
                    pm = None
            items.append((ov, pm))
        self.host.set_canvas_items(self, items)


PLUGIN = AlphaOverlays
