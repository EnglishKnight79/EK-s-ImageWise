"""Background Removal - cut the subject out of the selected photo with an AI model (rembg).

Click "Remove background". The AI makes a mask of the subject; the photo's background becomes
transparent. "Show cut-out" switches the cut-out on and off, and Edge shrink / Feather tidy the edge
instantly (the AI is not run again). The original photo is never changed. Every photo in a composition
can have its own cut-out.

The first time a model is used it is downloaded (about 40 to 180 MB) unless it was bundled with the
installer. Install the engine with:   pip install "rembg[cpu]"

Switching this plugin off (or deleting this file) removes background removal from the app.
"""
import os

from PIL import Image

from imagewise import paths
from imagewise.engine import background
from imagewise.plugins.api import Plugin

# label shown in the list -> rembg model name
MODELS = {
    "Standard (u2net)": "u2net",
    "Fast, smaller (u2netp)": "u2netp",
    "General purpose (isnet-general-use)": "isnet-general-use",
}

_sessions = {}


class BackgroundUnavailable(Exception):
    """Raised when rembg / onnxruntime is missing."""

    user_message = True  # its text is shown to the user as written


def _point_rembg_at_model(model):
    """Models shipped inside an installed app are read from there; others use rembg's normal per-user
    folder (~/.u2net) so a read-only install never blocks a download."""
    bundled = paths.bundled_models_dir()
    if bundled is not None and (bundled / f"{model}.onnx").is_file():
        os.environ["U2NET_HOME"] = str(bundled)
    elif os.environ.get("U2NET_HOME") == str(bundled):
        del os.environ["U2NET_HOME"]


def _get_session(model):
    try:
        from rembg import new_session
    except Exception as exc:  # ImportError, or onnxruntime failing to load
        raise BackgroundUnavailable(
            "Background removal needs the 'rembg' package.\n\n"
            "Install it with:\n    pip install \"rembg[cpu]\"\n\n"
            f"(Details: {exc})"
        ) from exc
    if model not in _sessions:
        _point_rembg_at_model(model)
        _sessions[model] = new_session(model)  # downloads the model on first use if it is not bundled
    return _sessions[model]


def compute_mask(image, model="u2net", max_side=1024):
    """Return an 'L' mask the same size as `image` (255 = keep).

    The model works on a downscaled copy (these models run at ~320-1024 px internally anyway), then the mask
    is scaled back up. This keeps big poster files fast and memory-safe.
    """
    session = _get_session(model)  # raises BackgroundUnavailable with a friendly message
    from rembg import remove  # safe now: _get_session confirmed rembg imports

    small = image.convert("RGB")
    small.thumbnail((max_side, max_side), Image.LANCZOS)
    cut = remove(small, session=session)  # RGBA PIL image
    mask = cut.getchannel("A")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.LANCZOS)
    return mask


