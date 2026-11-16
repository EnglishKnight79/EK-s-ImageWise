"""A sidebar category: a header (expand/collapse, optional on/off tick, Lock, Reset) and content.

* Starts minimised.
* Lock greys out the content (and the Reset button) so nothing in it can be changed by accident.
* Reset emits resetRequested; the owner decides what "reset" means for that category.
The content is also disabled while the app says it is unavailable (no image open) or blocked.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

ACCENT = "#16147d"
SMALL = "font-size: 11px; padding: 2px 4px;"


class CategoryBox(QWidget):
    resetRequested = Signal()
    lockedChanged = Signal(bool)
    enabledToggled = Signal(bool)  # only used when checkable=True (plugins)
    expandedChanged = Signal(bool)  # opened or minimised (the settings panel re-fits its width)

    def __init__(self, title: str, content: QWidget, checkable: bool = False, parent=None):
        super().__init__(parent)
        self._content = content
        self._available = False
        self._blocked = False
        self._locked = False

        self.btn_toggle = QToolButton()
        self.btn_toggle.setText(title)
        self.btn_toggle.setCheckable(True)  # checked = expanded
        self.btn_toggle.setChecked(False)  # minimised by default
        self.btn_toggle.setAutoRaise(True)
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_toggle.setArrowType(Qt.RightArrow)
        # a larger header that always shows the whole title
        self.btn_toggle.setStyleSheet("QToolButton { font-weight: bold; font-size: 14px; padding: 7px 4px; text-align: left; }")
        self.btn_toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_toggle.setToolTip(title)
        self.btn_toggle.toggled.connect(self._on_expand_toggled)

        self.chk_enable = None
        if checkable:
            self.chk_enable = QCheckBox()
            self.chk_enable.setChecked(True)
            self.chk_enable.setToolTip("Switch this on or off")
            self.chk_enable.toggled.connect(self.enabledToggled)

        self.btn_lock = QPushButton("Lock")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setToolTip("Lock this category so its settings cannot be changed by accident")
        self.btn_lock.setFixedWidth(46)
        self.btn_lock.setStyleSheet(SMALL)
        self.btn_lock.toggled.connect(self._on_lock_toggled)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setToolTip("Put this category back to its defaults (Undo brings it back)")
        self.btn_reset.setFixedWidth(46)
        self.btn_reset.setStyleSheet(SMALL)
        self.btn_reset.clicked.connect(lambda _=False: self.resetRequested.emit())

        header = QWidget()
        header.setObjectName("categoryHeader")
        header.setStyleSheet("#categoryHeader { border-left: 4px solid palette(highlight); }")
        row = QHBoxLayout(header)
        row.setContentsMargins(6, 2, 2, 2)
        row.setSpacing(3)
        row.addWidget(self.btn_toggle, 1)
        if self.chk_enable is not None:
            row.addWidget(self.chk_enable)
        row.addWidget(self.btn_lock)
        row.addWidget(self.btn_reset)

        self._frame = QFrame()
        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(8, 2, 2, 6)
        inner.addWidget(content)
        self._frame.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(header)
        outer.addWidget(self._frame)
        self._apply_enabled()

    # ----- state -----
    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def expanded(self) -> bool:
        return self.btn_toggle.isChecked()

    def set_expanded(self, on: bool):
        self.btn_toggle.setChecked(on)

    def set_available(self, on: bool):
        """False while there is nothing to edit (no image open)."""
        self._available = on
        self._apply_enabled()

    def set_blocked(self, blocked: bool):
        """The app can switch the content off for its own reasons (e.g. pattern mode)."""
        self._blocked = blocked
        self._apply_enabled()

    def set_locked(self, locked: bool):
        self.btn_lock.setChecked(locked)

    def _apply_enabled(self):
        self._content.setEnabled(self._available and not self._blocked and not self._locked)
        self.btn_reset.setEnabled(self._available and not self._locked)
        self.btn_lock.setEnabled(self._available)

    def _on_expand_toggled(self, on: bool):
        self.btn_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._frame.setVisible(on)
        self.expandedChanged.emit(on)

    def _on_lock_toggled(self, on: bool):
        self._locked = on
        self.btn_lock.setText("Locked" if on else "Lock")
        self.btn_lock.setStyleSheet(SMALL + (" background-color: palette(highlight); color: palette(highlighted-text);" if on else ""))
        self.btn_lock.setFixedWidth(52 if on else 46)
        self._apply_enabled()
        self.lockedChanged.emit(on)
