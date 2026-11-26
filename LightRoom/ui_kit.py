"""
PyLight UI kit - glass panels, round tool "nodes", animated slider, smooth-zoom photo view.
(No image processing in here; that lives in engine.py.)
"""
import math

import numpy as np
from PySide6.QtCore import (Qt, Signal, QSize, QPointF, QRectF, QTimer, QEvent, QVariantAnimation, QEasingCurve,
                            QPropertyAnimation)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient, QRadialGradient, QIcon,
                           QPixmap, QTransform, QFont, QFontMetrics)
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QAbstractButton, QPushButton,
                               QScrollArea, QButtonGroup, QStackedWidget, QSizePolicy, QInputDialog, QGraphicsView,
                               QGraphicsScene, QGraphicsPixmapItem, QGraphicsOpacityEffect)

import engine as E

ACCENT = '#746be0'
AC = QColor(ACCENT)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t, alpha=None):
    c = QColor(int(lerp(c1.red(), c2.red(), t)), int(lerp(c1.green(), c2.green(), t)), int(lerp(c1.blue(), c2.blue(), t)))
    c.setAlpha(int(lerp(c1.alpha(), c2.alpha(), t)) if alpha is None else alpha)
    return c


def glass_bg(p, rect, radius=12):
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 24), 1))
    p.setBrush(QColor(255, 255, 255, 12))
    p.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), radius, radius)


# ============================================================================ icons
ICON_KEY = {
    'exposure': 'sun', 'contrast': 'contrast', 'highlights': 'sunup', 'shadows': 'sundown', 'whites': 'ring',
    'blacks': 'disc', 'curve': 'curve', 'temp': 'thermo', 'tint': 'drop', 'vibrance': 'drops', 'saturation': 'dropfill',
    'color mix': 'mix', 'balance': 'seesaw', 'texture': 'zig', 'clarity': 'diamond', 'dehaze': 'haze',
    'vignette': 'vig', 'midpoint': 'conc', 'feather': 'dashring', 'grain': 'dots', 'sharpening': 'tri',
    'radius': 'radius', 'noise': 'dots', 'color noise': 'dots', 'amount': 'pie', 'range min': 'bars',
    'range max': 'bars', 'brush size': 'disc', 'brush feather': 'dashring', 'brush flow': 'drops', 'free': 'free',
    'original': 'orig', 'straighten': 'seesaw',
}


def icon_key(name):
    n = name.lower()
    if n in ICON_KEY:
        return ICON_KEY[n]
    if n.endswith(('hue', 'sat')):
        return 'wheel'
    if ':' in n:
        return 'ratio'
    for w in ('linear', 'radial', 'brush'):
        if n.startswith(w):
            return w
    return 'dot'


