"""
PyLight - a local, non-destructive photo editor inspired by Lightroom's Develop module.
Run:  python pylight.py [optional_image_path]
"""
import copy
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import (Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QPointF, QRectF, QSizeF)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QKeySequence, QBrush)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
                               QDoubleSpinBox, QAbstractSpinBox, QToolButton, QScrollArea, QGraphicsView,
                               QGraphicsScene, QGraphicsPixmapItem, QFrame, QComboBox, QPushButton, QListWidget,
                               QListWidgetItem, QCheckBox, QTabWidget, QFileDialog, QMessageBox, QDialog,
                               QDialogButtonBox, QLineEdit, QSpinBox, QToolBar, QProgressDialog, QFormLayout)

import engine as E
from PySide6.QtCore import QSize, QEasingCurve, QPropertyAnimation, QPoint
from PySide6.QtGui import QIcon, QCursor
from PySide6.QtWidgets import (QButtonGroup, QMenu, QAbstractButton, QSizePolicy, QStackedWidget, QInputDialog, QToolButton,
                               QComboBox)
from ui_kit import ImageView, pill, qicon, glass_bg, ACCENT, LIGHT, COLOR, GRADING, EFFECTS, DETAIL
from ui_shell import (Canvas, Surface, TabBar, ExportBar, TopPill, Histogram2, TopRight, Toolbar, PlusButton, Collapse,
                      TrafficLights, EditArea, SliderList, CurveBlock, MixPanel, ColorTabs, CropPanel, MaskPanel, PresetPanel,
                      HistoryPanel, Toast, PngPopup, BLUR, PURPLE, PANEL, TXT, TXT_DIM)
import png_convert

MASK_TOOLS = ('linear', 'radial', 'brush', 'edit')

PRESET_DIR = Path.home() / '.pylight' / 'presets'
SIDECAR = '.pylight.json'
BUILTIN_FOLDER = 'Built-in'
ROOT_FOLDER = 'My Presets'      # presets saved directly in PRESET_DIR; every other user folder is a sub-directory


def _safe(s):
    return ''.join(c for c in s if c.isalnum() or c in ' _-').strip()


def folder_dir(folder):
    return PRESET_DIR if folder == ROOT_FOLDER else PRESET_DIR / _safe(folder)


def unique_path(d, stem):
    p = d / (stem + '.json')
    n = 2
    while p.exists():
        p = d / f'{stem} {n}.json'
        n += 1
    return p

STYLE = """
QWidget { background:transparent; color:#d9d7e0; font-size:12px; }
QLabel { background:transparent; }
QMainWindow { background:transparent; }
QDialog, QMessageBox { background:#292733; }
QMenu { background:#292733; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:6px; }
QMenu::item { padding:7px 26px; border-radius:7px; }
QMenu::item:selected { background:#746be0; color:white; }
QMenu::separator { height:1px; background:rgba(255,255,255,0.10); margin:5px 8px; }
QPushButton#pill { background:#33313d; border:1px solid rgba(255,255,255,0.07); border-radius:13px; padding:5px 14px; color:#d9d7e0; }
QPushButton#pill:hover { background:#3d3a49; }
QPushButton#pill:checked { background:rgba(116,107,224,0.35); border:1px solid #8b83f0; color:white; }
QPushButton#pill:disabled { color:#5a5766; background:#2d2b37; border:1px solid rgba(255,255,255,0.04); }
QPushButton#primary { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #8079ea,stop:1 #746be0); border:1px solid rgba(255,255,255,0.22); border-radius:13px; padding:6px 20px; color:white; font-weight:700; }
QPushButton#primary:hover { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #918bf0,stop:1 #8179ea); }
QScrollArea { background:transparent; border:0; }
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background:#33313d; border:1px solid rgba(255,255,255,0.10); border-radius:7px; padding:4px 8px; }
QComboBox QAbstractItemView { background:#292733; selection-background-color:#746be0; border:1px solid rgba(255,255,255,0.12); }
QDialog QPushButton { background:#33313d; border:1px solid rgba(255,255,255,0.10); border-radius:8px; padding:6px 16px; }
QDialog QPushButton:hover { background:#3d3a49; }
QCheckBox { spacing:8px; }
QToolTip { background:#18141e; color:#d9d7e0; border:1px solid rgba(255,255,255,0.16); padding:4px 8px; }
"""


