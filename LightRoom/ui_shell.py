"""
PyLight shell - the new layout from the design mockup.

Everything here is drawing / layout / animation only. Editing logic stays in pylight.py + engine.py.
Palette was sampled from the mockup:  panel #292733 | bar #18141e | accent #746be0 | scroll thumb #a3a2a7
"""
import math
import os
import time

import cv2
import numpy as np
from PySide6.QtCore import (Qt, Signal, QPointF, QRectF, QSize, QTimer, QVariantAnimation, QEasingCurve, QRect)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QBrush, QPixmap, QLinearGradient, QRadialGradient,
                           QFont, QFontMetrics, QImage, QConicalGradient)
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QAbstractButton, QPushButton,
                               QScrollArea, QButtonGroup, QStackedWidget, QSizePolicy, QFrame, QSizeGrip,
                               QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QListWidget, QListWidgetItem, QMenu)

import engine as E
from ui_kit import (BigSlider, ChipStrip, NodeButton, paint_icon, pill, LIGHT, COLOR, GRADING, EFFECTS, DETAIL,
                    MASK_ITEMS, spec)

# ----------------------------------------------------------------------------- palette (from the mockup)
BG = '#1d1927'
PANEL = '#292733'
BAR = '#18141e'
BAR2 = '#191620'
TOPRIGHT = '#262330'
PURPLE = '#746be0'
PURPLE_HI = '#8b83f0'
TXT = '#d9d7e0'
TXT_DIM = '#8d8a99'
TRACK = '#33313d'
THUMB = '#a3a2a7'
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

BLUR = [spec('Blur', 'blur', 0, 100), spec('Glow', 'glow', 0, 100), spec('Edge blur', 'edge_blur', 0, 100)]

SCROLL_QSS = f"""
QScrollBar:vertical {{ background:{TRACK}; width:8px; margin:2px; border-radius:4px; }}
QScrollBar::handle:vertical {{ background:{THUMB}; border-radius:4px; min-height:48px; }}
QScrollBar::handle:vertical:hover {{ background:#c4c2c9; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
"""


def C(hexs, a=255):
    c = QColor(hexs)
    c.setAlpha(a)
    return c