def paint_icon(p, key, name=''):
    """Line icon in a 28x28 box. The caller sets pen colour/width first."""
    col, P = p.pen().color(), QPointF
    p.setBrush(Qt.NoBrush)

    def disc(x, y, r, a=255):
        f = QColor(col)
        f.setAlpha(a)
        p.setBrush(f)
        p.drawEllipse(P(x, y), r, r)
        p.setBrush(Qt.NoBrush)

    def rays(n, r0, r1, lo=0.0, hi=2 * math.pi, incl=False, cy=14):
        step = (hi - lo) / ((n - 1) if incl else n)
        for k in range(n):
            a = lo + step * k
            p.drawLine(P(14 + r0 * math.cos(a), cy + r0 * math.sin(a)), P(14 + r1 * math.cos(a), cy + r1 * math.sin(a)))

    def poly(pts):
        p.drawPolygon([P(*q) for q in pts])

    def drop():
        d = QPainterPath(P(14, 3))
        d.cubicTo(18, 9, 22, 13, 22, 17.5)
        d.cubicTo(22, 22, 18.5, 25, 14, 25)
        d.cubicTo(9.5, 25, 6, 22, 6, 17.5)
        d.cubicTo(6, 13, 10, 9, 14, 3)
        return d

    if key == 'sun':
        p.drawEllipse(P(14, 14), 5, 5)
        rays(8, 8.5, 12)
    elif key == 'sunup':
        p.drawEllipse(P(14, 17), 4.5, 4.5)
        rays(5, 8, 11.5, math.pi, 2 * math.pi, True, 17)
    elif key == 'sundown':
        p.drawEllipse(P(14, 11), 4.5, 4.5)
        rays(5, 8, 11.5, 0, math.pi, True, 11)
    elif key == 'contrast':
        p.drawEllipse(P(14, 14), 9, 9)
        p.setBrush(col)
        p.drawPie(QRectF(5, 5, 18, 18), 90 * 16, -180 * 16)
        p.setBrush(Qt.NoBrush)
    elif key == 'ring':
        p.drawEllipse(P(14, 14), 8, 8)
    elif key == 'disc':
        disc(14, 14, 8, 230)
    elif key == 'curve':
        c = QPainterPath(P(4, 23))
        c.cubicTo(13, 23, 15, 5, 24, 5)
        p.drawPath(c)
        disc(4, 23, 1.6)
        disc(24, 5, 1.6)
    elif key == 'thermo':
        p.drawRoundedRect(QRectF(11.5, 3, 5, 15), 2.5, 2.5)
        disc(14, 21, 4.5)
        p.drawLine(P(14, 8), P(14, 19))
    elif key in ('drop', 'dropfill', 'drops'):
        p.drawPath(drop())
        if key != 'drop':
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 90))
            p.drawPath(drop())
            p.setBrush(Qt.NoBrush)
    elif key == 'mix':
        for x, y in ((11, 12), (17, 12), (14, 18)):
            p.drawEllipse(P(x, y), 6.5, 6.5)
    elif key == 'wheel':
        p.drawEllipse(P(14, 14), 10, 10)
        disc(14 + 6.5 * math.cos(-0.7), 14 + 6.5 * math.sin(-0.7), 2.6)
        p.drawEllipse(P(14, 14), 3.5, 3.5)
    elif key == 'seesaw':
        p.drawLine(P(4, 17), P(24, 11))
        poly([(14, 14), (10, 24), (18, 24)])
    elif key == 'zig':
        for y in (8, 14, 20):
            p.drawPolyline([P(4 + 4 * i, y + (2 if i % 2 else -2)) for i in range(6)])
    elif key == 'diamond':
        poly([(14, 3), (25, 14), (14, 25), (3, 14)])
        poly([(14, 9), (19, 14), (14, 19), (9, 14)])
    elif key == 'haze':
        for y, a, x0 in ((8, 255, 4), (14, 170, 7), (20, 90, 10)):
            c = QColor(col)
            c.setAlpha(a)
            p.setPen(QPen(c, p.pen().widthF(), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(P(x0, y), P(28 - x0, y))
    elif key == 'vig':
        p.drawRoundedRect(QRectF(3.5, 5, 21, 18), 5, 5)
        p.drawEllipse(P(14, 14), 6.5, 5)
    elif key == 'conc':
        p.drawEllipse(P(14, 14), 4, 4)
        p.drawEllipse(P(14, 14), 9.5, 9.5)
    elif key == 'dashring':
        pen = QPen(p.pen())
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)
        p.drawEllipse(P(14, 14), 9.5, 9.5)
    elif key == 'dots':
        for x, y in ((7, 8), (14, 6), (21, 9), (10, 14), (18, 15), (6, 20), (13, 22), (22, 21), (15, 11)):
            disc(x, y, 1.5)
    elif key == 'tri':
        poly([(14, 4), (25, 24), (3, 24)])
        p.drawLine(P(14, 12), P(14, 19))
    elif key == 'radius':
        p.drawEllipse(P(14, 14), 9.5, 9.5)
        p.drawLine(P(14, 14), P(14 + 9.5 * math.cos(-0.7), 14 + 9.5 * math.sin(-0.7)))
        disc(14, 14, 1.8)
    elif key == 'pie':
        p.drawEllipse(P(14, 14), 9.5, 9.5)
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 150))
        p.drawPie(QRectF(4.5, 4.5, 19, 19), 90 * 16, -270 * 16)
        p.setBrush(Qt.NoBrush)
    elif key == 'bars':
        for x, y0 in ((8, 12), (14, 6), (20, 16)):
            p.drawLine(P(x, 22), P(x, y0))
    elif key == 'linear':
        p.drawRoundedRect(QRectF(4, 5, 20, 18), 4, 4)
        for y, a in ((10, 255), (14, 150), (18, 70)):
            c = QColor(col)
            c.setAlpha(a)
            p.setPen(QPen(c, p.pen().widthF(), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(P(8, y), P(20, y))
    elif key == 'radial':
        p.drawEllipse(P(14, 14), 10, 10)
        p.drawEllipse(P(14, 14), 5, 5)
        disc(14, 14, 1.5)
    elif key == 'brush':
        pen = QPen(p.pen())
        pen.setWidthF(4)
        p.setPen(pen)
        p.drawLine(P(11, 17), P(22, 6))
        pen.setWidthF(1.7)
        p.setPen(pen)
        p.drawEllipse(P(8, 20), 3.5, 3.5)
    elif key == 'ratio':
        try:
            a, b = (float(x) for x in name.split(':')[:2])
        except ValueError:
            a, b = 1, 1
        s = min(20 / a, 20 / b)
        p.drawRoundedRect(QRectF(14 - a * s / 2, 14 - b * s / 2, a * s, b * s), 2.5, 2.5)
    elif key == 'free':
        pen = QPen(p.pen())
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(4, 6, 20, 16), 3, 3)
    elif key == 'orig':
        p.drawRoundedRect(QRectF(3, 5, 22, 18), 3, 3)
        p.drawPolyline([P(6, 20), P(11, 13), P(15, 18), P(18, 15), P(23, 20)])
    elif key == 'folder':
        p.drawRoundedRect(QRectF(3, 8, 22, 15), 3, 3)
        p.drawPolyline([P(3, 8), P(3, 6), P(11, 6), P(13, 8)])
    elif key in ('undo', 'redo'):
        if key == 'redo':
            p.translate(28, 0)
            p.scale(-1, 1)
        c = QPainterPath(P(5, 12))
        c.cubicTo(14, 8, 24, 11, 22, 21)
        p.drawPath(c)
        p.drawPolyline([P(10, 6), P(5, 12), P(11, 17)])
    elif key == 'more':
        for x in (6, 14, 22):
            disc(x, 14, 2.2)
    elif key == 'export':
        p.drawPolyline([P(6, 15), P(6, 23), P(22, 23), P(22, 15)])
        p.drawLine(P(14, 18), P(14, 5))
        p.drawPolyline([P(9, 10), P(14, 5), P(19, 10)])
    elif key == 'compare':
        p.drawRoundedRect(QRectF(4, 5, 20, 18), 3, 3)
        p.drawLine(P(14, 5), P(14, 23))
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 110))
        p.drawRect(QRectF(4.5, 5.5, 9, 17))
        p.setBrush(Qt.NoBrush)
    elif key == 'blur':
        d = drop()
        p.drawPath(d)
        p.save()
        p.setClipRect(QRectF(14, 0, 14, 28))
        f = QColor(col)
        f.setAlpha(210)
        p.fillPath(d, f)
        p.restore()
    elif key == 'gear':
        p.drawEllipse(P(14, 14), 4, 4)
        p.drawEllipse(P(14, 14), 8.2, 8.2)
        rays(8, 8.2, 11.6)
    elif key == 'Presets':
        for x, y in ((4, 4), (17, 4), (4, 17), (17, 17)):
            p.drawRoundedRect(QRectF(x, y, 8, 8), 2.5, 2.5)
    elif key == 'Crop':
        p.drawPolyline([P(9, 3), P(9, 21), P(27, 21)])
        p.drawPolyline([P(3, 9), P(21, 9), P(21, 27)])
    elif key == 'Light':
        p.drawEllipse(P(14, 14), 5, 5)
        rays(8, 8.5, 12)
    elif key == 'Color':
        for x, y in ((11, 12), (17, 12), (14, 18)):
            p.drawEllipse(P(x, y), 6.5, 6.5)
    elif key == 'Effects':
        poly([(14, 2.5), (16.8, 11.2), (25.5, 14), (16.8, 16.8), (14, 25.5), (11.2, 16.8), (2.5, 14), (11.2, 11.2)])
    elif key == 'Detail':
        poly([(14, 5), (25, 24), (3, 24)])
    elif key == 'Masks':
        p.drawRoundedRect(QRectF(3.5, 6, 21, 17), 4.5, 4.5)
        p.drawEllipse(P(14, 14.5), 5, 5)
    else:
        disc(14, 14, 3.5)


