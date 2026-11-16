"""One picture in a composition (no UI code).

A Photo owns its original image plus its own non-destructive edits (crop,
background-removal mask) and where it sits on the canvas. A Document holds a
list of Photos; list order = layer order (index 0 is the bottom layer).

Placement values are FRACTIONS of the canvas, so previews and full-size exports
line up and a photo keeps its place if the canvas size changes:
    cx, cy    centre of the photo (0..1 of canvas width / height)
    scale     photo width as a fraction of canvas width (height follows its shape)
    rotation  degrees, clockwise
    fill      True = stretched to cover the whole canvas (the default for a lone photo)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from imagewise.engine import background, shapes
from imagewise.engine.background import refine_mask
from imagewise.engine.blend import apply_opacity

MIN_PHOTO_SCALE, MAX_PHOTO_SCALE = 0.02, 5.0


class Photo:
    def __init__(self, path: Path | None, image: Image.Image):
        self.path = path
        self.original = image
        self.crop: tuple[int, int, int, int] | None = None  # (left, top, right, bottom)
        # background removal: the mask is computed once (slow, AI); the rest is cheap
        self.mask: Image.Image | None = None  # 'L', same size as original; never edited in place
        self.remove_bg = False
        self.bg_shrink = 0
        self.bg_feather = 0
        # crop shape (set by the Crop Shapes plugin): the photo is trimmed to the shape and everything
        # outside it is transparent
        self.shape: str | None = None  # path of a shape picture
        self.shape_scale = 1.0  # 0.2..1: size of the shape inside the crop box
        self.shape_rotation = 0.0  # degrees, clockwise
        self.shape_invert = False  # swap inside / outside of the shape picture
        self.outline = False
        self.outline_color = (0, 0, 0)
        self.outline_width = 6  # px at full output size
        # placement on the canvas
        self.fill = True
        self.cx, self.cy = 0.5, 0.5
        self.scale = 1.0
        self.rotation = 0.0
        self.opacity = 1.0
        self.visible = True
        self._proxy: Image.Image | None = None

    # ---------- loading ----------
    @classmethod
    def open(cls, path: str | Path) -> "Photo":
        path = Path(path)
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)  # respect phone-camera rotation
        img.load()
        has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        img = img.convert("RGBA" if has_alpha else "RGB")
        return cls(path, img)

    @property
    def name(self) -> str:
        return self.path.name if self.path else "Photo"

    # ---------- crop ----------
    @property
    def size(self) -> tuple[int, int]:
        return self.original.size

    @property
    def crop_box(self) -> tuple[int, int, int, int]:
        return self.crop or (0, 0, *self.original.size)

    def active_shape(self) -> str | None:
        """The shape picture in use, or None (no shape chosen, plugin off, or the file is gone)."""
        if self.shape and shapes.is_active() and shapes.usable(self.shape, self.shape_invert):
            return self.shape
        return None

    @property
    def render_box(self) -> tuple[int, int, int, int]:
        """The part of the original that is actually used: the crop box, or with a crop shape
        the box around the (rotated) shape, fitted inside the crop box (times the shape size)."""
        l, t, r, b = self.crop_box
        shape = self.active_shape()
        if not shape:
            return l, t, r, b
        cw, ch = r - l, b - t
        ew, eh = shapes.fit_size(shape, (cw, ch), self.shape_scale, self.shape_rotation, self.shape_invert)
        cx, cy = (l + r) / 2, (t + b) / 2
        W, H = self.original.size
        nl, nt = max(0, round(cx - ew / 2)), max(0, round(cy - eh / 2))
        nr, nb = min(W, max(nl + 1, round(cx + ew / 2))), min(H, max(nt + 1, round(cy + eh / 2)))
        return nl, nt, nr, nb

    @property
    def crop_size(self) -> tuple[int, int]:
        """Size of the picture as used (after any crop shape)."""
        l, t, r, b = self.render_box
        return r - l, b - t

    @property
    def aspect(self) -> float:
        """Height / width of the cropped picture."""
        w, h = self.crop_size
        return h / w

    def set_crop(self, box: tuple[int, int, int, int] | None) -> None:
        """Clamp the box to the image; a box covering the whole image means 'no crop'."""
        if box is None:
            self.crop = None
            return
        w, h = self.original.size
        l, t, r, b = box
        l, t = max(0, min(l, w - 1)), max(0, min(t, h - 1))
        r, b = max(l + 1, min(r, w)), max(t + 1, min(b, h))
        self.crop = None if (l, t, r, b) == (0, 0, w, h) else (l, t, r, b)

    def proxy(self, max_side: int = 2000) -> Image.Image:
        """Cached downscaled copy of the ORIGINAL, used for fast on-screen display."""
        if self._proxy is None:
            p = self.original.copy()
            p.thumbnail((max_side, max_side), Image.BILINEAR, reducing_gap=2.0)
            self._proxy = p
        return self._proxy

    # ---------- placement helpers ----------
    def reset_placement(self, is_base: bool) -> None:
        self.fill = is_base
        self.cx = self.cy = 0.5
        self.scale = 1.0 if is_base else 0.5
        self.rotation = 0.0
        self.opacity = 1.0
        self.visible = True

    def reset_background(self) -> None:
        self.mask, self.remove_bg, self.bg_shrink, self.bg_feather = None, False, 0, 0

    def reset_shape(self) -> None:
        self.shape, self.shape_scale, self.shape_rotation, self.shape_invert = None, 1.0, 0.0, False
        self.outline, self.outline_color, self.outline_width = False, (0, 0, 0), 6

    # ---------- undo support ----------
    def key(self) -> tuple:
        """Cheap comparable summary of every setting (identity, not pixels, for the mask)."""
        return (id(self), self.crop, id(self.mask) if self.mask is not None else None, self.remove_bg,
                self.bg_shrink, self.bg_feather, self.fill, self.cx, self.cy, self.scale,
                self.rotation, self.opacity, self.visible, self.shape, self.shape_scale, self.shape_rotation,
                self.shape_invert, self.outline, self.outline_color, self.outline_width)

    def state(self) -> dict:
        return {"crop": self.crop, "mask": self.mask, "remove_bg": self.remove_bg,
                "bg_shrink": self.bg_shrink, "bg_feather": self.bg_feather, "fill": self.fill,
                "cx": self.cx, "cy": self.cy, "scale": self.scale, "rotation": self.rotation,
                "opacity": self.opacity, "visible": self.visible, "shape": self.shape,
                "shape_scale": self.shape_scale, "shape_rotation": self.shape_rotation,
                "shape_invert": self.shape_invert, "outline": self.outline,
                "outline_color": self.outline_color, "outline_width": self.outline_width}

    def restore(self, state: dict) -> None:
        for k, v in state.items():
            setattr(self, k, v)

    # ---------- rendering ----------
    def prepare(self, w: int, h: int, scale: float = 1.0, preview: bool = False,
                view: tuple[float, float, float, float] | None = None) -> Image.Image:
        """Crop, resize to (w, h) and apply the background-removal mask.

        `view` (x0, y0, x1, y1 as fractions of the cropped picture) selects just a
        window of it, which keeps zoomed previews fast at any zoom level.
        """
        l, t, r, b = self.render_box
        mask_src = self.mask if (self.remove_bg and self.mask is not None and background.is_active()) else None
        if view is None:
            box = (l, t, r, b)
        else:
            cw, ch = r - l, b - t
            x0, y0, x1, y1 = view
            box = (max(l, l + x0 * cw), max(t, t + y0 * ch), min(r, l + x1 * cw), min(b, t + y1 * ch))
            if box[2] <= box[0] + 1e-6:
                box = (box[0], box[1], box[0] + 1e-3, box[3])
            if box[3] <= box[1] + 1e-6:
                box = (box[0], box[1], box[2], box[1] + 1e-3)

        if view is None and (w, h) == (r - l, b - t):
            img = self.original.crop(box)
            mask = mask_src.crop(box) if mask_src is not None else None
        else:
            method = Image.BILINEAR if preview else Image.LANCZOS
            kw = {"reducing_gap": 2.0} if preview else {}
            img = self.original.resize((w, h), method, box=box, **kw)
            mask = mask_src.resize((w, h), method, box=box, **kw) if mask_src is not None else None

        if mask is not None:
            # slider values are defined at full output size, so scale them for previews
            mask = refine_mask(mask, self.bg_shrink * scale, self.bg_feather * scale)
            if img.mode == "RGBA":  # keep any transparency the file already had
                mask = ImageChops.multiply(img.getchannel("A"), mask)
            else:
                img = img.convert("RGBA")
            img.putalpha(mask)

        shape = self.active_shape()
        if shape:
            shape_mask = shapes.mask(shape, (w, h), view or (0.0, 0.0, 1.0, 1.0), self.shape_rotation, self.shape_invert)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            alpha = ImageChops.multiply(img.getchannel("A"), shape_mask)
            if self.outline and self.outline_width > 0:  # a ring just inside the edge of the shape
                inner = refine_mask(shape_mask, shrink=max(1.0, self.outline_width * scale))
                ring = ImageChops.subtract(shape_mask, inner)
                rgb = Image.composite(Image.new("RGB", (w, h), tuple(self.outline_color)), img.convert("RGB"), ring)
                alpha = ImageChops.lighter(alpha, ring)
                img = rgb.convert("RGBA")
            img.putalpha(alpha)
        return img

    def fill_piece(self, window: tuple[int, int, int, int], full_size: tuple[float, float],
                   scale: float, preview: bool, is_full: bool) -> Image.Image:
        """The photo stretched over the whole canvas, for the window (ox, oy, w, h) of it."""
        ox, oy, vw, vh = window
        view = None
        if not is_full:
            fw, fh = full_size
            view = (ox / fw, oy / fh, (ox + vw) / fw, (oy + vh) / fh)
        return self.prepare(vw, vh, scale, preview, view=view)

    def free_piece(self, window: tuple[int, int, int, int], full_size: tuple[float, float],
                   scale: float, preview: bool):
        """The photo placed freely (move / scale / rotate) on a canvas of `full_size` pixels.

        Returns (RGBA piece, (x, y) of the piece inside the window) or None when the
        photo is not visible in the window. Only the part of the photo that lands in
        the window is processed, so this stays cheap however far you zoom in.
        """
        ox, oy, vw, vh = window
        Wf, Hf = full_size
        cw, ch = self.crop_size
        tw = self.scale * Wf  # photo width in canvas pixels
        th = tw * ch / cw
        if tw < 0.5 or th < 0.5:
            return None
        cxp, cyp = self.cx * Wf, self.cy * Hf
        ang = math.radians(self.rotation)
        ca, sa = math.cos(ang), math.sin(ang)
        hw, hh = tw / 2, th / 2

        xs, ys = [], []
        for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
            xs.append(cxp + lx * ca - ly * sa)
            ys.append(cyp + lx * sa + ly * ca)
        bx0, by0 = max(math.floor(min(xs)), ox), max(math.floor(min(ys)), oy)
        bx1, by1 = min(math.ceil(max(xs)), ox + vw), min(math.ceil(max(ys)), oy + vh)
        if bx1 <= bx0 or by1 <= by0:
            return None
        pw, ph = bx1 - bx0, by1 - by0

        # which part of the (cropped) source lands inside that bounding box?
        f = tw / cw  # canvas pixels per source pixel
        us, vs = [], []
        for X, Y in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)):
            dx, dy = X - cxp, Y - cyp
            us.append((ca * dx + sa * dy + hw) / f)
            vs.append((-sa * dx + ca * dy + hh) / f)
        sx0, sy0 = max(0.0, min(us) - 2), max(0.0, min(vs) - 2)
        sx1, sy1 = min(float(cw), max(us) + 2), min(float(ch), max(vs) + 2)
        if sx1 <= sx0 or sy1 <= sy0:
            return None
        sub_w, sub_h = sx1 - sx0, sy1 - sy0

        # intermediate image at about output resolution (never upscaled; the transform does that)
        if f < 1:
            iw, ih = max(1, round(sub_w * f)), max(1, round(sub_h * f))
        else:
            iw, ih = max(1, math.ceil(sub_w)), max(1, math.ceil(sub_h))
        src = self.prepare(iw, ih, scale, preview, view=(sx0 / cw, sy0 / ch, sx1 / cw, sy1 / ch))
        kx, ky = iw / (sub_w * f), ih / (sub_h * f)  # intermediate px per canvas px
        lx0, ly0 = sx0 * f - hw, sy0 * f - hh  # local position of the intermediate's top-left

        # 1px transparent border gives soft, anti-aliased edges; premultiplied avoids dark fringes
        padded = ImageOps.expand(src.convert("RGBA"), 1, (0, 0, 0, 0)).convert("RGBa")
        dx0, dy0 = bx0 - cxp, by0 - cyp
        coeffs = (kx * ca, kx * sa, kx * (ca * dx0 + sa * dy0 - lx0) + 1,
                  -ky * sa, ky * ca, ky * (-sa * dx0 + ca * dy0 - ly0) + 1)
        resample = Image.BILINEAR if preview else Image.BICUBIC
        piece = padded.transform((pw, ph), Image.AFFINE, coeffs, resample=resample).convert("RGBA")
        return piece, (bx0 - ox, by0 - oy)

    def finished_piece(self, window, full_size, scale, preview, is_full):
        """Piece + position for this photo, with its opacity applied; None if nothing to draw."""
        if self.fill:
            piece, pos = self.fill_piece(window, full_size, scale, preview, is_full).convert("RGBA"), (0, 0)
        else:
            res = self.free_piece(window, full_size, scale, preview)
            if res is None:
                return None
            piece, pos = res
        apply_opacity(piece, self.opacity)
        return piece, pos