def corner_path(r, tl=0, tr=0, br=0, bl=0):
    p = QPainterPath()
    p.moveTo(r.left() + tl, r.top())
    p.lineTo(r.right() - tr, r.top())
    if tr:
        p.arcTo(r.right() - 2 * tr, r.top(), 2 * tr, 2 * tr, 90, -90)
    p.lineTo(r.right(), r.bottom() - br)
    if br:
        p.arcTo(r.right() - 2 * br, r.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
    p.lineTo(r.left() + bl, r.bottom())
    if bl:
        p.arcTo(r.left(), r.bottom() - 2 * bl, 2 * bl, 2 * bl, -90, -90)
    p.lineTo(r.left(), r.top() + tl)
    if tl:
        p.arcTo(r.left(), r.top(), 2 * tl, 2 * tl, 180, -90)
    p.closeSubpath()
    return p


def anim(parent, ms, fn, curve=QEasingCurve.OutCubic):
    a = QVariantAnimation(parent)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.valueChanged.connect(lambda v: fn(float(v)))
    return a


def go(a, start, end):
    a.stop()
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.start()


def draw_icon(p, key, cx, cy, size, color, width=1.9, rot=0.0, sx=1.0, sy=1.0, dy=0.0):
    """Paint one of ui_kit's line icons centred on (cx, cy) with optional animation transforms."""
    p.save()
    p.translate(cx, cy + dy)
    p.rotate(rot)
    k = size / 28.0
    p.scale(k * sx, k * sy)
    p.translate(-14, -14)
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    paint_icon(p, key)
    p.restore()


# ============================================================================ background + canvas
class Canvas(QWidget):
    """Root widget: paints the supplied background (aspect-fill) and positions every floating surface."""
    LEFT_W, TAB_H, EXPORT_H, TOP_PILL_H = 336, 72, 46, 50
    DRAWER_W, DRAWER_H, TB_W, TB_H = 262, 200, 330, 84

    def __init__(self, rounded=True):
        super().__init__()
        self.bg = QPixmap(os.path.join(ASSETS, 'background.png'))
        self.rounded = rounded
        self.visL = self.visB = self.visR = self.visP = self.visH = 1.0
        self.items = {}
        self._bgcache = None
        self.grip = QSizeGrip(self)
        self.grip.setStyleSheet('background:transparent;')
        self.a_left = anim(self, 420, self._set_l)
        self.a_bot = anim(self, 420, self._set_b)
        self.a_right = anim(self, 420, self._set_r)
        self.a_pre = anim(self, 420, self._set_p)
        self.a_his = anim(self, 420, self._set_h)
        # slow background drift: two sine waves with different periods (a gentle wander, never a loop you can spot)
        self.drift_on, self._t0 = True, time.monotonic()
        self.drift_timer = QTimer(self)
        self.drift_timer.setInterval(40)  # ~25 fps is plenty for something this slow
        self.drift_timer.timeout.connect(self._drift_tick)
        self.drift_timer.start()

    DRIFT_OVERSCAN, DRIFT_PERIOD_X, DRIFT_PERIOD_Y = 1.10, 80.0, 110.0  # 10% bigger than the window, seconds per cycle

    def _drift_tick(self):
        w = self.window()
        if not self.drift_on or self.bg.isNull() or not w.isVisible() or w.isMinimized() or not w.isActiveWindow():
            return  # no repaints while hidden / in the background
        self.update()

    def set_drift(self, on):
        self.drift_on = bool(on)
        self.update()

    def _set_l(self, v):
        self.visL = v
        self.relayout()

    def _set_b(self, v):
        self.visB = v
        self.relayout()

    def _set_r(self, v):
        self.visR = v
        self.relayout()

    def _set_p(self, v):
        self.visP = v
        self.relayout()

    def _set_h(self, v):
        self.visH = v
        self.relayout()

    def toggle_right(self, on=None):
        on = (self.visR < 0.5) if on is None else on
        go(self.a_right, self.visR, 1.0 if on else 0.0)
        return on

    def toggle_presets(self, on=None):
        on = (self.visP < 0.5) if on is None else on
        go(self.a_pre, self.visP, 1.0 if on else 0.0)
        return on

    def toggle_history(self, on=None):
        on = (self.visH < 0.5) if on is None else on
        go(self.a_his, self.visH, 1.0 if on else 0.0)
        return on

    def toggle_left(self, on=None):
        on = (self.visL < 0.5) if on is None else on
        go(self.a_left, self.visL, 1.0 if on else 0.0)
        return on

    def toggle_bottom(self, on=None):
        on = (self.visB < 0.5) if on is None else on
        go(self.a_bot, self.visB, 1.0 if on else 0.0)
        return on

    def add(self, name, w):
        w.setParent(self)
        w.show()
        self.items[name] = w
        return w

    def window_radius(self):
        w = self.window()
        return 14 if self.rounded and not (w.isMaximized() or w.isFullScreen()) else 0

    # -- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = self.window_radius()
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(BG))
        if not self.bg.isNull():
            if self._bgcache is None or self._bgcache[0] != self.size():
                big = QSize(int(self.width() * self.DRIFT_OVERSCAN) + 2, int(self.height() * self.DRIFT_OVERSCAN) + 2)
                s = self.bg.scaled(big, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self._bgcache = (self.size(), s)
            s = self._bgcache[1]
            ox, oy = (self.width() - s.width()) / 2, (self.height() - s.height()) / 2  # centred position
            if self.drift_on:
                t = time.monotonic() - self._t0
                spare_x, spare_y = (s.width() - self.width()) / 2, (s.height() - self.height()) / 2
                ox += 0.9 * spare_x * math.sin(t * 2 * math.pi / self.DRIFT_PERIOD_X)
                oy += 0.9 * spare_y * math.sin(t * 2 * math.pi / self.DRIFT_PERIOD_Y + 1.3)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(QPointF(ox, oy), s)
        else:
            g = QRadialGradient(self.width() * .9, self.height() * .65, self.width() * .6)
            g.setColorAt(0, QColor('#2a2536'))
            g.setColorAt(1, QColor(BG))
            p.fillRect(self.rect(), g)
        p.setClipping(False)
        p.setPen(QPen(C('#ffffff', 16), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), rad, rad)

    # -- window drag
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < 60:
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()

    # -- layout
    def place_hist(self):
        """Histogram slot in the top row; while held it grows 40% about its centre, hanging from the top edge."""
        h = self.items.get('hist')
        if h is None or not hasattr(self, '_hist_base'):
            return
        bx, by, bw, bh = self._hist_base
        k = 1 + h.POP * max(0.0, h.pop)
        w, hh = bw * k, bh * k
        h.setGeometry(int(round(bx + bw / 2 - w / 2)), by, int(round(w)), int(round(hh)))
        if h.pop > 0.01:
            h.raise_()

    def relayout(self):
        W, H = self.width(), self.height()
        it, L, B = self.items, self.visL, self.visB
        R, VP, VH = self.visR, self.visP, self.visH
        offx = -(1 - L) * (self.LEFT_W + 80)
        offy = (1 - B) * 320
        ea_w = self.LEFT_W
        it['tabbar'].setGeometry(int(offx), 52, 392, self.TAB_H)
        it['exportbar'].setGeometry(int(offx), 52 + self.TAB_H + 10, 268, self.EXPORT_H)
        it['editarea'].setGeometry(int(offx), 196, ea_w, max(0, H - 196))
        it['collapse'].setGeometry(16, 34, 34, 20)
        it['lights'].setGeometry(14, 10, 76, 22)
        view_l = 14 + L * (ea_w + 4 - 14)
        cx = (view_l + W - 14) / 2
        # top-centre pills (hang from the top edge)
        pw, hw = 216, 196
        gx = cx - (pw * 2 + hw + 24) / 2
        it['namepill'].setGeometry(int(gx), 0, pw, self.TOP_PILL_H)
        self._hist_base = (gx + pw + 12, 8, hw, 68)
        self.place_hist()
        it['sizepill'].setGeometry(int(gx + pw + hw + 24), 0, pw, self.TOP_PILL_H)
        trx = int(W - 232 + (1 - R) * 232)  # slides off the right edge when hidden
        it['topright'].setGeometry(trx, 50, 232, 72)
        if 'rcollapse' in it:
            it['rcollapse'].setGeometry(trx - 26, 50 + 19, 24, 34)
        # bottom group
        tbx = int(cx - self.TB_W / 2)
        tby = int(H - 124 + offy)
        it['toolbar'].setGeometry(tbx, tby, self.TB_W, self.TB_H)
        it['plus'].setGeometry(int(cx - 38), tby - 24, 76, 76)
        if 'png' in it:
            it['png'].setGeometry(int(cx - 34), tby - 24 - 82, 68, 82)  # sits right on top of the +
        hy = (H - 24) * (1 - B) + (tby + self.TB_H - 6) * B
        it['hide'].setGeometry(int(cx - 22), int(min(hy, H - 24)), 44, 22)
        dh = self.DRAWER_H
        offp, offh = (1 - min(B, VP)) * 320, (1 - min(B, VH)) * 320  # each drawer hides on its own
        px = int(tbx - 28 - self.DRAWER_W)
        hx = int(min(tbx + self.TB_W + 60, W - 12 - self.DRAWER_W))
        it['preset'].setGeometry(px, int(H - dh + offp), self.DRAWER_W, dh + 40)
        it['history'].setGeometry(hx, int(H - dh + offh), self.DRAWER_W, dh + 40)
        for key, x0, off in (('pcollapse', px, offp), ('hcollapse', hx, offh)):
            if key in it:
                it[key].setGeometry(int(x0 + self.DRAWER_W / 2 - 17), int(min(H - dh + off - 22, H - 24)), 34, 20)
                it[key].setVisible(B > 0.5)
        vb = H - (self.DRAWER_H + 14) * B - 18 * (1 - B)
        it['view'].setGeometry(int(view_l), 66, int(W - 14 - view_l), int(max(80, vb - 66)))
        it['toast'].move(int(cx - it['toast'].width() / 2), int(H - 170 * B - 56))
        self.grip.move(W - 18, H - 18)
        for n in ('toolbar', 'plus', 'png', 'hide', 'rcollapse', 'pcollapse', 'hcollapse', 'topright', 'namepill', 'hist', 'sizepill', 'tabbar', 'exportbar',
                  'editarea', 'collapse', 'lights', 'preset', 'history', 'toast'):
            if n in it:
                it[n].raise_()
        if 'hist' in it and it['hist'].pop > 0.01:
            it['hist'].raise_()
        self.grip.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if len(self.items) >= 16:
            self.relayout()


# ============================================================================ generic surface
class Surface(QWidget):
    def __init__(self, color=PANEL, radii=(0, 0, 0, 0), border=False):
        super().__init__()
        self.color, self.radii, self.border = QColor(color), radii, border

    def mousePressEvent(self, e):
        e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        path = corner_path(r, *self.radii)
        p.fillPath(path, self.color)
        g = QLinearGradient(0, 0, 0, min(60, r.height()))
        g.setColorAt(0, C('#ffffff', 10))
        g.setColorAt(1, C('#ffffff', 0))
        p.fillPath(path, g)
        if self.border:
            p.setPen(QPen(C('#ffffff', 14), 1))
            p.drawPath(corner_path(r.adjusted(.5, .5, -.5, -.5), *self.radii))


class FadeStack(QStackedWidget):
    """Stack that cross-fades between pages."""

    def setCurrentWidget(self, w):
        if w is self.currentWidget():
            return
        super().setCurrentWidget(w)
        if not self.isVisible():
            return
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = anim(w, 260, eff.setOpacity)
        a.finished.connect(lambda w=w: w.setGraphicsEffect(None))
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.start(QVariantAnimation.DeleteWhenStopped)
        self._a = a
        if hasattr(w, 'stagger'):
            w.stagger()


# ============================================================================ window chrome
class TrafficLights(QWidget):
    closeReq, minReq, zoomReq = Signal(), Signal(), Signal()

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.hov = False
        self.cols = ('#ff5f57', '#febc2e', '#28c840')

    def enterEvent(self, e):
        self.hov = True
        self.update()

    def leaveEvent(self, e):
        self.hov = False
        self.update()

    def _idx(self, x):
        i = int(x // 24)
        return i if 0 <= i < 3 else -1

    def mousePressEvent(self, e):
        i = self._idx(e.position().x())
        (self.closeReq, self.minReq, self.zoomReq)[i].emit() if i >= 0 else None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, c in enumerate(self.cols):
            cx, cy = 11 + i * 24, 11
            p.setPen(QPen(C('#000000', 60), 1))
            p.setBrush(QColor(c))
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            if self.hov:
                p.setPen(QPen(C('#000000', 150), 1.3, Qt.SolidLine, Qt.RoundCap))
                if i == 0:
                    p.drawLine(QPointF(cx - 2.4, cy - 2.4), QPointF(cx + 2.4, cy + 2.4))
                    p.drawLine(QPointF(cx - 2.4, cy + 2.4), QPointF(cx + 2.4, cy - 2.4))
                elif i == 1:
                    p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
                else:
                    p.drawPolyline([QPointF(cx - 2.5, cy + 2.5), QPointF(cx - 2.5, cy - 2.5), QPointF(cx + 2.5, cy - 2.5)])


class Collapse(QAbstractButton):
    """Small triangle toggle (top-left hides the editing side, bottom hides the toolbar)."""

    def __init__(self, up=False, rot=None):
        super().__init__()
        self.flip = 0.0
        self.h = 0.0
        self.up = up
        self.rot = rot  # e.g. -90 = arrow points right
        self.setCursor(Qt.PointingHandCursor)
        self.a_f = anim(self, 300, self._f, QEasingCurve.OutBack)
        self.a_h = anim(self, 160, self._h)

    def _f(self, v):
        self.flip = v
        self.update()

    def _h(self, v):
        self.h = v
        self.update()

    def set_open(self, on):
        go(self.a_f, self.flip, 0.0 if on else 1.0)

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        if self.rot is not None:
            p.translate(cx, cy)
            p.rotate(self.rot + 180 * self.flip)
            p.translate(0, 1.2 * self.h)  # nudges toward the pointing direction on hover
        else:
            p.translate(cx, cy + 1.2 * self.h * (1 if not self.up else -1))
            p.rotate(180 * self.flip + (180 if self.up else 0))
        col = QColor('#8c8a91')
        col = QColor(int(140 + 70 * self.h), int(138 + 68 * self.h), int(145 + 75 * self.h))
        path = QPainterPath()
        path.moveTo(-15, -6)
        path.lineTo(15, -6)
        path.lineTo(2.5, 6)
        path.quadTo(0, 8, -2.5, 6)
        path.closeSubpath()
        p.fillPath(path, col)


# ============================================================================ editing tabs
class TabButton(QAbstractButton):
    """Icon + label tab. The icon animates on hover / when selected (sun spins, drop bobs, thermometer pulses...)."""

    def __init__(self, name, key):
        super().__init__()
        self.name, self.key = name, key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(62, 60)
        self.h = self.s = self.ph = 0.0
        self.ang = 0.0
        self.a_h = anim(self, 180, self._h)
        self.a_s = anim(self, 320, self._s, QEasingCurve.OutBack)
        self.a_ang = anim(self, 450, self._ang, QEasingCurve.OutCubic)
        self.tick = QTimer(self, interval=33)
        self.tick.timeout.connect(self._tick)
        self.toggled.connect(lambda on: (go(self.a_s, self.s, 1.0 if on else 0.0), self._wake()))

    def _h(self, v):
        self.h = v
        self.update()

    def _s(self, v):
        self.s = v
        self.update()

    def _ang(self, v):
        self.ang = v
        self.update()

    def _wake(self):
        if (self.underMouse() or self.isChecked()) and not self.tick.isActive():
            self.a_ang.stop()
            self.tick.start()

    def _tick(self):
        if not (self.underMouse() or self.isChecked()):
            self.tick.stop()
            go(self.a_ang, self.ang, math.ceil(self.ang / 45.0) * 45.0)  # settle on a ray-symmetric angle
            return
        self.ph += 0.2
        self.ang += 1.1
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)
        self._wake()

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        a = max(self.h * 0.7, self.s)
        col = QColor(int(170 + 85 * a), int(168 + 87 * a), int(178 + 77 * a))
        cx, cy = self.width() / 2, 22
        rot, sx, sy, dy = 0.0, 1.0, 1.0, -2.5 * self.s
        s = math.sin(self.ph)
        if self.key == 'sun':
            rot = self.ang
        elif self.key == 'thermo':
            sy = 1 + 0.09 * s * a
            dy += -0.6 * s * a
        elif self.key == 'blur':
            dy += 1.8 * s * a
            sx = 1 + 0.04 * math.sin(self.ph * 2) * a
        elif self.key == 'Effects':
            rot = 14 * math.sin(self.ph * 0.6) * a
            sx = sy = 1 + 0.08 * s * a
        else:
            sx = sy = 1 + 0.07 * s * a
        if self.s > 0.01:
            g = QRadialGradient(cx, cy, 24)
            g.setColorAt(0, C(PURPLE, int(95 * min(1, self.s))))
            g.setColorAt(1, C(PURPLE, 0))
            p.fillRect(self.rect(), g)
        draw_icon(p, self.key, cx, cy, 26 * (1 + 0.06 * self.h), col, 2.0, rot, sx, sy, dy)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.DemiBold if self.s > .5 else QFont.Medium)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(0, 40, self.width(), 18), Qt.AlignCenter, self.name)
        if self.s > 0.01:  # accent dot
            p.setPen(Qt.NoPen)
            p.setBrush(C(PURPLE_HI, int(255 * min(1, self.s))))
            p.drawRoundedRect(QRectF(cx - 8 * self.s, 59, 16 * self.s, 2), 1, 1)