def qicon(key, off='#9fb0c8', on=ACCENT, size=28):
    ic = QIcon()
    for state, col in ((QIcon.Off, off), (QIcon.On, on)):
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 28, size / 28)
        p.setPen(QPen(QColor(col), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        paint_icon(p, key)
        p.end()
        ic.addPixmap(pm, QIcon.Normal, state)
    return ic


def cat_icon(name):
    return qicon(name, '#8fa2c0', '#ffffff', 28)


# ============================================================================ glass surfaces
class GlassBackground(QWidget):
    """Deep blue window background with soft glows - the 'glass' sits on top of this."""

    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w * 0.35, h)
        g.setColorAt(0, QColor('#050913'))
        g.setColorAt(0.5, QColor('#0a1325'))
        g.setColorAt(1, QColor('#060b18'))
        p.fillRect(self.rect(), g)
        for cx, cy, r, c in ((0.10, 0.06, 0.55, (40, 110, 255, 78)), (0.95, 0.30, 0.45, (70, 90, 255, 46)),
                             (0.18, 0.98, 0.55, (30, 150, 255, 70)), (0.82, 1.0, 0.5, (110, 70, 255, 58)),
                             (0.5, 0.55, 0.35, (20, 70, 160, 28))):
            rg = QRadialGradient(cx * w, cy * h, r * max(w, h))
            rg.setColorAt(0, QColor(*c))
            rg.setColorAt(1, QColor(c[0], c[1], c[2], 0))
            p.fillRect(self.rect(), rg)


class GlassPanel(QFrame):
    def __init__(self, radius=22):
        super().__init__()
        self.radius = radius

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(34, 54, 94, 150))
        g.setColorAt(1, QColor(12, 22, 42, 175))
        p.fillPath(path, g)
        s = QLinearGradient(0, 0, 0, r.height() * 0.55)
        s.setColorAt(0, QColor(255, 255, 255, 30))
        s.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, s)
        p.setPen(QPen(QColor(255, 255, 255, 48), 1))
        p.drawPath(path)
        hl = QLinearGradient(r.left(), 0, r.right(), 0)
        hl.setColorAt(0, QColor(255, 255, 255, 0))
        hl.setColorAt(0.5, QColor(255, 255, 255, 90))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(hl), 1))
        p.drawLine(QPointF(r.left() + self.radius, r.top() + 1), QPointF(r.right() - self.radius, r.top() + 1))


class Dock(GlassPanel):
    """Bottom tab bar with a glowing highlight that glides to the active tab."""

    def __init__(self):
        super().__init__(radius=30)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 10, 6)
        self.lay.setSpacing(2)
        self.hl, self.active = QRectF(), None
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(320)
        self.anim.setEasingCurve(QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._moved)

    def _moved(self, r):
        self.hl = r
        self.update()

    def _target(self):
        return QRectF(self.active.geometry()).adjusted(2, 0, -2, 0) if self.active else QRectF()

    def add(self, b):
        self.lay.addWidget(b)

    def activate(self, b, animate=True):
        self.active = b
        t = self._target()
        if animate and not self.hl.isNull() and self.isVisible():
            self.anim.stop()
            self.anim.setStartValue(self.hl)
            self.anim.setEndValue(t)
            self.anim.start()
        else:
            self.hl = t
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: self.activate(self.active, False))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self.activate(self.active, False))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.hl.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glow = QRadialGradient(self.hl.center(), self.hl.width() * 0.8)
        glow.setColorAt(0, QColor(116, 107, 224, 70))
        glow.setColorAt(1, QColor(116, 107, 224, 0))
        p.fillRect(self.rect(), glow)
        g = QLinearGradient(0, self.hl.top(), 0, self.hl.bottom())
        g.setColorAt(0, QColor(116, 107, 224, 95))
        g.setColorAt(1, QColor(96, 86, 200, 55))
        p.setBrush(g)
        p.setPen(QPen(QColor(150, 142, 245, 150), 1))
        p.drawRoundedRect(self.hl.adjusted(.5, .5, -.5, -.5), 22, 22)


