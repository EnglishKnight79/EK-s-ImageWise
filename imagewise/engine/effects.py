"""Hooks that let plugins change the picture. No UI code.

Two kinds of hook:

* EFFECT - runs after the canvas is built (photos, or whatever a generator drew) and changes the
  picture non-destructively. An effect is any object with
      enabled : bool                        (optional, default True)
      layer   : int                         (optional, default 0; higher layers run later)
      live_on_canvas : bool                 (optional; True = the on-screen canvas draws this itself so it
                                             can be dragged, so previews skip it and only the export uses it)
      apply(image, ctx) -> PIL.Image        must return an image of the SAME size

* GENERATOR - replaces how the canvas is built (for example the Pattern / Poster plugin). An object with
      enabled : bool
      canvas_size(document) -> (w, h) or None      (None = no opinion about the canvas size)
      render_base(document, ...) -> PIL.Image or None      (None = let the normal photos draw the canvas)

A failing plugin is skipped (and reported) instead of breaking the render.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

log = logging.getLogger("imagewise")


@dataclass
class RenderContext:
    scale: float = 1.0  # output pixels per full-size pixel (1.0 = full size; <1 = small preview, >1 = zoomed in)
    preview: bool = False  # True for on-screen previews, False for the final export
    origin: tuple = (0.0, 0.0)  # where this image sits inside the whole canvas (pixels at this scale)
    canvas_size: tuple | None = None  # the whole canvas in pixels at this scale (None = this image IS the canvas)
    dpi: float = 300.0  # the document's print resolution (for sizes given in cm)

    def whole_canvas(self, image) -> tuple:
        """Size of the whole canvas (so effects can place things relative to it, even in a zoomed window)."""
        return self.canvas_size or image.size


_effects: list = []
_generators: list = []
_errors: list[str] = []


def clear() -> None:
    _effects.clear()
    _generators.clear()


def register(effect) -> None:
    if effect not in _effects:
        _effects.append(effect)
        _effects.sort(key=lambda e: getattr(e, "layer", 0))  # stable: equal layers keep load order


def register_generator(generator) -> None:
    if generator not in _generators:
        _generators.append(generator)


def active() -> list:
    return [e for e in _effects if getattr(e, "enabled", True)]


def generators() -> list:
    return [g for g in _generators if getattr(g, "enabled", True)]


def report(name: str, exc: Exception) -> None:
    log.exception("Plugin %s failed", name)
    _errors.append(f"{name}: {type(exc).__name__}: {exc}")


def take_errors() -> list[str]:
    """Return (and clear) any problems reported since the last call."""
    out = list(dict.fromkeys(_errors))
    _errors.clear()
    return out


def apply_all(image: Image.Image, ctx: RenderContext, skip_live: bool = False) -> Image.Image:
    for fx in active():
        if skip_live and getattr(fx, "live_on_canvas", False):
            continue
        name = getattr(fx, "name", type(fx).__name__)
        try:
            out = fx.apply(image, ctx)
        except Exception as exc:
            report(name, exc)
            continue
        if out is None:
            continue
        if out.size != image.size:
            _errors.append(f"{name}: effects must keep the image size (ignored)")
            continue
        image = out
    return image
