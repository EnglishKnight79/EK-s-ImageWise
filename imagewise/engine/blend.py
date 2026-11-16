"""Small image-blending helpers shared by the engine and the plugins (no UI code)."""
from __future__ import annotations

from PIL import Image


def apply_opacity(piece: Image.Image, opacity: float) -> None:
    """Scale the alpha channel of an RGBA image in place (opacity 0..1)."""
    if opacity < 1.0:
        lut = [int(i * max(0.0, opacity)) for i in range(256)]
        piece.putalpha(piece.getchannel("A").point(lut))


def paste_alpha(base: Image.Image, piece: Image.Image, left: int, top: int) -> None:
    """Alpha-composite an RGBA `piece` onto `base` at (left, top), clipping at the edges.

    `base` is modified in place. Anything outside the canvas is ignored, so the
    piece may hang off any side. Only the overlapping region is processed, which
    keeps this fast on very large canvases.
    """
    bw, bh = base.size
    x0, y0 = max(left, 0), max(top, 0)
    x1, y1 = min(left + piece.width, bw), min(top + piece.height, bh)
    if x1 <= x0 or y1 <= y0:
        return
    part = piece.crop((x0 - left, y0 - top, x1 - left, y1 - top))
    region = base.crop((x0, y0, x1, y1)).convert("RGBA")
    base.paste(Image.alpha_composite(region, part).convert(base.mode), (x0, y0))