class FadeStack(QStackedWidget):
    """Stack that is only as tall as its current page and cross-fades when the page changes."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(self._fit)

    def addWidget(self, w):
        r = super().addWidget(w)
        self._fit(self.currentIndex())
        return r

    def _fit(self, i):
        for k in range(self.count()):
            pol = QSizePolicy.Preferred if k == i else QSizePolicy.Ignored
            self.widget(k).setSizePolicy(pol, pol)
        self.updateGeometry()

    def setCurrentWidget(self, w):
        if w is self.currentWidget():
            return
        super().setCurrentWidget(w)
        if not self.isVisible():
            return
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b'opacity', w)
        a.setDuration(240)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(lambda w=w: w.setGraphicsEffect(None))
        a.start(QPropertyAnimation.DeleteWhenStopped)
        self._anim = a


# ============================================================================ node buttons
class NodeButton(QAbstractButton):
    """Round Lightroom-style tool node (icon + name + value) with animated selection glow."""
    hoverChanged = Signal(bool)
    contextRequested = Signal()

    def __init__(self, name, kind='circle', pm=None):
        super().__init__()
        self.name, self.value, self.mod, self.kind, self.pm = name, '', False, kind, pm
        self.key = icon_key(name)
        self._t = self._h = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.a_sel, self.a_hov = QVariantAnimation(self), QVariantAnimation(self)
        self.a_sel.setDuration(260)
        self.a_sel.setEasingCurve(QEasingCurve.OutBack)
        self.a_hov.setDuration(160)
        self.a_sel.valueChanged.connect(self._set_t)
        self.a_hov.valueChanged.connect(self._set_h)
        self.toggled.connect(lambda on: self._go(self.a_sel, self._t, 1.0 if on else 0.0))
        if kind == 'circle':
            self.setFixedSize(74, 92)
        elif kind == 'card':
            self.setFixedSize(102, 126)
        else:
            self.setFixedHeight(36)
            self.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance(name) + 58)

    def _go(self, anim, a, b):
        anim.stop()
        anim.setStartValue(float(a))
        anim.setEndValue(float(b))
        anim.start()

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def enterEvent(self, e):
        self._go(self.a_hov, self._h, 1.0)
        self.hoverChanged.emit(True)

    def leaveEvent(self, e):
        self._go(self.a_hov, self._h, 0.0)
        self.hoverChanged.emit(False)

    def contextMenuEvent(self, e):
        self.contextRequested.emit()

    def _text(self, p, rect, txt, px, color, bold=False):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setWeight(QFont.DemiBold if bold else QFont.Medium)
        p.setFont(f)
        p.setPen(color)
        p.drawText(rect, Qt.AlignCenter, QFontMetrics(f).elidedText(txt, Qt.ElideRight, int(rect.width())))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t, h, w = max(0.0, min(1.0, self._t)), self._h, self.width()
        white = QColor(255, 255, 255)
        if self.kind == 'circle':
            cx, cy, r = w / 2, 31, 24
            s = 1 + 0.06 * self._t + 0.03 * h
            p.save()
            p.translate(cx, cy)
            p.scale(s, s)
            p.translate(-cx, -cy)
            if t > 0.01:
                g = QRadialGradient(cx, cy, 31)
                g.setColorAt(0.55, QColor(116, 107, 224, int(110 * t)))
                g.setColorAt(1, QColor(116, 107, 224, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(QPointF(cx, cy), 31, 31)
            base = mix(white, AC, t, 255)
            body = QLinearGradient(0, cy - r, 0, cy + r)
            c1, c2 = QColor(base), QColor(base)
            c1.setAlpha(int(34 + 40 * t + 14 * h))
            c2.setAlpha(int(10 + 46 * t + 8 * h))
            body.setColorAt(0, c1)
            body.setColorAt(1, c2)
            p.setBrush(body)
            p.setPen(QPen(mix(QColor(255, 255, 255, 52), QColor(150, 142, 245, 235), t), 1.3))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(mix(QColor(200, 214, 238), white, t, 255), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.save()
            p.translate(cx - 14, cy - 14)
            paint_icon(p, self.key, self.name)
            p.restore()
            p.restore()
            if self.mod:
                p.setPen(QPen(QColor(12, 20, 38), 2))
                p.setBrush(AC)
                p.drawEllipse(QPointF(cx + r * 0.74, cy - r * 0.74), 4.5, 4.5)
            self._text(p, QRectF(0, 59, w, 15), self.name, 11, mix(QColor(190, 204, 226), white, t, 255), t > .5)
            if self.value:
                self._text(p, QRectF(0, 74, w, 14), self.value, 10,
                           QColor(190, 184, 255) if self.mod else QColor(125, 142, 168))
        elif self.kind == 'card':
            x0, size = (w - 86) / 2, 86
            r = QRectF(x0, 6, size, size)
            path = QPainterPath()
            path.addRoundedRect(r, 15, 15)
            p.save()
            p.setClipPath(path)
            if self.pm is not None:
                p.drawPixmap(r.toRect(), self.pm)
            else:
                p.fillRect(r, QColor(255, 255, 255, 22))
            p.restore()
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(mix(QColor(255, 255, 255, 50), QColor(139, 131, 240, 255), t), 1.2 + 1.6 * t))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 16, 16)
            self._text(p, QRectF(2, 98, w - 4, 18), self.name, 11, mix(QColor(190, 204, 226), white, t, 255), t > .5)
        else:
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            fill = mix(QColor(255, 255, 255, 22 + int(14 * h)), QColor(116, 107, 224, 90), t)
            p.setBrush(fill)
            p.setPen(QPen(mix(QColor(255, 255, 255, 40), QColor(150, 142, 245, 220), t), 1.1))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.save()
            p.translate(10, 8)
            p.scale(0.7, 0.7)
            p.setPen(QPen(mix(QColor(190, 204, 226), white, t, 255), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            paint_icon(p, self.key, self.name)
            p.restore()
            self._text(p, QRectF(30, 0, w - 36, self.height()), self.name, 12, mix(QColor(200, 212, 232), white, t, 255), t > .5)


class ChipStrip(QScrollArea):
    """Horizontally scrolling row of NodeButtons."""
    picked = Signal(object)
    contextRequested = Signal(object)

    def __init__(self, height=96, kind='circle'):
        super().__init__()
        self.kind, self.hover_id = kind, None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(height)
        self.body = QWidget()
        self.lay = QHBoxLayout(self.body)
        self.lay.setContentsMargins(8, 2, 8, 2)
        self.lay.setSpacing(4 if kind == 'circle' else 8)
        self.lay.addStretch(1)
        self.setWidget(self.body)
        self.btns, self.group = {}, QButtonGroup(self)

    def wheelEvent(self, e):
        d = e.angleDelta()
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - (d.x() or d.y()))

    def _hv(self, i, on):
        self.hover_id = i if on else (None if self.hover_id == i else self.hover_id)

    def set_items(self, items):
        self.hover_id = None
        for b in self.btns.values():
            self.group.removeButton(b)
            b.setParent(None)
            b.deleteLater()
        self.btns = {}
        for it in items:
            id_, name, val = it[0], *(it[1].partition('\n')[0::2])
            pm = it[2].pixmap(QSize(86, 86)) if len(it) > 2 and it[2] is not None else None
            b = NodeButton(name, 'card' if (pm is not None or self.kind == 'card') else self.kind, pm)
            b.value = val
            b.clicked.connect(lambda _=False, i=id_: self.picked.emit(i))
            b.hoverChanged.connect(lambda on, i=id_: self._hv(i, on))
            b.contextRequested.connect(lambda i=id_: self.contextRequested.emit(i))
            self.group.addButton(b)
            self.lay.insertWidget(self.lay.count() - 1, b)
            self.btns[id_] = b

    def select(self, id_):
        b = self.btns.get(id_)
        if b:
            b.setChecked(True)

    def set_text(self, id_, text, modified=False):
        b = self.btns.get(id_)
        if b:
            b.value = text.partition('\n')[2]
            b.mod = bool(modified)
            b.update()


# ============================================================================ tool lists
def spec(label, key, lo, hi, d=0, st=1, dec=0, path=None):
    return (label, path or (key,), lo, hi, d, st, dec)


LIGHT = [spec('Exposure', 'exposure', -5, 5, 0, 0.01, 2), spec('Contrast', 'contrast', -100, 100),
         spec('Highlights', 'highlights', -100, 100), spec('Shadows', 'shadows', -100, 100),
         spec('Whites', 'whites', -100, 100), spec('Blacks', 'blacks', -100, 100)]
COLOR = [spec('Temp', 'temp', -100, 100), spec('Tint', 'tint', -100, 100),
         spec('Vibrance', 'vibrance', -100, 100), spec('Saturation', 'saturation', -100, 100)]
GRADING = [spec('Shadow hue', '', 0, 360, path=('grade', 'sh', 0)), spec('Shadow sat', '', 0, 100, path=('grade', 'sh', 1)),
           spec('Mid hue', '', 0, 360, path=('grade', 'mid', 0)), spec('Mid sat', '', 0, 100, path=('grade', 'mid', 1)),
           spec('High hue', '', 0, 360, path=('grade', 'hi', 0)), spec('High sat', '', 0, 100, path=('grade', 'hi', 1)),
           spec('Balance', '', -100, 100, path=('grade', 'balance'))]
EFFECTS = [spec('Texture', 'texture', -100, 100), spec('Clarity', 'clarity', -100, 100),
           spec('Dehaze', 'dehaze', -100, 100), spec('Vignette', 'vignette', -100, 100),
           spec('Midpoint', 'vig_mid', 0, 100, 50), spec('Feather', 'vig_feather', 0, 100, 50),
           spec('Grain', 'grain', 0, 100)]
DETAIL = [spec('Sharpening', 'sharpen', 0, 100), spec('Radius', 'sharpen_radius', 0.5, 3, 1.0, 0.1, 1),
          spec('Noise', 'nr_lum', 0, 100), spec('Color noise', 'nr_color', 0, 100)]
MASK_ITEMS = ([spec(n, '', lo, hi, d, st, dec, path=('mask', 'adj', k)) for n, k, lo, hi, d, st, dec in (
    ('Exposure', 'exposure', -5, 5, 0, 0.01, 2), ('Contrast', 'contrast', -100, 100, 0, 1, 0),
    ('Highlights', 'highlights', -100, 100, 0, 1, 0), ('Shadows', 'shadows', -100, 100, 0, 1, 0),
    ('Whites', 'whites', -100, 100, 0, 1, 0), ('Blacks', 'blacks', -100, 100, 0, 1, 0),
    ('Temp', 'temp', -100, 100, 0, 1, 0), ('Tint', 'tint', -100, 100, 0, 1, 0),
    ('Saturation', 'saturation', -100, 100, 0, 1, 0), ('Texture', 'texture', -100, 100, 0, 1, 0),
    ('Clarity', 'clarity', -100, 100, 0, 1, 0), ('Dehaze', 'dehaze', -100, 100, 0, 1, 0))] +
              [spec('Amount', '', 0, 100, 100, path=('mask', 'amount')),
               spec('Feather', '', 0, 100, 50, path=('mask', 'feather')),
               spec('Range min', '', 0, 100, 0, path=('mask', 'lum_lo')),
               spec('Range max', '', 0, 100, 100, path=('mask', 'lum_hi')),
               spec('Brush size', '', 1, 50, 5, path=('brush', 'size')),
               spec('Brush feather', '', 0, 100, 50, path=('brush', 'feather')),
               spec('Brush flow', '', 1, 100, 100, path=('brush', 'flow'))])



# ============================================================================ slider
# colourful slider tracks (Lightroom style): stops are evenly spaced from the left end to the right end
_GREY = '#74737d'
HUE_STOPS = ['#ff3b30', '#ffd60a', '#30d158', '#32d4ff', '#3d5afe', '#d63cf0', '#ff3b30']
TRACKS = {
    'temp': ['#3d5afe', _GREY, '#f5d63a'],
    'tint': ['#37c04a', _GREY, '#c94fe0'],
    'vibrance': ['#6a6972', '#7fa13f', '#d4b83a', '#e0453a'],
    'saturation': ['#6a6972', '#7fa13f', '#d4b83a', '#e0453a'],
}


def track_colors(path):
    """Gradient stops for a slider's track, or None for the normal purple one."""
    if not path or path[0] == 'hsl':
        return None
    if path[0] == 'grade' and len(path) == 3 and path[2] == 0:
        return HUE_STOPS  # shadow / mid / high hue
    key = path[-1]
    return TRACKS.get(key) if isinstance(key, str) else None


