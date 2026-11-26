"""
Convert (almost) any image to PNG.  No Qt in here, so it can be tested on its own.

    convert_to_png(src)            -> Path of the new .png (saved next to the original)
    convert_many(paths, progress)  -> (done: [Path], notes: [str])

RAW / DNG files go through rawpy (16-bit sRGB, camera white balance).  Everything else goes through Pillow
(EXIF rotation applied, colour profile kept, 16-bit TIFF/PNG kept at 16-bit where Pillow allows it).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

RAW_EXT = {'.dng', '.cr2', '.cr3', '.nef', '.arw', '.orf', '.rw2', '.raf', '.pef', '.srw', '.raw'}
OTHER_EXT = {'.jpg', '.jpeg', '.jfif', '.png', '.tif', '.tiff', '.bmp', '.webp', '.gif', '.heic', '.heif',
             '.avif', '.ico', '.tga', '.ppm', '.pgm'}
HEIC_EXT = {'.heic', '.heif', '.avif'}
ALL_EXT = RAW_EXT | OTHER_EXT


def _free_name(folder, stem):
    p = Path(folder) / (stem + '.png')
    n = 2
    while p.exists():
        p = Path(folder) / f'{stem} ({n}).png'
        n += 1
    return p


def _out_path(src, out_dir):
    src = Path(src)
    stem = src.stem + ('_converted' if src.suffix.lower() == '.png' else '')
    for folder in ([Path(out_dir)] if out_dir else [src.parent]) + [Path.home() / 'Pictures' / 'PyLight PNG']:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.access(folder, os.W_OK):
                return _free_name(folder, stem)
        except OSError:
            continue
    raise OSError('No writable folder to save the PNG in.')


def _save_raw(src, dst):
    import rawpy
    import cv2
    with rawpy.imread(str(src)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=16,
                              output_color=rawpy.ColorSpace.sRGB, highlight_mode=rawpy.HighlightMode.Blend)
    if not cv2.imwrite(str(dst), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
        raise OSError('Could not write the PNG.')


def _save_pillow(src, dst):
    from PIL import Image, ImageOps
    try:
        import pillow_heif  # optional - enables .heic / .heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    with Image.open(src) as im:
        icc = im.info.get('icc_profile')
        try:
            im.seek(0)  # first frame of GIF / multi-page TIFF
        except Exception:
            pass
        im = ImageOps.exif_transpose(im)
        if im.mode in ('I;16', 'I;16L', 'I;16B', 'I', 'F'):
            arr = np.asarray(im).astype(np.float64)
            if im.mode == 'F':
                arr = np.clip(arr, 0, 1) * 65535
            im = Image.fromarray(np.clip(arr, 0, 65535).astype(np.uint16))
        elif im.mode == 'P':
            im = im.convert('RGBA' if 'transparency' in im.info else 'RGB')
        elif im.mode in ('CMYK', 'YCbCr', 'LAB', 'HSV'):
            im = im.convert('RGB')
        elif im.mode == 'PA':
            im = im.convert('RGBA')
        elif im.mode not in ('1', 'L', 'LA', 'RGB', 'RGBA', 'I;16'):
            im = im.convert('RGBA' if 'A' in im.mode else 'RGB')
        kw = {'icc_profile': icc} if icc and im.mode != 'CMYK' else {}
        im.save(dst, 'PNG', **kw)


def _save_sips(src, dst):
    """macOS has a built-in converter (sips) that reads HEIC with nothing to install."""
    exe = shutil.which('sips')
    if not exe:
        raise RuntimeError('sips not available')
    r = subprocess.run([exe, '-s', 'format', 'png', str(src), '--out', str(dst)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not Path(dst).exists():
        raise RuntimeError((r.stderr or r.stdout or 'sips failed').strip())


def _save_heic(src, dst):
    try:
        _save_pillow(src, dst)  # works when pillow-heif is installed
        return
    except Exception as first:
        if sys.platform == 'darwin':
            try:
                _save_sips(src, dst)
                return
            except Exception:
                pass
        raise RuntimeError('Reading HEIC needs one extra package. Run:  pip install pillow-heif') from first


def convert_to_png(src, out_dir=None):
    src = Path(src)
    ext = src.suffix.lower()
    if ext not in ALL_EXT:
        raise ValueError(f'Unsupported file type "{ext or "?"}"')
    dst = _out_path(src, out_dir)
    try:
        (_save_raw if ext in RAW_EXT else _save_heic if ext in HEIC_EXT else _save_pillow)(src, dst)
    except Exception:
        if dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        raise
    return dst


def convert_many(paths, progress=None, out_dir=None):
    done, notes = [], []
    for i, p in enumerate(paths):
        if progress:
            progress(i, len(paths), os.path.basename(p))
        try:
            done.append(convert_to_png(p, out_dir))
        except Exception as ex:
            notes.append(f'{os.path.basename(p)}: {ex}')
    return done, notes