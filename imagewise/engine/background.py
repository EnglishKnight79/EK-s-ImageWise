"""Background-removal support in the core (no UI code, no AI).

The *Background Removal* plugin produces a greyscale MASK (white = keep, black = remove) with an AI
model and stores it on a Photo. The core only applies it (as the photo's alpha) and tidies its edge,
so it stays non-destructive: the original is untouched and the edge sliders (shrink / feather) can
change instantly without re-running the AI.

Cut-outs are only applied while the plugin is loaded and switched on (set_active), so removing the
plugin removes the feature.
"""
from __future__ import annotations

from PIL import Image, ImageFilter

_active = False


def set_active(on: bool) -> None:
    global _active
    _active = bool(on)


def is_active() -> bool:
    return _active


def refine_mask(mask: Image.Image, shrink: float = 0.0, feather: float = 0.0) -> Image.Image:
    """Tidy the mask edge. Units are pixels of the mask as passed in.

    shrink > 0 pulls the edge inwards (removes halos / leftover background),
    shrink < 0 grows it outwards. feather softens the edge.
    Implemented as blur + threshold so it stays fast on very large masks.
    """
    if shrink:
        sigma = max(0.5, abs(shrink) / 2)
        blurred = mask.filter(ImageFilter.GaussianBlur(sigma))
        # shrink: only keep pixels that are almost fully inside; grow: keep anything slightly inside
        threshold = 250 if shrink > 0 else 5
        mask = blurred.point(lambda v, t=threshold: 255 if v >= t else 0)
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask
