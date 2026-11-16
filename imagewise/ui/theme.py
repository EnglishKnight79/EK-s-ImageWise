"""Light and dark colour themes.

Both use Qt's "Fusion" style so the app looks the same on Windows and macOS whatever the
computer's own light / dark setting is. The choice is remembered (View > Theme).
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("Light", "Dark")
DEFAULT = "Dark"


def is_dark(name: str) -> bool:
    return name == "Dark"


def _palette(dark: bool) -> QPalette:
    if dark:
        c = dict(window=(43, 43, 48), base=(30, 30, 34), alt=(38, 38, 42), text=(232, 232, 235),
                 button=(60, 60, 67), highlight=(92, 88, 214), highlighted_text=(255, 255, 255),
                 disabled=(128, 128, 135), tip_base=(60, 60, 67), link=(130, 160, 255), mid=(80, 80, 88))
    else:
        c = dict(window=(240, 240, 243), base=(255, 255, 255), alt=(246, 246, 249), text=(28, 28, 33),
                 button=(228, 228, 235), highlight=(22, 20, 125), highlighted_text=(255, 255, 255),
                 disabled=(150, 150, 158), tip_base=(255, 255, 225), link=(22, 20, 125), mid=(190, 190, 200))
    p = QPalette()
    roles = {
        QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["base"],
        QPalette.AlternateBase: c["alt"], QPalette.ToolTipBase: c["tip_base"], QPalette.ToolTipText: c["text"],
        QPalette.Text: c["text"], QPalette.Button: c["button"], QPalette.ButtonText: c["text"],
        QPalette.BrightText: (255, 80, 80), QPalette.Link: c["link"], QPalette.Highlight: c["highlight"],
        QPalette.HighlightedText: c["highlighted_text"], QPalette.PlaceholderText: c["disabled"],
        QPalette.Mid: c["mid"],
    }
    for role, rgb in roles.items():
        p.setColor(role, QColor(*rgb))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):  # greyed-out controls
        p.setColor(QPalette.Disabled, role, QColor(*c["disabled"]))
    return p


def apply(app: QApplication, name: str) -> None:
    """Switch the whole application to the named theme."""
    app.setStyle("Fusion")
    app.setPalette(_palette(is_dark(name)))
    for widget in app.allWidgets():  # make widgets with style sheets pick up the new colours
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