def stops_at(stops, t):
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return mix(QColor(stops[i]), QColor(stops[i + 1]), t - i)


class LRSlider(QWidget):
    """Thin glass slider; the blue fill starts at the default value. The handle grows while dragged."""
    changed = Signal(float, bool)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.lo, self.hi, self.default, self.step, self.v = -100.0, 100.0, 0.0, 1.0, 0.0
        self._drag, self._g = False, 0.0
        self.colors = None  # gradient stops -> colourful track + colourful node
        self.setCursor(Qt.PointingHandCursor)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(150)
        self.anim.valueChanged.connect(self._set_g)

    def _set_g(self, v):
        self._g = float(v)
        self.update()

    def setup(self, lo, hi, default, step):
        self.lo, self.hi, self.default, self.step = float(lo), float(hi), float(default), float(step)
        self.update()

    def set_colors(self, stops):
        self.colors = stops
        self.update()

    def set_value(self, v):
        self.v = float(v)
        self.update()

    def _x(self, v):
        return 14 + (v - self.lo) / (self.hi - self.lo) * (self.width() - 28)

    def _val(self, x):
        t = min(1.0, max(0.0, (x - 14) / max(1, self.width() - 28)))
        v = round((self.lo + t * (self.hi - self.lo)) / self.step) * self.step
        return round(min(self.hi, max(self.lo, v)), 4)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y, on = self.height() / 2, self.isEnabled()
        x0, x1 = self._x(self.default), self._x(self.v)
        p.setPen(Qt.NoPen)
        col = None
        if self.colors:
            col = stops_at(self.colors, (self.v - self.lo) / (self.hi - self.lo))
            tg = QLinearGradient(14, 0, self.width() - 14, 0)
            for i, c in enumerate(self.colors):
                cc = QColor(c)
                cc.setAlpha(235 if on else 90)
                tg.setColorAt(i / (len(self.colors) - 1), cc)
            p.setBrush(tg)
            p.drawRoundedRect(QRectF(14, y - 2.5, self.width() - 28, 5), 2.5, 2.5)
        else:
            p.setBrush(QColor(255, 255, 255, 38))
            p.drawRoundedRect(QRectF(14, y - 2, self.width() - 28, 4), 2, 2)
        if abs(x1 - x0) > 0.5 and not self.colors:
            g = QLinearGradient(min(x0, x1), 0, max(x0, x1) + 1, 0)
            g.setColorAt(0, QColor('#746be0') if on else QColor('#444'))
            g.setColorAt(1, QColor('#a39cff') if on else QColor('#555'))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(min(x0, x1), y - 2, abs(x1 - x0), 4), 2, 2)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawRoundedRect(QRectF(x0 - 0.75, y - 7, 1.5, 14), .75, .75)
        if self._g > 0.01 and on:
            gc = col or QColor(116, 107, 224)
            gl = QRadialGradient(x1, y, 26)
            gl.setColorAt(0.4, QColor(gc.red(), gc.green(), gc.blue(), int(110 * self._g)))
            gl.setColorAt(1, QColor(gc.red(), gc.green(), gc.blue(), 0))
            p.setBrush(gl)
            p.drawEllipse(QPointF(x1, y), 26, 26)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawEllipse(QPointF(x1, y + 1.6), 11, 11)
        r = 10 + 2.5 * self._g
        p.setBrush(QColor('#ffffff') if on else QColor('#777'))
        p.drawEllipse(QPointF(x1, y), r, r)
        if on and col is not None:  # the node takes the colour of the track under it
            p.setBrush(col)
            p.drawEllipse(QPointF(x1, y), r - 3.2, r - 3.2)
        elif on:
            p.setBrush(QColor(116, 107, 224, 230))
            p.drawEllipse(QPointF(x1, y), 3, 3)

    def _grow(self, to):
        self.anim.stop()
        self.anim.setStartValue(self._g)
        self.anim.setEndValue(to)
        self.anim.start()

    def _set(self, x, final):
        nv = self._val(x)
        if nv != self.v or final:
            self.v = nv
            self.update()
            self.changed.emit(nv, final)

    def mousePressEvent(self, e):
        if self.isEnabled():
            self._drag = True
            self._grow(1.0)
            self._set(e.position().x(), False)

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set(e.position().x(), False)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self._grow(0.0)
            self._set(e.position().x(), True)

    def mouseDoubleClickEvent(self, e):
        if self.isEnabled():
            self._drag = False
            self._grow(0.0)
            self.v = self.default
            self.update()
            self.changed.emit(self.default, True)


