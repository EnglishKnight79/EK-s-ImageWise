"""Non-destructive document model for EK's Image Wise.

A Document is a composition: a canvas holding one or more Photos (layer order = list order, index 0 at
the bottom). Plugins can take over how the canvas is built (a generator, e.g. Pattern / Poster), change
the picture afterwards (effects, e.g. Filters, Text, Alpha Overlays).

Originals are never modified. Everything (crop, placement, background mask, canvas size...) is stored as
simple settings and applied only when rendering. This file has NO dependency on the UI, so plugins, tests
and a future batch mode can all reuse it.
"""
from __future__ import annotations

import copy
import dataclasses
import logging
from pathlib import Path

from PIL import Image

from imagewise.engine import effects
from imagewise.engine import gradient as gradients
from imagewise.engine.blend import paste_alpha
from imagewise.engine.effects import RenderContext
from imagewise.engine.gradient import Gradient
from imagewise.engine.photo import Photo

# Posters are huge. Disable Pillow's decompression-bomb guard for trusted local files.
Image.MAX_IMAGE_PIXELS = None

log = logging.getLogger("imagewise")

SUPPORTED_EXPORT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
MAX_EXPORT_PIXELS = 600_000_000  # refuse exports that would exhaust memory
MAX_PHOTOS = 8


