"""Canvas widget: shows an image, with zoom and pan.

Zoom: mouse wheel zooms towards the cursor. Pan by dragging with the middle or
right button, or Alt + left button. The zoom buttons next to the canvas call
zoom_in / zoom_out / zoom_fit / zoom_actual.

Crop mode (the crop pane): shows the full original, dims everything outside the
crop box, and lets the user drag out a new crop rectangle. Coordinates are
emitted in ORIGINAL image pixels, even though a smaller proxy image is drawn.

Preview mode (the preview pane): shows the edited image with the alpha overlays
on top. Overlays can be dragged to move, dragged by the corner handle to
resize, or resized with Shift + wheel. A sharper "detail" picture of just the
visible part can be supplied when zoomed in (set_detail), drawn over the
overall picture.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from imagewise.engine.photo import MAX_PHOTO_SCALE, MIN_PHOTO_SCALE

HANDLE = 12  # px, size of the overlay resize handle
MIN_SCALE, MAX_SCALE = 0.02, 2.0  # size limits (fraction of the canvas width) for live canvas items
KEEP_VISIBLE = 60  # px of the image that must stay on screen when panning


class ImageCanvas(QWidget):
    cropDragged = Signal(int, int, int, int)  # left, top, right, bottom (original px)
    overlayEdited = Signal(int)  # overlay index whose position/size changed
    overlaySelected = Signal(int)  # -1 = nothing selected
    photoSelected = Signal(int)  # Document.photos index, -1 = none
    photoEdited = Signal(int)  # a photo was moved / resized by dragging
    photoDragFinished = Signal()
    zoomChanged = Signal(float)  # zoom as a percentage of actual image pixels
    viewChanged = Signal()  # zoom, pan or widget size changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 240)
        self.setMouseTracking(True)
        self.detail_supported = False  # True: caller can provide sharper detail when zoomed in
        self._pixmap: QPixmap | None = None
        self._orig_size = (1, 1)
        self._crop_mode = False
        self._crop = (0, 0, 1, 1)  # original px
        self._shape_dim = None  # dark layer that dims everything outside the crop shape
        self._drag_start: QPointF | None = None
        self._bg = QColor(40, 40, 44)  # window colour behind the picture (set by set_theme)
        self._fg = QColor(170, 170, 175)  # colour of the hint text
        self._checker = self._make_checker(True)
        # overlays: list of (Overlay model, display QPixmap or None); drawn in list order
        self._ov_items: list[tuple[object, QPixmap | None]] = []
        self._sel = -1
        self._ov_drag: tuple | None = None  # (mode, index, start_pos, start_cx, start_cy)
        # photos of the composition (live Photo models) and their selection
        self._photos: list = []
        self._psel = -1
        self._photo_drag: tuple | None = None  # (mode, index, start_pos, start_cx, start_cy)
        # locked categories ignore mouse editing
        self._crop_locked = self._ov_locked = self._photos_locked = False
        # zoom / pan: zoom 1.0 = fit to window; pan = offset of the image centre in widget px
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._pan_drag: tuple[QPointF, QPointF] | None = None
        # sharper picture of part of the image (region = fractions of the whole image)
        self._detail_pm: QPixmap | None = None
        self._detail_region: tuple[float, float, float, float] | None = None

    @staticmethod
    def _make_checker(dark: bool) -> QBrush:
        """The checkerboard shown behind transparent areas."""
        light_sq, dark_sq = (QColor(92, 92, 96), QColor(68, 68, 72)) if dark else (QColor(255, 255, 255), QColor(205, 205, 212))
        tile = QPixmap(20, 20)
        tile.fill(light_sq)
        tp = QPainter(tile)
        tp.fillRect(0, 0, 10, 10, dark_sq)
        tp.fillRect(10, 10, 10, 10, dark_sq)
        tp.end()
        return QBrush(tile)

    def set_theme(self, dark: bool):
        self._bg = QColor(40, 40, 44) if dark else QColor(222, 223, 229)
        self._fg = QColor(170, 170, 175) if dark else QColor(95, 95, 105)
        self._checker = self._make_checker(dark)
        self.update()

    # ----- public API -----
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_image(self, pixmap: QPixmap | None, original_size: tuple[int, int] | None = None):
        self._pixmap = pixmap
        if original_size:
            self._orig_size = original_size
        if pixmap is None:
            self._zoom, self._pan = 1.0, QPointF(0, 0)
            self.clear_detail()
        elif self._zoom > self._max_zoom():
            self._set_zoom(self._max_zoom(), self._centre())
        self._emit_zoom()
        self.update()

    def set_detail(self, pixmap: QPixmap, region: tuple[float, float, float, float]):
        self._detail_pm, self._detail_region = pixmap, region
        self.update()

    def clear_detail(self):
        if self._detail_pm is not None:
            self._detail_pm, self._detail_region = None, None
            self.update()

    def set_crop_mode(self, enabled: bool):
        self._crop_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    def set_crop(self, box: tuple[int, int, int, int]):
        self._crop = box
        self.update()

    def set_shape_dim(self, pixmap):
        """A see-through dark layer (same shape as the crop pane picture) that dims what is outside a
        crop shape; None hides it."""
        self._shape_dim = pixmap
        self.update()

    def set_overlays(self, items: list[tuple[object, QPixmap | None]]):
        self._ov_items = items
        if self._sel >= len(items):
            self._sel = -1
        self.update()

    def select_overlay(self, index: int):
        self._sel = index
        if index >= 0:
            self._psel = -1
        self.update()

    def set_photos(self, photos: list):
        """The photos that can be selected and dragged in the preview (live models)."""
        self._photos = list(photos)
        if self._psel >= len(self._photos):
            self._psel = -1
        self.update()

    def select_photo(self, index: int):
        self._psel = index
        if index >= 0:
            self._sel = -1
        self.update()

    def set_locks(self, crop: bool | None = None, overlays: bool | None = None, photos: bool | None = None):
        if crop is not None:
            self._crop_locked = crop
        if overlays is not None:
            self._ov_locked = overlays
        if photos is not None:
            self._photos_locked = photos

    def visible_region(self, margin: float = 0.0):
        """The part of the image currently on screen, as fractions (x0, y0, x1, y1),
        plus its size in widget pixels. `margin` widens it (e.g. 0.1 = 10% each side)."""
        d = self._display_rect()
        if self._pixmap is None or d.width() <= 0 or d.height() <= 0:
            return None
        vis = d.intersected(QRectF(self.rect()))
        if vis.isEmpty():
            return None
        x0, x1 = (vis.left() - d.left()) / d.width(), (vis.right() - d.left()) / d.width()
        y0, y1 = (vis.top() - d.top()) / d.height(), (vis.bottom() - d.top()) / d.height()
        mx, my = (x1 - x0) * margin, (y1 - y0) * margin
        x0, y0 = max(0.0, x0 - mx), max(0.0, y0 - my)
        x1, y1 = min(1.0, x1 + mx), min(1.0, y1 + my)
        return (x0, y0, x1, y1), ((x1 - x0) * d.width(), (y1 - y0) * d.height())

    # ----- zoom -----
    def zoom_in(self):
        self._set_zoom(self._zoom * 1.25, self._centre())

    def zoom_out(self):
        self._set_zoom(self._zoom / 1.25, self._centre())

    def zoom_fit(self):
        self._set_zoom(1.0, self._centre())

    def zoom_actual(self):
        """1 image pixel = 1 screen pixel (as far as the zoom limit allows)."""
        fit = self._fit_rect()
        if not fit.isEmpty():
            self._set_zoom(self._orig_size[0] / fit.width(), self._centre())

    def _centre(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def _max_zoom(self) -> float:
        fit = self._fit_rect()
        if self._pixmap is None or fit.isEmpty():
            return 1.0
        if self.detail_supported:  # sharp detail can be rendered, so allow up to 100%
            return max(4.0, self._orig_size[0] / fit.width())
        return max(4.0, 2.0 * self._pixmap.width() / fit.width())  # only the proxy picture exists

    def _set_zoom(self, zoom: float, anchor: QPointF):
        """Change zoom keeping the image point under `anchor` where it is."""
        fit = self._fit_rect()
        if self._pixmap is None or fit.isEmpty():
            return
        zoom = min(max(zoom, 1.0), self._max_zoom())
        old = self._display_rect()
        u = QPointF((anchor.x() - old.left()) / old.width(), (anchor.y() - old.top()) / old.height())
        self._zoom = zoom
        if zoom <= 1.0001:
            self._pan = QPointF(0, 0)
        else:
            w, h = fit.width() * zoom, fit.height() * zoom
            top_left = QPointF(anchor.x() - u.x() * w, anchor.y() - u.y() * h)
            self._pan = QPointF(top_left.x() - (fit.center().x() - w / 2),
                                top_left.y() - (fit.center().y() - h / 2))
            self._clamp_pan()
        self._emit_zoom()
        self.viewChanged.emit()
        self.update()

    def _clamp_pan(self):
        d = self._display_rect()
        dx = dy = 0.0
        if d.right() < KEEP_VISIBLE:
            dx = KEEP_VISIBLE - d.right()
        elif d.left() > self.width() - KEEP_VISIBLE:
            dx = (self.width() - KEEP_VISIBLE) - d.left()
        if d.bottom() < KEEP_VISIBLE:
            dy = KEEP_VISIBLE - d.bottom()
        elif d.top() > self.height() - KEEP_VISIBLE:
            dy = (self.height() - KEEP_VISIBLE) - d.top()
        self._pan = QPointF(self._pan.x() + dx, self._pan.y() + dy)

    def _emit_zoom(self):
        d = self._display_rect()
        if self._pixmap is not None and d.width() > 0:
            self.zoomChanged.emit(d.width() / max(1, self._orig_size[0]) * 100)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._emit_zoom()
        self.viewChanged.emit()

    # ----- geometry helpers -----
    def _fit_rect(self) -> QRectF:
        """Where the image sits at zoom 1 (fitted and centred)."""
        if not self._pixmap:
            return QRectF()
        avail = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if avail.width() <= 0 or avail.height() <= 0 or pw <= 0 or ph <= 0:
            return QRectF()
        scale = min(avail.width() / pw, avail.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def _display_rect(self) -> QRectF:
        """Where the whole image is drawn, including zoom and pan (may extend past the widget)."""
        fit = self._fit_rect()
        if fit.isEmpty():
            return QRectF()
        w, h = fit.width() * self._zoom, fit.height() * self._zoom
        return QRectF(fit.center().x() - w / 2 + self._pan.x(), fit.center().y() - h / 2 + self._pan.y(), w, h)

    def _to_widget(self, x: float, y: float) -> QPointF:
        d = self._display_rect()
        ow, oh = self._orig_size
        return QPointF(d.left() + x / ow * d.width(), d.top() + y / oh * d.height())

    def _to_image(self, p: QPointF) -> QPointF:
        d = self._display_rect()
        ow, oh = self._orig_size
        x = (p.x() - d.left()) / d.width() * ow
        y = (p.y() - d.top()) / d.height() * oh
        return QPointF(min(max(x, 0), ow), min(max(y, 0), oh))

    def _ov_rect(self, ov, pm: QPixmap) -> QRectF:
        """Overlay rectangle in widget coordinates (position/size are fractions of the image)."""
        d = self._display_rect()
        w = ov.scale * d.width()
        h = w * pm.height() / pm.width()
        cx = d.left() + ov.cx * d.width()
        cy = d.top() + ov.cy * d.height()
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _photo_geom(self, ph):
        """(centre, width, height, angle in degrees) of a photo in widget pixels, or None."""
        d = self._display_rect()
        if not ph.visible or d.width() <= 0:
            return None
        if ph.fill:
            return d.center(), d.width(), d.height(), 0.0
        w = ph.scale * d.width()
        return QPointF(d.left() + ph.cx * d.width(), d.top() + ph.cy * d.height()), w, w * ph.aspect, ph.rotation

    @staticmethod
    def _to_local(pos: QPointF, centre: QPointF, angle_deg: float) -> QPointF:
        """Widget point -> the photo's own (unrotated) frame, origin at its centre."""
        a = math.radians(angle_deg)
        dx, dy = pos.x() - centre.x(), pos.y() - centre.y()
        return QPointF(math.cos(a) * dx + math.sin(a) * dy, -math.sin(a) * dx + math.cos(a) * dy)

    def _hit_photo(self, pos: QPointF) -> int:
        for i in reversed(range(len(self._photos))):
            geom = self._photo_geom(self._photos[i])
            if geom is None:
                continue
            centre, w, h, ang = geom
            local = self._to_local(pos, centre, ang)
            if abs(local.x()) <= w / 2 and abs(local.y()) <= h / 2:
                return i
        return -1

    def _paint_photo_outline(self, p: QPainter):
        if not (0 <= self._psel < len(self._photos)):
            return
        ph = self._photos[self._psel]
        geom = self._photo_geom(ph)
        if geom is None:
            return
        centre, w, h, ang = geom
        p.save()
        p.translate(centre)
        p.rotate(ang)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 170), 3))
        p.drawRect(QRectF(-w / 2, -h / 2, w, h))
        p.setPen(QPen(QColor(255, 200, 0), 1, Qt.DashLine))
        p.drawRect(QRectF(-w / 2, -h / 2, w, h))
        if not ph.fill:  # fills the canvas -> nothing to resize
            p.setPen(QPen(QColor(0, 0, 0), 1))
            p.setBrush(QColor(255, 200, 0))
            p.drawRect(QRectF(w / 2 - HANDLE / 2, h / 2 - HANDLE / 2, HANDLE, HANDLE))
        p.restore()

    def _photo_handle_hit(self, pos: QPointF) -> bool:
        if not (0 <= self._psel < len(self._photos)):
            return False
        ph = self._photos[self._psel]
        geom = self._photo_geom(ph)
        if geom is None or ph.fill:
            return False
        centre, w, h, ang = geom
        local = self._to_local(pos, centre, ang)
        return abs(local.x() - w / 2) <= HANDLE and abs(local.y() - h / 2) <= HANDLE

    def _handle_rect(self, rect: QRectF) -> QRectF:
        return QRectF(rect.right() - HANDLE / 2, rect.bottom() - HANDLE / 2, HANDLE, HANDLE)

    def _draw_scaled(self, p: QPainter, pm: QPixmap, target: QRectF):
        """Draw `pm` stretched to `target`, but only the part that is on screen
        (so very large zoomed rectangles stay cheap)."""
        vis = target.intersected(QRectF(self.rect()))
        if vis.isEmpty() or target.width() <= 0 or target.height() <= 0:
            return
        sx, sy = pm.width() / target.width(), pm.height() / target.height()
        src = QRectF((vis.left() - target.left()) * sx, (vis.top() - target.top()) * sy,
                     vis.width() * sx, vis.height() * sy)
        p.drawPixmap(vis, pm, src)

    # ----- painting -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), self._bg)
        if not self._pixmap:
            p.setPen(self._fg)
            p.drawText(self.rect(), Qt.AlignCenter, "Open an image to begin\n(File > Open, or drop a file here)")
            return
        d = self._display_rect()
        screen = QRectF(self.rect())
        p.fillRect(d.intersected(screen), self._checker)  # checkerboard behind transparent areas
        self._draw_scaled(p, self._pixmap, d)

        if self._detail_pm is not None and self._detail_region is not None:
            x0, y0, x1, y1 = self._detail_region
            target = QRectF(d.left() + x0 * d.width(), d.top() + y0 * d.height(),
                            (x1 - x0) * d.width(), (y1 - y0) * d.height())
            p.fillRect(target.intersected(screen), self._checker)  # avoid double-blending soft edges
            self._draw_scaled(p, self._detail_pm, target)

        if self._crop_mode:
            self._paint_crop_box(p, d)
            return

        # overlays, bottom layer first, clipped to the image
        p.save()
        p.setClipRect(d)
        for ov, pm in self._ov_items:
            if pm is not None and ov.visible:
                p.setOpacity(ov.opacity)
                self._draw_scaled(p, pm, self._ov_rect(ov, pm))
        p.restore()

        # selection outline + resize handle
        if 0 <= self._sel < len(self._ov_items):
            ov, pm = self._ov_items[self._sel]
            if pm is not None and ov.visible:
                rect = self._ov_rect(ov, pm)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(0, 0, 0, 170), 3))
                p.drawRect(rect)
                p.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
                p.drawRect(rect)
                p.setPen(QPen(QColor(0, 0, 0), 1))
                p.setBrush(QColor(255, 255, 255))
                p.drawRect(self._handle_rect(rect))
        self._paint_photo_outline(p)

    def _paint_crop_box(self, p: QPainter, d: QRectF):
        l, t, r, b = self._crop
        box = QRectF(self._to_widget(l, t), self._to_widget(r, b))
        dim = QColor(0, 0, 0, 150)
        if self._shape_dim is not None:  # dim everything outside the crop SHAPE
            self._draw_scaled(p, self._shape_dim, d)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 170), 1, Qt.DashLine))  # the crop box the shape sits in
            p.drawRect(box)
            return
        p.fillRect(QRectF(d.left(), d.top(), d.width(), box.top() - d.top()), dim)
        p.fillRect(QRectF(d.left(), box.bottom(), d.width(), d.bottom() - box.bottom()), dim)
        p.fillRect(QRectF(d.left(), box.top(), box.left() - d.left(), box.height()), dim)
        p.fillRect(QRectF(box.right(), box.top(), d.right() - box.right(), box.height()), dim)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawRect(box)

    # ----- mouse -----
    @staticmethod
    def _is_pan_gesture(e) -> bool:
        return e.button() in (Qt.MiddleButton, Qt.RightButton) or (
            e.button() == Qt.LeftButton and bool(e.modifiers() & Qt.AltModifier))

    def mousePressEvent(self, e):
        if not self._pixmap:
            return
        pos = e.position()
        if self._is_pan_gesture(e):
            self._pan_drag = (pos, QPointF(self._pan))
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        if self._crop_mode:
            if not self._crop_locked:
                self._drag_start = self._to_image(pos)
            return

        # 1) resize handle of the selected overlay
        if not self._ov_locked and 0 <= self._sel < len(self._ov_items):
            ov, pm = self._ov_items[self._sel]
            if pm is not None and ov.visible:
                grab = self._handle_rect(self._ov_rect(ov, pm)).adjusted(-4, -4, 4, 4)
                if grab.contains(pos):
                    self._ov_drag = ("scale", self._sel, pos, ov.cx, ov.cy)
                    return
        # 2) resize handle of the selected photo
        if not self._photos_locked and self._photo_handle_hit(pos):
            ph = self._photos[self._psel]
            self._photo_drag = ("scale", self._psel, pos, ph.cx, ph.cy)
            return
        # 3) the top-most overlay under the cursor
        if not self._ov_locked:
            for i in reversed(range(len(self._ov_items))):
                ov, pm = self._ov_items[i]
                if pm is not None and ov.visible and self._ov_rect(ov, pm).contains(pos):
                    self._sel, self._psel = i, -1
                    self._ov_drag = ("move", i, pos, ov.cx, ov.cy)
                    self.overlaySelected.emit(i)
                    self.photoSelected.emit(-1)
                    self.update()
                    return
        # 4) the top-most photo under the cursor
        if not self._photos_locked:
            i = self._hit_photo(pos)
            if i >= 0:
                ph = self._photos[i]
                self._psel, self._sel = i, -1
                self._photo_drag = None if ph.fill else ("move", i, pos, ph.cx, ph.cy)
                self.overlaySelected.emit(-1)
                self.photoSelected.emit(i)
                self.update()
                return
        # 5) empty space: deselect
        self._sel = self._psel = -1
        self.overlaySelected.emit(-1)
        self.photoSelected.emit(-1)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._pan_drag is not None:
            start, pan0 = self._pan_drag
            self._pan = QPointF(pan0.x() + pos.x() - start.x(), pan0.y() + pos.y() - start.y())
            self._clamp_pan()
            self.viewChanged.emit()
            self.update()
            return
        if self._drag_start is not None:  # crop dragging
            a, b = self._drag_start, self._to_image(pos)
            l, r = sorted((a.x(), b.x()))
            t, bt = sorted((a.y(), b.y()))
            if r - l >= 1 and bt - t >= 1:
                self.cropDragged.emit(round(l), round(t), round(r), round(bt))
            return
        d = self._display_rect()
        if self._photo_drag is not None and d.width() > 0:
            mode, i, start, cx0, cy0 = self._photo_drag
            ph = self._photos[i]
            if mode == "move":
                ph.cx = cx0 + (pos.x() - start.x()) / d.width()
                ph.cy = cy0 + (pos.y() - start.y()) / d.height()
            else:  # the corner handle sits at distance |m| from the centre; width follows from the shape
                geom = self._photo_geom(ph)
                if geom is not None:
                    centre = geom[0]
                    dist = math.hypot(pos.x() - centre.x(), pos.y() - centre.y())
                    width = 2 * dist / math.sqrt(1 + ph.aspect ** 2)
                    ph.scale = min(max(width / d.width(), MIN_PHOTO_SCALE), MAX_PHOTO_SCALE)
            self.photoEdited.emit(i)
            self.update()
            return
        if self._ov_drag is None:
            return
        mode, i, start, cx0, cy0 = self._ov_drag
        ov, pm = self._ov_items[i]
        if mode == "move":
            ov.cx = cx0 + (pos.x() - start.x()) / d.width()
            ov.cy = cy0 + (pos.y() - start.y()) / d.height()
        else:  # scale about the overlay centre
            centre_x = d.left() + ov.cx * d.width()
            half = abs(pos.x() - centre_x)
            ov.scale = min(max(2 * half / d.width(), MIN_SCALE), MAX_SCALE)
        self.overlayEdited.emit(i)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pan_drag is not None:
            self._pan_drag = None
            self.setCursor(Qt.CrossCursor if self._crop_mode else Qt.ArrowCursor)
            self.viewChanged.emit()
        if self._photo_drag is not None:
            self.photoDragFinished.emit()
        self._drag_start = None
        self._ov_drag = None
        self._photo_drag = None

    def wheelEvent(self, e):
        if not self._pixmap:
            return
        delta = e.angleDelta().y() or e.angleDelta().x()  # Shift+wheel can arrive as horizontal
        if delta == 0:
            return
        steps = delta / 120
        if (e.modifiers() & Qt.ShiftModifier) and not self._crop_mode:
            if not self._ov_locked and 0 <= self._sel < len(self._ov_items):
                ov, pm = self._ov_items[self._sel]
                if pm is not None:
                    ov.scale = min(max(ov.scale * 1.05 ** steps, MIN_SCALE), MAX_SCALE)
                    self.overlayEdited.emit(self._sel)
                    self.update()
                return
            if not self._photos_locked and 0 <= self._psel < len(self._photos):
                ph = self._photos[self._psel]
                if not ph.fill:
                    ph.scale = min(max(ph.scale * 1.05 ** steps, MIN_PHOTO_SCALE), MAX_PHOTO_SCALE)
                    self.photoEdited.emit(self._psel)
                    self.photoDragFinished.emit()
                    self.update()
                return
        self._set_zoom(self._zoom * 1.2 ** steps, e.position())
