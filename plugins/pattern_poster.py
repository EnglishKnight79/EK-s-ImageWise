"""Pattern / Poster - repeat the photos across a poster-sized canvas.

Tick "Tile the image as a pattern" and the canvas becomes a poster of the size you choose, filled with
copies of your photos (cut-outs and crop shapes included). Every visible photo is mixed into the repeat.

  * Poster size and tile size are in cm; the DPI (Canvas size / output) sets the pixel size.
  * Gap, stagger (brick or half-drop), random rotation (Shuffle for a new arrangement), and a background
    colour or transparency.
  * Seamless repeat: the spacing is adjusted so a whole number of tiles fit and tiles crossing an edge
    wrap round, so the poster repeats perfectly if printed side by side.

Switching the plugin off (or deleting this file) removes the feature; the photos draw the canvas as usual.
"""
import dataclasses
import math
import random
from dataclasses import dataclass

from PIL import Image

from imagewise.engine.blend import paste_alpha
from imagewise.plugins.api import Plugin

STAGGERS = ("None", "Brick (offset rows)", "Half-drop (offset columns)")
MAX_TILES = 20000


@dataclass
class Pattern:
    enabled: bool = False
    canvas_w_cm: float = 100.0
    canvas_h_cm: float = 300.0
    tile_w_cm: float = 20.0  # tile height follows the image's aspect ratio
    gap_cm: float = 2.0
    stagger: int = 0  # index into STAGGERS
    seamless: bool = True
    random_rotation: bool = False
    max_angle: float = 15.0  # degrees, +/-
    transparent: bool = False
    bg_color: tuple = (255, 255, 255)
    seed: int = 1

    def canvas_px(self, dpi) -> tuple:
        return (max(1, round(self.canvas_w_cm / 2.54 * dpi)),
                max(1, round(self.canvas_h_cm / 2.54 * dpi)))

    def estimate(self, dpi) -> tuple:
        """(width px, height px, megapixels, approx. memory in MB) of the full-size canvas."""
        w, h = self.canvas_px(dpi)
        channels = 4 if self.transparent else 3
        return w, h, w * h / 1e6, w * h * channels / 1e6


def _rotate_rgba(img, angle):
    """Rotate with transparent corners, premultiplied so edges don't pick up dark fringes."""
    try:
        return img.convert("RGBa").rotate(angle, resample=Image.BICUBIC, expand=True).convert("RGBA")
    except (ValueError, OSError):
        return img.rotate(angle, resample=Image.BICUBIC, expand=True)


def render_pattern(p, size, px_per_cm, make_motifs, full_size=None, origin=(0.0, 0.0), background=None):
    """Draw the pattern on a canvas of `size` pixels.

    make_motifs(tile_width_px) must return the RGBA motifs (one per photo, each that wide). With several,
    every tile picks one at random (repeatably, from the seed).

    To draw only a window of a bigger poster (zoomed preview), pass the whole poster's size as `full_size`
    and the window's top-left corner as `origin` (same pixel units as px_per_cm).
    """
    vw, vh = size
    W, H = full_size or size
    ox, oy = origin
    if background is not None:  # e.g. a canvas gradient; overrides the pattern's own background
        canvas = background.convert("RGB")
    elif p.transparent:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    else:
        canvas = Image.new("RGB", size, tuple(p.bg_color))

    tw = max(1, round(p.tile_w_cm * px_per_cm))
    motifs = make_motifs(tw)
    th = max(m.height for m in motifs)  # the tallest motif sets the row spacing
    gap = p.gap_cm * px_per_cm
    pitch_x, pitch_y = max(1.0, tw + gap), max(1.0, th + gap)
    brick, drop = p.stagger == 1, p.stagger == 2

    if p.seamless:
        ncols = max(1, round(W / pitch_x))
        nrows = max(1, round(H / pitch_y))
        if brick and nrows % 2:
            nrows += 1  # offset rows must pair up to wrap cleanly
        if drop and ncols % 2:
            ncols += 1
        pitch_x, pitch_y = W / ncols, H / nrows
        cols, rows = range(ncols), range(nrows)
        origin_x, origin_y = pitch_x / 2, pitch_y / 2  # first tile centre
        wraps = [(dx, dy) for dx in (-W, 0, W) for dy in (-H, 0, H)]
    else:
        nx = math.ceil(W / 2 / pitch_x) + 2
        ny = math.ceil(H / 2 / pitch_y) + 2
        cols, rows = range(-nx, nx + 1), range(-ny, ny + 1)
        origin_x, origin_y = W / 2, H / 2  # a tile sits in the middle of the canvas
        wraps = [(0, 0)]

    if len(cols) * len(rows) > MAX_TILES:
        raise ValueError("That would need too many tiles. Make the tiles bigger or the gap larger.")

    use_rotation = p.random_rotation and p.max_angle > 0
    ext = math.hypot(tw, th) / 2 + 2  # largest half-size a (rotated) tile can have
    rox, roy = round(ox), round(oy)
    for iy in rows:
        for ix in cols:
            cx = origin_x + ix * pitch_x + (pitch_x / 2 if brick and iy % 2 else 0)
            cy = origin_y + iy * pitch_y + (pitch_y / 2 if drop and ix % 2 else 0)
            # skip copies that cannot touch the visible window (keeps zoomed views fast)
            visible = [(dx, dy) for dx, dy in wraps
                       if cx + dx + ext >= ox and cx + dx - ext <= ox + vw
                       and cy + dy + ext >= oy and cy + dy - ext <= oy + vh]
            if not visible:
                continue
            rng = random.Random(f"{p.seed}:{ix}:{iy}")
            piece = motifs[rng.randrange(len(motifs))] if len(motifs) > 1 else motifs[0]
            if use_rotation:
                piece = _rotate_rgba(piece, rng.uniform(-p.max_angle, p.max_angle))
            left, top = round(cx - piece.width / 2), round(cy - piece.height / 2)
            for dx, dy in visible:
                paste_alpha(canvas, piece, round(left + dx) - rox, round(top + dy) - roy)
    return canvas


