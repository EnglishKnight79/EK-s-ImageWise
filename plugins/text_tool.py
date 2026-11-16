"""Text - add styled text to the picture (a small word-processor style tool).

Several text boxes, each with: multi-line text, any installed font (or your own
font file), size in cm, bold / italic / underline / strike-through, colour,
alignment, line and letter spacing, position, rotation, opacity, outline (colour
and width) and drop shadow (colour, offset, blur, opacity).

The text is drawn on the finished canvas (photos, pattern, filters) and before the
alpha overlays, on previews, zoomed views and the final export. Sizes are physical
(cm at the document's DPI), so the printed text is the size you ask for.
"""
import copy
import math
import os
import sys
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from imagewise.engine.blend import apply_opacity, paste_alpha
from imagewise.plugins.api import Plugin

# ======================================================================
# fonts
# ======================================================================
_FONT_INDEX = None  # {family: {"regular"|"bold"|"italic"|"bolditalic": path}}
PREFERRED = ["Arial", "Helvetica", "Helvetica Neue", "Segoe UI", "DejaVu Sans", "Liberation Sans", "Noto Sans"]


def _font_dirs():
    home = Path.home()
    dirs = []
    if sys.platform.startswith("win"):
        dirs += [Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
                 Path(os.environ.get("LOCALAPPDATA", str(home))) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
                 Path("/Library/Fonts"), home / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts", home / ".local" / "share" / "fonts"]
    return dirs


def _style_key(style):
    s = (style or "").lower()
    bold, italic = "bold" in s, ("italic" in s or "oblique" in s)
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    if s in ("", "regular", "book", "normal", "roman", "medium"):
        return "regular"
    return None  # light / black / condensed ... are skipped


def font_index(extra_dirs=()):
    """Scan the usual font folders once. Returns {family: {style: path}}."""
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    index = {}
    seen = 0
    for folder in list(_font_dirs()) + [Path(p) for p in extra_dirs]:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() not in (".ttf", ".otf") or not path.is_file():
                continue
            seen += 1
            if seen > 4000:
                break
            try:
                family, style = ImageFont.truetype(str(path), 12).getname()
            except Exception:
                continue
            key = _style_key(style)
            if key:
                index.setdefault(family, {}).setdefault(key, str(path))
    _FONT_INDEX = index
    return index


def families():
    return sorted(font_index(), key=str.lower)


def resolve_font(name, bold, italic):
    """-> (path or None, fake_bold, fake_italic). None means Pillow's built-in font."""
    if name and (os.sep in name or name.lower().endswith((".ttf", ".otf"))) and os.path.isfile(name):
        return name, bold, italic  # a font file picked by the user: no style variants known
    index = font_index()
    entry = index.get(name)
    if not entry:
        for pref in PREFERRED:
            if pref in index:
                entry = index[pref]
                break
    if not entry and index:
        entry = index[sorted(index)[0]]
    if not entry:
        return None, bold, italic
    want = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    if want in entry:
        return entry[want], False, False
    # no exact variant: use the closest one and imitate the missing style
    closest = {"bolditalic": ["bold", "italic", "regular"], "bold": ["regular"], "italic": ["regular"], "regular": []}
    for key in closest[want]:
        if key in entry:
            return entry[key], bold and "bold" not in key, italic and "italic" not in key
    path = entry.get("regular") or next(iter(entry.values()))
    return path, bold, italic


@lru_cache(maxsize=96)
def load_font(path, px):
    if path:
        try:
            return ImageFont.truetype(path, px)
        except Exception:
            pass
    try:
        return ImageFont.load_default(px)  # Pillow 10.1+: scalable built-in font
    except TypeError:
        return ImageFont.load_default()


# ======================================================================
# a text box and how it is drawn
# ======================================================================
@dataclass
class TextItem:
    text: str = ""
    font: str = ""  # family name, or a path to a .ttf / .otf file ("" = a sensible default)
    size_cm: float = 3.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: tuple = (0, 0, 0)
    align: str = "center"  # left | center | right
    line_spacing: float = 1.1
    tracking: float = 0.0  # letter spacing, % of the font size
    x: float = 50.0  # centre of the text, % of the canvas
    y: float = 50.0
    rotation: float = 0.0  # degrees, clockwise
    opacity: int = 100
    outline: bool = False
    outline_color: tuple = (255, 255, 255)
    outline_width: float = 6.0  # % of the font size
    shadow: bool = False
    shadow_color: tuple = (0, 0, 0)
    shadow_dx: float = 6.0  # % of the font size
    shadow_dy: float = 6.0
    shadow_blur: float = 8.0
    shadow_opacity: int = 60
    visible: bool = True

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        item = cls(**{k: v for k, v in d.items() if k in names})
        for k in ("color", "outline_color", "shadow_color"):
            setattr(item, k, tuple(getattr(item, k)))
        return item


def _shear(mask, amount):
    w, h = mask.size
    return mask.transform((w, h), Image.AFFINE, (1, amount, -amount * h / 2, 0, 1, 0), resample=Image.BILINEAR)


def _rotate_rgba(img, angle):
    try:
        return img.convert("RGBa").rotate(angle, resample=Image.BICUBIC, expand=True).convert("RGBA")
    except (ValueError, OSError):
        return img.rotate(angle, resample=Image.BICUBIC, expand=True)


def render_item(item, ctx):
    """The text box as a transparent RGBA picture at the render scale, or None if there is nothing to draw."""
    if not item.text.strip():
        return None
    px = max(2, round(item.size_cm / 2.54 * ctx.dpi * ctx.scale))
    path, fake_bold, fake_italic = resolve_font(item.font, item.bold, item.italic)
    font = load_font(path, px)
    lines = item.text.split("\n")
    track = item.tracking / 100 * px
    try:
        ascent, descent = font.getmetrics()
    except Exception:
        ascent, descent = px * 0.9, px * 0.25
    line_h = (ascent + descent) * item.line_spacing

    def width(line):
        if not line:
            return 0.0
        if track == 0:
            return font.getlength(line)
        return sum(font.getlength(ch) for ch in line) + track * (len(line) - 1)

    widths = [width(line) for line in lines]
    tw = max(widths)
    th = line_h * (len(lines) - 1) + ascent + descent
    stroke = round(item.outline_width / 100 * px) if item.outline else 0
    bold_stroke = max(1, round(px / 30)) if fake_bold else 0
    sdx, sdy = item.shadow_dx / 100 * px, item.shadow_dy / 100 * px
    sblur = item.shadow_blur / 100 * px
    pad = math.ceil(stroke + bold_stroke + 4 + (max(abs(sdx), abs(sdy)) + 3 * sblur if item.shadow else 0)
                    + (0.25 * th if fake_italic else 0))
    W, H = math.ceil(tw) + 2 * pad, math.ceil(th) + 2 * pad
    thick = max(1, round(px / 16))

    def draw_mask(extra_stroke):
        mask = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(mask)
        sw = bold_stroke + extra_stroke
        for i, line in enumerate(lines):
            lw = widths[i]
            x0 = pad + {"left": 0.0, "right": tw - lw}.get(item.align, (tw - lw) / 2)
            y0 = pad + i * line_h
            if line:
                if track == 0:
                    d.text((x0, y0), line, font=font, fill=255, stroke_width=sw, stroke_fill=255)
                else:
                    x = x0
                    for ch in line:
                        d.text((x, y0), ch, font=font, fill=255, stroke_width=sw, stroke_fill=255)
                        x += font.getlength(ch) + track
            if line and item.underline:
                top = y0 + ascent + thick
                d.rectangle((x0 - sw, top - sw, x0 + lw + sw, top + thick + sw), fill=255)
            if line and item.strike:
                mid = y0 + ascent * 0.62
                d.rectangle((x0 - sw, mid - thick / 2 - sw, x0 + lw + sw, mid + thick / 2 + sw), fill=255)
        return _shear(mask, 0.22) if fake_italic else mask

    fill_mask = draw_mask(0)
    edge_mask = draw_mask(stroke) if stroke else None

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if item.shadow:
        silhouette = edge_mask if edge_mask is not None else fill_mask
        soft = silhouette.filter(ImageFilter.GaussianBlur(sblur)) if sblur >= 0.3 else silhouette
        strength = max(0, min(100, item.shadow_opacity)) / 100
        soft = soft.point([round(v * strength) for v in range(256)])
        shadow = Image.new("RGBA", (W, H), tuple(item.shadow_color) + (0,))
        shadow.putalpha(soft)
        paste_alpha(layer, shadow, round(sdx), round(sdy))
    if edge_mask is not None:
        edge = Image.new("RGBA", (W, H), tuple(item.outline_color) + (0,))
        edge.putalpha(edge_mask)
        layer = Image.alpha_composite(layer, edge)
    fill = Image.new("RGBA", (W, H), tuple(item.color) + (0,))
    fill.putalpha(fill_mask)
    layer = Image.alpha_composite(layer, fill)

    if item.rotation:
        layer = _rotate_rgba(layer, -item.rotation)
    apply_opacity(layer, max(0, min(100, item.opacity)) / 100)
    return layer


# ======================================================================
# the plugin
# ======================================================================
class TextTool(Plugin):
    name = "Text"
    version = "1.0"
    author = "EK"
    description = "Add styled text: fonts, sizes in cm, outline, drop shadow, rotation and more."

    def __init__(self, host):
        super().__init__(host)
        self.items = [TextItem()]
        self.sel = 0
        self._ui = None

    # ----- the picture change (may run on a background thread: only reads settings) -----
    def apply(self, image, ctx):
        items = [it for it in list(self.items) if it.visible and it.text.strip()]
        if not items:
            return image
        out = image.copy()
        cw, ch = ctx.whole_canvas(image)
        ox, oy = ctx.origin
        for it in items:
            layer = render_item(it, ctx)
            if layer is not None:
                cx, cy = cw * it.x / 100 - ox, ch * it.y / 100 - oy
                paste_alpha(out, layer, round(cx - layer.width / 2), round(cy - layer.height / 2))
        return out

    # ----- remembered settings / undo -----
    def get_state(self):
        return {"items": [asdict(it) for it in self.items], "sel": self.sel}

    def set_state(self, state):
        items = [TextItem.from_dict(copy.deepcopy(d)) for d in state.get("items", [])]
        self.items = items or [TextItem()]
        self.sel = min(max(int(state.get("sel", 0)), 0), len(self.items) - 1)
        self._refresh_list()
        self._populate()

    def reset(self):
        self.items, self.sel = [TextItem()], 0
        self._refresh_list()
        self._populate()
        self.host.request_refresh()

    @property
    def current(self):
        return self.items[min(self.sel, len(self.items) - 1)]

    # ======================= the sidebar controls =======================
    def create_panel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import (
            QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
            QListWidget, QPlainTextEdit, QPushButton, QSlider, QVBoxLayout, QWidget,
        )

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        self._ui = {"binds": []}
        binds = self._ui["binds"]

        def changed():
            self.host.request_refresh()

        def refresh_current_row():
            row = self.list.item(self.sel)
            if row is not None:
                first = (self.current.text.strip().split("\n") or [""])[0]
                row.setText(first[:28] or "(empty text)")

        # ---- list of text boxes ----
        self.list = QListWidget()
        self.list.setMaximumHeight(84)
        self.list.currentRowChanged.connect(self._on_row)
        buttons = QHBoxLayout()
        for label, slot in (("Add", self._add_item), ("Copy", self._copy_item), ("Remove", self._remove_item)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=slot: f())
            buttons.addWidget(b)
        outer.addWidget(QLabel("Text boxes"))
        outer.addWidget(self.list)
        outer.addLayout(buttons)

        # ---- small generic helpers that bind a control to one attribute of the selected text box ----
        def bind_slider(form, label, attr, lo, hi, unit=""):
            row = QHBoxLayout()
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            v = QLabel("")
            v.setMinimumWidth(44)
            row.addWidget(s, 1)
            row.addWidget(v)

            def on(val, a=attr, lab=v, u=unit):
                setattr(self.current, a, val)
                lab.setText(f"{val}{u}")
                changed()

            s.valueChanged.connect(on)
            binds.append(("slider", attr, s, v, unit))
            form.addRow(label, row)
            return s

        def bind_check(form, text, attr):
            c = QCheckBox(text)

            def on(val, a=attr):
                setattr(self.current, a, val)
                changed()

            c.toggled.connect(on)
            binds.append(("check", attr, c, None, ""))
            form.addRow(c)
            return c

        def bind_colour(form, label, attr):
            b = QPushButton("")
            b.setFixedWidth(60)
            b.setToolTip("Pick a colour")

            def pick(_=False, a=attr):
                chosen = QColorDialog.getColor(QColor(*getattr(self.current, a)), panel, "Colour")
                if chosen.isValid():
                    setattr(self.current, a, (chosen.red(), chosen.green(), chosen.blue()))
                    self._populate()
                    changed()

            b.clicked.connect(pick)
            binds.append(("colour", attr, b, None, ""))
            form.addRow(label, b)
            return b

        # ---- text ----
        self.txt = QPlainTextEdit()
        self.txt.setFixedHeight(64)
        self.txt.setPlaceholderText("Type your text here")

        def on_text():
            self.current.text = self.txt.toPlainText()
            refresh_current_row()
            changed()

        self.txt.textChanged.connect(on_text)
        outer.addWidget(self.txt)

        # ---- character ----
        form = QFormLayout()
        self.font_box = QComboBox()
        self.font_box.currentIndexChanged.connect(self._on_font)
        add_font = QPushButton("Add font file...")

        def pick_font(_=False):
            path, _f = QFileDialog.getOpenFileName(panel, "Choose a font file", "", "Fonts (*.ttf *.otf)")
            if path:
                self.current.font = path
                self._populate()
                changed()

        add_font.clicked.connect(pick_font)
        form.addRow("Font", self.font_box)
        form.addRow(add_font)
        size = QDoubleSpinBox()
        size.setRange(0.2, 300.0)
        size.setDecimals(1)
        size.setSingleStep(0.5)
        size.setSuffix(" cm")

        def on_size(v):
            self.current.size_cm = v
            changed()

        size.valueChanged.connect(on_size)
        binds.append(("dspin", "size_cm", size, None, ""))
        form.addRow("Size", size)
        styles = QHBoxLayout()
        for attr, label, tip in (("bold", "B", "Bold"), ("italic", "I", "Italic"),
                                 ("underline", "U", "Underline"), ("strike", "S", "Strike-through")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.setToolTip(tip)
            b.toggled.connect(lambda on, a=attr: (setattr(self.current, a, on), changed()))
            binds.append(("check", attr, b, None, ""))
            styles.addWidget(b)
        styles.addStretch()
        form.addRow("Style", styles)
        align = QComboBox()
        align.addItems(["Left", "Centre", "Right"])
        align.currentIndexChanged.connect(
            lambda i: (setattr(self.current, "align", ["left", "center", "right"][i]), changed()))
        binds.append(("align", "align", align, None, ""))
        form.addRow("Align", align)
        bind_colour(form, "Colour", "color")
        spacing = QDoubleSpinBox()
        spacing.setRange(0.5, 4.0)
        spacing.setSingleStep(0.1)
        spacing.setDecimals(1)
        spacing.valueChanged.connect(lambda v: (setattr(self.current, "line_spacing", v), changed()))
        binds.append(("dspin", "line_spacing", spacing, None, ""))
        form.addRow("Line spacing", spacing)
        bind_slider(form, "Letter spacing", "tracking", -10, 100, "%")
        outer.addLayout(form)

        # ---- position ----
        pos = QFormLayout()
        bind_slider(pos, "Across", "x", 0, 100, "%")
        bind_slider(pos, "Down", "y", 0, 100, "%")
        bind_slider(pos, "Rotate", "rotation", -180, 180, "\u00b0")
        bind_slider(pos, "Opacity", "opacity", 0, 100, "%")
        centre = QPushButton("Centre on canvas")
        centre.clicked.connect(lambda _=False: (setattr(self.current, "x", 50.0), setattr(self.current, "y", 50.0),
                                                self._populate(), changed()))
        pos.addRow(centre)
        outer.addWidget(QLabel("Position"))
        outer.addLayout(pos)

        # ---- outline ----
        out = QFormLayout()
        bind_check(out, "Outline", "outline")
        bind_colour(out, "Outline colour", "outline_color")
        bind_slider(out, "Outline width", "outline_width", 0, 30, "%")
        outer.addLayout(out)

        # ---- drop shadow ----
        sh = QFormLayout()
        bind_check(sh, "Drop shadow", "shadow")
        bind_colour(sh, "Shadow colour", "shadow_color")
        bind_slider(sh, "Offset across", "shadow_dx", -50, 50, "%")
        bind_slider(sh, "Offset down", "shadow_dy", -50, 50, "%")
        bind_slider(sh, "Blur", "shadow_blur", 0, 60, "%")
        bind_slider(sh, "Opacity", "shadow_opacity", 0, 100, "%")
        outer.addLayout(sh)

        bind_check_vis = QCheckBox("Show this text box")
        bind_check_vis.toggled.connect(lambda on: (setattr(self.current, "visible", on), changed()))
        binds.append(("check", "visible", bind_check_vis, None, ""))
        outer.addWidget(bind_check_vis)

        self._refresh_list()
        self._populate()
        return panel

    # ----- list handling -----
    def _refresh_list(self):
        if self._ui is None:
            return
        self.list.blockSignals(True)
        self.list.clear()
        for it in self.items:
            first = (it.text.strip().split("\n") or [""])[0]
            self.list.addItem(first[:28] or "(empty text)")
        self.list.setCurrentRow(min(self.sel, len(self.items) - 1))
        self.list.blockSignals(False)

    def _on_row(self, row):
        if row >= 0:
            self.sel = row
            self._populate()

    def _add_item(self):
        item = TextItem(text="New text")
        self.items.append(item)
        self.sel = len(self.items) - 1
        self._refresh_list()
        self._populate()
        self.host.request_refresh()

    def _copy_item(self):
        dup = copy.deepcopy(self.current)
        dup.x, dup.y = min(100.0, dup.x + 4), min(100.0, dup.y + 4)
        self.items.append(dup)
        self.sel = len(self.items) - 1
        self._refresh_list()
        self._populate()
        self.host.request_refresh()

    def _remove_item(self):
        del self.items[self.sel]
        if not self.items:
            self.items = [TextItem()]
        self.sel = min(self.sel, len(self.items) - 1)
        self._refresh_list()
        self._populate()
        self.host.request_refresh()

    # ----- font box -----
    def _fill_fonts(self):
        box = self.font_box
        box.blockSignals(True)
        box.clear()
        box.addItem("Default", "")
        for fam in families():
            box.addItem(fam, fam)
        current = self.current.font
        if current and box.findData(current) < 0:  # a font file the user picked
            box.addItem(os.path.basename(current), current)
        box.setCurrentIndex(max(0, box.findData(current)))
        box.blockSignals(False)

    def _on_font(self, _i):
        if self._ui is not None:
            self.current.font = self.font_box.currentData() or ""
            self.host.request_refresh()

    # ----- model -> controls -----
    def _populate(self):
        if self._ui is None:
            return
        it = self.current
        self.txt.blockSignals(True)
        if self.txt.toPlainText() != it.text:
            self.txt.setPlainText(it.text)
        self.txt.blockSignals(False)
        self._fill_fonts()
        for kind, attr, widget, label, unit in self._ui["binds"]:
            value = getattr(it, attr)
            widget.blockSignals(True)
            if kind == "slider":
                widget.setValue(int(round(value)))
                label.setText(f"{int(round(value))}{unit}")
            elif kind == "check":
                widget.setChecked(bool(value))
            elif kind == "dspin":
                widget.setValue(float(value))
            elif kind == "align":
                widget.setCurrentIndex({"left": 0, "center": 1, "right": 2}.get(value, 1))
            elif kind == "colour":
                widget.setStyleSheet(f"background-color: rgb({value[0]},{value[1]},{value[2]});")
            widget.blockSignals(False)


PLUGIN = TextTool
