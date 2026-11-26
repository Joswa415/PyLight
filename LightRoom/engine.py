"""
PyLight engine - non-destructive develop pipeline (no UI code in here).

Pipeline order (same for preview and export, so what you see is what you save):
  geometry (flip / straighten / crop) -> white balance + exposure (linear light)
  -> sRGB encode -> tone (blacks/whites/shadows/highlights/contrast/texture/
  clarity/dehaze/vibrance/saturation) -> tone curve -> HSL -> color grading
  -> local masks -> detail (sharpen / noise reduction) -> vignette / grain
All radii are expressed relative to image size, so a small preview and the
full-resolution export look the same.
"""
import base64
import copy
import json
import math
import mmap
import os
import shutil
import struct
import colorsys

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps
from scipy.interpolate import PchipInterpolator

Image.MAX_IMAGE_PIXELS = None
RAW_EXT = {'.dng', '.cr2', '.cr3', '.nef', '.arw', '.orf', '.rw2', '.raf', '.pef', '.srw', '.raw'}
IMG_EXT = RAW_EXT | {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
BANDS = ['red', 'orange', 'yellow', 'green', 'aqua', 'blue', 'purple', 'magenta']
BAND_HUES = [0, 30, 60, 120, 180, 240, 270, 300]
LOCAL_KEYS = ['exposure', 'temp', 'tint', 'contrast', 'highlights', 'shadows', 'whites',
              'blacks', 'texture', 'clarity', 'dehaze', 'saturation']
IDENT = [[0.0, 0.0], [1.0, 1.0]]

# ----------------------------------------------------------------------------- settings
SCALARS = {
    'temp': 0, 'tint': 0, 'exposure': 0.0, 'contrast': 0, 'highlights': 0, 'shadows': 0,
    'whites': 0, 'blacks': 0, 'texture': 0, 'clarity': 0, 'dehaze': 0, 'vibrance': 0,
    'saturation': 0, 'sharpen': 0, 'sharpen_radius': 1.0, 'nr_lum': 0, 'nr_color': 0,
    'vignette': 0, 'vig_mid': 50, 'vig_feather': 50, 'grain': 0, 'angle': 0.0,
    'blur': 0, 'glow': 0, 'edge_blur': 0,
}

GROUPS = {
    'Basic': ['temp', 'tint', 'exposure', 'contrast', 'highlights', 'shadows', 'whites',
              'blacks', 'texture', 'clarity', 'dehaze', 'vibrance', 'saturation'],
    'Tone Curve': ['curve'], 'HSL': ['hsl'], 'Color Grading': ['grade'],
    'Detail': ['sharpen', 'sharpen_radius', 'nr_lum', 'nr_color'],
    'Effects': ['vignette', 'vig_mid', 'vig_feather', 'grain'],
    'Blur': ['blur', 'glow', 'edge_blur'],
    'Masks': ['masks'], 'Geometry': ['crop', 'angle', 'flip'],
}


def default_settings():
    s = dict(SCALARS)
    s['curve'] = {c: copy.deepcopy(IDENT) for c in ('rgb', 'r', 'g', 'b')}
    s['hsl'] = {'hue': [0] * 8, 'sat': [0] * 8, 'lum': [0] * 8}
    s['grade'] = {'sh': [0, 0], 'mid': [0, 0], 'hi': [0, 0], 'balance': 0}
    s['crop'] = [0.0, 0.0, 1.0, 1.0]
    s['flip'] = [False, False]
    s['masks'] = []
    return s


def normalize(S):
    """Fill missing keys of a loaded settings dict with defaults."""
    d = default_settings()
    for k, v in (S or {}).items():
        if k in d and isinstance(d[k], dict) and isinstance(v, dict):
            for kk, vv in v.items():
                d[k][kk] = vv
        elif k in d:
            d[k] = v
    return d


def extract(S, groups):
    out = {}
    for g in groups:
        for k in GROUPS[g]:
            out[k] = copy.deepcopy(S[k])
    return out


def new_mask(t):
    m = {'type': t, 'invert': False, 'feather': 50, 'amount': 100, 'lum_lo': 0, 'lum_hi': 100, 'adj': {}}
    if t == 'linear':
        m.update(p1=[0.5, 0.3], p2=[0.5, 0.6])
    elif t == 'radial':
        m.update(c=[0.5, 0.5], r=[0.25, 0.25])
    else:
        m['strokes'] = []
    return m


# ----------------------------------------------------------------------------- helpers
def srgb_to_lin(x):
    x = np.asarray(x, np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def lin_to_srgb(x):
    x = np.maximum(x, 0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def lum(x):
    return x[..., 0] * 0.2126 + x[..., 1] * 0.7152 + x[..., 2] * 0.0722


def sstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def gblur(img, sigma):
    """Gaussian blur that stays fast for huge radii (blurs a downscaled copy)."""
    if sigma < 0.4:
        return img
    if sigma > 6:
        f = sigma / 3.0
        h, w = img.shape[:2]
        sm = cv2.resize(img, (max(1, int(w / f)), max(1, int(h / f))), interpolation=cv2.INTER_AREA)
        sm = cv2.GaussianBlur(sm, (0, 0), 3.0, borderType=cv2.BORDER_REFLECT)
        return cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(img, (0, 0), sigma)


def curve_lut(pts, n=4096):
    pts = sorted(pts, key=lambda p: p[0])
    xs, ys = [], []
    for x, y in pts:
        if xs and x <= xs[-1] + 1e-4:
            continue
        xs.append(x)
        ys.append(y)
    if len(xs) < 2:
        return np.linspace(0, 1, n, dtype=np.float32)
    f = PchipInterpolator(xs, ys, extrapolate=True)
    return np.clip(f(np.linspace(0, 1, n)), 0, 1).astype(np.float32)


def apply_lut(img, lut):
    n = len(lut) - 1
    p = np.clip(img, 0, 1) * n
    i = p.astype(np.int32)
    np.minimum(i, n - 1, out=i)
    f = p - i
    return lut[i] * (1 - f) + lut[i + 1] * f


# ----------------------------------------------------------------------------- stages
def geometry(img, S, crop=True):
    h, w = img.shape[:2]
    if S['flip'][0]:
        img = img[:, ::-1]
    if S['flip'][1]:
        img = img[::-1]
    a = float(S['angle'])
    if abs(a) > 1e-4:
        th = math.radians(abs(a))
        s = math.cos(th) + math.sin(th) * max(w / h, h / w)  # zoom so no empty corners appear
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, s)
        img = cv2.warpAffine(np.ascontiguousarray(img), M, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REFLECT)
    if crop:
        x0, y0, x1, y1 = S['crop']
        X0, Y0 = int(round(x0 * w)), int(round(y0 * h))
        X1, Y1 = max(X0 + 1, int(round(x1 * w))), max(Y0 + 1, int(round(y1 * h)))
        img = img[Y0:Y1, X0:X1]
    return img


def tone_stage(x, p, md):
    g = lambda k: float(p.get(k, 0) or 0)
    bl, wh = g('blacks'), g('whites')
    if bl or wh:
        b0, w0 = -bl / 100 * 0.10, 1 - wh / 100 * 0.15
        x = (x - b0) / (w0 - b0)
    sh, hi = g('shadows'), g('highlights')
    if sh or hi:
        Lb = np.clip(gblur(lum(x), 0.02 * md), 0, 1)
        gain = np.ones_like(Lb)
        if sh:
            gain *= 2 ** (sh / 100 * 1.2 * (1 - Lb) ** 2)
        if hi:
            gain *= 2 ** (hi / 100 * 1.0 * Lb ** 2)
        x = x * gain[..., None]
    c = g('contrast') / 100
    if c:
        xc = np.clip(x, 0, 1)
        x = xc + (xc * xc * (3 - 2 * xc) - xc) * c if c > 0 else xc * (1 + c * 0.5) - c * 0.25
    for key, frac, mid in (('texture', 0.0015, False), ('clarity', 0.01, True)):
        a = g(key) / 100
        if a:
            L = lum(x)
            d = L - gblur(L, frac * md)
            if mid:
                Lc = np.clip(L, 0, 1)
                d = d * 4 * Lc * (1 - Lc)
            x = x + (d * a * 1.5)[..., None]
    d = g('dehaze') / 100
    if d > 0:
        x = (x - 0.15 * d) / (1 - 0.15 * d)
        x = _saturate(x, 1 + 0.25 * d)
    elif d < 0:
        x = x + (0.75 - x) * (-d * 0.4)
    s, v = g('saturation') / 100, g('vibrance') / 100
    if s or v:
        xc = np.clip(x, 0, 1)
        sat = (xc.max(2) - xc.min(2)) / (xc.max(2) + 1e-4)
        f = np.maximum((1 + s) + v * (1 - sat), 0)
        L = lum(xc)[..., None]
        x = L + (xc - L) * f[..., None]
    return x


def _saturate(x, f):
    L = lum(x)[..., None]
    return L + (x - L) * f


def curve_stage(x, curves):
    if all(curves[c] == IDENT for c in curves):
        return x
    base = curve_lut(curves['rgb'])
    for i, c in enumerate('rgb'):
        if curves['rgb'] == IDENT and curves[c] == IDENT:
            continue
        lut = base if curves[c] == IDENT else apply_lut(base, curve_lut(curves[c], len(base)))
        x[..., i] = apply_lut(x[..., i], lut)
    return x


def hsl_stage(x, hsl):
    if not any(any(v) for v in hsl.values()):
        return x
    hls = cv2.cvtColor(x, cv2.COLOR_RGB2HLS)
    H = hls[..., 0]
    idx = (H * 10).astype(np.int32) % 3600
    xs = np.arange(3600) / 10.0
    centers = BAND_HUES + [360]

    def mk(v):
        return np.interp(xs, centers, list(v) + [v[0]]).astype(np.float32)[idx]

    hs, ss, ls = mk(hsl['hue']), mk(hsl['sat']), mk(hsl['lum'])
    S0 = hls[..., 2].copy()
    hls[..., 0] = (H + hs * 0.3) % 360
    hls[..., 2] = np.clip(S0 * (1 + ss / 100), 0, 1)
    hls[..., 1] = np.clip(hls[..., 1] * 2 ** (ls / 100 * 0.8 * S0), 0, 1)
    return cv2.cvtColor(hls, cv2.COLOR_HLS2RGB)


def grade_stage(x, g):
    if all(g[k][1] == 0 for k in ('sh', 'mid', 'hi')):
        return x
    Lb = np.clip(lum(x) + g['balance'] / 100 * 0.25, 0, 1)
    weights = {'sh': (1 - Lb) ** 2, 'hi': Lb ** 2, 'mid': 4 * Lb * (1 - Lb)}
    for k, w in weights.items():
        hue, sat = g[k]
        if sat:
            c = np.array(colorsys.hsv_to_rgb(hue / 360.0, 1, 1), np.float32)
            off = (c - c.mean()) * (sat / 100) * 0.3
            x = x + w[..., None] * off
    return x


def compute_mask(m, h, w, x=None):
    t = m['type']
    px = np.arange(w, dtype=np.float32)[None, :]
    py = np.arange(h, dtype=np.float32)[:, None]
    if t == 'linear':
        (x1, y1), (x2, y2) = m['p1'], m['p2']
        dx, dy = (x2 - x1) * w, (y2 - y1) * h
        L2 = dx * dx + dy * dy
        if L2 < 1:
            mk = np.zeros((h, w), np.float32)
        else:
            mk = sstep(1 - ((px - x1 * w) * dx + (py - y1 * h) * dy) / L2)
    elif t == 'radial':
        cx, cy = m['c']
        rx, ry = max(m['r'][0], 1e-4), max(m['r'][1], 1e-4)
        d = np.sqrt(((px / w - cx) / rx) ** 2 + ((py / h - cy) / ry) ** 2)
        f = max(0.02, m.get('feather', 50) / 100)
        mk = 1 - sstep((d - (1 - f)) / f)
    else:
        mk = brush_mask(m.get('strokes', []), h, w)
    mk = mk.astype(np.float32)
    if m.get('invert'):
        mk = 1 - mk
    lo, hi = m.get('lum_lo', 0) / 100, m.get('lum_hi', 100) / 100
    if x is not None and (lo > 0 or hi < 1):
        L = lum(x)
        mk = mk * np.clip((L - lo) / 0.08, 0, 1) * np.clip((hi - L) / 0.08, 0, 1)
    return mk * (m.get('amount', 100) / 100)


def brush_mask(strokes, h, w):
    m = np.zeros((h, w), np.float32)
    md = max(h, w)
    for st in strokes:
        fe = st.get('feather', 0.5)
        r = max(1.0, st['size'] * md / 2)
        pts = np.array(st['pts'], np.float32) * [w, h]
        pad = r * 2.5 + 4
        x0, y0 = np.maximum((pts.min(0) - pad).astype(int), 0)
        x1, y1 = np.minimum((pts.max(0) + pad).astype(int) + 1, [w, h])
        if x1 <= x0 or y1 <= y0:
            continue
        roi = np.zeros((y1 - y0, x1 - x0), np.float32)
        p = pts - [x0, y0]
        rc = max(1, int(r * (1 - 0.5 * fe)))
        if len(p) > 1:
            cv2.polylines(roi, [np.round(p).astype(np.int32).reshape(-1, 1, 2)], False, 1.0,
                          thickness=max(1, 2 * rc), lineType=cv2.LINE_AA)
        for q in p:
            cv2.circle(roi, (int(q[0]), int(q[1])), rc, 1.0, -1, cv2.LINE_AA)
        if fe > 0:
            roi = cv2.GaussianBlur(roi, (0, 0), max(0.5, fe * r * 0.35))
        roi *= st.get('flow', 1.0)
        sub = m[y0:y1, x0:x1]
        m[y0:y1, x0:x1] = sub * (1 - roi) if st.get('erase') else np.maximum(sub, roi)
    return m


def local_adjust(x, adj, md):
    y = x.copy()
    t, ti, ev = adj.get('temp', 0), adj.get('tint', 0), adj.get('exposure', 0)
    if t or ti or ev:
        gains = np.array([2 ** (t * .006 + ev), 2 ** (-ti * .004 + ev), 2 ** (-t * .006 + ev)], np.float32)
        y = lin_to_srgb(srgb_to_lin(np.clip(y, 0, 1)) * gains)
    return tone_stage(y, adj, md)


def masks_stage(x, S, md):
    h, w = x.shape[:2]
    for m in S['masks']:
        adj = m.get('adj', {})
        if not any(adj.get(k, 0) for k in LOCAL_KEYS):
            continue
        mk = compute_mask(m, h, w, x)
        y = local_adjust(x, adj, md)
        x = x + (y - x) * mk[..., None]
        x = np.clip(x, 0, 1)
    return x


def detail_stage(x, S, md):
    if S['nr_color'] or S['nr_lum']:
        ycc = cv2.cvtColor(x, cv2.COLOR_RGB2YCrCb)
        if S['nr_color']:
            c = np.ascontiguousarray(ycc[..., 1:])
            ycc[..., 1:] = gblur(c, S['nr_color'] / 100 * 0.004 * md)
        if S['nr_lum']:
            y = np.ascontiguousarray(ycc[..., 0])
            sc = max(1.0, md / 3000)
            ycc[..., 0] = cv2.bilateralFilter(y, 7, S['nr_lum'] / 100 * 0.15, 3.0 * sc)
        x = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
    a = S['sharpen'] / 100
    if a:
        L = lum(x)
        sig = max(0.3, S['sharpen_radius'] * md / 5000)
        d = L - cv2.GaussianBlur(L, (0, 0), sig)
        x = x + (d * a * 1.5)[..., None]
    return x


def blur_stage(x, S, md):
    """Blur tab: global gaussian blur, soft highlight glow, and edge (tilt-shift style) blur."""
    b, g, e = S['blur'] / 100, S['glow'] / 100, S['edge_blur'] / 100
    if b:
        x = gblur(x, b * 0.012 * md)
    if g:
        L = lum(x)
        hi = np.clip((L - 0.45) / 0.55, 0, 1)[..., None]
        halo = gblur(np.ascontiguousarray(x * hi), 0.015 * md)
        x = 1 - (1 - x) * (1 - halo * g * 0.8)
    if e:
        h, w = x.shape[:2]
        xs = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        ys = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        t = sstep((np.sqrt(xs * xs + ys * ys) / 1.4142 - 0.25) / 0.6)[..., None]
        x = x + (gblur(np.ascontiguousarray(x), e * 0.014 * md) - x) * t
    return x


def effects_stage(x, S):
    h, w = x.shape[:2]
    v = S['vignette'] / 100
    if v:
        xs = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        ys = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        r = np.sqrt(xs * xs + ys * ys) / 1.4142
        e0 = S['vig_mid'] / 100 * 0.8
        e1 = e0 + 0.05 + S['vig_feather'] / 100 * 0.8
        t = sstep((r - e0) / (e1 - e0))[..., None]
        x = x * (1 + v * t * 0.9) if v < 0 else x + (1 - x) * v * t * 0.9
    if S['grain']:
        n = np.random.default_rng(7).standard_normal((h, w)).astype(np.float32)
        n = cv2.GaussianBlur(n, (0, 0), 0.6)
        L = np.clip(lum(x), 0, 1)
        x = x + (n * S['grain'] / 100 * 0.08 * (0.3 + 0.7 * 4 * L * (1 - L)))[..., None]
    return x


def process(lin, S, crop=True, raw_base=False):
    """linear-light float32 RGB (h,w,3) -> display sRGB float32 in 0..1"""
    x = np.array(geometry(lin, S, crop), dtype=np.float32, order='C', copy=True)
    md = float(max(x.shape[:2]))
    t, ti, ev = S['temp'], S['tint'], S['exposure']
    if t or ti or ev:
        x *= np.array([2 ** (t * .006 + ev), 2 ** (-ti * .004 + ev), 2 ** (-t * .006 + ev)], np.float32)
    x = lin_to_srgb(x)
    if raw_base:  # gentle camera-like base contrast for RAW files
        xc = np.minimum(x, 1)
        x = x + (xc * xc * (3 - 2 * xc) - xc) * 0.5
    x = tone_stage(x, S, md)
    np.clip(x, 0, 1, out=x)
    x = curve_stage(x, S['curve'])
    x = hsl_stage(np.ascontiguousarray(x), S['hsl'])
    x = grade_stage(x, S['grade'])
    np.clip(x, 0, 1, out=x)
    x = masks_stage(x, S, md)
    x = detail_stage(np.ascontiguousarray(x, dtype=np.float32), S, md)
    x = blur_stage(np.ascontiguousarray(x, dtype=np.float32), S, md)
    x = effects_stage(x, S)
    return np.clip(x, 0, 1, out=x)


# ----------------------------------------------------------------------------- photo
class Photo:
    def __init__(self, path):
        self.path = path
        self.ext = os.path.splitext(path)[1].lower()
        self.is_raw = self.ext in RAW_EXT
        self.exif = None
        self._proxies = {}
        self.kelvin, self.tint0 = None, 0
        self.lin = self._load()
        self.h, self.w = self.lin.shape[:2]

    def _load(self):
        if self.is_raw:
            import rawpy
            kw = dict(use_camera_wb=True, no_auto_bright=True, output_bps=16, gamma=(1, 1),
                      output_color=rawpy.ColorSpace.sRGB, highlight_mode=rawpy.HighlightMode.Blend)
            with rawpy.imread(self.path) as raw:
                self.kelvin, self.tint0 = as_shot_cct(raw)
                try:
                    rgb = raw.postprocess(demosaic_algorithm=rawpy.DemosaicAlgorithm.DHT, **kw)
                except Exception:
                    rgb = raw.postprocess(demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, **kw)
            lin = rgb.astype(np.float32) / 65535.0
            del rgb
            p = float(np.percentile(lin[::8, ::8].mean(2), 99.5))
            lin *= float(np.clip(0.9 / max(p, 1e-4), 1.0, 8.0))  # base exposure
            try:
                self.exif = Image.open(self.path).getexif().tobytes()
            except Exception:
                self.exif = None
            return lin
        if self.ext in ('.png', '.tif', '.tiff'):
            a = cv2.imdecode(np.fromfile(self.path, np.uint8), cv2.IMREAD_UNCHANGED)
            if a is not None and a.dtype == np.uint16:
                a = cv2.cvtColor(a, cv2.COLOR_GRAY2RGB) if a.ndim == 2 else cv2.cvtColor(a[..., :3], cv2.COLOR_BGR2RGB)
                return srgb_to_lin(a.astype(np.float32) / 65535.0)
        im = ImageOps.exif_transpose(Image.open(self.path))
        try:
            ex = im.getexif()
            ex[274] = 1
            self.exif = ex.tobytes()
        except Exception:
            self.exif = None
        return srgb_to_lin(np.asarray(im.convert('RGB'), np.float32) / 255.0)

    def source(self, max_edge):
        if not max_edge or max_edge >= max(self.h, self.w):
            return self.lin
        if max_edge not in self._proxies:
            if len(self._proxies) > 3:
                self._proxies.clear()
            s = max_edge / max(self.h, self.w)
            self._proxies[max_edge] = cv2.resize(self.lin, (round(self.w * s), round(self.h * s)),
                                                 interpolation=cv2.INTER_AREA)
        return self._proxies[max_edge]

    def render(self, S, max_edge=None, crop=True):
        return process(self.source(max_edge), S, crop, self.is_raw)

    def output_size(self, S, crop=True):
        if not crop:
            return self.w, self.h
        x0, y0, x1, y1 = S['crop']
        return max(1, round(self.w * (x1 - x0))), max(1, round(self.h * (y1 - y0)))


# ----------------------------------------------------------------------------- XMP / DNG
def crs_attrs(S):
    f = lambda v: f"{v:+.2f}"
    i = lambda v: f"{int(round(v)):+d}"
    a = {'crs:Version': '15.0', 'crs:ProcessVersion': '11.0', 'crs:HasSettings': 'True',
         'crs:Exposure2012': f(S['exposure']), 'crs:IncrementalTemperature': i(S['temp']),
         'crs:IncrementalTint': i(S['tint'])}
    for k, n in (('contrast', 'Contrast2012'), ('highlights', 'Highlights2012'), ('shadows', 'Shadows2012'),
                 ('whites', 'Whites2012'), ('blacks', 'Blacks2012'), ('texture', 'Texture'),
                 ('clarity', 'Clarity2012'), ('dehaze', 'Dehaze'), ('vibrance', 'Vibrance'),
                 ('saturation', 'Saturation')):
        a['crs:' + n] = i(S[k])
    a['crs:Sharpness'] = str(int(S['sharpen'] * 1.5))
    a['crs:LuminanceSmoothing'] = str(int(S['nr_lum']))
    a['crs:ColorNoiseReduction'] = str(int(S['nr_color']))
    a['crs:PostCropVignetteAmount'] = i(S['vignette'])
    a['crs:GrainAmount'] = str(int(S['grain']))
    for j, b in enumerate(BANDS):
        cap = b.capitalize()
        a[f'crs:HueAdjustment{cap}'] = i(S['hsl']['hue'][j])
        a[f'crs:SaturationAdjustment{cap}'] = i(S['hsl']['sat'][j])
        a[f'crs:LuminanceAdjustment{cap}'] = i(S['hsl']['lum'][j])
    x0, y0, x1, y1 = S['crop']
    if S['crop'] != [0.0, 0.0, 1.0, 1.0] or S['angle']:
        a.update({'crs:HasCrop': 'True', 'crs:CropLeft': f'{x0:.6f}', 'crs:CropTop': f'{y0:.6f}',
                  'crs:CropRight': f'{x1:.6f}', 'crs:CropBottom': f'{y1:.6f}',
                  'crs:CropAngle': f"{-S['angle']:.4f}"})
    return a


def build_xmp(S):
    attrs = crs_attrs(S)
    blob = base64.b64encode(json.dumps(S).encode()).decode()
    attrs['pylight:Settings'] = blob
    at = '\n   '.join(f'{k}="{v}"' for k, v in attrs.items())
    curve = ''
    if S['curve']['rgb'] != IDENT:
        li = ''.join(f'<rdf:li>{round(x * 255)}, {round(y * 255)}</rdf:li>' for x, y in sorted(S['curve']['rgb']))
        curve = f'<crs:ToneCurvePV2012><rdf:Seq>{li}</rdf:Seq></crs:ToneCurvePV2012>'
    xmp = ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
           '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="PyLight">\n'
           ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
           '  <rdf:Description rdf:about=""\n'
           '   xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"\n'
           '   xmlns:pylight="http://pylight.local/1.0/"\n'
           f'   {at}>\n   {curve}\n  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>')
    return xmp.encode('utf-8')


def read_embedded_settings(path):
    """Read settings that PyLight embedded in a DNG earlier (None if absent)."""
    try:
        with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            tag = b'pylight:Settings="'
            i = m.rfind(tag)
            if i < 0:
                return None
            j = m.find(b'"', i + len(tag))
            return normalize(json.loads(base64.b64decode(m[i + len(tag):j])))
    except Exception:
        return None


def embed_xmp_tiff(src, dst, xmp):
    """Copy a TIFF-based file (DNG) and write an XMP packet into IFD0 (tag 700)."""
    d = bytearray(open(src, 'rb').read())
    e = '<' if d[:2] == b'II' else '>' if d[:2] == b'MM' else None
    if e is None or struct.unpack(e + 'H', d[2:4])[0] != 42:
        raise ValueError('Not a classic TIFF/DNG container')
    ifd = struct.unpack(e + 'I', d[4:8])[0]
    n = struct.unpack(e + 'H', d[ifd:ifd + 2])[0]
    entries = [bytes(d[ifd + 2 + 12 * k: ifd + 14 + 12 * k]) for k in range(n)]
    nxt = bytes(d[ifd + 2 + 12 * n: ifd + 6 + 12 * n])
    entries = [x for x in entries if struct.unpack(e + 'H', x[:2])[0] != 700]
    if len(d) % 2:
        d.append(0)
    off = len(d)
    d += xmp
    if len(d) % 2:
        d.append(0)
    entries.append(struct.pack(e + 'HHII', 700, 1, len(xmp), off))
    entries.sort(key=lambda x: struct.unpack(e + 'H', x[:2])[0])
    new_ifd = len(d)
    d += struct.pack(e + 'H', len(entries)) + b''.join(entries) + nxt
    d[4:8] = struct.pack(e + 'I', new_ifd)
    with open(dst, 'wb') as f:
        f.write(d)


# ----------------------------------------------------------------------------- export
def export_image(photo, S, path, fmt, quality=100, bits=8, long_edge=0):
    """Full-resolution export. Without cropping / resize the output has exactly the input size."""
    if fmt == 'DNG':
        if photo.ext != '.dng':
            raise ValueError('DNG export needs a DNG source file.')
        if os.path.abspath(path) == os.path.abspath(photo.path):
            raise ValueError('Choose a different file name than the original.')
        embed_xmp_tiff(photo.path, path, build_xmp(S))
        return photo.output_size(S)
    x = photo.render(S, None, True)
    if long_edge and long_edge != max(x.shape[:2]):
        s = long_edge / max(x.shape[:2])
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LANCZOS4
        x = np.clip(cv2.resize(x, (max(1, round(x.shape[1] * s)), max(1, round(x.shape[0] * s))),
                               interpolation=interp), 0, 1)
    h, w = x.shape[:2]
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    if fmt in ('PNG', 'TIFF') and bits == 16:
        u16 = np.clip(x * 65535 + 0.5, 0, 65535).astype(np.uint16)
        ok, buf = cv2.imencode('.png' if fmt == 'PNG' else '.tif', np.ascontiguousarray(u16[..., ::-1]))
        buf.tofile(path)
        return w, h
    im = Image.fromarray((x * 255 + 0.5).astype(np.uint8))
    kw = {'icc_profile': icc}
    if photo.exif:
        kw['exif'] = photo.exif
    if fmt == 'JPEG':
        im.save(path, 'JPEG', quality=int(quality), subsampling=0, optimize=True, **kw)
    elif fmt == 'PNG':
        im.save(path, 'PNG', compress_level=6, **kw)
    else:
        im.save(path, 'TIFF', compression='tiff_lzw', **kw)
    return w, h


# ----------------------------------------------------------------------------- Kelvin / tint display (RAW)
def cct_from_xyz(xyz):
    """XYZ white point -> (CCT in kelvin, Lightroom-style tint number)."""
    X, Y, Z = (float(v) for v in xyz)
    s = X + Y + Z
    x, y = X / s, Y / s
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33
    if not (1500 < cct < 30000):
        return None, 0
    d = -2 * x + 12 * y + 3
    u, v = 4 * x / d, 6 * y / d
    T = cct
    up = (0.860117757 + 1.54118254e-4 * T + 1.28641212e-7 * T * T) / (1 + 8.42420235e-4 * T + 7.08145163e-7 * T * T)
    vp = (0.317398726 + 4.22806245e-5 * T + 4.20481691e-8 * T * T) / (1 - 2.89741816e-5 * T + 1.61456053e-7 * T * T)
    duv = math.copysign(math.hypot(u - up, v - vp), v - vp)
    return float(round(cct, -1)), int(round(-duv * 3000))


def as_shot_cct(raw):
    """Approximate as-shot temperature (K) and tint from the camera's white-balance multipliers."""
    try:
        wb = np.array(raw.camera_whitebalance[:3], float)
        M = np.array(raw.rgb_xyz_matrix, float)[:3, :3]
        if not np.isfinite(wb).all() or wb.min() <= 0 or np.abs(M).sum() < 1e-6:
            return None, 0
        return cct_from_xyz(np.linalg.solve(M, 1.0 / wb))
    except Exception:
        return None, 0


def kelvin_shift(k0, t):
    """Displayed Kelvin for a Temp slider offset t (-100..100); warmer = higher, like Lightroom."""
    return float(min(50000.0, max(2000.0, 1e6 / max(20.0, 1e6 / k0 - t * 1.2))))


# ----------------------------------------------------------------------------- Lightroom preset import
import re  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

CRS = '{http://ns.adobe.com/camera-raw-settings/1.0/}'
RDF = '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
LR_SCALARS = {
    'Exposure2012': ('exposure', 1), 'Contrast2012': ('contrast', 1), 'Highlights2012': ('highlights', 1),
    'Shadows2012': ('shadows', 1), 'Whites2012': ('whites', 1), 'Blacks2012': ('blacks', 1),
    'Texture': ('texture', 1), 'Clarity2012': ('clarity', 1), 'Dehaze': ('dehaze', 1),
    'Vibrance': ('vibrance', 1), 'Saturation': ('saturation', 1),
    'IncrementalTemperature': ('temp', 1), 'IncrementalTint': ('tint', 1),
    'Sharpness': ('sharpen', 1 / 1.5), 'SharpenRadius': ('sharpen_radius', 1),
    'LuminanceSmoothing': ('nr_lum', 1), 'ColorNoiseReduction': ('nr_color', 1),
    'PostCropVignetteAmount': ('vignette', 1), 'PostCropVignetteMidpoint': ('vig_mid', 1),
    'PostCropVignetteFeather': ('vig_feather', 1), 'GrainAmount': ('grain', 1),
}
LR_CURVES = {'ToneCurvePV2012': 'rgb', 'ToneCurvePV2012Red': 'r', 'ToneCurvePV2012Green': 'g', 'ToneCurvePV2012Blue': 'b'}
LR_GRADE = {'SplitToningShadowHue': ('sh', 0), 'SplitToningShadowSaturation': ('sh', 1),
            'SplitToningHighlightHue': ('hi', 0), 'SplitToningHighlightSaturation': ('hi', 1),
            'ColorGradeMidtoneHue': ('mid', 0), 'ColorGradeMidtoneSat': ('mid', 1)}
LR_MASK_KEYS = ('MaskGroupBasedCorrections', 'GradientBasedCorrections', 'CircularGradientBasedCorrections',
                'PaintBasedCorrections')


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_xmp(data):
    root = ET.fromstring(data)
    attrs, curves, name = {}, {}, None
    for desc in root.iter(RDF + 'Description'):
        for k, v in desc.attrib.items():
            if k.startswith(CRS):
                attrs[k[len(CRS):]] = v
        for el in desc:
            if not el.tag.startswith(CRS):
                continue
            local = el.tag[len(CRS):]
            if local in LR_CURVES:
                pts = []
                for li in el.iter(RDF + 'li'):
                    if li.text and ',' in li.text:
                        a, b = li.text.split(',')[:2]
                        pts.append((float(a), float(b)))
                if pts:
                    curves[LR_CURVES[local]] = pts
            elif local == 'Name':
                li = next(el.iter(RDF + 'li'), None)
                name = li.text if li is not None and li.text else name
            elif el.text and el.text.strip() and len(el) == 0:
                attrs[local] = el.text.strip()
            else:
                attrs.setdefault(local, '1')
    return attrs, curves, name


def parse_lrtemplate(text):
    m = re.search(r'title\s*=\s*"([^"]+)"', text)
    name = m.group(1) if m else None
    curves, attrs = {}, {}
    for m in re.finditer(r'(ToneCurvePV2012(?:Red|Green|Blue)?)\s*=\s*\{([^}]*)\}', text):
        nums = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', m.group(2))]
        curves[LR_CURVES[m.group(1)]] = list(zip(nums[0::2], nums[1::2]))
    for m in re.finditer(r'\b([A-Za-z0-9]+)\s*=\s*(-?\d+(?:\.\d+)?|true|false|"[^"]*")', text):
        v = m.group(2).strip('"')
        attrs.setdefault(m.group(1), 'True' if v == 'true' else 'False' if v == 'false' else v)
    for k in LR_MASK_KEYS:
        if re.search(k + r'\s*=', text):
            attrs[k] = '1'
    return attrs, curves, name


def settings_from_crs(attrs, curves):
    """Lightroom develop values -> (partial PyLight settings, list of things that could not be carried over)."""
    S, notes = {}, []
    for k, (dst, mul) in LR_SCALARS.items():
        v = _num(attrs.get(k))
        if v is not None:
            S[dst] = round(v * mul, 4)
    hsl, any_h = {'hue': [0] * 8, 'sat': [0] * 8, 'lum': [0] * 8}, False
    for i, b in enumerate(BANDS):
        for mode, pref in (('hue', 'HueAdjustment'), ('sat', 'SaturationAdjustment'), ('lum', 'LuminanceAdjustment')):
            v = _num(attrs.get(pref + b.capitalize()))
            if v is not None:
                hsl[mode][i], any_h = v, True
    if any_h:
        S['hsl'] = hsl
    g, any_g = {'sh': [0, 0], 'mid': [0, 0], 'hi': [0, 0], 'balance': 0}, False
    for k, (zone, idx) in LR_GRADE.items():
        v = _num(attrs.get(k))
        if v is not None:
            g[zone][idx], any_g = v, True
    v = _num(attrs.get('SplitToningBalance'))
    if v is not None:
        g['balance'], any_g = v, True
    if any_g:
        S['grade'] = g
    cv = {c: copy.deepcopy(IDENT) for c in ('rgb', 'r', 'g', 'b')}
    for ch, pts in curves.items():
        p = [[round(x / 255, 5), round(y / 255, 5)] for x, y in sorted(pts)]
        if len(p) >= 2 and p != [[0.0, 0.0], [1.0, 1.0]]:
            cv[ch] = p
    if cv != {c: IDENT for c in cv}:
        S['curve'] = cv
    if attrs.get('ConvertToGrayscale') == 'True':
        S['saturation'] = -100
        notes.append('Black & white conversion (approximated with Saturation -100)')
    if any(k in attrs for k in LR_MASK_KEYS):
        notes.append('Masks / local adjustments')
    if 'Temperature' in attrs and attrs.get('WhiteBalance') not in (None, 'As Shot'):
        notes.append('Absolute white balance (Kelvin)')
    if any(k in attrs for k in ('ProfileName', 'LookName', 'Look')):
        notes.append('Camera profile / Look')
    if any(k.startswith('LensProfile') or k.startswith('Lens') for k in attrs):
        notes.append('Lens corrections')
    if 'Exposure' in attrs and 'Exposure2012' not in attrs:
        notes.append('Old Lightroom process version (values differ)')
    return S, notes


def _find_xmp(path):
    with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        end = len(m)
        while True:
            j = m.rfind(b'</x:xmpmeta>', 0, end)
            if j < 0:
                break
            i = m.rfind(b'<x:xmpmeta', 0, j)
            if i < 0:
                break
            pkt = bytes(m[i:j + 12])
            if b'camera-raw-settings' in pkt:
                return pkt
            end = i
    raise ValueError('No Lightroom develop settings found in this file.')


def import_lr(path):
    """Read a Lightroom preset (.xmp / .lrtemplate) or the edit settings stored in a .dng."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.lrtemplate':
        attrs, curves, name = parse_lrtemplate(open(path, encoding='utf-8', errors='ignore').read())
    else:
        attrs, curves, name = parse_xmp(_find_xmp(path))
    S, notes = settings_from_crs(attrs, curves)
    if not S:
        raise ValueError('No supported develop settings found in this file.')
    return {'name': name or os.path.splitext(os.path.basename(path))[0], 'settings': S, 'notes': notes,
            'count': len(S)}