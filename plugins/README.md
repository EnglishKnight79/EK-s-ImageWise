# Plugins for EK's Image Wise

A plugin is one Python file (or a folder with `__init__.py`). Copy `_template.py`,
rename it, edit it, then choose **Plugins > Reload plugins** in the app.

Where plugins live (both are scanned):
- the `plugins` folder next to the app (built-in ones), and
- your own folder: `<your home folder>/EKImageWise/plugins`
  (**Plugins > Open plugins folder** opens it).

Files and folders whose names start with `_` or `.` are ignored.

## What a plugin can do

Subclass `Plugin` from `imagewise.plugins.api` and override any of:

| Method | Purpose |
|---|---|
| `create_panel()` | Return a Qt widget with your controls (shown in the sidebar) |
| `apply(image, ctx)` | Change the picture. Return a PIL image of the **same size** |
| `get_state()` / `set_state(d)` | Settings remembered between sessions, and used by Undo / Redo |
| `reset()` | Restore defaults (called by the category's Reset button) |
| `on_document_changed(doc)` | Called when a new image is opened, another photo is selected, or Undo / Redo changed things (refresh your controls here) |

Your plugin gets `self.host` with:
`host.document`, `host.request_refresh()`, `host.message(text)`, `host.data_dir(name)`, `host.api_version`, and
for bigger plugins `host.run_task(fn, on_done, on_error)` (run something slow on a background thread),
`host.set_canvas_items(self, [(model, pixmap), ...])` (draggable items on the preview),
`host.block_canvas_size(bool)` and `host.set_photos_interactive(bool)`.

### Bigger plugins: three kinds of power

* **Effect** (`apply`) - changes the finished picture. `layer = 100` makes it run last; `live_on_canvas = True`
  means the preview draws your items itself (see `alpha_overlays.py`) and only the export calls `apply`.
* **Generator** (`canvas_size`, `render_base`) - replaces how the canvas is built (see `pattern_poster.py`).
* **Editor of the selected photo** - changes settings stored on the photo (`host.document.active_photo`), such
  as a crop shape or a cut-out (see `crop_shapes.py`, `background_removal.py`); refresh your controls in
  `on_document_changed`.

## How `apply` is used

It runs on every preview, zoomed view and on the final export, after the image
(or pattern) is built and before overlays are added. The original is never changed.

* `ctx.scale` - output scale (1.0 = full size). Multiply pixel-based settings
  (e.g. a blur radius) by it so previews match the export.
* `ctx.preview` - `True` on screen, `False` when exporting.
* `ctx.origin`, `ctx.whole_canvas(image)` - the image you receive can be just a window of the
  canvas (when the preview is zoomed in). These say where it sits, so anything placed
  relative to the canvas (text, gradients, vignettes) looks the same in every view.
* `ctx.dpi` - the print resolution, for sizes given in cm.
* It may run on a background thread: only read your settings, never touch widgets.
* If your plugin raises an error it is skipped and the problem is shown in the status bar.

Built-in examples: `colour_brightness.py` (simple sliders), `filters.py` (17 filters incl. gradient map
and gradient overlay) and `text_tool.py` (a full text tool) and `crop_shapes.py` (a plugin that edits the selected photo's settings and has its own folder picker).

The plugin's tick box in the sidebar switches it on or off. Its category can be minimised, locked and reset like the built-in ones; spin boxes, sliders and drop-downs in your panel get the click-before-scroll protection automatically.

For Undo to cover your plugin, make `get_state()` return everything that changes the picture and `set_state()` apply it (and update your widgets).
