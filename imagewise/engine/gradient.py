"""Colour gradients (no UI code, no numpy).

A Gradient has colour stops, a direction (angle, or radial from the centre) and
is always laid across the WHOLE canvas. Functions take an optional window
(origin + full canvas size) so a zoomed preview shows exactly the same gradient
as the full-size export.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image


@dataclass
class Gradient:
    # (position 0..1, (r, g, b)), at least two stops
    stops: list = field(default_factory=lambda: [(0.0, (255, 255, 255)), (1.0, (0, 0, 120))])
    angle: float = 90.0  # degrees: 0 = left to right, 90 = top to bottom
    radial: bool = False  # True = from the centre outwards

    @classmethod
    def two(cls, c1, c2, angle: float = 90.0, radial: bool = False) -> "Gradient":
        return cls([(0.0, tuple(c1)), (1.0, tuple(c2))], angle, radial)

    @property
    def first(self) -> tuple:
        return tuple(sorted(self.stops)[0][1])

    @property
    def last(self) -> tuple:
        return tuple(sorted(self.stops)[-1][1])

    def set_ends(self, c1=None, c2=None) -> None:
        ordered = sorted(self.stops)
        if c1 is not None:
            ordered[0] = (ordered[0][0], tuple(c1))
        if c2 is not None:
            ordered[-1] = (ordered[-1][0], tuple(c2))
        self.stops = ordered


def lut(stops) -> tuple[list[int], list[int], list[int]]:
    """Three 256-entry lookup tables (R, G, B) that turn a 0..255 value into the gradient colour."""
    pts = sorted((max(0.0, min(1.0, p)), tuple(c)) for p, c in stops)
    if len(pts) == 1:
        pts = [(0.0, pts[0][1]), (1.0, pts[0][1])]
    chans = ([], [], [])
    for i in range(256):
        t = i / 255
        for k in range(len(pts) - 1):
            (p0, c0), (p1, c1) = pts[k], pts[k + 1]
            if t <= p1 or k == len(pts) - 2:
                f = 0.0 if p1 == p0 else min(1.0, max(0.0, (t - p0) / (p1 - p0)))
                for ch in range(3):
                    chans[ch].append(round(c0[ch] + (c1[ch] - c0[ch]) * f))
                break
    return chans


@lru_cache(maxsize=1)
def _linear_source() -> Image.Image:
    """2 x 258 ramp: rows 1..257 run black to white, rows 0 and 257 pad the ends for clean sampling."""
    data = bytearray()
    for r in range(258):
        v = round(255 * min(1.0, max(0.0, (r - 1) / 256)))
        data += bytes((v, v))
    return Image.frombytes("L", (2, 258), bytes(data))


@lru_cache(maxsize=1)
def _radial_source() -> Image.Image:
    """256 x 256 ramp: black at the centre, white at distance 128 (clipped beyond)."""
    data = bytearray()
    for y in range(256):
        for x in range(256):
            d = math.hypot(x + 0.5 - 128, y + 0.5 - 128)
            data.append(min(255, round(255 * d / 128)))
    return Image.frombytes("L", (256, 256), bytes(data))


def ramp(size: tuple[int, int], angle: float = 90.0, radial: bool = False,
         origin: tuple[float, float] = (0, 0), full_size: tuple[float, float] | None = None) -> Image.Image:
    """An 'L' image where 0 = start of the gradient and 255 = end, for a window of the canvas."""
    w, h = size
    Wf, Hf = full_size or size
    ox, oy = origin
    if radial:
        R = (math.hypot(Wf, Hf) / 2) or 1.0
        k = 128 / R
        coeffs = (k, 0, 128 + (ox - Wf / 2) * k, 0, k, 128 + (oy - Hf / 2) * k)
        src = _radial_source()
    else:
        a = math.radians(angle)
        dx, dy = math.cos(a), math.sin(a)
        length = (abs(Wf * dx) + abs(Hf * dy)) or 1.0
        k = 256 / length
        coeffs = (0, 0, 1, k * dx, k * dy, 129 + k * (dx * (ox - Wf / 2) + dy * (oy - Hf / 2)))
        src = _linear_source()
    return src.transform((w, h), Image.AFFINE, coeffs, resample=Image.BILINEAR)


def apply_lut(l_image: Image.Image, stops) -> Image.Image:
    """Colour an 'L' image through gradient stops -> RGB."""
    r, g, b = lut(stops)
    return Image.merge("RGB", (l_image.point(r), l_image.point(g), l_image.point(b)))


def render(grad: Gradient, size: tuple[int, int], origin=(0, 0), full_size=None) -> Image.Image:
    """The gradient as an RGB image for a window of the canvas."""
    return apply_lut(ramp(size, grad.angle, grad.radial, origin, full_size), grad.stops)