class BigSlider(QWidget):
    """One large slider with a name + value header, re-bound to whichever adjustment is selected."""
    changed = Signal(object, float, bool)  # path, value, final

    def __init__(self, win=None):
        super().__init__()
        self.win, self.spec = win, None
        self.lab = QLabel('')
        self.lab.setStyleSheet('color:#d9d7e0;font-size:13px;font-weight:600;')
        self.val = QLabel('0')
        self.val.setStyleSheet('color:white;font-size:15px;font-weight:700;background:rgba(0,0,0,0.28);'
                               'border:1px solid rgba(255,255,255,0.12);border-radius:12px;padding:3px 14px;')
        self.val.setToolTip('Double-click to type a value')
        self.val.mouseDoubleClickEvent = self._type
        self.sl = LRSlider()
        self.sl.changed.connect(self._moved)
        top = QHBoxLayout()
        top.setContentsMargins(12, 0, 12, 0)
        top.addWidget(self.lab)
        top.addStretch(1)
        top.addWidget(self.val)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.sl)

    def _fmt(self, v):
        if self.win is not None and self.spec:
            return self.win.display_value(self.spec[1], v, self.spec)
        return f'{v:.0f}'

    def bind(self, spec_, value):
        self.spec = spec_
        self.lab.setText(spec_[0])
        self.sl.setup(spec_[2], spec_[3], spec_[4], spec_[5])
        self.sl.set_colors(track_colors(spec_[1]))
        self.set_value(value)

    def set_value(self, v):
        self.sl.set_value(v)
        self.val.setText(self._fmt(v))

    def _moved(self, v, final):
        self.val.setText(self._fmt(v))
        if self.spec:
            self.changed.emit(self.spec[1], v, final)

    def _type(self, e):
        if not self.spec or not self.isEnabled():
            return
        _, _, lo, hi, d, st, dec = self.spec
        v, ok = QInputDialog.getDouble(self, self.spec[0], 'Value', self.sl.v, lo, hi, dec)
        if ok:
            self.set_value(v)
            self.changed.emit(self.spec[1], v, True)


def pill(text, fn=None, checkable=False, name='pill', icon=None):
    b = QPushButton(text)
    b.setObjectName(name)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    if icon:
        b.setIcon(qicon(icon, '#dbe6f7', '#ffffff', 18))
        b.setIconSize(QSize(18, 18))
    if fn:
        b.clicked.connect(fn)
    return b


def centered(lay):
    lay.insertStretch(0, 1)
    lay.addStretch(1)


# ============================================================================ panels
class SliderPanel(QWidget):
    """Row of tool nodes + one big slider. 'extras' are special widgets (curve, color mix) shown instead of the slider."""

    def __init__(self, win, items, extras=None, extras_at=None):
        super().__init__()
        self.win, self.items, self.extras, self.cur = win, items, extras or {}, 0
        self.big = BigSlider(win)
        self.big.changed.connect(win.route_slider)
        self.stack = FadeStack()
        self.stack.addWidget(self.big)
        for w in self.extras.values():
            self.stack.addWidget(w)
        self.strip = ChipStrip(96)
        chips = [(i, f'{s[0]}\n{win.display_value(s[1], s[4], s)}') for i, s in enumerate(items)]
        at = len(chips) if extras_at is None else extras_at
        chips[at:at] = [(k, k) for k in self.extras]
        self.strip.set_items(chips)
        self.strip.picked.connect(self.pick)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 0)
        lay.setSpacing(2)
        lay.addWidget(self.stack)
        lay.addWidget(self.strip)
        centered(lay)
        self.pick(0)

    def pick(self, id_):
        if id_ in self.extras:
            self.stack.setCurrentWidget(self.extras[id_])
        else:
            self.cur = id_
            self.stack.setCurrentWidget(self.big)
            self.refresh_slider()
        self.strip.select(id_)

    def refresh_slider(self):
        s = self.items[self.cur]
        v = self.win.get_value(s[1], s[4])
        self.big.setEnabled(v is not None)
        self.big.bind(s, s[4] if v is None else v)

    def refresh_chips(self):
        for i, s in enumerate(self.items):
            v = self.win.get_value(s[1], s[4])
            self.strip.set_text(i, f'{s[0]}\n{self.win.display_value(s[1], v, s)}', v is not None and abs(v - s[4]) > 1e-9)

    def refresh(self):
        self.refresh_chips()
        self.refresh_slider()
        for w in self.extras.values():
            if hasattr(w, 'refresh'):
                w.refresh()


class CurvePanel(QWidget):
    def __init__(self, curve):
        super().__init__()
        curve.setFixedHeight(150)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.addWidget(curve, 1)
        col = QVBoxLayout()
        grp = QButtonGroup(self)
        for t, ch in (('RGB', 'rgb'), ('Red', 'r'), ('Green', 'g'), ('Blue', 'b')):
            b = pill(t, lambda _=False, ch=ch: (setattr(curve, 'ch', ch), curve.update()), True)
            b.setChecked(ch == 'rgb')
            grp.addButton(b)
            col.addWidget(b)
        lay.addLayout(col)


