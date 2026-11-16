"""Filters - an array of image filters, including colour gradients.

Tick the filters you want and set each one's amount. They are applied in the
order listed, to the whole picture (all photos, pattern and canvas), on previews,
zoomed views and the final export. Nothing is ever changed in the originals.

Gradient filters:
  * Duotone        - shadows take colour 1, highlights colour 2
  * Gradient map   - shadows, mid-tones and highlights take colours 1, 2 and 3
  * Gradient overlay - a colour gradient laid over the picture (blend mode + opacity),
                       linear at any angle or radial, spread across the whole canvas
"""
import copy

from PIL import Image, ImageChops, ImageFilter, ImageOps

from imagewise.engine import gradient
from imagewise.plugins.api import Plugin

BLEND_MODES = ["Normal", "Multiply", "Screen", "Overlay", "Soft light"]

# id, label, min, max, default amount, unit shown after the value
SPECS = [
    ("bw", "Black & white", 0, 100, 100, "%"),
    ("sepia", "Sepia", 0, 100, 100, "%"),
    ("invert", "Invert colours", 0, 100, 100, "%"),
    ("blur", "Blur", 1, 60, 6, " px"),
    ("sharpen", "Sharpen", 0, 100, 50, "%"),
    ("vignette", "Vignette (dark edges)", 0, 100, 50, "%"),
    ("posterize", "Posterize", 1, 7, 4, " bits"),
    ("solarize", "Solarize", 0, 255, 128, ""),
    ("emboss", "Emboss", 0, 100, 100, "%"),
    ("edges", "Line drawing (edges)", 0, 100, 100, "%"),
    ("pixelate", "Pixelate", 2, 120, 12, " px"),
    ("grain", "Film grain", 0, 100, 30, "%"),
    ("hue", "Hue shift", -180, 180, 60, "\u00b0"),
    ("tint", "Warm / cool tint", -100, 100, 40, ""),
    ("duotone", "Duotone", 0, 100, 100, "%"),
    ("gradmap", "Gradient map", 0, 100, 100, "%"),
    ("gradient", "Gradient overlay", 0, 100, 60, "%"),
]
COLOURS = {  # filters that have colour pickers -> default colours
    "duotone": [(25, 10, 70), (255, 205, 120)],
    "gradmap": [(0, 0, 40), (200, 60, 120), (255, 235, 160)],
    "gradient": [(255, 120, 0), (80, 0, 170)],
}


def _blend(a, b, amount):
    return Image.blend(a, b, max(0.0, min(1.0, amount / 100)))


def _gray(img):
    return ImageOps.grayscale(img)


# Each function: (rgb image, settings dict, render context) -> rgb image of the same size
def f_bw(img, c, ctx):
    return _blend(img, _gray(img).convert("RGB"), c["amt"])


def f_sepia(img, c, ctx):
    tone = ImageOps.colorize(_gray(img), (30, 15, 5), (255, 240, 210), mid=(150, 100, 60))
    return _blend(img, tone, c["amt"])


def f_invert(img, c, ctx):
    return _blend(img, ImageChops.invert(img), c["amt"])


def f_blur(img, c, ctx):
    radius = c["amt"] * ctx.scale  # sizes are given at full size, so scale them for previews
    return img.filter(ImageFilter.GaussianBlur(radius)) if radius >= 0.3 else img


def f_sharpen(img, c, ctx):
    return img.filter(ImageFilter.UnsharpMask(radius=max(0.5, 2 * ctx.scale), percent=int(c["amt"] * 3), threshold=2))


def f_vignette(img, c, ctx):
    ramp = gradient.ramp(img.size, 0, True, ctx.origin, ctx.whole_canvas(img))  # 0 centre .. 255 corners
    s = c["amt"] / 100
    table = [max(0, min(255, round(255 * (1 - s * (v / 255) ** 2.2)))) for v in range(256)]
    shade = ramp.point(table)
    return ImageChops.multiply(img, Image.merge("RGB", (shade, shade, shade)))


def f_posterize(img, c, ctx):
    return ImageOps.posterize(img, int(c["amt"]))


def f_solarize(img, c, ctx):
    return ImageOps.solarize(img, int(c["amt"]))


def f_emboss(img, c, ctx):
    return _blend(img, img.filter(ImageFilter.EMBOSS), c["amt"])


def f_edges(img, c, ctx):
    lines = ImageOps.autocontrast(ImageOps.invert(_gray(img).filter(ImageFilter.FIND_EDGES)))
    return _blend(img, lines.convert("RGB"), c["amt"])


def f_pixelate(img, c, ctx):
    block = max(2, round(c["amt"] * ctx.scale))
    w, h = img.size
    small = img.resize((max(1, w // block), max(1, h // block)), Image.BOX)
    return small.resize((w, h), Image.NEAREST)


def f_grain(img, c, ctx):
    noise = Image.effect_noise(img.size, 8 + c["amt"] * 0.5).convert("RGB")  # centred on 128
    return ImageChops.add(img, noise, 1.0, -128)


def f_hue(img, c, ctx):
    h, s, v = img.convert("HSV").split()
    shift = round(c["amt"] * 255 / 360)
    h = h.point([(i + shift) % 256 for i in range(256)])
    return Image.merge("HSV", (h, s, v)).convert("RGB")


def f_tint(img, c, ctx):
    a = c["amt"] / 100 * 55
    r, g, b = img.split()
    clip = lambda v: max(0, min(255, round(v)))
    return Image.merge("RGB", (r.point([clip(i + a) for i in range(256)]),
                               g.point([clip(i + a * 0.15) for i in range(256)]),
                               b.point([clip(i - a) for i in range(256)])))


def f_duotone(img, c, ctx):
    c1, c2 = c["colours"][:2]
    return _blend(img, ImageOps.colorize(_gray(img), tuple(c1), tuple(c2)), c["amt"])


def f_gradmap(img, c, ctx):
    c1, c2, c3 = c["colours"][:3]
    return _blend(img, ImageOps.colorize(_gray(img), tuple(c1), tuple(c3), mid=tuple(c2)), c["amt"])


def f_gradient(img, c, ctx):
    grad = gradient.Gradient.two(c["colours"][0], c["colours"][1], c["angle"], c["radial"])
    layer = gradient.render(grad, img.size, ctx.origin, ctx.whole_canvas(img))
    mode = c.get("blend", "Normal")
    try:
        mixed = {"Multiply": ImageChops.multiply, "Screen": ImageChops.screen, "Overlay": ImageChops.overlay,
                 "Soft light": ImageChops.soft_light}.get(mode, lambda a, b: b)(img, layer)
    except Exception:
        mixed = layer
    return _blend(img, mixed, c["amt"])


FUNCS = {"bw": f_bw, "sepia": f_sepia, "invert": f_invert, "blur": f_blur, "sharpen": f_sharpen,
         "vignette": f_vignette, "posterize": f_posterize, "solarize": f_solarize, "emboss": f_emboss,
         "edges": f_edges, "pixelate": f_pixelate, "grain": f_grain, "hue": f_hue, "tint": f_tint,
         "duotone": f_duotone, "gradmap": f_gradmap, "gradient": f_gradient}


def default_config() -> dict:
    cfg = {}
    for fid, _label, _lo, _hi, default, _unit in SPECS:
        cfg[fid] = {"on": False, "amt": default}
        if fid in COLOURS:
            cfg[fid]["colours"] = [tuple(col) for col in COLOURS[fid]]
        if fid == "gradient":
            cfg[fid].update({"angle": 90, "radial": False, "blend": "Normal"})
    return cfg


class Filters(Plugin):
    name = "Filters"
    version = "1.0"
    author = "EK"
    description = "A set of image filters and colour gradients. Tick a filter and set its amount."

    def __init__(self, host):
        super().__init__(host)
        self.cfg = default_config()
        self._ui = {}

    # ----- the picture change (may run on a background thread: only reads settings) -----
    def apply(self, image, ctx):
        cfg = self.cfg
        active = [fid for fid, *_ in SPECS if cfg[fid]["on"]]
        if not active:
            return image
        alpha = image.getchannel("A") if image.mode == "RGBA" else None
        rgb = image.convert("RGB")
        for fid in active:
            rgb = FUNCS[fid](rgb, cfg[fid], ctx)
        if alpha is not None:
            rgb.putalpha(alpha)
        return rgb

    # ----- remembered settings / undo -----
    def get_state(self):
        return copy.deepcopy(self.cfg)

    def set_state(self, state):
        for fid, saved in state.items():
            if fid in self.cfg:
                self.cfg[fid].update(copy.deepcopy(saved))
                if "colours" in self.cfg[fid]:
                    self.cfg[fid]["colours"] = [tuple(col) for col in self.cfg[fid]["colours"]]
        self._sync_widgets()

    def reset(self):
        self.cfg = default_config()
        self._sync_widgets()
        self.host.request_refresh()

    # ----- the sidebar controls -----
    def create_panel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import (
            QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
        )

        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self._ui = {}

        def changed():
            self.host.request_refresh()

        for fid, label, lo, hi, _default, unit in SPECS:
            ui = {}
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)

            head = QHBoxLayout()
            chk = QCheckBox(label)
            value = QLabel("")
            value.setMinimumWidth(50)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            head.addWidget(chk, 1)
            head.addWidget(value)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            col.addLayout(head)
            col.addWidget(slider)

            def on_check(on, f=fid):
                self.cfg[f]["on"] = on
                changed()

            def on_slide(v, f=fid, lab=value, u=unit):
                self.cfg[f]["amt"] = v
                lab.setText(f"{v}{u}")
                changed()

            chk.toggled.connect(on_check)
            slider.valueChanged.connect(on_slide)
            ui.update(chk=chk, slider=slider, value=value, unit=unit)

            if fid in COLOURS:  # colour pickers
                row = QHBoxLayout()
                buttons = []
                for idx in range(len(COLOURS[fid])):
                    btn = QPushButton("")
                    btn.setFixedWidth(46)
                    btn.setToolTip("Pick a colour")

                    def pick(_=False, f=fid, i=idx):
                        start = QColor(*self.cfg[f]["colours"][i])
                        chosen = QColorDialog.getColor(start, panel, "Colour")
                        if chosen.isValid():
                            self.cfg[f]["colours"][i] = (chosen.red(), chosen.green(), chosen.blue())
                            self._sync_widgets()
                            changed()

                    btn.clicked.connect(pick)
                    row.addWidget(btn)
                    buttons.append(btn)
                row.addStretch()
                col.addLayout(row)
                ui["buttons"] = buttons

            if fid == "gradient":  # angle, radial, blend mode
                ang_row = QHBoxLayout()
                ang_label = QLabel("Angle")
                ang = QSlider(Qt.Horizontal)
                ang.setRange(0, 360)
                ang_val = QLabel("")
                ang_val.setMinimumWidth(40)
                ang_row.addWidget(ang_label)
                ang_row.addWidget(ang, 1)
                ang_row.addWidget(ang_val)
                col.addLayout(ang_row)
                opt_row = QHBoxLayout()
                radial = QCheckBox("Radial")
                blend = QComboBox()
                blend.addItems(BLEND_MODES)
                opt_row.addWidget(radial)
                opt_row.addWidget(blend, 1)
                col.addLayout(opt_row)

                def on_angle(v, lab=ang_val):
                    self.cfg["gradient"]["angle"] = v
                    lab.setText(f"{v}\u00b0")
                    changed()

                def on_radial(on):
                    self.cfg["gradient"]["radial"] = on
                    changed()

                def on_blend(_i, combo=blend):
                    self.cfg["gradient"]["blend"] = combo.currentText()
                    changed()

                ang.valueChanged.connect(on_angle)
                radial.toggled.connect(on_radial)
                blend.currentIndexChanged.connect(on_blend)
                ui.update(angle=ang, angle_val=ang_val, radial=radial, blend=blend)

            outer.addWidget(box)
            self._ui[fid] = ui

        reset_btn = QPushButton("Switch all filters off")
        reset_btn.clicked.connect(lambda _=False: self._all_off())
        outer.addWidget(reset_btn)
        self._sync_widgets()
        return panel

    def _all_off(self):
        for fid in self.cfg:
            self.cfg[fid]["on"] = False
        self._sync_widgets()
        self.host.request_refresh()

    def _sync_widgets(self):
        """Show the current settings in the controls (without triggering their handlers)."""
        for fid, ui in self._ui.items():
            c = self.cfg[fid]
            for w in (ui["chk"], ui["slider"]) + tuple(ui.get(k) for k in ("angle", "radial", "blend") if ui.get(k)):
                w.blockSignals(True)
            ui["chk"].setChecked(c["on"])
            ui["slider"].setValue(c["amt"])
            ui["value"].setText(f"{c['amt']}{ui['unit']}")
            for btn, rgb in zip(ui.get("buttons", []), c.get("colours", [])):
                btn.setStyleSheet(f"background-color: rgb({rgb[0]},{rgb[1]},{rgb[2]});")
            if "angle" in ui:
                ui["angle"].setValue(int(c["angle"]))
                ui["angle_val"].setText(f"{int(c['angle'])}\u00b0")
                ui["radial"].setChecked(bool(c["radial"]))
                ui["blend"].setCurrentIndex(max(0, BLEND_MODES.index(c.get("blend", "Normal"))))
            for w in (ui["chk"], ui["slider"]) + tuple(ui.get(k) for k in ("angle", "radial", "blend") if ui.get(k)):
                w.blockSignals(False)


PLUGIN = Filters
