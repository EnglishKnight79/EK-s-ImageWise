"""Crop shapes loaded from image files (no UI code).

A crop shape is just a picture file: either a PNG / WebP / TIFF with transparency
(the visible part is the shape), or a plain picture where the shape is dark on a
light background or light on a dark background (detected from the corners; use the
"invert" option if it guesses wrong). The Crop Shapes plugin lets the user point
the app at a folder of such files.

A photo with a shape is trimmed to the shape's bounding box and everything outside the
shape becomes transparent. The shape can be scaled (size inside the crop box) and rotated.

The feature only works while the plugin is loaded and switched on (set_active), so removing
the plugin removes crop shapes from the app.
"""
from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

EXTS = {".png", ".webp", ".tif", ".tiff", ".bmp", ".jpg", ".jpeg"}
MAX_SIDE = 3000  # larger shape pictures are shrunk to this (memory)

_active = False


def set_active(on: bool) -> None:
    global _active
    _active = bool(on)


def is_active() -> bool:
    return _active


def scan_folder(folder) -> list[Path]:
    """All shape pictures in a folder and its sub-folders, sorted by name."""
    if not folder or not Path(folder).is_dir():
        return []
    root = Path(folder)
    files = [p for p in root.rglob("*") if p.suffix.lower() in EXTS and p.is_file() and not p.name.startswith(".")]
    return sorted(files, key=lambda p: str(p.relative_to(root)).lower())


@lru_cache(maxsize=48)
def _load(path: str, invert: bool, mtime: int) -> Image.Image:
    img = Image.open(path)
    img.load()
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    mask = None
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        alpha = img.convert("RGBA").getchannel("A")
        if alpha.getextrema()[0] < 250:  # really has transparent parts: the visible part is the shape
            mask = alpha
    if mask is None:  # a plain picture: the shape is whichever of dark / light is NOT the background
        gray = img.convert("L")
        w, h = gray.size
        corners = [gray.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        light_background = sum(corners) / 4 > 127
        mask = ImageOps.invert(gray) if light_background else gray
    if invert:
        mask = ImageOps.invert(mask)
    box = mask.point([255 if v > 24 else 0 for v in range(256)]).getbbox()
    if box is None:
        raise ValueError("This picture has no visible shape in it.")
    return mask.crop(box)  # trimmed to the shape itself


def load_mask(path, invert: bool = False) -> Image.Image:
    """The shape as an 'L' mask (255 inside), trimmed to its own bounding box."""
    p = str(path)
    return _load(p, bool(invert), os.stat(p).st_mtime_ns)


def aspect(path, invert: bool = False) -> float:
    """Natural width / height of the shape."""
    w, h = load_mask(path, invert).size
    return w / h


def usable(path, invert: bool = False) -> bool:
    try:
        load_mask(path, invert)
        return True
    except Exception:
        return False


def _bounding(mw: float, mh: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return abs(mw * math.cos(a)) + abs(mh * math.sin(a)), abs(mw * math.sin(a)) + abs(mh * math.cos(a))


def fit_size(path, crop_size: tuple[int, int], scale: float, rotation: float, invert: bool = False) -> tuple[float, float]:
    """Size of the box the (rotated) shape occupies when it is fitted inside a crop box of crop_size."""
    mw, mh = load_mask(path, invert).size
    bw, bh = _bounding(mw, mh, rotation)
    k = min(crop_size[0] / bw, crop_size[1] / bh) * scale
    return k * bw, k * bh


def mask(path, size: tuple[int, int], view: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
         rotation: float = 0.0, invert: bool = False) -> Image.Image:
    """'L' mask (255 inside the shape) for a window of the shape's bounding box.

    The box is the axis-aligned box around the shape after it has been rotated by `rotation`
    degrees (clockwise). size = mask size in pixels; view = (x0, y0, x1, y1) fractions of the box
    that the mask covers (the whole box by default).
    """
    src = load_mask(path, invert)
    mw, mh = src.size
    w, h = size
    x0, y0, x1, y1 = view
    a = math.radians(rotation)
    ca, sa = math.cos(a), math.sin(a)
    bw, bh = _bounding(mw, mh, rotation)
    sx, sy = (x1 - x0) * bw / w, (y1 - y0) * bh / h  # shape pixels per output pixel
    r = min(1.0, 1.0 / max(sx, sy, 1e-6))
    if r < 0.7:  # shrinking a lot: average first so thin parts of the shape don't alias
        src = src.resize((max(1, round(mw * r)), max(1, round(mh * r))), Image.LANCZOS)
    rx, ry = src.width / mw, src.height / mh
    src = ImageOps.expand(src, 1, 0)  # a transparent border gives soft edges
    ox, oy = x0 * bw - bw / 2, y0 * bh - bh / 2
    coeffs = (ca * sx * rx, sa * sy * rx, (ca * ox + sa * oy + mw / 2) * rx + 1,
              -sa * sx * ry, ca * sy * ry, (-sa * ox + ca * oy + mh / 2) * ry + 1)
    return src.transform((w, h), Image.AFFINE, coeffs, resample=Image.BILINEAR)