class Document:
    def __init__(self, photo: Photo):
        self.photos: list[Photo] = [photo]  # index 0 = bottom layer
        self.active = 0  # the photo the crop / plugin controls act on
        self.out_size: tuple[int, int] | None = None  # canvas size; None = same as the first photo's crop
        self.dpi = 300
        self.canvas_color: tuple[int, int, int] | None = None  # None = transparent canvas
        self.canvas_gradient: Gradient | None = None  # when set, the canvas is this gradient instead

    # ---------- loading ----------
    @classmethod
    def open(cls, path: str | Path) -> "Document":
        return cls(Photo.open(path))

    # ---------- the active photo (what the crop controls and plugins edit) ----------
    @property
    def active_photo(self) -> Photo:
        return self.photos[min(max(self.active, 0), len(self.photos) - 1)]

    @property
    def path(self) -> Path | None:
        return self.photos[0].path

    @property
    def original(self) -> Image.Image:
        return self.active_photo.original

    @property
    def size(self) -> tuple[int, int]:
        return self.active_photo.size

    @property
    def crop(self):
        return self.active_photo.crop

    @property
    def crop_box(self) -> tuple[int, int, int, int]:
        return self.active_photo.crop_box

    @property
    def crop_size(self) -> tuple[int, int]:
        return self.active_photo.crop_size

    def set_crop(self, box) -> None:
        self.active_photo.set_crop(box)

    def proxy(self, max_side: int = 2000) -> Image.Image:
        return self.active_photo.proxy(max_side)

    mask = property(lambda self: self.active_photo.mask,
                    lambda self, v: setattr(self.active_photo, "mask", v))
    remove_bg = property(lambda self: self.active_photo.remove_bg,
                         lambda self, v: setattr(self.active_photo, "remove_bg", v))
    bg_shrink = property(lambda self: self.active_photo.bg_shrink,
                         lambda self, v: setattr(self.active_photo, "bg_shrink", v))
    bg_feather = property(lambda self: self.active_photo.bg_feather,
                          lambda self, v: setattr(self.active_photo, "bg_feather", v))

    # ---------- photos in the composition ----------
    def add_photo(self, photo: Photo) -> None:
        """Put another picture on the canvas (on top, half the canvas wide, centred)."""
        if len(self.photos) >= MAX_PHOTOS:
            raise ValueError(f"A composition can hold up to {MAX_PHOTOS} photos.")
        if len(self.photos) == 1 and self.out_size is None and self._generated_size() is None:
            self.out_size = self.final_size  # freeze the canvas so it stops following photo 1's crop
        photo.reset_placement(is_base=False)
        self.photos.append(photo)
        self.active = len(self.photos) - 1

    def remove_photo(self, index: int) -> None:
        if len(self.photos) <= 1:
            raise ValueError("A composition needs at least one photo.")
        del self.photos[index]
        self.active = min(self.active, len(self.photos) - 1)

    def move_photo(self, index: int, step: int) -> int:
        """Move a photo up (+1) or down (-1) one layer. Returns its new index."""
        new = index + step
        if 0 <= new < len(self.photos):
            self.photos[index], self.photos[new] = self.photos[new], self.photos[index]
            if self.active == index:
                self.active = new
            elif self.active == new:
                self.active = index
            return new
        return index

    # ---------- sizes ----------
    def _generated_size(self):
        """A canvas size dictated by a generator plugin (Pattern / Poster), or None."""
        for gen in effects.generators():
            try:
                size = gen.canvas_size(self)
            except Exception as exc:
                effects.report(getattr(gen, "name", "plugin"), exc)
                continue
            if size:
                return size
        return None

    @property
    def final_size(self) -> tuple[int, int]:
        return self._generated_size() or self.out_size or self.photos[0].crop_size

    def print_size_cm(self) -> tuple[float, float]:
        w, h = self.final_size
        return w / self.dpi * 2.54, h / self.dpi * 2.54

    # ---------- undo support (plugin settings are saved separately by the app) ----------
    def snapshot(self) -> tuple[tuple, dict]:
        """(key, data). `key` is cheap to compare; `data` restores the whole state.
        Big images are shared by reference, never copied."""
        key = (tuple(p.key() for p in self.photos), self.active, self.out_size, self.dpi, self.canvas_color,
               dataclasses.astuple(self.canvas_gradient) if self.canvas_gradient else None)
        data = {
            "photos": [(p, p.state()) for p in self.photos],
            "active": self.active, "out_size": self.out_size, "dpi": self.dpi,
            "canvas_color": self.canvas_color, "canvas_gradient": copy.deepcopy(self.canvas_gradient),
        }
        return key, data

    def restore(self, data: dict) -> None:
        self.photos = []
        for photo, state in data["photos"]:
            photo.restore(state)
            self.photos.append(photo)
        self.active = data["active"]
        self.out_size, self.dpi, self.canvas_color = data["out_size"], data["dpi"], data["canvas_color"]
        self.canvas_gradient = copy.deepcopy(data["canvas_gradient"])

    # ---------- rendering ----------
    def _render_window(self, full_size: tuple[float, float], scale: float, preview: bool,
                       origin: tuple[float, float], size: tuple[int, int], is_full: bool) -> Image.Image:
        """Draw a window of the canvas, before effects.

        full_size = the whole canvas in pixels at this scale; origin / size = the window.
        """
        ox, oy = round(origin[0]), round(origin[1])
        vw, vh = size
        window = (ox, oy, vw, vh)
        visible = [p for p in self.photos if p.visible]
        background = None
        if self.canvas_gradient is not None:  # one gradient across the whole canvas
            background = gradients.render(self.canvas_gradient, size, (ox, oy), full_size)

        for gen in effects.generators():  # a plugin may build the canvas itself (e.g. a pattern)
            try:
                img = gen.render_base(self, full_size, scale, preview, (ox, oy), size, is_full, background)
            except ValueError:
                raise  # a message meant for the user (e.g. "too many tiles")
            except Exception as exc:
                effects.report(getattr(gen, "name", "plugin"), exc)
                continue
            if img is not None:
                return img

        # fast path: one photo filling a transparent canvas (the classic single-image workflow)
        if (len(visible) == 1 and visible[0].fill and visible[0].opacity >= 1
                and self.canvas_color is None and background is None):
            return visible[0].fill_piece(window, full_size, scale, preview, is_full)

        if background is not None:
            canvas = background
        elif self.canvas_color is None:
            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        else:
            canvas = Image.new("RGB", size, tuple(self.canvas_color))
        for photo in visible:
            res = photo.finished_piece(window, full_size, scale, preview, is_full)
            if res is not None:
                paste_alpha(canvas, res[0], res[1][0], res[1][1])
        return canvas

    def render(self, max_side: int | None = None, overlays: bool = True) -> Image.Image:
        """Produce the result: the canvas (photos, or a generator's picture), then plugin effects.

        With max_side set, make a fast reduced preview. overlays=False leaves out the plugins that draw
        their own live, draggable items on the on-screen canvas (the Alpha Overlays plugin).
        """
        w, h = self.final_size
        scale, preview = 1.0, False
        if max_side and max(w, h) > max_side:
            scale = max_side / max(w, h)
            w, h = max(1, round(w * scale)), max(1, round(h * scale))
            preview = True
        img = self._render_window((w, h), scale, preview, (0, 0), (w, h), True)
        return effects.apply_all(img, RenderContext(scale=scale, preview=preview, origin=(0, 0),
                                                    canvas_size=(w, h), dpi=self.dpi), skip_live=not overlays)

    def render_view(self, region: tuple[float, float, float, float], out_w: int) -> Image.Image:
        """Render only a window of the result, for zoomed previews (without live canvas items).

        region = (x0, y0, x1, y1) as fractions of the final image; out_w = width in
        pixels of the returned image. Cost depends on out_w, not on the poster size.
        """
        W, H = self.final_size
        x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in region)
        x1, y1 = max(x1, x0 + 1e-6), max(y1, y0 + 1e-6)
        out_w = max(1, int(out_w))
        s = out_w / ((x1 - x0) * W)  # output pixels per full-size pixel
        out_h = max(1, round((y1 - y0) * H * s))
        origin = (round(x0 * W * s), round(y0 * H * s))
        img = self._render_window((W * s, H * s), s, True, origin, (out_w, out_h), False)
        return effects.apply_all(img, RenderContext(scale=s, preview=True, origin=origin,
                                                    canvas_size=(W * s, H * s), dpi=self.dpi), skip_live=True)

    # ---------- export ----------
    def export(self, path: str | Path, quality: int = 95) -> None:
        path = Path(path)
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXPORT:
            raise ValueError(f"Unsupported export format: {ext or '(none)'}")
        w, h = self.final_size
        if w * h > MAX_EXPORT_PIXELS:
            raise ValueError(
                f"The output would be {w} x {h} px ({w * h / 1e6:.0f} megapixels), which is too large "
                "to build in memory. Lower the DPI or the output size and try again."
            )
        effects.take_errors()  # forget old problems
        img = self.render()
        problems = effects.take_errors()
        if problems:  # better to stop than to quietly save a picture that is missing something
            raise RuntimeError("A plugin reported a problem, so the file was not saved:\n\n" + "\n".join(problems[:5]))
        if ext in (".jpg", ".jpeg") and img.mode == "RGBA":
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        kwargs: dict = {"dpi": (self.dpi, self.dpi)}
        if ext == ".png":
            kwargs["compress_level"] = 3  # much faster than the default on poster-sized files
        if ext in (".jpg", ".jpeg", ".webp"):
            kwargs["quality"] = quality
        if ext in (".tif", ".tiff"):
            kwargs["compression"] = "tiff_lzw"
        img.save(path, **kwargs)