class MixPanel(QWidget):
    MODES = {'hue': 'Hue', 'sat': 'Saturation', 'lum': 'Luminance'}
    COLORS = ['#e04040', '#e8903a', '#e8d33a', '#46b946', '#3ac9c9', '#4a7de8', '#8a5ae0', '#d84fb4']

    def __init__(self, win):
        super().__init__()
        self.win, self.mode, self.idx = win, 'hue', 0
        self.big = BigSlider(win)
        self.big.changed.connect(win.route_slider)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        mg, dg = QButtonGroup(self), QButtonGroup(self)
        for k, t in self.MODES.items():
            b = pill(t, lambda _=False, k=k: self._mode(k), True)
            b.setChecked(k == 'hue')
            mg.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        for i, c in enumerate(self.COLORS):
            d = QPushButton()
            d.setCheckable(True)
            d.setFixedSize(28, 28)
            d.setFocusPolicy(Qt.NoFocus)
            d.setCursor(Qt.PointingHandCursor)
            d.setStyleSheet(f'QPushButton{{background:{c};border-radius:14px;border:2px solid rgba(255,255,255,0.18);}}'
                            f'QPushButton:hover{{border:2px solid rgba(255,255,255,0.6);}}'
                            f'QPushButton:checked{{border:3px solid white;}}')
            d.setChecked(i == 0)
            d.clicked.connect(lambda _=False, i=i: self._color(i))
            dg.addButton(d)
            row.addWidget(d)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.big)
        lay.addLayout(row)

    def _mode(self, k):
        self.mode = k
        self.refresh()

    def _color(self, i):
        self.idx = i
        self.refresh()

    def refresh(self):
        s = (f'{self.MODES[self.mode]} \u00b7 {E.BANDS[self.idx].capitalize()}', ('hsl', self.mode, self.idx), -100, 100, 0, 1, 0)
        self.big.bind(s, self.win.S['hsl'][self.mode][self.idx])


class CropPanel(QWidget):
    ASPECTS = ['Free', 'Original', '1:1', '4:5', '5:4', '3:2', '2:3', '4:3', '3:4', '16:9', '9:16']
    SPEC = ('Straighten', ('angle',), -15, 15, 0, 0.1, 1)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.big = BigSlider(win)
        self.big.changed.connect(win.route_slider)
        self.strip = ChipStrip(96)
        self.strip.set_items([(a, a) for a in self.ASPECTS])
        self.strip.select('Free')
        self.strip.picked.connect(win.set_aspect)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        row.addWidget(pill('Flip H', lambda: win.flip(0)))
        row.addWidget(pill('Flip V', lambda: win.flip(1)))
        row.addWidget(pill('Reset', win.reset_crop))
        row.addStretch(1)
        row.addWidget(pill('Cancel', lambda: win.end_crop(False)))
        row.addWidget(pill('Done', lambda: win.end_crop(True), name='primary'))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 0)
        lay.setSpacing(2)
        lay.addWidget(self.big)
        lay.addWidget(self.strip)
        lay.addLayout(row)
        centered(lay)
        self.refresh()

    def refresh(self):
        self.big.bind(self.SPEC, self.win.S['angle'])


class PresetPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.strip = ChipStrip(132, 'card')
        self.strip.picked.connect(win.apply_preset)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        for t, fn in (('Save current\u2026', win.save_preset), ('Import\u2026', win.import_preset),
                      ('Export\u2026', win.export_preset), ('Delete', win.delete_preset)):
            row.addWidget(pill(t, fn))
        row.addStretch(1)
        hint = QLabel('Lightroom .xmp / .lrtemplate / .dng presets work')
        hint.setStyleSheet('color:#7f93b3;font-size:11px;')
        row.addWidget(hint)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 0)
        lay.addWidget(self.strip)
        lay.addLayout(row)
        centered(lay)

    def refresh(self, thumbs=False):
        w = self.win
        self.strip.set_items([(i, p['name'], w.preset_icon(p) if thumbs else None) for i, p in enumerate(w.presets)])
        if 0 <= w.cur_preset < len(w.presets):
            self.strip.select(w.cur_preset)


class MaskPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        self.tool_btns = {}
        for t, txt in (('linear', 'Linear'), ('radial', 'Radial'), ('brush', 'Brush')):
            b = pill(txt, lambda _=False, t=t: win.toggle_mask_tool(t), True, icon=t)
            self.tool_btns[t] = b
            row.addWidget(b)
        row.addStretch(1)
        self.inv = pill('Invert', win.mask_invert, True)
        self.ov = pill('Overlay', win.toggle_overlay, True)
        self.ov.setChecked(True)
        self.dele = pill('Delete', win.delete_mask)
        for b in (self.inv, self.ov, self.dele):
            row.addWidget(b)
        self.hint = QLabel('Pick Linear, Radial or Brush, then drag on the photo.  Hover a mask + Delete key removes it.')
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet('color:#7f93b3;')
        self.masks = ChipStrip(44, 'pill')
        self.masks.picked.connect(win.select_mask)
        self.masks.contextRequested.connect(win.mask_menu)
        self.adj = SliderPanel(win, MASK_ITEMS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 0)
        lay.setSpacing(2)
        lay.addLayout(row)
        lay.addWidget(self.hint)
        lay.addWidget(self.masks)
        lay.addWidget(self.adj)

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
        self.adj.refresh()
        self.sync_tools()