class Histogram(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(90)
        self.h = None

    def set_image(self, u8):
        small = cv2.resize(u8, (min(u8.shape[1], 600), min(u8.shape[0], 400)), interpolation=cv2.INTER_AREA)
        self.h = [cv2.calcHist([small], [c], None, [256], [0, 256]).ravel() for c in range(3)]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        glass_bg(p, self.rect(), 10)
        if self.h is None:
            return
        mx = max(np.percentile(h[2:254], 99.5) if h[2:254].size else 1 for h in self.h) or 1
        W, H = self.width(), self.height()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for h, col in zip(self.h, ((200, 40, 40), (40, 180, 40), (50, 80, 220))):
            path = QPainterPath(QPointF(0, H))
            for i in range(256):
                path.lineTo(i / 255 * W, H - min(1, h[i] / mx) * (H - 4))
            path.lineTo(W, H)
            p.fillPath(path, QColor(*col, 140))


class CurveWidget(QWidget):
    changed = Signal(str, list, bool)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(150)
        self.ch = 'rgb'
        self.curves = {c: copy.deepcopy(E.IDENT) for c in ('rgb', 'r', 'g', 'b')}
        self.sel = None

    def set_curves(self, c):
        self.curves = copy.deepcopy(c)
        self.update()

    def _px(self, pt):
        return QPointF(10 + pt[0] * (self.width() - 20), self.height() - 10 - pt[1] * (self.height() - 20))

    def _pt(self, pos):
        return [min(1, max(0, (pos.x() - 10) / (self.width() - 20))),
                min(1, max(0, (self.height() - 10 - pos.y()) / (self.height() - 20)))]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glass_bg(p, self.rect(), 10)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        for i in range(5):
            a, b = self._px([i / 4, 0]), self._px([i / 4, 1])
            p.drawLine(a, b)
            p.drawLine(self._px([0, i / 4]), self._px([1, i / 4]))
        pts = self.curves[self.ch]
        lut = E.curve_lut(pts, 256)
        col = {'rgb': '#dddddd', 'r': '#e04040', 'g': '#40c040', 'b': '#5080ff'}[self.ch]
        p.setPen(QPen(QColor(col), 2))
        path = QPainterPath(self._px([0, lut[0]]))
        for i in range(1, 256):
            path.lineTo(self._px([i / 255, lut[i]]))
        p.drawPath(path)
        p.setBrush(QColor(col))
        for pt in pts:
            p.drawEllipse(self._px(pt), 4, 4)

    def _near(self, pos):
        pts = self.curves[self.ch]
        for i, pt in enumerate(pts):
            q = self._px(pt)
            if (q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2 < 100:
                return i
        return None

    def mousePressEvent(self, e):
        pts = self.curves[self.ch]
        i = self._near(e.position())
        if e.button() == Qt.RightButton:
            if i is not None and 0 < i < len(pts) - 1:
                pts.pop(i)
                self.update()
                self.changed.emit(self.ch, copy.deepcopy(pts), True)
            return
        if i is None:
            pts.append(self._pt(e.position()))
            pts.sort(key=lambda q: q[0])
            i = self._near(e.position())
        self.sel = i

    def mouseMoveEvent(self, e):
        pts = self.curves[self.ch]
        if self.sel is None or self.sel >= len(pts):
            return
        x, y = self._pt(e.position())
        i = self.sel
        if 0 < i < len(pts) - 1:
            x = min(max(x, pts[i - 1][0] + 0.01), pts[i + 1][0] - 0.01)
        else:
            x = pts[i][0]
        pts[i] = [x, y]
        self.update()
        self.changed.emit(self.ch, copy.deepcopy(pts), False)

    def mouseReleaseEvent(self, e):
        if self.sel is not None:
            self.sel = None
            self.changed.emit(self.ch, copy.deepcopy(self.curves[self.ch]), True)

    def mouseDoubleClickEvent(self, e):
        self.curves[self.ch] = copy.deepcopy(E.IDENT)
        self.update()
        self.changed.emit(self.ch, copy.deepcopy(E.IDENT), True)


# ============================================================================ background jobs
class Signals(QObject):
    rendered = Signal(object)
    exported = Signal(object)


class RenderJob(QRunnable):
    def __init__(self, photo, S, edge, crop, sig):
        super().__init__()
        self.photo, self.S, self.edge, self.crop, self.sig = photo, S, edge, crop, sig

    def run(self):
        try:
            x = self.photo.render(self.S, self.edge, self.crop)
            self.sig.rendered.emit((x * 255 + 0.5).astype(np.uint8))
        except Exception:
            traceback.print_exc()
            self.sig.rendered.emit(None)


class ExportJob(QRunnable):
    def __init__(self, photo, S, path, opts, sig):
        super().__init__()
        self.photo, self.S, self.path, self.opts, self.sig = photo, S, path, opts, sig

    def run(self):
        try:
            sz = E.export_image(self.photo, self.S, self.path, **self.opts)
            self.sig.exported.emit(('ok', sz))
        except Exception as ex:
            traceback.print_exc()
            self.sig.exported.emit(('err', str(ex)))


# ============================================================================ dialogs
class ExportDialog(QDialog):
    def __init__(self, parent, can_dng, size):
        super().__init__(parent)
        self.setWindowTitle('Export')
        self.size0 = size
        f = QFormLayout(self)
        self.fmt = QComboBox()
        self.fmt.addItems(['JPEG', 'PNG', 'TIFF', 'DNG (original + edit settings)'])
        if not can_dng:
            self.fmt.model().item(3).setEnabled(False)
        self.q = QSpinBox()
        self.q.setRange(1, 100)
        self.q.setValue(100)
        self.bits = QComboBox()
        self.bits.addItems(['8-bit', '16-bit'])
        self.rs = QComboBox()
        self.rs.addItems(['Original size (no resize)', 'Long edge (px)'])
        self.edge = QSpinBox()
        self.edge.setRange(16, 60000)
        self.edge.setValue(max(size))
        self.info = QLabel()
        f.addRow('Format', self.fmt)
        f.addRow('JPEG quality', self.q)
        f.addRow('Bit depth (PNG/TIFF)', self.bits)
        f.addRow('Size', self.rs)
        f.addRow('Long edge', self.edge)
        f.addRow(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        for s in (self.fmt.currentIndexChanged, self.rs.currentIndexChanged, self.edge.valueChanged):
            s.connect(self._upd)
        self._upd()

    def _upd(self):
        i = self.fmt.currentIndex()
        self.q.setEnabled(i == 0)
        self.bits.setEnabled(i in (1, 2))
        dng = i == 3
        self.rs.setEnabled(not dng)
        self.edge.setEnabled(self.rs.currentIndex() == 1 and not dng)
        w, h = self.size0
        if self.rs.currentIndex() == 1 and not dng:
            s = self.edge.value() / max(w, h)
            w, h = max(1, round(w * s)), max(1, round(h * s))
        self.info.setText(f'Output: {w} x {h} px' + ('  (original raw data kept, edits stored as settings)' if dng else ''))

    def values(self):
        fmt = ['JPEG', 'PNG', 'TIFF', 'DNG'][self.fmt.currentIndex()]
        return dict(fmt=fmt, quality=self.q.value(), bits=8 if self.bits.currentIndex() == 0 else 16,
                    long_edge=self.edge.value() if self.rs.currentIndex() == 1 else 0)


class PresetDialog(QDialog):
    def __init__(self, parent, folders=(), current=ROOT_FOLDER):
        super().__init__(parent)
        self.setWindowTitle('Save preset')
        lay = QVBoxLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Preset name')
        lay.addWidget(self.name)
        lay.addWidget(QLabel('Folder (type a new name to create one)'))
        self.folder_box = QComboBox()
        self.folder_box.setEditable(True)
        self.folder_box.addItems(list(folders))
        self.folder_box.setCurrentText(current)
        lay.addWidget(self.folder_box)
        self.boxes = {}
        for g in E.GROUPS:
            cb = QCheckBox(g)
            cb.setChecked(g not in ('Masks', 'Geometry'))
            self.boxes[g] = cb
            lay.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def groups(self):
        return [g for g, c in self.boxes.items() if c.isChecked()]

    def folder(self):
        return self.folder_box.currentText().strip() or ROOT_FOLDER


def builtin_presets():
    def mk(**kw):
        s = {}
        for k, v in kw.items():
            s[k] = v
        return s

    bw = {'saturation': -100, 'contrast': 25, 'clarity': 15}
    warm = {'temp': 18, 'tint': 4, 'contrast': 10, 'vibrance': 15, 'vignette': -15,
            'grade': {'sh': [220, 15], 'mid': [0, 0], 'hi': [40, 20], 'balance': 0}}
    teal = {'contrast': 15, 'saturation': 5,
            'grade': {'sh': [200, 35], 'mid': [0, 0], 'hi': [35, 30], 'balance': 0}}
    matte = {'curve': {'rgb': [[0, 0.07], [0.5, 0.5], [1, 0.95]], 'r': E.IDENT, 'g': E.IDENT, 'b': E.IDENT},
             'saturation': -10, 'contrast': -10}
    punch = {'contrast': 30, 'clarity': 25, 'vibrance': 25, 'dehaze': 10, 'sharpen': 30}
    return {'Black & White': bw, 'Warm Film': warm, 'Teal & Orange': teal, 'Matte Fade': matte,
            'Punchy': punch}


# ============================================================================ main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PyLight')
        self.native = os.environ.get('PYLIGHT_NATIVE_FRAME') == '1'   # set to 1 for the normal OS title bar
        if not self.native:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1360, 900)
        self.setMinimumSize(1180, 760)
        self.setAcceptDrops(True)
        self.photo, self.S = None, E.default_settings()
        self.undo, self.redo = [], []
        self.tool, self.sel = 'hand', -1
        self.crop_mode, self.crop_rect, self.aspect = False, [0, 0, 1, 1], None
        self.before, self.fw, self.fh = False, 1, 1
        self.drag, self.clip, self.overlay = None, None, None
        self.show_overlay = True
        self.brush = {'size': 0.05, 'feather': 0.5, 'flow': 1.0, 'erase': False}
        self.cur_cat, self.panels, self.cat_pages, self.cat_btns = 'Light', [], {}, {}
        self.presets, self.cur_preset, self._thumbs = [], -1, {}
        self.folders = ['My Presets']
        self.cursor_scene, self.panels_open, self._full_h = None, True, 300
        self.folder, self.folder_idx = [], -1
        self.hist_names, self.redo_names, self.size_mode, self.path = [], [], 0, ''
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)
        self.sig = Signals()
        self.sig.rendered.connect(self._on_rendered)
        self.sig.exported.connect(self._on_exported)
        self._busy, self._pending, self.quality_edge = False, None, 3000
        self.qtimer = QTimer(singleShot=True, interval=350)
        self.qtimer.timeout.connect(lambda: self.request(True))
        self.view = ImageView(self)
        self._build_ui()
        self._build_actions()
        self.statusBar().showMessage('Open a photo (Ctrl+O) or drop one onto the window.')

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self):
        cv = self.canvas = Canvas(rounded=not self.native)
        cv.visL = cv.visB = 0.0                       # panels slide in after the window appears
        self.tabbar = cv.add('tabbar', TabBar())
        self.exportbar = cv.add('exportbar', ExportBar(self))
        self.edit = cv.add('editarea', EditArea())
        self.collapse = cv.add('collapse', Collapse())
        self.collapse.flip = 1.0
        self.collapse.clicked.connect(lambda: self.set_left())
        self.lights = cv.add('lights', TrafficLights())
        self.lights.closeReq.connect(self.close)
        self.lights.minReq.connect(self.showMinimized)
        self.lights.zoomReq.connect(lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        self.lights.setVisible(not self.native)
        self.namepill = cv.add('namepill', TopPill('No image'))
        self.namepill.clicked.connect(self.open_dialog)
        self.namepill.setToolTip('Open a photo')
        self.hist = cv.add('hist', Histogram2())
        self.sizepill = cv.add('sizepill', TopPill('size'))
        self.sizepill.clicked.connect(self.cycle_size)
        self.sizepill.setToolTip('Click to switch: output / original / file size')
        self.topright = cv.add('topright', TopRight(self))
        self.topright.settings.clicked.connect(lambda: self.settings_menu.exec(
            self.topright.settings.mapToGlobal(QPoint(-90, self.topright.settings.height() + 4))))
        self.toolbar = cv.add('toolbar', Toolbar(self))
        self.toolbar.crop.clicked.connect(lambda: self.tool_clicked('Crop'))
        self.toolbar.mask.clicked.connect(lambda: self.tool_clicked('Masks'))
        self.plus = cv.add('plus', PlusButton())
        self.plus.clicked.connect(self.open_dialog)
        self.hide_btn = cv.add('hide', Collapse())
        self.hide_btn.flip = 1.0
        self.hide_btn.clicked.connect(lambda: self.set_bottom())
        cv.add('view', self.view)
        self.toast = cv.add('toast', Toast())

        # editing pages
        self.curve = CurveWidget()
        self.curve.setFixedHeight(150)
        self.curve.changed.connect(self.on_curve)
        self.mix = MixPanel(self)
        light = SliderList(self, [('Basic', LIGHT), ('Tone curve', CurveBlock(self.curve))])
        color = SliderList(self, [('White balance', COLOR[:2]), ('Presence', COLOR[2:]),
                                  (None, ColorTabs(self, self.mix, GRADING))])
        blur = SliderList(self, [('Blur', BLUR)])
        effects, detail = SliderList(self, [('Effects', EFFECTS)]), SliderList(self, [('Detail', DETAIL)])
        self.panels = [light, color, blur, effects, detail]
        self.crop_panel, self.mask_panel = CropPanel(self), MaskPanel(self)
        for name, page in (('Light', light), ('Color', color), ('Blur', blur), ('Effects', effects),
                           ('Detail', detail), ('Crop', self.crop_panel), ('Masks', self.mask_panel)):
            self.edit.stack.addWidget(page)
            self.cat_pages[name] = page
        self.tabbar.changed.connect(self.go_category)

        # drawers
        self.preset_panel = cv.add('preset', PresetPanel(self))
        self.history_panel = cv.add('history', HistoryPanel(self))
        # hover the + -> a PNG converter pops up above it (added last so canvas layout never sees it half-built)
        self.png_pop = cv.add('png', PngPopup())
        self.plus.hoverChanged.connect(lambda on: self.png_pop.pop(on and self.canvas.visB > 0.5))
        self.png_pop.clicked.connect(self.convert_dialog)
        self.png_pop.filesDropped.connect(self.convert_files)
        # side hide-arrows: Before/Settings cluster, preset drawer, history drawer (each hides on its own)
        self.rcollapse = cv.add('rcollapse', Collapse(rot=-90))
        self.rcollapse.clicked.connect(lambda: self.set_topright())
        self.rcollapse.setToolTip('Hide / show Before & Settings')
        self.pcollapse = cv.add('pcollapse', Collapse())
        self.pcollapse.clicked.connect(lambda: self.set_presets_drawer())
        self.pcollapse.setToolTip('Hide / show presets')
        self.hcollapse = cv.add('hcollapse', Collapse())
        self.hcollapse.clicked.connect(lambda: self.set_history_drawer())
        self.hcollapse.setToolTip('Hide / show history')
        self.settings_menu = self._build_menu()
        em = QMenu(self)
        for text, fn in (('Export\u2026', self.export), ('Copy settings', self.copy_settings),
                         ('Paste settings', self.paste_settings), ('Reset all edits', self.reset_all)):
            em.addAction(text).triggered.connect(fn)
        self.exportbar.more.clicked.connect(lambda: em.exec(self.exportbar.more.mapToGlobal(QPoint(0, 40))))
        self._em = em

        self.setCentralWidget(cv)
        self.statusBar().hide()
        self.statusBar().messageChanged.connect(lambda t: t and self.toast.say(t))
        self.refresh_presets()
        self.refresh_history()
        for b in self.findChildren(QAbstractButton):
            b.setFocusPolicy(Qt.NoFocus)
        self.go_category('Light')
        cv.relayout()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, '_intro', False):
            self._intro = True
            QTimer.singleShot(120, lambda: self.set_left(True))
            QTimer.singleShot(320, lambda: self.set_bottom(True))

    def set_left(self, on=None):
        self.collapse.set_open(self.canvas.toggle_left(on))

    def set_topright(self, on=None):
        self.rcollapse.set_open(self.canvas.toggle_right(on))

    def set_presets_drawer(self, on=None):
        self.pcollapse.set_open(self.canvas.toggle_presets(on))

    def set_history_drawer(self, on=None):
        self.hcollapse.set_open(self.canvas.toggle_history(on))

    def set_bottom(self, on=None):
        self.hide_btn.set_open(self.canvas.toggle_bottom(on))

    def _build_menu(self):
        m = QMenu(self)
        for text, fn, sc in (('Open photo\u2026', self.open_dialog, None), ('Export\u2026', self.export, None)):
            m.addAction(text).triggered.connect(fn)
        m.addSeparator()
        qm = m.addMenu('Preview quality')
        qg = QActionGroup(self)
        for i, t in enumerate(('Draft (1600 px)', 'Standard (3000 px)', 'Full resolution (slow)')):
            a = qg.addAction(t)
            a.setCheckable(True)
            a.setChecked(i == 1)
            a.triggered.connect(lambda _=False, i=i: self.set_quality(i))
            qm.addAction(a)
        m.addSeparator()
        for text, fn, sc in (('Undo', self.do_undo, None), ('Redo', self.do_redo, None),
                             ('Copy settings', self.copy_settings, 'Ctrl+Shift+C'),
                             ('Paste settings', self.paste_settings, 'Ctrl+Shift+V'),
                             ('Reset all edits', self.reset_all, None),
                             ('Import presets\u2026', self.import_preset, None),
                             ('Convert images to PNG\u2026', self.convert_dialog, None),
                             ('Hide / show panels', self.toggle_panels, 'Tab'),
                             ('Fit to screen', lambda: self.view.fit_view(), 'Ctrl+0'),
                             ('Zoom 100%', lambda: self.view.zoom_100(), 'Ctrl+1')):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if sc:
                a.setShortcut(QKeySequence(sc))
            self.addAction(a)
            m.addAction(a)
        a = QAction('Animated background', self)
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(self.canvas.set_drift)
        m.addSeparator()
        m.addAction(a)
        return m

    def cycle_size(self):
        self.size_mode = (self.size_mode + 1) % 3
        self.update_info()

    def update_info(self):
        if not self.photo:
            self.namepill.set_text('No image')
            self.sizepill.set_text('size')
            return
        self.namepill.set_text(os.path.basename(self.path))
        if self.size_mode == 0:
            w, h = self.photo.output_size(self.S)
            t = f'{w} \u00d7 {h} px'
        elif self.size_mode == 1:
            t = f'original {self.photo.w} \u00d7 {self.photo.h}'
        else:
            try:
                t = f'{os.path.getsize(self.path) / 1048576:.1f} MB'
            except OSError:
                t = 'size'
        self.sizepill.set_text(t)

    def _build_actions(self):
        def act(fn, *keys):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)

        act(self.open_dialog, 'Ctrl+O')
        act(self.export, 'Ctrl+E')
        act(self.do_undo, 'Ctrl+Z')
        act(self.do_redo, 'Ctrl+Y', 'Ctrl+Shift+Z')
        act(self.toggle_before, '\\')
        act(lambda: self.go_category('Crop'), 'R')
        act(lambda: self.pick_mask_tool('linear'), 'L')
        act(lambda: self.pick_mask_tool('radial'), 'O')
        act(lambda: self.pick_mask_tool('brush'), 'B')
        act(lambda: self.set_tool('hand'), 'H')
        act(lambda: self.set_erase(not self.brush['erase']), 'E')
        act(self.delete_under_cursor, 'Delete', 'Backspace')
        act(lambda: self.crop_mode and self.end_crop(True), 'Return')
        act(lambda: self.crop_mode and self.end_crop(False), 'Escape')
        act(lambda: self.step_folder(1), 'Right')
        act(lambda: self.step_folder(-1), 'Left')

    # ------------------------------------------------------------------ category navigation
    def go_category(self, name):
        self.cur_cat = name
        if name not in ('Crop', 'Masks'):
            self.last_tab = name
        self.tabbar.select(name)
        self.toolbar.crop.setChecked(name == 'Crop')
        self.toolbar.mask.setChecked(name == 'Masks')
        self.edit.stack.setCurrentWidget(self.cat_pages[name])
        if self.canvas.visL < 0.5:
            self.set_left(True)
        m = self.cur_mask()
        if name == 'Crop':
            self.set_tool('crop')
        elif name == 'Masks':
            if self.crop_mode or (m and self.tool == 'hand'):
                self.set_tool('edit' if m else 'hand')
        elif self.crop_mode or self.tool in MASK_TOOLS:
            self.set_tool('hand')

    def tool_clicked(self, name):
        """Crop / Mask buttons: first click opens the tool, second click closes it again."""
        if self.cur_cat == name:
            if name == 'Crop':
                self.end_crop(True)
            self.go_category(getattr(self, 'last_tab', 'Light'))
        else:
            self.go_category(name)

    def pick_mask_tool(self, t):
        self.go_category('Masks')
        self.set_tool(t)

    def toggle_mask_tool(self, t):
        self.set_tool('edit' if self.tool == t else t)

    def sync_tool_ui(self):
        if hasattr(self, 'mask_panel'):
            self.mask_panel.sync_tools()

    def toggle_panels(self):
        on = not (self.canvas.visL > 0.5 or self.canvas.visB > 0.5)
        self.set_left(on)
        self.set_bottom(on)

    def delete_under_cursor(self):
        """Delete / Backspace removes the mask chip under the cursor (or the selected mask when over the photo)."""
        if self.cur_cat != 'Masks':
            return
        hid = self.mask_panel.masks.hover_id
        if hid is not None and 0 <= hid < len(self.S['masks']):
            self.sel = hid
            self.delete_mask()
        elif self.cur_mask() is not None and self.view.underMouse():
            self.delete_mask()

    def mask_menu(self, idx):
        m = QMenu(self)
        a = m.addAction('Delete mask')
        if m.exec(QCursor.pos()) is a and 0 <= idx < len(self.S['masks']):
            self.sel = idx
            self.delete_mask()

    # ------------------------------------------------------------------ value access used by the panels
    def get_value(self, path, default=0):
        if path[0] == 'brush':
            return self.brush[path[1]] * 100
        if path[0] == 'mask':
            m = self.cur_mask()
            if m is None:
                return None
            base = m
            for k in path[1:-1]:
                base = base[k]
            return base.get(path[-1], default)
        base = self.S
        for k in path[:-1]:
            base = base[k]
        return base[path[-1]]

    def display_value(self, path, v, s):
        """Text shown for a slider value. RAW photos show real Kelvin and tint numbers like Lightroom."""
        if v is None:
            return '\u2014'
        ph = self.photo
        if ph is not None and ph.kelvin:
            if path == ('temp',):
                return f'{E.kelvin_shift(ph.kelvin, v):.0f}K'
            if path == ('tint',):
                return f'{ph.tint0 + v:+.0f}'
        dec = s[6]
        if abs(v) < 1e-9:
            return f'{0:.{dec}f}'
        return f'{v:+.{dec}f}' if s[2] < 0 else f'{v:.{dec}f}'

    def route_slider(self, path, val, final):
        if path[0] == 'brush':
            self.on_brush_param(path, val, final)
        else:
            self.on_slider(path, val, final)
        self.refresh_chips()

    def refresh_chips(self):
        for p in self.panels + [self.mask_panel.adj]:
            p.refresh_chips()

    # ------------------------------------------------------------------ file handling
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        presets = [f for f in files if os.path.splitext(f)[1].lower() in ('.xmp', '.lrtemplate')]
        if presets:
            self.import_preset_files(presets)
            return
        for f in files:
            self.open_path(f)
            break

    def open_dialog(self):
        exts = ' '.join('*' + x for x in sorted(E.IMG_EXT))
        p, _ = QFileDialog.getOpenFileName(self, 'Open photo', '', f'Images ({exts});;All files (*)')
        if p:
            self.open_path(p)

    # ------------------------------------------------------------------ convert to PNG
    def convert_dialog(self):
        exts = ' '.join('*' + x for x in sorted(png_convert.ALL_EXT))
        paths, _ = QFileDialog.getOpenFileNames(self, 'Choose images to convert to PNG', '',
                                                f'Images ({exts});;All files (*)')
        self.convert_files(paths)

    def convert_files(self, paths):
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return

        def prog(i, n, name):
            self.toast.say(f'Converting to PNG  {i + 1}/{n}  -  {name}' if n > 1 else f'Converting {name} to PNG...')
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            done, notes = png_convert.convert_many(paths, prog)
        finally:
            QApplication.restoreOverrideCursor()
        if done:
            self.open_path(str(done[0]))  # straight into the editor so you can edit the PNG
            self.toast.say(f'Saved {done[0].name} in {done[0].parent.name}  -  opened for editing' if len(done) == 1
                           else f'Converted {len(done)} PNGs  -  editing {done[0].name}')
        if notes:
            QMessageBox.warning(self, 'Convert to PNG', "Couldn't convert:\n- " + '\n- '.join(notes))

    def open_path(self, path):
        if not os.path.isfile(path):
            return
        self.save_sidecar()
        self.toast.say('Loading... (RAW files can take a few seconds)')
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            photo = E.Photo(path)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, 'Cannot open', f'{path}\n\n{ex}')
            return
        QApplication.restoreOverrideCursor()
        self.photo, self.path = photo, path
        S = None
        sc = path + SIDECAR
        if os.path.exists(sc):
            try:
                S = E.normalize(json.load(open(sc))['settings'])
            except Exception:
                S = None
        if S is None and photo.ext == '.dng':
            S = E.read_embedded_settings(path)
        self.S = S or E.default_settings()
        self.undo, self.redo, self.sel, self.crop_mode = [copy.deepcopy(self.S)], [], -1, False
        self.hist_names, self.redo_names = ['Open'], []
        d = os.path.dirname(os.path.abspath(path))
        self.folder = sorted(os.path.join(d, f) for f in os.listdir(d) if os.path.splitext(f)[1].lower() in E.IMG_EXT)
        self.folder_idx = self.folder.index(os.path.abspath(path)) if os.path.abspath(path) in self.folder else -1
        self.setWindowTitle(f'PyLight - {os.path.basename(path)}')
        self.view.fade_next = True
        self.refresh_ui()
        self.refresh_history()
        self.update_info()
        self.preset_panel.refresh(True)
        self.go_category(self.cur_cat if self.cur_cat != 'Crop' else 'Light')
        self.view.fit = True
        self.request(True)

    def step_folder(self, d):
        if self.folder and self.folder_idx >= 0 and not self.focusWidget().__class__ in (QDoubleSpinBox, QSpinBox):
            i = self.folder_idx + d
            if 0 <= i < len(self.folder):
                self.open_path(self.folder[i])

    def save_sidecar(self):
        if self.photo:
            try:
                with open(self.path + SIDECAR, 'w') as f:
                    json.dump({'version': 1, 'settings': self.S}, f)
            except OSError:
                pass

    def closeEvent(self, e):
        self.save_sidecar()
        self.pool.waitForDone(3000)
        super().closeEvent(e)

    # ------------------------------------------------------------------ settings editing
    def resolve(self, path):
        if path[0] == 'mask':
            m = self.cur_mask()
            if m is None:
                return None, None
            base, rest = m, path[1:]
        else:
            base, rest = self.S, path
        for k in rest[:-1]:
            base = base[k]
        return base, rest[-1]

    def on_slider(self, path, val, final):
        if not self.photo:
            return
        base, key = self.resolve(path)
        if base is None:
            return
        if isinstance(key, int) or key in ('hue', 'sat', 'lum') or path[0] == 'grade':
            val = float(val)
        base[key] = val
        if path[0] == 'mask' and path[1] != 'adj':
            self.update_overlay()
        self.after_change(final, path[-1] if isinstance(path[-1], str) else 'Edit')

    def on_curve(self, ch, pts, final):
        self.S['curve'][ch] = pts
        self.after_change(final, 'Tone curve')

    # ---- brush eraser
    def erasing(self):
        """Erase mode is on (Erase button / E key) or Option/Alt is held for a quick erase."""
        return bool(self.brush['erase']) or bool(QApplication.keyboardModifiers() & Qt.AltModifier)

    def set_erase(self, on):
        self.brush['erase'] = bool(on)
        self.mask_panel.erase_btn.setChecked(bool(on))
        if on and self.tool != 'brush':
            m = self.cur_mask()
            if m and m['type'] == 'brush':
                self.set_tool('brush')
        self.toast.say('Eraser on - paint over the red to remove it' if on else 'Brush on')
        self.view.viewport().update()

    def clear_strokes(self):
        m = self.cur_mask()
        if m and m['type'] == 'brush' and m.get('strokes'):
            m['strokes'] = []
            self.commit('Clear brush strokes')
            self.update_overlay()
            self.request(True)

    def on_brush_param(self, path, val, final):
        self.brush[path[1]] = val / 100.0

    def after_change(self, final, name='Edit'):
        self.request(False)
        if final:
            self.commit(name)

    def commit(self, name='Edit'):
        snap = copy.deepcopy(self.S)
        if not self.undo or snap != self.undo[-1]:
            self.undo.append(snap)
            self.hist_names.append(str(name).capitalize())
            self.redo.clear()
            self.redo_names.clear()
            self.refresh_history()
            self.save_sidecar()

    def refresh_history(self):
        if hasattr(self, 'history_panel'):
            self.history_panel.refresh()

    def jump_history(self, row):
        cur = len(self.undo) - 1
        for _ in range(max(0, cur - row)):
            self.do_undo()
        for _ in range(max(0, row - cur)):
            self.do_redo()

    def do_undo(self):
        if len(self.undo) > 1:
            self.redo.append(self.undo.pop())
            self.redo_names.append(self.hist_names.pop())
            self.S = copy.deepcopy(self.undo[-1])
            self.refresh_ui()
            self.refresh_history()
            self.update_info()
            self.request(True)

    def do_redo(self):
        if self.redo:
            self.undo.append(self.redo.pop())
            self.hist_names.append(self.redo_names.pop() if self.redo_names else 'Redo')
            self.S = copy.deepcopy(self.undo[-1])
            self.refresh_ui()
            self.refresh_history()
            self.update_info()
            self.request(True)

    def refresh_ui(self):
        self.curve.set_curves(self.S['curve'])
        for p in self.panels:
            p.refresh()
        self.mix.refresh()
        self.crop_panel.refresh()
        self.refresh_masks_ui()

    def reset_all(self):
        if self.photo:
            self.S = E.default_settings()
            self.sel = -1
            self.commit('Reset all')
            self.refresh_ui()
            self.request(True)

    def copy_settings(self):
        self.clip = copy.deepcopy(self.S)
        self.statusBar().showMessage('Settings copied')

    def paste_settings(self):
        if self.clip and self.photo:
            keep = {k: self.S[k] for k in ('crop', 'angle', 'flip')}
            self.S = copy.deepcopy(self.clip)
            self.S.update(copy.deepcopy(keep))
            self.commit('Paste settings')
            self.refresh_ui()
            self.request(True)

    # ------------------------------------------------------------------ rendering
    def set_quality(self, i):
        self.quality_edge = (1600, 3000, 0)[i]
        self.request(True)

    def request(self, quality):
        if not self.photo:
            return
        self._pending = quality
        if not quality:
            self.qtimer.start()
        if not self._busy:
            self._launch()

    def _launch(self):
        q, self._pending, self._busy = self._pending, None, True
        S = E.default_settings() if self.before else copy.deepcopy(self.S)
        if q:
            edge = self.quality_edge or None
        elif self.drag is not None and self.drag[0] in ('new', 'handle', 'brush'):
            edge = 720  # light preview while dragging a mask so it stays fluid
        else:
            edge = min(1200, self.quality_edge or 1200)
        crop = not self.crop_mode
        self._frame_crop = crop
        self._frame_S = S
        self.pool.start(RenderJob(self.photo, S, edge, crop, self.sig))

    def _on_rendered(self, u8):
        self._busy = False
        if u8 is not None:
            h, w = u8.shape[:2]
            qi = QImage(u8.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            self.fw, self.fh = self.photo.output_size(self._frame_S, self._frame_crop)
            self.view.set_image(QPixmap.fromImage(qi), self.fw, self.fh)
            self.hist.set_image(u8)
            self.update_info()
            self.update_overlay()
            self.view.viewport().update()
        if self._pending is not None:
            self._launch()

    def toggle_before(self):
        self.set_before(not self.before)

    def set_before(self, on):
        if self.before != on:
            self.before = on
            self.request(True)

    # ------------------------------------------------------------------ tools & overlay
    def set_tool(self, t):
        if self.crop_mode and t != 'crop':
            self.end_crop(True)
        self.tool = t
        if t == 'crop' and self.photo and not self.crop_mode:
            self.begin_crop()
        self.update_cursor()
        self.update_overlay()
        self.sync_tool_ui()
        self.view.viewport().update()

    def update_cursor(self):
        self.view.viewport().setCursor(Qt.OpenHandCursor if self.tool == 'hand' else Qt.CrossCursor)

    def cur_mask(self):
        return self.S['masks'][self.sel] if 0 <= self.sel < len(self.S['masks']) else None

    def refresh_masks_ui(self):
        if self.sel >= len(self.S['masks']):
            self.sel = len(self.S['masks']) - 1
        self.mask_panel.refresh()
        self.update_overlay()

    def select_mask(self, row):
        self.sel = row
        if self.cur_mask() and self.cur_cat == 'Masks':
            self.set_tool('edit')
        self.refresh_masks_ui()
        self.view.viewport().update()

    def delete_mask(self):
        if self.cur_mask() is not None:
            self.S['masks'].pop(self.sel)
            self.sel = len(self.S['masks']) - 1
            self.commit('Delete mask')
            self.refresh_masks_ui()
            self.request(True)

    def mask_invert(self, on):
        m = self.cur_mask()
        if m:
            m['invert'] = on
            self.commit('Invert mask')
            self.update_overlay()
            self.request(True)

    def toggle_overlay(self, on):
        self.show_overlay = on
        self.update_overlay()
        self.view.viewport().update()

    def update_overlay(self):
        m = self.cur_mask()
        self.overlay = None
        if m and self.show_overlay and not self.crop_mode and self.tool in MASK_TOOLS:
            s = min(1.0, 420 / max(self.fw, self.fh))
            h, w = max(1, int(self.fh * s)), max(1, int(self.fw * s))
            mk = E.compute_mask(m, h, w)
            a = np.zeros((h, w, 4), np.uint8)
            a[..., 0], a[..., 1], a[..., 2] = 255, 60, 70
            a[..., 3] = (mk * 105).astype(np.uint8)
            self.overlay = QImage(a.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        self.view.viewport().update()

    def draw_overlay(self, p, scale):
        if not self.photo:
            return
        fw, fh, u = self.fw, self.fh, 1.0 / max(scale, 1e-6)
        p.setRenderHint(QPainter.Antialiasing)
        if self.crop_mode:
            x0, y0, x1, y1 = self.crop_rect
            r = QRectF(x0 * fw, y0 * fh, (x1 - x0) * fw, (y1 - y0) * fh)
            path = QPainterPath()
            path.addRect(QRectF(0, 0, fw, fh))
            inner = QPainterPath()
            inner.addRect(r)
            p.fillPath(path.subtracted(inner), QColor(0, 0, 0, 150))
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5 * u))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setPen(QPen(QColor(255, 255, 255, 90), 1 * u))
            for i in (1, 2):
                p.drawLine(QPointF(r.left() + r.width() * i / 3, r.top()), QPointF(r.left() + r.width() * i / 3, r.bottom()))
                p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 3), QPointF(r.right(), r.top() + r.height() * i / 3))
            p.setBrush(QColor('white'))
            for pt in self.crop_handles().values():
                p.drawRect(QRectF(pt.x() - 4 * u, pt.y() - 4 * u, 8 * u, 8 * u))
            return
        if self.tool == 'brush' and self.cursor_scene and not self.crop_mode:
            cx, cy = self.cursor_scene
            rr = self.brush['size'] * max(fw, fh) / 2
            p.setBrush(Qt.NoBrush)
            er = self.erasing()
            rgb = (255, 120, 120) if er else (255, 255, 255)  # eraser ring is red-tinted with a minus in the middle
            p.setPen(QPen(QColor(*rgb, 235), 1.4 * u))
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            if er:
                p.drawLine(QPointF(cx - 5 * u, cy), QPointF(cx + 5 * u, cy))
            p.setPen(QPen(QColor(*rgb, 120), 1.0 * u, Qt.DashLine))
            p.drawEllipse(QPointF(cx, cy), rr * (1 - 0.5 * self.brush['feather']), rr * (1 - 0.5 * self.brush['feather']))
        m = self.cur_mask()
        if not m or self.tool not in MASK_TOOLS:
            return
        if self.overlay is not None:
            p.drawImage(QRectF(0, 0, fw, fh), self.overlay)
        pen = QPen(QColor(255, 255, 255, 230), 1.5 * u)
        p.setPen(pen)
        p.setBrush(QColor(255, 255, 255, 80))
        if m['type'] == 'linear':
            a = QPointF(m['p1'][0] * fw, m['p1'][1] * fh)
            b = QPointF(m['p2'][0] * fw, m['p2'][1] * fh)
            d = b - a
            ln = max((d.x() ** 2 + d.y() ** 2) ** .5, 1e-6)
            n = QPointF(-d.y() / ln, d.x() / ln) * max(fw, fh)
            p.drawLine(a - n, a + n)
            p.setPen(QPen(QColor(255, 255, 255, 160), 1.2 * u, Qt.DashLine))
            p.drawLine(b - n, b + n)
            p.setPen(pen)
            p.drawLine(a, b)
            for q in (a, b):
                p.drawEllipse(q, 7 * u, 7 * u)
        elif m['type'] == 'radial':
            c = QPointF(m['c'][0] * fw, m['c'][1] * fh)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, m['r'][0] * fw, m['r'][1] * fh)
            p.setBrush(QColor(255, 255, 255, 120))
            for q in self.radial_handles(m).values():
                p.drawEllipse(q, 6 * u, 6 * u)

    def radial_handles(self, m):
        fw, fh = self.fw, self.fh
        cx, cy = m['c'][0] * fw, m['c'][1] * fh
        return {'c': QPointF(cx, cy), 'rx': QPointF(cx + m['r'][0] * fw, cy), 'ry': QPointF(cx, cy + m['r'][1] * fh)}

    def crop_handles(self):
        x0, y0, x1, y1 = [v * d for v, d in zip(self.crop_rect, (self.fw, self.fh, self.fw, self.fh))]
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        return {'tl': QPointF(x0, y0), 't': QPointF(xm, y0), 'tr': QPointF(x1, y0), 'l': QPointF(x0, ym),
                'r': QPointF(x1, ym), 'bl': QPointF(x0, y1), 'b': QPointF(xm, y1), 'br': QPointF(x1, y1)}

    # ------------------------------------------------------------------ mouse tools
    def tool_press(self, sx, sy, scale):
        fw, fh = self.fw, self.fh
        nx, ny = min(1, max(0, sx / fw)), min(1, max(0, sy / fh))
        tol = 14 / max(scale, 1e-6)
        if self.crop_mode:
            hit = None
            for k, q in self.crop_handles().items():
                if abs(q.x() - sx) < tol and abs(q.y() - sy) < tol:
                    hit = k
                    break
            x0, y0, x1, y1 = self.crop_rect
            if hit is None and x0 <= nx <= x1 and y0 <= ny <= y1:
                hit = 'move'
            self.drag = ('crop', hit, (nx - x0, ny - y0))
            return True
        m = self.cur_mask()
        if m and m['type'] in ('linear', 'radial') and (self.tool == 'edit' or m['type'] == self.tool):
            hs = ({'p1': QPointF(m['p1'][0] * fw, m['p1'][1] * fh), 'p2': QPointF(m['p2'][0] * fw, m['p2'][1] * fh)}
                  if m['type'] == 'linear' else self.radial_handles(m))
            for k, q in hs.items():
                if (q.x() - sx) ** 2 + (q.y() - sy) ** 2 < tol * tol:
                    self.drag = ('handle', k)
                    return True
        if self.tool in ('linear', 'radial'):
            nm = E.new_mask(self.tool)
            if self.tool == 'linear':
                nm['p1'] = nm['p2'] = [nx, ny]
            else:
                nm['c'], nm['r'] = [nx, ny], [0.001, 0.001]
            self.S['masks'].append(nm)
            self.sel = len(self.S['masks']) - 1
            self.refresh_masks_ui()
            self.drag = ('new', self.tool, (nx, ny))
            return True
        if self.tool == 'brush':
            if not (m and m['type'] == 'brush'):
                self.S['masks'].append(E.new_mask('brush'))
                self.sel = len(self.S['masks']) - 1
                self.refresh_masks_ui()
                m = self.cur_mask()
            st = dict(self.brush, pts=[[nx, ny]], erase=self.erasing())
            m['strokes'].append(st)
            self.drag = ('brush', st)
            self.update_overlay()
            self.request(False)
            return True
        return False

    def tool_move(self, sx, sy, scale):
        if not self.drag or not self.photo:
            return
        fw, fh = self.fw, self.fh
        nx, ny = min(1, max(0, sx / fw)), min(1, max(0, sy / fh))
        kind = self.drag[0]
        m = self.cur_mask()
        if kind == 'crop':
            self.drag_crop(self.drag[1], nx, ny, self.drag[2])
        elif kind == 'new' and m:
            if m['type'] == 'linear':
                m['p2'] = [nx, ny]
            else:
                cx, cy = self.drag[2]
                rx = max(0.005, ((nx - cx) ** 2 * fw * fw + (ny - cy) ** 2 * fh * fh) ** .5 / fw)
                m['r'] = [rx, rx * fw / fh]
            self.update_overlay()
        elif kind == 'handle' and m:
            k = self.drag[1]
            if k in ('p1', 'p2'):
                m[k] = [nx, ny]
            elif k == 'c':
                dx, dy = nx - m['c'][0], ny - m['c'][1]
                m['c'] = [nx, ny]
            elif k == 'rx':
                m['r'][0] = max(0.005, abs(nx - m['c'][0]))
            else:
                m['r'][1] = max(0.005, abs(ny - m['c'][1]))
            self.update_overlay()
        elif kind == 'brush':
            pts = self.drag[1]['pts']
            if (pts[-1][0] - nx) ** 2 * fw * fw + (pts[-1][1] - ny) ** 2 * fh * fh > 9:
                pts.append([nx, ny])
                self.update_overlay()
                self.request(False)
            return
        if kind != 'crop':
            self.request(False)
        self.view.viewport().update()

    def tool_release(self):
        d, self.drag = self.drag, None
        if not d or not self.photo:
            return
        if d[0] == 'crop':
            return
        m = self.cur_mask()
        if d[0] == 'new' and m:
            if (m['type'] == 'linear' and m['p1'] == m['p2']) or (m['type'] == 'radial' and m['r'][0] < 0.01):
                self.S['masks'].pop(self.sel)  # a click without a drag creates nothing
                self.sel = len(self.S['masks']) - 1
                self.refresh_masks_ui()
                return
        self.commit(f'{d[0]} mask')
        self.request(True)
        if d[0] == 'new':
            self.set_tool('edit')  # keep the handles draggable, stop creating new masks
        self.refresh_masks_ui()

    # ------------------------------------------------------------------ crop
    def begin_crop(self):
        self.crop_mode = True
        self.crop_rect = list(self.S['crop'])
        self.view.fit = True
        self.request(True)

    def end_crop(self, apply):
        if not self.crop_mode:
            return
        self.crop_mode = False
        if apply:
            self.S['crop'] = [round(v, 6) for v in self.crop_rect]
            self.commit('Crop')
        self.tool = 'hand'
        self.update_cursor()
        self.sync_tool_ui()
        self.view.fit = True
        self.request(True)

    def reset_crop(self):
        self.S['crop'] = [0.0, 0.0, 1.0, 1.0]
        self.crop_rect = [0, 0, 1, 1]
        self.commit('Reset crop')
        self.request(True)

    def set_aspect(self, text):
        if text == 'Free':
            self.aspect = None
        elif text == 'Original':
            self.aspect = self.photo.w / self.photo.h if self.photo else None
        else:
            a, b = text.split(':')
            self.aspect = float(a) / float(b)
        if self.crop_mode and self.aspect:
            x0, y0, x1, y1 = self.crop_rect
            cw, ch = (x1 - x0) * self.fw, (y1 - y0) * self.fh
            nw = min(cw, ch * self.aspect)
            nh = nw / self.aspect
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self.crop_rect = [cx - nw / self.fw / 2, cy - nh / self.fh / 2, cx + nw / self.fw / 2, cy + nh / self.fh / 2]
            self.view.viewport().update()

    def drag_crop(self, h, nx, ny, off):
        if h is None:
            return
        x0, y0, x1, y1 = self.crop_rect
        if h == 'move':
            w_, h_ = x1 - x0, y1 - y0
            nx0, ny0 = min(max(nx - off[0], 0), 1 - w_), min(max(ny - off[1], 0), 1 - h_)
            self.crop_rect = [nx0, ny0, nx0 + w_, ny0 + h_]
            self.view.viewport().update()
            return
        if 'l' in h:
            x0 = min(nx, x1 - 0.02)
        if 'r' in h:
            x1 = max(nx, x0 + 0.02)
        if 't' in h:
            y0 = min(ny, y1 - 0.02)
        if 'b' in h:
            y1 = max(ny, y0 + 0.02)
        ar, fw, fh = self.aspect, self.fw, self.fh
        if ar:
            w_, h_ = (x1 - x0) * fw, (y1 - y0) * fh
            if h in ('l', 'r'):
                nh = w_ / ar / fh
                cy = (y0 + y1) / 2
                y0, y1 = cy - nh / 2, cy + nh / 2
            elif h in ('t', 'b'):
                nw = h_ * ar / fw
                cx = (x0 + x1) / 2
                x0, x1 = cx - nw / 2, cx + nw / 2
            else:
                nh = w_ / ar / fh
                if 't' in h:
                    y0 = y1 - nh
                else:
                    y1 = y0 + nh
        if x0 < 0 or y0 < 0 or x1 > 1 or y1 > 1:
            return
        self.crop_rect = [x0, y0, x1, y1]
        self.view.viewport().update()

    def flip(self, i):
        self.S['flip'][i] = not self.S['flip'][i]
        self.commit('Flip')
        self.request(True)

    # ------------------------------------------------------------------ presets
    def refresh_presets(self):
        self.presets = []  # built-in presets removed - only your own presets / folders are shown
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        self.folders = [ROOT_FOLDER]
        dirs = [(ROOT_FOLDER, PRESET_DIR)] + [(d.name, d) for d in sorted(PRESET_DIR.iterdir(), key=lambda x: x.name.lower())
                                              if d.is_dir() and not d.name.startswith('.')]
        for folder, d in dirs:
            if folder not in self.folders:
                self.folders.append(folder)
            for f in sorted(d.glob('*.json')):
                try:
                    j = json.load(open(f))
                    self.presets.append({'name': j.get('name', f.stem), 'settings': j['settings'], 'file': str(f),
                                         'folder': folder})
                except Exception:
                    pass
        if hasattr(self, 'preset_panel'):
            self.preset_panel.refresh(True)

    def merge_settings(self, S, d):
        for k, v in d.items():
            if k in S:
                if isinstance(S[k], dict) and isinstance(v, dict):
                    S[k].update(copy.deepcopy(v))
                else:
                    S[k] = copy.deepcopy(v)

    def preset_icon(self, p):
        """Little preview of the current photo with this preset applied."""
        if not self.photo:
            return None
        key = (self.photo.path, p['name'], json.dumps(p['settings'], sort_keys=True))
        if key not in self._thumbs:
            try:
                S = E.default_settings()
                self.merge_settings(S, p['settings'])
                x = E.process(self.photo.source(240), S, False, self.photo.is_raw)
                u8 = (x * 255 + 0.5).astype(np.uint8)
                h, w = u8.shape[:2]
                s = min(h, w)
                sq = np.ascontiguousarray(u8[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s])
                qi = QImage(sq.data, s, s, 3 * s, QImage.Format_RGB888).copy()
                self._thumbs[key] = QIcon(QPixmap.fromImage(qi).scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:
                traceback.print_exc()
                self._thumbs[key] = None
        return self._thumbs[key]

    def apply_preset(self, idx):
        if not self.photo or not (0 <= idx < len(self.presets)):
            return
        self.cur_preset = idx
        self.merge_settings(self.S, self.presets[idx]['settings'])
        self.commit('Preset: ' + self.presets[idx]['name'])
        self.refresh_ui()
        self.request(True)

    def save_preset(self):
        if not self.photo:
            return
        cur = self.presets[self.cur_preset]['folder'] if 0 <= self.cur_preset < len(self.presets) else ROOT_FOLDER
        if cur == BUILTIN_FOLDER:
            cur = ROOT_FOLDER
        dlg = PresetDialog(self, [f for f in self.folders if f != BUILTIN_FOLDER], cur)
        if dlg.exec() and dlg.name.text().strip():
            name = dlg.name.text().strip()
            folder = dlg.folder()
            if folder.lower() == BUILTIN_FOLDER.lower() or not _safe(folder):
                folder = ROOT_FOLDER
            d = folder_dir(folder)
            d.mkdir(parents=True, exist_ok=True)
            fn = d / ((_safe(name) or 'preset') + '.json')
            json.dump({'name': name, 'groups': dlg.groups(), 'settings': E.extract(self.S, dlg.groups())}, open(fn, 'w'))
            self.refresh_presets()
            self._select_file(fn)
            self.preset_panel.collapsed.discard(folder if folder in self.folders else ROOT_FOLDER)
            self.preset_panel.refresh(True)

    def rename_preset(self):
        if not (0 <= self.cur_preset < len(self.presets)):
            return
        p = self.presets[self.cur_preset]
        if not p.get('file'):
            QMessageBox.information(self, 'Rename preset', "Built-in presets can't be renamed. Save a copy as your own preset first.")
            return
        name, ok = QInputDialog.getText(self, 'Rename preset', 'New name:', text=p['name'])
        name = name.strip() if ok else ''
        if not name or name == p['name']:
            return
        old = Path(p['file'])
        try:
            j = json.load(open(old))
            j['name'] = name
            dest = old.parent / ((_safe(name) or 'preset') + '.json')
            if dest.exists() and dest != old:
                dest = unique_path(old.parent, _safe(name) or 'preset')
            with open(dest, 'w') as f:
                json.dump(j, f)
            if dest != old:
                os.remove(old)
        except Exception as ex:
            QMessageBox.warning(self, 'Rename preset', str(ex))
            return
        self.refresh_presets()
        self._select_file(dest)
        self.preset_panel.refresh(True)

    def _select_file(self, fn):
        self.cur_preset = -1
        for i, p in enumerate(self.presets):
            if p.get('file') and os.path.abspath(p['file']) == os.path.abspath(str(fn)):
                self.cur_preset = i

    # ---- folders
    def new_folder(self, move_selected=False):
        name, ok = QInputDialog.getText(self, 'New folder', 'Folder name:')
        name = _safe(name) if ok else ''
        if not name:
            return None
        if name.lower() in (BUILTIN_FOLDER.lower(), ROOT_FOLDER.lower()):
            QMessageBox.information(self, 'New folder', f'"{name}" is a reserved name.')
            return None
        if name in self.folders:
            QMessageBox.information(self, 'New folder', f'A folder called "{name}" already exists.')
            return None
        folder_dir(name).mkdir(parents=True, exist_ok=True)
        self.refresh_presets()
        if move_selected:
            self.move_preset(name)
        return name

    def rename_folder(self, folder):
        if folder in (BUILTIN_FOLDER, ROOT_FOLDER):
            return
        name, ok = QInputDialog.getText(self, 'Rename folder', 'New name:', text=folder)
        name = _safe(name) if ok else ''
        if not name or name == folder:
            return
        if name.lower() in (BUILTIN_FOLDER.lower(), ROOT_FOLDER.lower()) or name in self.folders:
            QMessageBox.information(self, 'Rename folder', f'Can\'t use "{name}" - that name is taken.')
            return
        os.rename(folder_dir(folder), folder_dir(name))
        if folder in self.preset_panel.collapsed:
            self.preset_panel.collapsed.discard(folder)
            self.preset_panel.collapsed.add(name)
        self.cur_preset = -1
        self.refresh_presets()

    def delete_folder(self, folder):
        """Presets inside are NOT deleted - they move to My Presets."""
        if folder in (BUILTIN_FOLDER, ROOT_FOLDER):
            return
        d = folder_dir(folder)
        files = list(d.glob('*.json'))
        msg = f'Delete the folder "{folder}"?'
        if files:
            msg += f'\n\nIts {len(files)} preset(s) will be moved to "{ROOT_FOLDER}".'
        if QMessageBox.question(self, 'Delete folder', msg) != QMessageBox.Yes:
            return
        for f in files:
            shutil.move(str(f), str(unique_path(PRESET_DIR, f.stem)))
        try:
            shutil.rmtree(d)
        except Exception:
            traceback.print_exc()
        self.cur_preset = -1
        self.refresh_presets()

    def move_preset(self, folder):
        if not (0 <= self.cur_preset < len(self.presets)):
            return
        p = self.presets[self.cur_preset]
        if not p.get('file') or p['folder'] == folder:
            return
        d = folder_dir(folder)
        d.mkdir(parents=True, exist_ok=True)
        dest = unique_path(d, Path(p['file']).stem)
        shutil.move(p['file'], str(dest))
        self.refresh_presets()
        self._select_file(dest)
        self.preset_panel.collapsed.discard(folder)
        self.preset_panel.refresh(True)

    def delete_preset(self):
        if 0 <= self.cur_preset < len(self.presets) and self.presets[self.cur_preset].get('file'):
            os.remove(self.presets[self.cur_preset]['file'])
            self.cur_preset = -1
            self.refresh_presets()

    def export_preset(self):
        if not (0 <= self.cur_preset < len(self.presets)):
            return
        p = self.presets[self.cur_preset]
        path, _ = QFileDialog.getSaveFileName(self, 'Export preset', p['name'] + '.json', 'Preset (*.json)')
        if path:
            json.dump({'name': p['name'], 'settings': p['settings']}, open(path, 'w'))

    def import_preset(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import presets (Lightroom .xmp / .lrtemplate / .dng, or PyLight .json)',
                                                '', 'Presets (*.xmp *.lrtemplate *.dng *.json);;All files (*)')
        self.import_preset_files(paths)

    def import_preset_files(self, paths):
        done, notes = [], []
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            try:
                if ext == '.json':
                    d = json.load(open(p))
                    name, settings, extra = d.get('name', Path(p).stem), d['settings'], []
                else:
                    r = E.import_lr(p)
                    name, settings, extra = r['name'], r['settings'], r['notes']
                PRESET_DIR.mkdir(parents=True, exist_ok=True)
                safe = ''.join(c for c in name if c.isalnum() or c in ' _-').strip() or 'preset'
                with open(PRESET_DIR / (safe + '.json'), 'w') as f:
                    json.dump({'name': name, 'settings': settings, 'source': ext}, f)
                done.append(name)
                notes += [f'{name}: {x}' for x in extra]
            except Exception as ex:
                notes.append(f'{os.path.basename(p)}: {ex}')
        if not paths:
            return
        self.refresh_presets()
        if done:
            for i, p in enumerate(self.presets):
                if p['name'] == done[-1]:
                    self.cur_preset = i
            self.go_category('Presets')
        msg = ('Imported: ' + ', '.join(done) if done else 'Nothing was imported.')
        if notes:
            msg += '\n\nNot carried over:\n- ' + '\n- '.join(notes)
        QMessageBox.information(self, 'Import presets', msg)

    # ------------------------------------------------------------------ export
    def export(self):
        if not self.photo:
            return
        if self.crop_mode:
            self.end_crop(True)
        size = self.photo.output_size(self.S)
        dlg = ExportDialog(self, self.photo.ext == '.dng', size)
        if not dlg.exec():
            return
        opts = dlg.values()
        ext = {'JPEG': '.jpg', 'PNG': '.png', 'TIFF': '.tif', 'DNG': '.dng'}[opts['fmt']]
        flt = {'JPEG': 'JPEG (*.jpg *.jpeg)', 'PNG': 'PNG (*.png)', 'TIFF': 'TIFF (*.tif *.tiff)', 'DNG': 'DNG (*.dng)'}
        default = os.path.splitext(self.path)[0] + '_edit' + ext
        path, _ = QFileDialog.getSaveFileName(self, 'Export', default, flt[opts['fmt']])
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ext
        self.export_path = path
        self.prog = QProgressDialog('Exporting at full resolution...', None, 0, 0, self)
        self.prog.setWindowModality(Qt.WindowModal)
        self.prog.setMinimumDuration(0)
        self.prog.show()
        self.pool.start(ExportJob(self.photo, copy.deepcopy(self.S), path, opts, self.sig))

    def _on_exported(self, res):
        self.prog.close()
        if res[0] == 'ok':
            self.statusBar().showMessage(f'Exported {res[1][0]}x{res[1][1]} px -> {self.export_path}')
            QMessageBox.information(self, 'Export finished', f'Saved {res[1][0]} x {res[1][1]} px\n{self.export_path}')
        else:
            QMessageBox.critical(self, 'Export failed', res[1])

    def keyReleaseEvent(self, e):
        super().keyReleaseEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.open_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == '__main__':
    main()