class BackgroundRemoval(Plugin):
    name = "Background Removal"
    version = "1.0"
    author = "EK"
    description = "Cut the subject out of the selected photo with an AI model. Tidy the edge with shrink and feather."

    def __init__(self, host):
        super().__init__(host)
        self._enabled = True
        background.set_active(True)  # the app only applies cut-outs while this plugin is loaded and on
        self.model_label = next(iter(MODELS))
        self._busy = False  # an AI job is running
        self._ui = None
        self._syncing = False

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, on):
        self._enabled = bool(on)
        background.set_active(self._enabled)

    def _photo(self):
        doc = self.host.document
        return doc.active_photo if doc is not None else None

    # ----- remembered settings / undo -----
    def get_state(self):
        return {"model": self.model_label}

    def set_state(self, state):
        label = state.get("model")
        if label in MODELS:
            self.model_label = label
        self._sync()

    def reset(self):
        """Remove the cut-out from the selected photo."""
        ph = self._photo()
        if ph is not None:
            ph.reset_background()
        self._sync()
        self.host.request_refresh()

    def on_document_changed(self, document):
        self._sync()  # another photo was selected, or Undo changed things

    # ======================= the sidebar controls =======================
    def create_panel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QFormLayout, QLabel, QMessageBox, QPushButton, QSlider, QWidget,
        )

        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        u = self._ui = {"QMessageBox": QMessageBox}
        u["model"] = QComboBox()
        u["model"].addItems(list(MODELS))
        u["run"] = QPushButton("Remove background")
        u["show"] = QCheckBox("Show cut-out")
        u["shrink_lbl"], u["feather_lbl"] = QLabel("Edge shrink: 0 px"), QLabel("Feather: 0 px")
        u["shrink"], u["feather"] = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
        u["shrink"].setRange(-20, 20)
        u["feather"].setRange(0, 20)
        u["status"] = QLabel("")
        u["status"].setWordWrap(True)
        for key in ("shrink", "feather"):
            u[key].setValue(0)
        form.addRow("Model", u["model"])
        form.addRow(u["run"])
        form.addRow(u["show"])
        form.addRow(u["shrink_lbl"])
        form.addRow(u["shrink"])
        form.addRow(u["feather_lbl"])
        form.addRow(u["feather"])
        form.addRow(u["status"])

        def on_model(_i):
            self.model_label = u["model"].currentText()

        u["model"].currentIndexChanged.connect(on_model)
        u["run"].clicked.connect(lambda _=False: self._run())
        u["show"].toggled.connect(self._on_show)
        u["shrink"].valueChanged.connect(self._on_adjust)
        u["feather"].valueChanged.connect(self._on_adjust)
        self._sync()
        return panel

    # ----- actions -----
    def _run(self):
        ph = self._photo()
        if ph is None or self._busy:
            return
        model = MODELS[self.model_label]
        self._busy = True
        self._sync()
        self._ui["status"].setText("Working... the first run downloads the model, which can take a minute.")
        original = ph.original
        self.host.run_task(lambda: compute_mask(original, model),
                           lambda mask, p=ph: self._done(p, mask),
                           lambda msg, p=ph: self._failed(p, msg))

    def _done(self, photo, mask):
        self._busy = False
        doc = self.host.document
        if doc is not None and photo in doc.photos:  # the photo (or image) may be gone by now
            photo.mask = mask
            photo.remove_bg = True
        self._sync()
        self.host.request_refresh()

    def _failed(self, photo, message):
        self._busy = False
        self._sync()
        self._ui["status"].setText("Background removal failed.")
        self._ui["QMessageBox"].warning(None, "Background removal", message)

    def _on_show(self, on):
        ph = self._photo()
        if ph is not None and not self._syncing and ph.mask is not None:
            ph.remove_bg = on
            self.host.request_refresh()

    def _on_adjust(self, _=None):
        ph, u = self._photo(), self._ui
        if ph is None or self._syncing:
            return
        ph.bg_shrink, ph.bg_feather = u["shrink"].value(), u["feather"].value()
        u["shrink_lbl"].setText(f"Edge shrink: {ph.bg_shrink} px")
        u["feather_lbl"].setText(f"Feather: {ph.bg_feather} px")
        if ph.mask is not None:
            self.host.request_refresh()

    # ----- model -> controls -----
    def _sync(self):
        u = self._ui
        if u is None:
            return
        ph = self._photo()
        self._syncing = True
        try:
            has_mask = ph is not None and ph.mask is not None
            for w in (u["show"], u["shrink"], u["feather"], u["model"]):
                w.blockSignals(True)
            u["model"].setCurrentIndex(max(0, u["model"].findText(self.model_label)))
            u["show"].setEnabled(has_mask)
            u["show"].setChecked(bool(has_mask and ph.remove_bg))
            u["shrink"].setValue(ph.bg_shrink if ph is not None else 0)
            u["feather"].setValue(ph.bg_feather if ph is not None else 0)
            for w in (u["show"], u["shrink"], u["feather"], u["model"]):
                w.blockSignals(False)
            u["shrink_lbl"].setText(f"Edge shrink: {u['shrink'].value()} px")
            u["feather_lbl"].setText(f"Feather: {u['feather'].value()} px")
            u["run"].setEnabled(ph is not None and not self._busy)
            if not self._busy:
                u["status"].setText("Cut-out ready. Use the sliders to tidy the edge." if has_mask else "")
        finally:
            self._syncing = False


PLUGIN = BackgroundRemoval