class Pager(QAbstractButton):
    """The slim pill at the end of a bar (exactly as in the mockup); click = next tab / menu."""

    def __init__(self, w=28, h=76, color=PANEL):
        super().__init__()
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.col, self.h, self.press = QColor(color), 0.0, 0.0
        self.a = anim(self, 160, self._h)

    def _h(self, v):
        self.h = v
        self.update()

    def enterEvent(self, e):
        go(self.a, self.h, 1)

    def leaveEvent(self, e):
        go(self.a, self.h, 0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 2, -4, -2)
        c = QColor(self.col)
        c = QColor(min(255, c.red() + int(14 * self.h)), min(255, c.green() + int(14 * self.h)), min(255, c.blue() + int(18 * self.h)))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, r.width() / 2, r.width() / 2)
        if self.h > 0.02:
            p.setPen(QPen(C('#ffffff', int(150 * self.h)), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cx, cy = r.center().x(), r.center().y()
            p.drawPolyline([QPointF(cx - 2.5, cy - 4), QPointF(cx + 2.5, cy), QPointF(cx - 2.5, cy + 4)])


class TabBar(Surface):
    changed = Signal(str)
    TABS = (('Light', 'sun'), ('Color', 'thermo'), ('Blur', 'blur'), ('Effects', 'Effects'), ('Detail', 'Detail'))

    def __init__(self):
        super().__init__(BAR, (0, 36, 36, 0))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 8, 6)
        lay.setSpacing(2)
        self.grp, self.btns = QButtonGroup(self), {}
        for n, k in self.TABS:
            b = TabButton(n, k)
            b.clicked.connect(lambda _=False, n=n: self.changed.emit(n))
            self.grp.addButton(b)
            self.btns[n] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.pager = Pager(28, 46, PANEL)
        self.pager.setToolTip('Next tab')
        self.pager.clicked.connect(self.next_tab)
        lay.addWidget(self.pager)
        self.hl, self.cur = QRectF(), None
        self.a_hl = QVariantAnimation(self)
        self.a_hl.setDuration(340)
        self.a_hl.setEasingCurve(QEasingCurve.OutBack)
        self.a_hl.valueChanged.connect(lambda r: (setattr(self, 'hl', r), self.update()))

    def next_tab(self):
        names = [t[0] for t in self.TABS]
        cur = names.index(self.cur) if self.cur in names else -1
        self.changed.emit(names[(cur + 1) % len(names)])

    def select(self, name):
        for n, b in self.btns.items():
            b.setChecked(n == name)
        if name not in self.btns:
            self.cur = None
            self.hl = QRectF()
            self.update()
            return
        self.cur = name
        t = QRectF(self.btns[name].geometry()).adjusted(2, 0, -2, 0)
        if self.hl.isNull() or not self.isVisible():
            self.hl = t
            self.update()
        else:
            self.a_hl.stop()
            self.a_hl.setStartValue(self.hl)
            self.a_hl.setEndValue(t)
            self.a_hl.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.cur:
            QTimer.singleShot(0, lambda: self.select(self.cur))

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.hl.isNull():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(C(PURPLE_HI, 70), 1))
            p.setBrush(C(PURPLE, 38))
            p.drawRoundedRect(self.hl.adjusted(.5, 2.5, -.5, -2.5), 18, 18)


# ============================================================================ export bar / top bars
class ExportBar(Surface):
    def __init__(self, win):
        super().__init__(BAR2, (0, 23, 23, 0))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 5, 8, 5)
        lay.setSpacing(8)
        self.btn = ExportButton()
        self.btn.clicked.connect(win.export)
        lay.addWidget(self.btn)
        lay.addStretch(1)
        self.more = Pager(26, 32, PANEL)
        self.more.setToolTip('Quick actions')
        lay.addWidget(self.more)


class ExportButton(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setText('Export')
        self.setFixedSize(138, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.h = self.pr = 0.0
        self.a_h, self.a_p = anim(self, 160, self._h), anim(self, 140, self._p)
        self.setToolTip('Export  (Cmd/Ctrl+E)')

    def _h(self, v):
        self.h = v
        self.update()

    def _p(self, v):
        self.pr = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)

    def mousePressEvent(self, e):
        go(self.a_p, self.pr, 1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        go(self.a_p, self.pr, 0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1 + self.pr, -1, -1)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(PURPLE_HI).lighter(100 + int(10 * self.h)))
        g.setColorAt(1, QColor(PURPLE))
        p.setPen(QPen(C('#ffffff', 40), 1))
        p.setBrush(g)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        draw_icon(p, 'export', 33, 17 + self.pr - 1.5 * self.h, 20, '#ffffff', 2.0)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor('#ffffff'))
        p.drawText(QRectF(50, 0, 80, self.height()), Qt.AlignVCenter | Qt.AlignLeft, 'Export')


class TopPill(Surface):
    """Pill hanging from the top edge (file name / size)."""
    clicked = Signal()

    def __init__(self, text=''):
        super().__init__(PANEL, (0, 0, 24, 24))
        self.text, self.h = text, 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.a = anim(self, 160, self._h)

    def _h(self, v):
        self.h = v
        self.update()

    def set_text(self, t):
        self.text = t
        self.update()

    def enterEvent(self, e):
        go(self.a, self.h, 1)

    def leaveEvent(self, e):
        go(self.a, self.h, 0)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont(self.font())
        f.setPixelSize(15)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        col = QColor(int(206 + 40 * self.h), int(204 + 40 * self.h), int(214 + 36 * self.h))
        p.setPen(col)
        t = QFontMetrics(f).elidedText(self.text, Qt.ElideMiddle, self.width() - 28)
        p.drawText(QRectF(0, 0, self.width(), self.height() - 4), Qt.AlignCenter, t)


