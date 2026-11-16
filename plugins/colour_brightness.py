"""Colour & Brightness - the first built-in plugin.

Brightness, contrast and saturation sliders. It works on previews, zoomed views
and the final export, never changes the original, and keeps transparency.
Use it as a worked example when writing your own plugins.
"""
from PIL import ImageEnhance

from imagewise.plugins.api import Plugin


class ColourBrightness(Plugin):
    name = "Colour & Brightness"
    version = "1.0"
    author = "EK"
    description = "Adjust brightness, contrast and saturation."

    def __init__(self, host):
        super().__init__(host)
        # plain numbers, -100..100 (0 = unchanged). The UI writes them, apply() reads them.
        self.brightness = 0
        self.contrast = 0
        self.saturation = 0
        self._sliders = {}

    # ----- the picture change -----
    def apply(self, image, ctx):
        if not (self.brightness or self.contrast or self.saturation):
            return image  # nothing to do
        alpha = image.getchannel("A") if image.mode == "RGBA" else None
        out = image.convert("RGB")
        if self.brightness:
            out = ImageEnhance.Brightness(out).enhance(1 + self.brightness / 100)
        if self.contrast:
            out = ImageEnhance.Contrast(out).enhance(1 + self.contrast / 100)
        if self.saturation:
            out = ImageEnhance.Color(out).enhance(1 + self.saturation / 100)
        if alpha is not None:
            out.putalpha(alpha)
        return out

    # ----- the sidebar controls -----
    def create_panel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        for attr, label in (("brightness", "Brightness"), ("contrast", "Contrast"), ("saturation", "Saturation")):
            text = QLabel(f"{label}: {getattr(self, attr)}")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(-100, 100)
            slider.setValue(getattr(self, attr))

            def changed(value, a=attr, t=text, name=label):
                setattr(self, a, value)
                t.setText(f"{name}: {value}")
                self.host.request_refresh()

            slider.valueChanged.connect(changed)
            self._sliders[attr] = slider
            layout.addWidget(text)
            layout.addWidget(slider)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)
        return panel

    # ----- remembered between sessions -----
    def get_state(self):
        return {"brightness": self.brightness, "contrast": self.contrast, "saturation": self.saturation}

    def set_state(self, state):
        for key in ("brightness", "contrast", "saturation"):
            if key in state:
                setattr(self, key, int(state[key]))
        for key, slider in self._sliders.items():  # panel already built? keep it in step
            slider.setValue(getattr(self, key))

    def reset(self):
        self.brightness = self.contrast = self.saturation = 0
        for slider in self._sliders.values():
            slider.setValue(0)  # this also triggers a refresh
        self.host.request_refresh()


PLUGIN = ColourBrightness