# ============================================================================ photo view with smooth zoom
class ImageView(QGraphicsView):
    """Photo canvas. Trackpad: pinch = zoom, two-finger scroll = pan. Mouse wheel / Ctrl-wheel = eased zoom."""
    MAX_SCALE = 8.0

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.sc = QGraphicsScene(self)
        self.setScene(self.sc)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.sc.addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet('background:transparent;border:0;')
        self.viewport().setAutoFillBackground(False)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.fit, self._pan, self._last = True, False, None
        self._ztarget, self._zanchor, self.fade_next = None, QPointF(), False
        self._ztimer = QTimer(self)
        self._ztimer.setInterval(15)
        self._ztimer.timeout.connect(self._zstep)
        self.fadeanim = QVariantAnimation(self)
        self.fadeanim.setDuration(420)
        self.fadeanim.setEasingCurve(QEasingCurve.OutCubic)
        self.fadeanim.valueChanged.connect(lambda v: self.item.setOpacity(float(v)))
        self.hint = self.sc.addText('Open a photo  (Cmd/Ctrl+O)  or drop one here')
        self.hint.setDefaultTextColor(QColor('#7f93b3'))
        self.hint.setPos(210, 230)
        self.sc.setSceneRect(0, 0, 800, 500)

    # -- image
    def set_image(self, pm, fw, fh):
        if self.hint is not None:
            self.sc.removeItem(self.hint)
            self.hint = None
        changed = self.sc.sceneRect().size() != QSizeF_(fw, fh)
        self.item.setPixmap(pm)
        self.item.setScale(fw / pm.width())
        self.sc.setSceneRect(0, 0, fw, fh)
        if changed and self.fit:
            self.fit_view()
        if self.fade_next:
            self.fade_next = False
            self.fadeanim.stop()
            self.fadeanim.setStartValue(0.0)
            self.fadeanim.setEndValue(1.0)
            self.fadeanim.start()

    def drawBackground(self, p, rect):
        if self.hint is not None:
            return
        r, u = self.sc.sceneRect(), 1.0 / max(self.transform().m11(), 1e-6)
        p.setPen(Qt.NoPen)
        for i in range(14):
            p.setBrush(QColor(0, 0, 0, int(15 * (1 - i / 14) ** 2) + 1))
            d = (3 + i * 2.2) * u
            p.drawRoundedRect(r.adjusted(-d, -d + 6 * u, d, d + 6 * u), (6 + i) * u, (6 + i) * u)

    def drawForeground(self, p, rect):
        self.win.draw_overlay(p, self.transform().m11())

    # -- zoom
    def fit_scale(self):
        r, vp = self.sc.sceneRect().adjusted(-24, -24, 24, 24), self.viewport().size()
        return max(1e-4, min(vp.width() / r.width(), vp.height() / r.height()))

    def fit_view(self):
        self._ztarget = None
        self.fit = True
        self.resetTransform()
        self.fitInView(self.sc.sceneRect().adjusted(-24, -24, 24, 24), Qt.KeepAspectRatio)

    def zoom_at(self, factor, vp):
        cur, fs = self.transform().m11(), self.fit_scale()
        s = min(max(cur * factor, fs), self.MAX_SCALE)
        if s <= fs * 1.002:
            self.fit_view()
            return
        self.fit = False
        old = self.mapToScene(vp.toPoint())
        self.setTransform(QTransform.fromScale(s, s))
        d = self.mapToScene(vp.toPoint()) - old
        self.translate(d.x(), d.y())
        self.viewport().update()

    def zoom_smooth(self, factor, vp, absolute=None):
        cur = self.transform().m11()
        base = self._ztarget or cur
        tgt = absolute if absolute else base * factor
        self._ztarget = min(max(tgt, self.fit_scale()), self.MAX_SCALE)
        self._zanchor = QPointF(vp)
        if not self._ztimer.isActive():
            self._ztimer.start()

    def _zstep(self):
        if self._ztarget is None:
            self._ztimer.stop()
            return
        cur = self.transform().m11()
        ratio = self._ztarget / cur
        if abs(math.log(ratio)) < 0.003:
            self.zoom_at(ratio, self._zanchor)
            self._ztarget = None
            self._ztimer.stop()
            return
        self.zoom_at(ratio ** 0.22, self._zanchor)

    def toggle_zoom(self, vp):
        if self.fit:
            self.zoom_smooth(1, vp, absolute=1.0 / self.devicePixelRatioF())
        else:
            self.zoom_smooth(1, vp, absolute=self.fit_scale())

    def zoom_100(self):
        self.zoom_smooth(1, QPointF(self.viewport().rect().center()), absolute=1.0 / self.devicePixelRatioF())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            self.fit_view()

    def wheelEvent(self, e):
        ctrl = bool(e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
        pd, ad = e.pixelDelta(), e.angleDelta()
        # macOS reports pixel deltas for *every* wheel, mice included, so pixelDelta alone can't tell a trackpad
        # from a mouse. A real trackpad / Magic Mouse gesture carries a scroll phase; a plain wheel does not.
        gesture = e.phase() != Qt.ScrollPhase.NoScrollPhase
        if gesture and not pd.isNull():  # trackpad two-finger scroll
            if ctrl:
                self.zoom_at(math.exp(max(-40, min(40, pd.y())) * 0.0035), e.position())
            elif not self.fit:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - pd.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pd.y())
            e.accept()
            return
        dy = ad.y() or pd.y()  # mouse wheel: gentle, eased zoom toward the cursor
        if not dy:
            return
        dy = max(-360, min(360, dy))  # fast spins / OS acceleration can't make it jump
        self.zoom_smooth(math.exp(dy / 120.0 * 0.07), e.position())
        e.accept()

    def viewportEvent(self, ev):
        if ev.type() == QEvent.NativeGesture:
            try:
                gt = ev.gestureType()
                if gt == Qt.NativeGestureType.ZoomNativeGesture:
                    self._ztarget = None
                    self.zoom_at(max(0.9, min(1.1, 1.0 + ev.value() * 0.85)), ev.position())
                    return True
                if gt == Qt.NativeGestureType.SmartZoomNativeGesture:
                    self.toggle_zoom(ev.position())
                    return True
            except Exception:
                pass
        return super().viewportEvent(ev)

    # -- mouse
    def _start_pan(self, e):
        self._pan, self._last = True, e.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseDoubleClickEvent(self, e):
        if self.win.tool in ('hand', 'edit') and not self.win.crop_mode and self.win.photo:
            self.toggle_zoom(e.position())

    def mousePressEvent(self, e):
        w = self.win
        if e.button() == Qt.MiddleButton:
            self._start_pan(e)
            return
        if e.button() != Qt.LeftButton or not w.photo:
            return
        sp, sc = self.mapToScene(e.position().toPoint()), self.transform().m11()
        if w.tool in ('hand', 'edit') and not w.crop_mode:
            if w.tool == 'edit' and w.tool_press(sp.x(), sp.y(), sc):
                return
            self._start_pan(e)
            return
        w.tool_press(sp.x(), sp.y(), sc)

    def mouseMoveEvent(self, e):
        if self._pan:
            d = e.position() - self._last
            self._last = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        sp = self.mapToScene(e.position().toPoint())
        self.win.cursor_scene = (sp.x(), sp.y())
        self.win.tool_move(sp.x(), sp.y(), self.transform().m11())
        if self.win.tool == 'brush':
            self.viewport().update()

    def leaveEvent(self, e):
        self.win.cursor_scene = None
        self.viewport().update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan:
            self._pan = False
            self.win.update_cursor()
            return
        self.win.tool_release()


def QSizeF_(w, h):
    from PySide6.QtCore import QSizeF
    return QSizeF(w, h)