class Histogram2(QWidget):
    """Glass histogram. Hover = pops big, tap = next view, right-click = pick one.
    Views: RGB (additive colour), Luminance, Red, Green, Blue, Waveform."""
    MODES = ['RGB', 'Luminance', 'Red', 'Green', 'Blue', 'Waveform']
    COLS = {'r': (255, 78, 92), 'g': (74, 226, 104), 'b': (86, 128, 255), 'l': (236, 236, 248)}
    BASE_W, BASE_H, POP, HOLD_MS = 196, 68, 1.80, 220  # POP 1.8 = held size is 2.8x (twice the old 1.4x)

    def __init__(self):
        super().__init__()
        self.small = None
        self.h = self.luma = self.wave = None
        self.mode, self.hov = 0, 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Hover to enlarge  |  tap to switch view  |  right-click for the list')
        self.a_h = anim(self, 160, self._hv)
        self.pop, self._down, self._held, self._sh = 0.0, False, False, None
        self.a_pop = anim(self, 300, self._pv)
        self.t_hold = QTimer(self)
        self.t_hold.setSingleShot(True)
        self.t_hold.setInterval(self.HOLD_MS)
        self.t_hold.timeout.connect(self._hold)

    def _pv(self, v):
        self.pop = v
        pr = self.parentWidget()
        if hasattr(pr, 'place_hist'):
            pr.place_hist()
        if v > 0.01 and self._sh is None:  # soft shadow only while it is lifted
            self._sh = QGraphicsDropShadowEffect(self)
            self._sh.setColor(QColor(0, 0, 0, 170))
            self.setGraphicsEffect(self._sh)
        if self._sh is not None:
            t = min(1.0, max(0.0, v))
            self._sh.setBlurRadius(10 + 34 * t)
            self._sh.setOffset(0, 3 + 9 * t)
        if v <= 0.001 and self._sh is not None:
            self.setGraphicsEffect(None)
            self._sh = None
        self.update()

    def _to(self, v):
        self.a_pop.setEasingCurve(QEasingCurve.OutBack if v > self.pop else QEasingCurve.OutCubic)
        self.a_pop.setDuration(320 if v > self.pop else 220)
        go(self.a_pop, self.pop, v)

    def _hold(self):
        if self._down:
            self._held = True
            self._to(1.0)

    def _hv(self, v):
        self.hov = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.hov, 1)
        self._to(1.0)  # hover -> pops big

    def leaveEvent(self, e):
        go(self.a_h, self.hov, 0)
        self._down = False
        self._to(0.0)  # move away -> settles back

    # -- data
    @staticmethod
    def _smooth(h):
        return cv2.GaussianBlur(h.astype(np.float32)[None, :], (0, 0), 1.1)[0]

    def set_image(self, u8):
        self.small = cv2.resize(u8, (min(u8.shape[1], 600), min(u8.shape[0], 400)), interpolation=cv2.INTER_AREA)
        self.h = [self._smooth(cv2.calcHist([self.small], [c], None, [256], [0, 256]).ravel()) for c in range(3)]
        g = cv2.cvtColor(self.small, cv2.COLOR_RGB2GRAY)
        self.luma = self._smooth(cv2.calcHist([g], [0], None, [256], [0, 256]).ravel())
        self.wave = self._make_wave() if self.mode == 5 else None
        self.update()

    def _make_wave(self):
        """Colour waveform: x = position in the photo, y = brightness, glow = how many pixels sit there."""
        if self.small is None:
            return None
        arr = cv2.resize(self.small, (256, 160), interpolation=cv2.INTER_AREA).astype(np.int32)
        bins = 64
        cols = np.arange(256, dtype=np.int32)[None, :]
        out = np.zeros((bins, 256, 3), np.float32)
        for c in range(3):
            flat = (arr[:, :, c] * (bins - 1) // 255) * 256 + cols
            out[:, :, c] = np.bincount(flat.ravel(), minlength=bins * 256).reshape(bins, 256)
        nz = out[out > 0]
        v = np.clip(out / max(float(np.percentile(nz, 99)) if nz.size else 1.0, 1.0), 0, 1) ** 0.55
        v = v[::-1]  # bright at the top
        rgba = np.zeros((bins, 256, 4), np.uint8)
        rgba[:, :, :3] = np.clip(v * 255 * 1.15, 0, 255).astype(np.uint8)
        rgba[:, :, 3] = np.clip(v.max(2) * 255 * 1.1, 0, 255).astype(np.uint8)
        qi = QImage(rgba.data, 256, bins, 256 * 4, QImage.Format_RGBA8888).copy()
        return qi

    # -- interaction
    def set_mode(self, i):
        self.mode = i % len(self.MODES)
        if self.mode == 5 and self.wave is None:
            self.wave = self._make_wave()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._down = True
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            self.set_mode(self.mode + 1)  # tap -> next view
        e.accept()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        for i, n in enumerate(self.MODES):
            a = m.addAction(n)
            a.setCheckable(True)
            a.setChecked(i == self.mode)
            a.triggered.connect(lambda _=False, i=i: self.set_mode(i))
        m.exec(e.globalPos())

    # -- painting
    def _series(self):
        if self.h is None:
            return []
        m = self.MODES[self.mode]
        if m == 'RGB':
            return [(self.h[0], self.COLS['r']), (self.h[1], self.COLS['g']), (self.h[2], self.COLS['b'])]
        if m == 'Luminance':
            return [(self.luma, self.COLS['l'])]
        i = {'Red': 0, 'Green': 1, 'Blue': 2}[m]
        return [(self.h[i], self.COLS['rgb'[i]])]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        sc = self.width() / self.BASE_W  # everything (graph, text, dots) scales with the card
        p.scale(sc, sc)
        W, H = self.BASE_W, self.height() / sc
        rad = 16
        path = QPainterPath()
        path.addRoundedRect(QRectF(.5, .5, W - 1, H - 1), rad, rad)
        # glass: dark tint + light top-to-bottom gradient + diagonal sheen
        p.fillPath(path, QColor(18, 16, 30, 105))
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, C('#ffffff', 58))
        g.setColorAt(.55, C('#ffffff', 20))
        g.setColorAt(1, C('#ffffff', 9))
        p.fillPath(path, g)
        sh = QLinearGradient(0, 0, W * .8, H * 1.3)
        sh.setColorAt(0, C('#ffffff', 46))
        sh.setColorAt(.38, C('#ffffff', 0))
        p.fillPath(path, sh)
        p.setClipPath(path)
        # faint graticule
        p.setPen(QPen(C('#ffffff', 16), 1))
        for i in (1, 2, 3):
            x = W * i / 4
            p.drawLine(QPointF(x, 6), QPointF(x, H - 6))
        if self.MODES[self.mode] == 'Waveform':
            for i in (1, 2, 3):
                y = H * i / 4
                p.drawLine(QPointF(6, y), QPointF(W - 6, y))
            if self.wave is not None:
                p.drawImage(QRectF(6, 6, W - 12, H - 12), self.wave)
        else:
            ser = self._series()
            if ser:
                mx = max((np.percentile(h[2:254], 99.5) if h[2:254].size else 1) for h, _ in ser) or 1
                dpr = self.devicePixelRatioF() * sc
                img = QImage(int(W * dpr), int(H * dpr), QImage.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
                img.fill(0)
                q = QPainter(img)
                q.setRenderHint(QPainter.Antialiasing)
                q.setCompositionMode(QPainter.CompositionMode_Plus)
                for h, col in ser:
                    area = QPainterPath(QPointF(0, H))
                    line = QPainterPath()
                    for i in range(256):
                        x, y = i / 255 * W, H - 3 - min(1.0, h[i] / mx) * (H - 12)
                        area.lineTo(x, y)
                        line.moveTo(x, y) if i == 0 else line.lineTo(x, y)
                    area.lineTo(W, H)
                    fg = QLinearGradient(0, 0, 0, H)
                    fg.setColorAt(0, QColor(*col, 215))
                    fg.setColorAt(1, QColor(*col, 95))
                    q.fillPath(area, fg)
                    q.setPen(QPen(QColor(*col, 255), 1.2))
                    q.drawPath(line)
                q.end()
                p.drawImage(0, 0, img)
        p.setClipping(False)
        # glass edge: bright top, soft bottom
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0, C('#ffffff', 120))
        bg.setColorAt(1, C('#ffffff', 34))
        p.setPen(QPen(QBrush(bg), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(QPen(C('#ffffff', 80), 1))
        p.drawLine(QPointF(rad, 1.5), QPointF(W - rad, 1.5))  # inner top highlight
        # view name + position dots
        f = QFont()
        f.setPixelSize(9)
        f.setWeight(QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.3)
        p.setFont(f)
        p.setPen(C('#ffffff', int(120 + 100 * self.hov)))
        p.drawText(QRectF(12, 6, W - 24, 14), Qt.AlignLeft | Qt.AlignVCenter, self.MODES[self.mode].upper())
        p.setPen(Qt.NoPen)
        for i in range(len(self.MODES)):
            p.setBrush(C('#ffffff', 215 if i == self.mode else 60))
            p.drawEllipse(QPointF(W - 14 - (len(self.MODES) - 1 - i) * 8, 13), 2.2, 2.2)


class IconButton(QAbstractButton):
    """Icon (+ optional label under it) with hover lift and an animated glyph: gear spins, compare slides."""

    def __init__(self, key, label='', size=26, tip=''):
        super().__init__()
        self.key, self.label, self.isz = key, label, size
        self.h = self.pr = self.spin = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFixedSize(64, 62 if label else 46)
        self.a_h, self.a_p = anim(self, 170, self._h), anim(self, 130, self._p)
        self.a_s = anim(self, 650, self._s, QEasingCurve.InOutCubic)

    def _h(self, v):
        self.h = v
        self.update()

    def _p(self, v):
        self.pr = v
        self.update()

    def _s(self, v):
        self.spin = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)
        if self.key == 'gear':
            go(self.a_s, 0, 1)

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)

    def mousePressEvent(self, e):
        go(self.a_p, self.pr, 1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        go(self.a_p, self.pr, 0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(int(196 + 59 * self.h), int(194 + 61 * self.h), int(204 + 51 * self.h))
        cy = (22 if self.label else self.height() / 2) - 1.5 * self.h + 1.2 * self.pr
        cx = self.width() / 2
        rot = 120 * self.spin if self.key == 'gear' else 0
        sc = 1 + 0.08 * self.h - 0.1 * self.pr
        draw_icon(p, self.key, cx, cy, self.isz, col, 1.9, rot, sc, sc)
        if self.key == 'compare' and self.h > 0.01:  # hover: the split line nudges
            p.setPen(QPen(C(PURPLE_HI, int(220 * self.h)), 1.6, Qt.SolidLine, Qt.RoundCap))
            x = cx + 5 * math.sin(self.h * math.pi)
            p.drawLine(QPointF(x, cy - 9), QPointF(x, cy + 9))
        if self.label:
            f = QFont(self.font())
            f.setPixelSize(11)
            f.setWeight(QFont.Medium)
            p.setFont(f)
            p.setPen(col)
            p.drawText(QRectF(0, 40, self.width(), 16), Qt.AlignCenter, self.label)


class UndoPill(QWidget):
    """The black pill from the mockup. Upper half = undo, lower half = redo (chevrons appear on hover)."""
    undo, redo = Signal(), Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(26, 64)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.h, self.zone, self.fl = 0.0, 0, [0.0, 0.0]
        self.a = anim(self, 180, self._h)
        self.setToolTip('Click top = Undo   |   bottom = Redo')

    def _h(self, v):
        self.h = v
        self.update()

    def enterEvent(self, e):
        go(self.a, self.h, 1)

    def leaveEvent(self, e):
        go(self.a, self.h, 0)
        self.zone = 0
        self.update()

    def mouseMoveEvent(self, e):
        z = 1 if e.position().y() < self.height() / 2 else 2
        if z != self.zone:
            self.zone = z
            self.update()

    def mousePressEvent(self, e):
        (self.undo if e.position().y() < self.height() / 2 else self.redo).emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 0, -4, 0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#000000'))
        p.drawRoundedRect(r, r.width() / 2, r.width() / 2)
        if self.h > 0.02:
            cx = r.center().x()
            for z, cy, d in ((1, r.height() * .27, 1), (2, r.height() * .73, -1)):
                a = int(235 * self.h) if self.zone == z else int(95 * self.h)
                p.setPen(QPen(C(PURPLE_HI if self.zone == z else '#ffffff', a), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline([QPointF(cx - 3.5, cy + 2 * d), QPointF(cx, cy - 2 * d), QPointF(cx + 3.5, cy + 2 * d)])


class TopRight(Surface):
    def __init__(self, win):
        super().__init__(TOPRIGHT, (36, 0, 0, 36))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 4, 6, 4)
        lay.setSpacing(6)
        self.undo_pill = UndoPill()
        self.undo_pill.undo.connect(win.do_undo)
        self.undo_pill.redo.connect(win.do_redo)
        self.before = IconButton('compare', 'Before', 26, 'Hold to see the original  (or press \\)')
        self.before.pressed.connect(lambda: win.set_before(True))
        self.before.released.connect(lambda: win.set_before(False))
        self.settings = IconButton('gear', 'Settings', 26, 'Settings')
        lay.addWidget(self.undo_pill)
        lay.addSpacing(6)
        lay.addWidget(self.before)
        lay.addWidget(self.settings)


# ============================================================================ bottom toolbar
class PngPopup(QAbstractButton):
    """Little purple 'PNG' folder that pops up above the + while it is hovered.
    Click = pick images to convert to PNG.  Drop files on it = convert them.  The + itself is unchanged."""
    filesDropped = Signal(list)
    SIZE, PAD = 56, 20

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setToolTip('Convert any image to PNG  (click, or drop files here)')
        self.t = self.h = self.pr = 0.0
        self.drag = False
        self.a_t = anim(self, 230, self._t, QEasingCurve.OutBack)
        self.a_h = anim(self, 150, self._h)
        self.a_p = anim(self, 110, self._p)
        self.timer = QTimer(self, singleShot=True, interval=320)  # grace period so the mouse can travel + -> PNG
        self.timer.timeout.connect(lambda: go(self.a_t, self.t, 0))
        self.hide()

    def _t(self, v):
        self.t = v
        self.setVisible(v > 0.01)
        self.update()

    def _h(self, v):
        self.h = v
        self.update()

    def _p(self, v):
        self.pr = v
        self.update()

    def pop(self, on):
        if on:
            self.timer.stop()
            if self.t < 0.999 and self.a_t.endValue() != 1.0:
                self.show()
                go(self.a_t, self.t, 1)
        else:
            self.timer.start()

    def enterEvent(self, e):
        self.timer.stop()
        go(self.a_h, self.h, 1)

    def leaveEvent(self, e):
        self.timer.start()
        go(self.a_h, self.h, 0)

    def mousePressEvent(self, e):
        go(self.a_p, self.pr, 1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        go(self.a_p, self.pr, 0)
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drag = True
            self.timer.stop()
            self.update()

    def dragLeaveEvent(self, e):
        self.drag = False
        self.timer.start()
        self.update()

    def dropEvent(self, e):
        self.drag = False
        e.acceptProposedAction()
        self.timer.start()
        self.filesDropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        self.update()

    def paintEvent(self, e):
        tt = max(0.0, min(1.0, self.t))
        if tt <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(tt)
        s = self.SIZE
        sc = 1 + 0.06 * self.h - 0.07 * self.pr + (0.08 if self.drag else 0)
        cx = self.width() / 2
        top = self.height() - s - 8 + (1 - self.t) * 22  # slides up as it appears
        r = QRectF(0, 0, s * sc, s * sc)
        r.moveCenter(QPointF(cx, top + s / 2 + 2 * self.pr))
        p.setPen(Qt.NoPen)
        p.setBrush(C('#000000', 90))
        p.drawRoundedRect(r.translated(0, 5), 16, 16)
        p.setBrush(QColor('#5d54c4'))  # darker lip along the bottom, like the mockup
        p.drawRoundedRect(r.translated(0, 3), 16, 16)
        gr = QLinearGradient(0, r.top(), 0, r.bottom())
        gr.setColorAt(0, QColor('#8079ea' if not self.drag else '#948dff'))
        gr.setColorAt(1, QColor(PURPLE))
        p.setBrush(gr)
        p.setPen(QPen(QColor('#5d54c4'), 1.5))
        p.drawRoundedRect(r, 16, 16)
        # grey folder
        c = r.center()
        fw, fh = 34 * sc, 27 * sc
        fx, fy = c.x() - fw / 2, c.y() - fh / 2 - 1
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#a9a8ae'))
        p.drawRoundedRect(QRectF(fx, fy, fw * 0.42, 8 * sc), 3, 3)
        p.drawRoundedRect(QRectF(fx, fy + 4 * sc, fw, fh - 4 * sc), 5, 5)
        f = QFont()
        f.setPixelSize(int(11 * sc))
        f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor('#6a62c9'))
        p.drawText(QRectF(fx, fy + 8 * sc, fw, fh - 8 * sc), Qt.AlignCenter, 'PNG')


class ToolButton(QAbstractButton):
    """Crop / Mask button: lifts on hover, glows when its tool is active."""

    def __init__(self, key, tip):
        super().__init__()
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFixedSize(64, 64)
        self.h = self.s = self.pr = 0.0
        self.a_h, self.a_s, self.a_p = anim(self, 170, self._h), anim(self, 320, self._s, QEasingCurve.OutBack), anim(self, 120, self._p)
        self.toggled.connect(lambda on: go(self.a_s, self.s, 1.0 if on else 0.0))

    def _h(self, v):
        self.h = v
        self.update()

    def _s(self, v):
        self.s = v
        self.update()

    def _p(self, v):
        self.pr = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)

    def mousePressEvent(self, e):
        go(self.a_p, self.pr, 1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        go(self.a_p, self.pr, 0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        a = max(self.h * .6, self.s)
        if self.s > 0.01:
            g = QRadialGradient(32, 32, 34)
            g.setColorAt(0, C(PURPLE, int(110 * min(1, self.s))))
            g.setColorAt(1, C(PURPLE, 0))
            p.fillRect(self.rect(), g)
        col = QColor(int(200 + 55 * a), int(198 + 57 * a), int(210 + 45 * a))
        sc = 1 + 0.1 * self.h + 0.08 * self.s - 0.12 * self.pr
        draw_icon(p, self.key, 32, 32 - 2 * self.h, 36, col, 1.7, 0, sc, sc)


class PlusButton(QAbstractButton):
    """The raised purple + (Add image). Squishes when pressed, '+' turns a quarter on hover."""
    hoverChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Add image  (Cmd/Ctrl+O)')
        self.h = self.pr = self.pulse = 0.0
        self.a_h, self.a_p = anim(self, 220, self._h, QEasingCurve.OutBack), anim(self, 120, self._p)
        self.a_pulse = QVariantAnimation(self)
        self.a_pulse.setDuration(2400)
        self.a_pulse.setLoopCount(-1)
        self.a_pulse.setStartValue(0.0)
        self.a_pulse.setEndValue(1.0)
        self.a_pulse.valueChanged.connect(lambda v: (setattr(self, 'pulse', float(v)), self.update()))
        self.a_pulse.start()

    def _h(self, v):
        self.h = v
        self.update()

    def _p(self, v):
        self.pr = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.h, 1)
        self.hoverChanged.emit(True)

    def leaveEvent(self, e):
        go(self.a_h, self.h, 0)
        self.hoverChanged.emit(False)

    def mousePressEvent(self, e):
        go(self.a_p, self.pr, 1)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        go(self.a_p, self.pr, 0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        gl = 0.5 + 0.5 * math.sin(self.pulse * 2 * math.pi)
        g = QRadialGradient(w / 2, w / 2, w * 0.62)
        g.setColorAt(0.55, C(PURPLE, int(35 + 40 * gl + 50 * self.h)))
        g.setColorAt(1, C(PURPLE, 0))
        p.fillRect(self.rect(), g)
        sc = 1 + 0.05 * self.h - 0.06 * self.pr
        r = QRectF(0, 0, 60 * sc, 60 * sc)
        r.moveCenter(QPointF(w / 2, w / 2 + 2 * self.pr))
        p.setPen(Qt.NoPen)
        p.setBrush(C('#000000', 90))
        p.drawRoundedRect(r.translated(0, 4), 18, 18)
        gr = QLinearGradient(0, r.top(), 0, r.bottom())
        gr.setColorAt(0, QColor('#8079ea'))
        gr.setColorAt(1, QColor(PURPLE))
        p.setBrush(gr)
        p.setPen(QPen(QColor('#5d54c4'), 1.5))
        p.drawRoundedRect(r, 18, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(C('#ffffff', 40))
        p.drawRoundedRect(QRectF(r.left() + 6, r.top() + 3, r.width() - 12, 4), 2, 2)
        p.save()
        p.translate(r.center())
        p.rotate(90 * self.h)
        p.setPen(QPen(QColor('#ffffff'), 3.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(-9, 0), QPointF(9, 0))
        p.drawLine(QPointF(0, -9), QPointF(0, 9))
        p.restore()


# ============================================================================ drawers (preset area / history)
class Drawer(Surface):
    def __init__(self):
        super().__init__(PANEL, (30, 30, 0, 0))
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 12, 12, 40)
        self.lay.setSpacing(6)
        self.menu_btn = Pager(26, 26, BAR)
        self.menu_btn.setParent(self)
        self.menu_btn.show()
        self.menu_btn.setToolTip('More')

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.menu_btn.move(self.width() - 34, 8)
        self.menu_btn.raise_()


class FolderHeader(QPushButton):
    def __init__(self, name, count, is_open):
        super().__init__(f"{'\u25be' if is_open else '\u25b8'}  {name.upper()}   {count}")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setStyleSheet(f'QPushButton{{text-align:left;color:{TXT_DIM};font-size:10px;font-weight:700;'
                           f'letter-spacing:1.4px;padding:12px 4px 4px 4px;border:none;background:transparent;}}'
                           f'QPushButton:hover{{color:{TXT};}}')


class PresetPanel(Drawer):
    """Preset cards (2 columns) grouped into collapsible folders.
    Folder header: click = collapse/expand, right-click = rename / delete / new folder.
    Preset card:   right-click = move to folder / export / delete.   Interface: refresh(thumbs)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.collapsed = set()
        self.sa = QScrollArea()
        self.sa.setWidgetResizable(True)
        self.sa.setFrameShape(QFrame.NoFrame)
        self.sa.setStyleSheet(SCROLL_QSS + 'QScrollArea{background:transparent;}')
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(4)
        self.grid.setAlignment(Qt.AlignTop)
        self.sa.setWidget(self.body)
        self.lay.addWidget(self.sa)
        self.group, self.btns = QButtonGroup(self), {}
        m = QMenu(self)
        for t, fn in (('Save current as preset\u2026', win.save_preset), ('Import presets\u2026', win.import_preset),
                      ('Export selected preset\u2026', win.export_preset), ('Delete selected preset', win.delete_preset)):
            m.addAction(t).triggered.connect(fn)
        m.addAction('Rename selected preset\u2026').triggered.connect(lambda: win.rename_preset())
        m.addSeparator()
        m.addAction('New folder\u2026').triggered.connect(lambda: win.new_folder())
        self._move_menu = m.addMenu('Move selected to')
        self._move_menu.aboutToShow.connect(lambda: self._fill_move_menu(self._move_menu))
        self.menu_btn.clicked.connect(lambda: m.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft())))
        self._m = m

    def _fill_move_menu(self, menu):
        w = self.win
        menu.clear()
        p = w.presets[w.cur_preset] if 0 <= w.cur_preset < len(w.presets) else None
        menu.setEnabled(bool(p and p.get('file')))
        for f in w.folders:
            if f == 'Built-in':
                continue
            a = menu.addAction(f)
            a.setEnabled(not (p and p['folder'] == f))
            a.triggered.connect(lambda _=False, f=f: w.move_preset(f))
        menu.addSeparator()
        menu.addAction('New folder\u2026').triggered.connect(lambda: w.new_folder(move_selected=True))

    def toggle(self, folder):
        self.collapsed.symmetric_difference_update({folder})
        self.refresh(True)

    def folder_menu(self, folder, pos):
        w = self.win
        m = QMenu(self)
        user = folder not in ('Built-in', 'My Presets')
        if user:
            m.addAction('Rename folder\u2026').triggered.connect(lambda: w.rename_folder(folder))
            m.addAction('Delete folder').triggered.connect(lambda: w.delete_folder(folder))
            m.addSeparator()
        m.addAction('New folder\u2026').triggered.connect(lambda: w.new_folder())
        m.exec(pos)

    def card_menu(self, i, pos):
        w = self.win
        w.cur_preset = i
        if i in self.btns:
            self.btns[i].setChecked(True)
        m = QMenu(self)
        if w.presets[i].get('file'):
            m.addAction('Rename\u2026').triggered.connect(lambda: w.rename_preset())
            mv = m.addMenu('Move to')
            self._fill_move_menu(mv)
            m.addAction('Export\u2026').triggered.connect(w.export_preset)
            m.addSeparator()
            m.addAction('Delete').triggered.connect(w.delete_preset)
        else:
            m.addAction('Export\u2026').triggered.connect(w.export_preset)
        m.exec(pos)

    def refresh(self, thumbs=False):
        w = self.win
        for b in self.btns.values():
            self.group.removeButton(b)
        while self.grid.count():
            wd = self.grid.takeAt(0).widget()
            if wd is not None:
                wd.setParent(None)
                wd.deleteLater()
        self.btns = {}
        row = 0
        for folder in w.folders:
            idxs = [i for i, p in enumerate(w.presets) if p['folder'] == folder]
            is_open = folder not in self.collapsed
            h = FolderHeader(folder, len(idxs), is_open)
            h.clicked.connect(lambda _=False, f=folder: self.toggle(f))
            h.customContextMenuRequested.connect(lambda pt, f=folder, h=h: self.folder_menu(f, h.mapToGlobal(pt)))
            self.grid.addWidget(h, row, 0, 1, 2)
            row += 1
            if not is_open:
                continue
            if not idxs:
                lbl = QLabel('No presets yet \u2013 use \u22ef \u203a Save current as preset, or import some' if folder == 'My Presets' and len(w.folders) == 1 else 'Empty \u2013 right-click a preset to move it here')
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f'color:{TXT_DIM};font-size:11px;padding:2px 6px 8px 6px;')
                self.grid.addWidget(lbl, row, 0, 1, 2)
                row += 1
                continue
            for n, i in enumerate(idxs):
                pr = w.presets[i]
                ic = w.preset_icon(pr) if (thumbs or w.photo) else None
                pm = ic.pixmap(QSize(86, 86)) if ic is not None else None
                b = NodeButton(pr['name'], 'card', pm)
                b.clicked.connect(lambda _=False, i=i: w.apply_preset(i))
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pt, i=i, b=b: self.card_menu(i, b.mapToGlobal(pt)))
                self.group.addButton(b)
                self.btns[i] = b
                self.grid.addWidget(b, row + n // 2, n % 2, Qt.AlignHCenter | Qt.AlignTop)
            row += (len(idxs) + 1) // 2
        if w.cur_preset in self.btns:
            self.btns[w.cur_preset].setChecked(True)


class HistoryPanel(Drawer):
    """Edit history. Click an entry to jump to that state (undo / redo as far as needed)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lst = QListWidget()
        self.lst.setFrameShape(QFrame.NoFrame)
        self.lst.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.lst.setStyleSheet(SCROLL_QSS + f"""
            QListWidget {{ background:transparent; outline:0; }}
            QListWidget::item {{ padding:7px 12px; margin:2px 6px 2px 0; border-radius:12px; color:{TXT}; }}
            QListWidget::item:hover {{ background:rgba(255,255,255,0.06); }}
            QListWidget::item:selected {{ background:{PURPLE}; color:white; }}""")
        self.lst.itemClicked.connect(lambda it: win.jump_history(self.lst.row(it)))
        self.lay.addWidget(self.lst)
        m = QMenu(self)
        m.addAction('Undo').triggered.connect(win.do_undo)
        m.addAction('Redo').triggered.connect(win.do_redo)
        m.addSeparator()
        m.addAction('Reset all edits').triggered.connect(win.reset_all)
        self.menu_btn.clicked.connect(lambda: m.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft())))
        self._m = m

    def refresh(self):
        w = self.win
        names = list(getattr(w, 'hist_names', []))
        cur = len(names) - 1
        names += list(reversed(getattr(w, 'redo_names', [])))
        self.lst.blockSignals(True)
        self.lst.clear()
        for i, n in enumerate(names):
            it = QListWidgetItem(n)
            if i > cur:
                it.setForeground(QBrush(QColor(TXT_DIM)))
            self.lst.addItem(it)
        if cur >= 0:
            self.lst.setCurrentRow(cur)
            self.lst.scrollToItem(self.lst.item(cur))
        self.lst.blockSignals(False)


# ============================================================================ editing area pages
class Section(QLabel):
    def __init__(self, t):
        super().__init__(t.upper())
        self.setStyleSheet(f'color:{TXT_DIM};font-size:10px;font-weight:700;letter-spacing:1.4px;padding:14px 4px 2px 4px;')


class Page(QScrollArea):
    """One scrolling page of the editing area."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(SCROLL_QSS + 'QScrollArea{background:transparent;}')
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(20, 16, 16, 28)
        self.lay.setSpacing(2)
        self.setWidget(self.body)
        self.rows, self.sliders, self.win = [], [], None

    def add_sliders(self, win, specs):
        for s in specs:
            r = BigSlider(win)
            r.changed.connect(win.route_slider)
            r.setFixedHeight(70)
            r.layout().setContentsMargins(0, 4, 0, 0)
            v = win.get_value(s[1], s[4])
            r.bind(s, s[4] if v is None else v)
            self.lay.addWidget(r)
            self.sliders.append(r)
            self.rows.append(r)

    def sync_row(self, r):
        s = r.spec
        v = self.win.get_value(s[1], s[4])
        r.setEnabled(v is not None)
        if r.sl._drag:
            return
        val = s[4] if v is None else v
        if abs(r.sl.v - val) > 1e-9 or r.val.text() != r._fmt(val):
            r.set_value(val)

    def stagger(self):
        """Rows slide/fade in one after another whenever the page opens."""
        for i, r in enumerate(self.rows):
            eff = QGraphicsOpacityEffect(r)
            eff.setOpacity(0.0)
            r.setGraphicsEffect(eff)
            a = anim(r, 320, eff.setOpacity)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.finished.connect(lambda r=r: r.setGraphicsEffect(None))
            QTimer.singleShot(30 * i, lambda a=a: a.start(QVariantAnimation.DeleteWhenStopped))
            r._a = a


class SliderList(Page):
    """Vertical list of sliders. blocks = [(title|None, [specs] | QWidget), ...]."""

    def __init__(self, win, blocks):
        super().__init__()
        self.win, self.extras = win, []
        for title, content in blocks:
            if title:
                self.lay.addWidget(Section(title))
            if isinstance(content, list):
                self.add_sliders(win, content)
            else:
                self.lay.addWidget(content)
                self.extras.append(content)
        self.lay.addStretch(1)

    def refresh_chips(self):
        for r in self.sliders:
            self.sync_row(r)
        for x in self.extras:
            if hasattr(x, 'refresh_chips'):
                x.refresh_chips()

    def refresh(self):
        self.refresh_chips()
        for x in self.extras:
            if hasattr(x, 'refresh'):
                x.refresh()


class CurveBlock(QWidget):
    def __init__(self, curve):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.addWidget(curve)
        row = QHBoxLayout()
        grp = QButtonGroup(self)
        for t, ch in (('RGB', 'rgb'), ('Red', 'r'), ('Green', 'g'), ('Blue', 'b')):
            b = pill(t, lambda _=False, ch=ch: (setattr(curve, 'ch', ch), curve.update()), True)
            b.setChecked(ch == 'rgb')
            b.setStyleSheet('padding:4px 8px;')
            grp.addButton(b)
            row.addWidget(b)
        lay.addLayout(row)


class MixPanel(QWidget):
    MODES = {'hue': 'Hue', 'sat': 'Sat', 'lum': 'Lum'}
    COLORS = ['#e04040', '#e8903a', '#e8d33a', '#46b946', '#3ac9c9', '#4a7de8', '#8a5ae0', '#d84fb4']

    def __init__(self, win):
        super().__init__()
        self.win, self.mode, self.idx = win, 'hue', 0
        self.big = BigSlider(win)
        self.big.changed.connect(win.route_slider)
        self.big.setFixedHeight(70)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        row = QHBoxLayout()
        g = QButtonGroup(self)
        for k, t in self.MODES.items():
            b = pill(t, lambda _=False, k=k: self._set('mode', k), True)
            b.setChecked(k == 'hue')
            g.addButton(b)
            row.addWidget(b)
        lay.addLayout(row)
        dots = QHBoxLayout()
        dg = QButtonGroup(self)
        for i, c in enumerate(self.COLORS):
            d = QPushButton()
            d.setCheckable(True)
            d.setFixedSize(26, 26)
            d.setCursor(Qt.PointingHandCursor)
            d.setStyleSheet(f'QPushButton{{background:{c};border-radius:13px;border:2px solid rgba(255,255,255,0.15);}}'
                            f'QPushButton:hover{{border:2px solid rgba(255,255,255,0.6);}}'
                            f'QPushButton:checked{{border:3px solid white;}}')
            d.setChecked(i == 0)
            d.clicked.connect(lambda _=False, i=i: self._set('idx', i))
            dg.addButton(d)
            dots.addWidget(d)
        lay.addLayout(dots)
        lay.addWidget(self.big)
        self.refresh()

    def _set(self, k, v):
        setattr(self, k, v)
        self.refresh()

    def refresh(self):
        s = (f'{self.MODES[self.mode]} \u00b7 {E.BANDS[self.idx].capitalize()}', ('hsl', self.mode, self.idx), -100, 100, 0, 1, 0)
        self.big.bind(s, self.win.S['hsl'][self.mode][self.idx])

    def refresh_chips(self):
        pass


class GradeBlock(QWidget):
    """The colour-grading sliders (same rows as any page, but inside a widget so they can be swapped in and out)."""
    add_sliders, sync_row = Page.add_sliders, Page.sync_row

    def __init__(self, win, specs):
        super().__init__()
        self.win, self.rows, self.sliders = win, [], []
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)
        self.add_sliders(win, specs)

    def refresh_chips(self):
        for r in self.sliders:
            self.sync_row(r)

    refresh = refresh_chips


class SubTab(QAbstractButton):
    """Dark rounded pill with an icon + label: 'Grading' / 'Color mix'."""

    def __init__(self, text, kind):
        super().__init__()
        self.setText(text)
        self.kind = kind
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hov, self.on = 0.0, 0.0
        self.a_h = anim(self, 140, self._h)
        self.a_o = anim(self, 220, self._o)
        self.toggled.connect(lambda c: go(self.a_o, self.on, 1.0 if c else 0.0))

    def _h(self, v):
        self.hov = v
        self.update()

    def _o(self, v):
        self.on = v
        self.update()

    def enterEvent(self, e):
        go(self.a_h, self.hov, 1)

    def leaveEvent(self, e):
        go(self.a_h, self.hov, 0)

    def _icon(self, p, cx, cy):
        if self.kind == 'grading':  # three little rings
            p.setPen(Qt.NoPen)
            for dx, dy in ((0, -5.2), (-5.4, 4.2), (5.4, 4.2)):
                path = QPainterPath()
                path.addEllipse(QPointF(cx + dx, cy + dy), 4.6, 4.6)
                path.addEllipse(QPointF(cx + dx, cy + dy), 1.7, 1.7)
                p.setBrush(C('#ffffff', 245))
                p.drawPath(path)
        else:  # colour wheel ring
            g = QConicalGradient(cx, cy, 90)
            for i, c in enumerate(HUE_RING):
                g.setColorAt(i / (len(HUE_RING) - 1), QColor(c))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QBrush(g), 3.4))
            p.drawEllipse(QPointF(cx, cy), 8.6, 8.6)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        t = max(self.on, 0.0)
        p.setBrush(mixc('#1b1a21', '#2c2942', t) if self.hov < 0.01 else mixc(mixc('#1b1a21', '#2c2942', t).name(), '#34313f', self.hov * (1 - t * .5)))
        p.setPen(QPen(mixc('#3a3844', PURPLE, t), 1.2))
        p.drawRoundedRect(r, 12, 12)
        f = QFont()
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.Medium)
        p.setFont(f)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self.text())
        total = 24 + 12 + tw
        x0 = (self.width() - total) / 2
        self._icon(p, x0 + 12, self.height() / 2)
        p.setPen(mixc('#c9c8cf', '#ffffff', max(t, self.hov * .6)))
        p.drawText(QRectF(x0 + 36, 0, tw + 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


HUE_RING = ['#ff3b30', '#ff9f0a', '#ffd60a', '#30d158', '#32d4ff', '#3d5afe', '#bf5af2', '#ff3b30']


def mixc(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class ColorTabs(QWidget):
    """[Grading] [Color mix] switcher with the matching controls underneath."""

    def __init__(self, win, mix, grade_specs):
        super().__init__()
        self.mix, self.grade = mix, GradeBlock(win, grade_specs)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 4)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btns = {'grading': SubTab('Grading', 'grading'), 'mix': SubTab('Color mix', 'mix')}
        g = QButtonGroup(self)
        for k, b in self.btns.items():
            g.addButton(b)
            row.addWidget(b)
            b.clicked.connect(lambda _=False, k=k: self.show_tab(k))
        lay.addLayout(row)
        self.panes = {'grading': self.grade, 'mix': mix}
        for w in self.panes.values():
            lay.addWidget(w)
        self.show_tab('grading', animate=False)

    def show_tab(self, k, animate=True):
        self.btns[k].setChecked(True)
        for n, w in self.panes.items():
            w.setVisible(n == k)
        if animate:
            w = self.panes[k]
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            a = anim(w, 240, eff.setOpacity)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.finished.connect(lambda w=w: w.setGraphicsEffect(None))
            a.start(QVariantAnimation.DeleteWhenStopped)
            self._a = a

    def refresh(self):
        self.grade.refresh()
        self.mix.refresh()

    def refresh_chips(self):
        self.grade.refresh_chips()


class CropPanel(Page):
    ASPECTS = ['Free', 'Original', '1:1', '4:5', '5:4', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16']
    SPEC = ('Straighten', ('angle',), -15, 15, 0, 0.1, 1)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.big = BigSlider(win)
        self.big.changed.connect(win.route_slider)
        self.big.setFixedHeight(70)
        self.lay.addWidget(Section('Crop'))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.grp = QButtonGroup(self)
        for i, a in enumerate(self.ASPECTS):
            b = pill(a, lambda _=False, a=a: win.set_aspect(a), True)
            b.setChecked(a == 'Free')
            self.grp.addButton(b)
            grid.addWidget(b, i // 3, i % 3)
        self.lay.addLayout(grid)
        self.lay.addWidget(Section('Rotate'))
        self.lay.addWidget(self.big)
        row = QHBoxLayout()
        row.addWidget(pill('Flip H', lambda: win.flip(0)))
        row.addWidget(pill('Flip V', lambda: win.flip(1)))
        row.addWidget(pill('Reset', win.reset_crop))
        self.lay.addLayout(row)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.addWidget(pill('Cancel', lambda: win.end_crop(False)))
        row.addWidget(pill('Done', lambda: win.end_crop(True), name='primary'))
        self.lay.addLayout(row)
        self.lay.addStretch(1)
        self.rows = [self.big]
        self.refresh()

    def refresh(self):
        self.big.bind(self.SPEC, self.win.S['angle'])

    def refresh_chips(self):
        pass


class MaskPanel(Page):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.tool_btns = {}
        self.lay.addWidget(Section('New mask'))
        row = QHBoxLayout()
        for t, txt in (('linear', 'Linear'), ('radial', 'Radial'), ('brush', 'Brush')):
            b = pill(txt, lambda _=False, t=t: win.toggle_mask_tool(t), True, icon=t)
            b.setStyleSheet('padding:5px 8px;')
            self.tool_btns[t] = b
            row.addWidget(b)
        self.lay.addLayout(row)
        row = QHBoxLayout()
        b = pill('Auto select', lambda _=False: win.toggle_mask_tool('auto'), True, icon='auto')
        b.setStyleSheet('padding:5px 8px;')
        b.setToolTip('Click an area (or drag a box around a subject) and it is selected for you.  (A)')
        self.tool_btns['auto'] = b
        row.addWidget(b)
        self.lay.addLayout(row)
        row = QHBoxLayout()
        for txt, kind in (('Subject', 'subject'), ('Background', 'background')):
            b2 = pill(txt, lambda _=False, k=kind: win.make_auto_whole(k), False, icon='auto')
            b2.setStyleSheet('padding:5px 8px;')
            b2.setToolTip('Scans the whole photo and masks the ' + kind + ' automatically.')
            row.addWidget(b2)
        self.lay.addLayout(row)
        tip = QLabel('Auto select: click an area, or drag a box around a subject.\n'
                     'Shift + click adds more, Option / Alt + click takes away.')
        tip.setWordWrap(True)
        tip.setStyleSheet(f'color:{TXT_DIM};padding:2px 2px 4px 2px;font-size:11px;')
        self.lay.addWidget(tip)
        self.hint = QLabel('Pick a tool, then drag on the photo.\nHover a mask + Delete removes it.')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f'color:{TXT_DIM};padding:6px 2px;')
        self.lay.addWidget(self.hint)
        self.masks = ChipStrip(44, 'pill')
        self.masks.picked.connect(win.select_mask)
        self.masks.contextRequested.connect(win.mask_menu)
        self.lay.addWidget(self.masks)
        row = QHBoxLayout()
        self.inv = pill('Invert', win.mask_invert, True)
        self.ov = pill('Overlay', win.toggle_overlay, True)
        self.ov.setChecked(True)
        self.dele = pill('Delete', win.delete_mask)
        for b in (self.inv, self.ov, self.dele):
            b.setStyleSheet('padding:5px 8px;')
            row.addWidget(b)
        self.lay.addLayout(row)
        self.win = win
        items = MASK_ITEMS
        for title, part in (('Adjustments', items[:12]), ('Mask', items[12:18]), ('Brush', items[18:])):
            self.lay.addWidget(Section(title))
            if title == 'Brush':
                row = QHBoxLayout()
                self.erase_btn = pill('Erase  (E)', lambda on=False: win.set_erase(on), True)
                self.erase_btn.setToolTip('Paint over the red to remove it.  Tip: hold Option / Alt to erase while painting.')
                self.clear_btn = pill('Clear strokes', lambda _=False: win.clear_strokes())
                for b in (self.erase_btn, self.clear_btn):
                    b.setStyleSheet('padding:5px 8px;')
                    row.addWidget(b)
                self.lay.addLayout(row)
                tip = QLabel('Hold Option / Alt (or press E) to erase brush strokes.')
                tip.setWordWrap(True)
                tip.setStyleSheet(f'color:{TXT_DIM};padding:2px 2px 4px 2px;font-size:11px;')
                self.lay.addWidget(tip)
            self.add_sliders(win, part)
        self.lay.addStretch(1)
        self.adj = self

    def sync_tools(self):
        for t, b in self.tool_btns.items():
            b.setChecked(self.win.tool == t)

    def refresh(self):
        w = self.win
        masks = w.S['masks']
        self.masks.set_items([(i, f"{m['type'].capitalize()} {i + 1}") for i, m in enumerate(masks)])
        self.masks.setVisible(bool(masks))
        self.hint.setVisible(not masks)
        if 0 <= w.sel < len(masks):
            self.masks.select(w.sel)
        m = w.cur_mask()
        self.inv.setChecked(bool(m and m.get('invert')))
        self.inv.setEnabled(m is not None)
        self.dele.setEnabled(m is not None)
        self.clear_btn.setEnabled(bool(m and m['type'] == 'brush' and m.get('strokes')))
        self.refresh_chips()
        self.sync_tools()

    def refresh_chips(self):
        for r in self.sliders:
            self.sync_row(r)


class Toast(QLabel):
    """Small status message that fades in above the toolbar and disappears by itself."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f'background:{BAR};color:{TXT};border:1px solid rgba(255,255,255,0.10);'
                           'border-radius:16px;padding:7px 18px;font-size:12px;')
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0)
        self.setGraphicsEffect(self.eff)
        self.a = anim(self, 260, self.eff.setOpacity)
        self.t = QTimer(self, singleShot=True, interval=2800)
        self.t.timeout.connect(lambda: go(self.a, self.eff.opacity(), 0))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def say(self, text):
        self.setText(text)
        self.adjustSize()
        self.parent().relayout()
        go(self.a, self.eff.opacity(), 1)
        self.t.start()


class EditArea(Surface):
    def __init__(self):
        super().__init__(PANEL, (0, 34, 0, 0))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        self.stack = FadeStack()
        lay.addWidget(self.stack)


class Toolbar(Surface):
    def __init__(self, win):
        super().__init__(PANEL, (42, 42, 42, 42))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(40, 10, 40, 10)
        self.crop = ToolButton('Crop', 'Crop  (R)')
        self.mask = ToolButton('Masks', 'Mask  (L / O / B)')
        # click handlers are connected in pylight.py (tool_clicked) - connecting here too made crop open and close at once
        lay.addWidget(self.crop)
        lay.addStretch(1)
        lay.addWidget(self.mask)