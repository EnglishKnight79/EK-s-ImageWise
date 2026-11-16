"""Plugin API for EK's Image Wise (version 1).

A plugin is a Python file (or a folder with __init__.py) dropped into a plugins
folder. It defines one subclass of `Plugin`:

    from imagewise.plugins.api import Plugin

    class MyPlugin(Plugin):
        name = "My plugin"
        version = "1.0"
        description = "What it does, in one line."

        def create_panel(self):          # optional: controls shown in the sidebar
            ...return a QWidget

        def apply(self, image, ctx):     # optional: change the picture
            ...return a PIL image of the same size

What a plugin can use (`self.host`):
    host.document            the open Document, or None
    host.request_refresh()   call after your settings change to redraw the preview
    host.message(text)       show a short message in the status bar
    host.data_dir(name)      a writable folder for your own files
    host.run_task(fn, on_done, on_error)   run fn() on a background thread; callbacks run on the UI thread
    host.set_canvas_items(owner, items)    show draggable items on the preview (see below)
    host.block_canvas_size(bool)           stop the Canvas size controls being edited (a plugin sets the size)
    host.set_photos_interactive(bool)      allow / forbid dragging photos in the preview
    host.api_version         plugin API version of this app

Rules for apply():
  * return an image of the SAME size (it runs on previews, zoomed views and the
    final export; `ctx.scale` tells you the output scale, so size-based values
    such as a blur radius in pixels should be multiplied by ctx.scale)
  * the image may be only a WINDOW of the canvas (a zoomed view). `ctx.origin` is where
    it sits in the whole canvas, `ctx.whole_canvas(image)` the whole canvas size and
    `ctx.dpi` the print resolution, so things placed relative to the canvas (text,
    gradients, vignettes) come out identical in every view
  * it can run on a background thread, so only read your settings; don't touch widgets
"""
from __future__ import annotations

API_VERSION = 1


class Plugin:
    name = "Unnamed plugin"
    version = "1.0"
    author = ""
    description = ""
    api_version = 1  # the plugin API this plugin was written for

    enabled = True  # set by the app from the checkbox on the plugin's sidebar box
    layer = 0  # effects run in ascending layer order (alpha overlays use 100 so they sit on top)
    live_on_canvas = False  # True: the plugin draws live items on the canvas (host.set_canvas_items), so
    # previews skip its apply() and only the final export uses it

    def __init__(self, host):
        self.host = host

    # ----- override any of these -----
    def create_panel(self):
        """Return a QWidget with your controls, or None for no panel."""
        return None

    def apply(self, image, ctx):
        """Change the picture (see the rules above). Default: no change."""
        return image

    def get_state(self) -> dict:
        """Settings to remember between sessions (JSON-friendly dict)."""
        return {}

    def set_state(self, state: dict) -> None:
        """Restore settings saved by get_state()."""

    def reset(self) -> None:
        """Put all settings back to their defaults."""

    # ----- plugins that replace how the canvas is built (like Pattern / Poster) -----
    def canvas_size(self, document):
        """Return (width, height) in pixels to take over the canvas size, or None to leave it alone."""
        return None

    def render_base(self, document, full_size, scale, preview, origin, size, is_full, background):
        """Return the canvas picture for the window (origin, size) instead of the photos, or None to let
        the photos draw it. `full_size` is the whole canvas in pixels at this scale; `background` is a
        gradient picture for the window or None."""
        return None

    # ----- called by the app -----
    def on_canvas_item_selected(self, index: int) -> None:
        """The user clicked one of your canvas items (see host.set_canvas_items); -1 = deselected."""

    def on_canvas_item_edited(self, index: int) -> None:
        """The user dragged / resized one of your canvas items; refresh your controls."""

    def on_document_changed(self, document) -> None:
        """Called when a new image is opened, another photo is selected, or Undo / Redo changed the document."""

    # ----- used by the app -----
    @classmethod
    def has_effect(cls) -> bool:
        return cls.apply is not Plugin.apply

    @classmethod
    def has_generator(cls) -> bool:
        return cls.render_base is not Plugin.render_base or cls.canvas_size is not Plugin.canvas_size
