"""Stops the mouse wheel from changing settings by accident.

A spin box, slider or drop-down only reacts to the wheel after it has been
clicked (it has keyboard focus). Until then the wheel scrolls the sidebar instead.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSlider, QSpinBox

GUARDED = (QSpinBox, QDoubleSpinBox, QSlider, QComboBox)


class WheelGuard(QObject):
    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self._scroll = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            # hand the wheel to the sidebar's scroll bar instead of changing the value
            QCoreApplication.sendEvent(self._scroll.verticalScrollBar(), event)
            return True
        return False

    def protect(self, root):
        """Guard every spin box / slider / drop-down inside `root` (call again for new widgets)."""
        for kind in GUARDED:
            for widget in root.findChildren(kind):
                if widget.property("wheelGuarded"):
                    continue
                widget.setProperty("wheelGuarded", True)
                widget.setFocusPolicy(Qt.StrongFocus)  # click or Tab gives focus; the wheel doesn't
                widget.installEventFilter(self)