class PatternPoster(Plugin):
    name = "Pattern / Poster"
    version = "1.0"
    author = "EK"
    description = "Repeat your photos across a poster-sized canvas, with seamless repeat, stagger and rotation."

    def __init__(self, host):
        super().__init__(host)
        self.p = Pattern()
        self._enabled = True
        self._ui = None
        self._busy = False

    # ----- the plugin tick switches the whole feature on or off -----
    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, on):
        self._enabled = bool(on)
        self._apply_host_flags()

    def _active(self):
        return self._enabled and self.p.enabled

    def _apply_host_flags(self):
        """Tell the app when the canvas size comes from the pattern and the photos are tiles."""
        on = self._active()
        self.host.block_canvas_size(on)
        self.host.set_photos_interactive(not on)

    # ----- the canvas (called by the render engine; may run on a background thread) -----
    def canvas_size(self, document):
        return self.p.canvas_px(document.dpi) if self.p.enabled else None

    def render_base(self, document, full_size, scale, preview, origin, size, is_full, background):
        if not self.p.enabled:
            return None
        visible = [ph for ph in document.photos if ph.visible]
        if not visible:
            return Image.new("RGBA", size, (0, 0, 0, 0))

        def make_motifs(tile_w):
            return [ph.prepare(tile_w, max(1, round(tile_w * ph.aspect)), scale, preview).convert("RGBA")
                    for ph in visible]

        return render_pattern(self.p, size, document.dpi / 2.54 * scale, make_motifs,
                              full_size=full_size, origin=origin, background=background)

    # ----- remembered settings / undo -----
    def get_state(self):
        d = dataclasses.asdict(self.p)
        d["bg_color"] = list(d["bg_color"])
        return d

    def set_state(self, state):
        names = {f.name for f in dataclasses.fields(Pattern)}
        p = Pattern(**{k: v for k, v in state.items() if k in names})
        p.bg_color = tuple(p.bg_color)
        self.p = p
        self._apply_host_flags()
        self._sync()

    def reset(self):
        self.p = Pattern()
        self._apply_host_flags()
        self._sync()
        self.host.request_refresh()

    def on_document_changed(self, document):
        self._sync()  # e.g. the DPI shown in the size note

    # ======================= the sidebar controls =======================
    def create_panel(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import (
            QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSpinBox, QWidget,
        )

        def dspin(lo, hi, value, suffix=" cm"):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(1)
            sp.setSingleStep(1.0)
            sp.setSuffix(suffix)
            sp.setValue(value)
            return sp

        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        u = self._ui = {}
        u["on"] = QCheckBox("Tile the image as a pattern")
        u["w"], u["h"] = dspin(1, 2000, 100), dspin(1, 2000, 300)
        u["tile"], u["gap"] = dspin(0.5, 1000, 20), dspin(-100, 1000, 2)
        u["stagger"] = QComboBox()
        u["stagger"].addItems(list(STAGGERS))
        u["seamless"] = QCheckBox("Seamless repeat (edges wrap)")
        u["seamless"].setToolTip("Adjusts the spacing so a whole number of tiles fit, so the poster "
                                 "repeats perfectly if printed side by side.")
        u["rot"] = QCheckBox("Random rotation")
        u["angle"] = QSpinBox()
        u["angle"].setRange(1, 180)
        u["angle"].setSuffix(" deg max")
        u["transparent"] = QCheckBox("Transparent background")
        u["bg"] = QPushButton("Background colour...")
        u["seed"] = QSpinBox()
        u["seed"].setRange(1, 999999)
        u["shuffle"] = QPushButton("Shuffle")
        u["shuffle"].setToolTip("Pick a different random arrangement of rotations")
        u["info"] = QLabel("")
        u["info"].setWordWrap(True)

        form.addRow(u["on"])
        form.addRow("Poster width", u["w"])
        form.addRow("Poster height", u["h"])
        form.addRow("Tile width", u["tile"])
        form.addRow("Gap", u["gap"])
        form.addRow("Stagger", u["stagger"])
        form.addRow(u["seamless"])
        form.addRow(u["rot"])
        form.addRow("Angle", u["angle"])
        form.addRow("Arrangement", u["seed"])
        form.addRow(u["shuffle"])
        form.addRow(u["transparent"])
        form.addRow(u["bg"])
        form.addRow(u["info"])

        def pick_bg(_=False):
            chosen = QColorDialog.getColor(QColor(*self.p.bg_color), panel, "Background colour")
            if chosen.isValid():
                self.p.bg_color = (chosen.red(), chosen.green(), chosen.blue())
                self._sync()
                self.host.request_refresh()

        u["bg"].clicked.connect(pick_bg)
        u["shuffle"].clicked.connect(lambda _=False: u["seed"].setValue(random.randint(1, 999999)))
        for sig in (u["on"].toggled, u["w"].valueChanged, u["h"].valueChanged, u["tile"].valueChanged,
                    u["gap"].valueChanged, u["stagger"].currentIndexChanged, u["seamless"].toggled,
                    u["rot"].toggled, u["angle"].valueChanged, u["transparent"].toggled, u["seed"].valueChanged):
            sig.connect(self._on_changed)
        self._sync()
        return panel

    def _on_changed(self, *_):
        if self._busy or self._ui is None:
            return
        u, p = self._ui, self.p
        was_on = p.enabled
        p.enabled = u["on"].isChecked()
        p.canvas_w_cm, p.canvas_h_cm = u["w"].value(), u["h"].value()
        p.tile_w_cm, p.gap_cm = u["tile"].value(), u["gap"].value()
        p.stagger = u["stagger"].currentIndex()
        p.seamless = u["seamless"].isChecked()
        p.random_rotation = u["rot"].isChecked()
        p.max_angle = float(u["angle"].value())
        p.transparent = u["transparent"].isChecked()
        p.seed = u["seed"].value()
        doc = self.host.document
        if p.enabled and not was_on and doc is not None and doc.dpi > 150:
            doc.dpi = 100  # a 3 m poster at 300 DPI would be over 400 megapixels
        self._apply_host_flags()
        self._sync()
        self.host.request_refresh()

    def _sync(self):
        """Show the current settings in the controls (without triggering their handlers)."""
        u, p = self._ui, self.p
        if u is None:
            return
        self._busy = True
        try:
            for key, value in (("on", p.enabled), ("seamless", p.seamless), ("rot", p.random_rotation),
                               ("transparent", p.transparent)):
                u[key].setChecked(bool(value))
            for key, value in (("w", p.canvas_w_cm), ("h", p.canvas_h_cm), ("tile", p.tile_w_cm), ("gap", p.gap_cm)):
                u[key].setValue(float(value))
            u["stagger"].setCurrentIndex(int(p.stagger))
            u["angle"].setValue(round(p.max_angle))
            u["seed"].setValue(int(p.seed))
            for key in ("angle", "seed", "shuffle"):
                u[key].setEnabled(p.random_rotation)
            u["bg"].setEnabled(not p.transparent)
            r, g, b = p.bg_color
            u["bg"].setStyleSheet(f"border-left: 18px solid rgb({r},{g},{b});")
            doc = self.host.document
            if p.enabled and doc is not None:
                w, h, mp, mb = p.estimate(doc.dpi)
                text = f"Output: {w} x {h} px at {doc.dpi} DPI ({mp:.0f} megapixels, about {mb / 1000:.1f} GB of memory)."
                big = mp > 200
                if big:
                    text += " That is very large: lower the DPI if export is slow or fails."
                u["info"].setText(text)
                u["info"].setStyleSheet("color: #d9534f;" if big else "")
            else:
                u["info"].setText("")
        finally:
            self._busy = False


PLUGIN = PatternPoster
