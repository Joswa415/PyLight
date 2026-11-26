# PyLight

A desktop photo editor written in Python with a glass-style dark interface.
Open a photo, edit it with sliders, curves, colour grading and masks, save presets, and export.
It also has a built-in converter that turns almost any image (RAW, HEIC, TIFF, WebP...) into PNG.

## Features

* **Light** - exposure, contrast, highlights, shadows, whites, blacks and a tone curve
* **Color** - temp, tint, vibrance, saturation with colourful slider tracks, plus **Grading** and **Color mix**
* **Blur**, **Effects** and **Detail** tabs (blur / glow / edge blur, texture, clarity, dehaze, vignette, grain, sharpening, noise reduction)
* **Crop** and **Masks** tools
* Live **histogram** - hover to enlarge, tap to switch view (RGB, Luminance, Red, Green, Blue, Waveform)
* **Presets** and **History** drawers, **Before** view, undo / redo
* **PNG converter** - hover the **+** button, then click the popup (RAW, DNG, HEIC, TIFF, WebP, GIF and more)

## What you need

| Thing | Version |
|---|---|
| Python | **3.11 or 3.12 recommended** (3.9 to 3.13 should work; avoid very new releases like 3.14 until all packages publish builds for them) |
| pip | comes with Python |
| Operating system | macOS, Windows or Linux |

Python packages (installed for you by `requirements.txt`): PySide6, opencv-python, numpy, Pillow, rawpy.
Optional: `pillow-heif` for iPhone HEIC photos.

## Step 1 - Install Python

* **macOS** - download from <https://www.python.org/downloads/> (or `brew install python@3.12`).
* **Windows** - download from <https://www.python.org/downloads/>. **Tick "Add python.exe to PATH"** on the first installer screen.
* **Linux** - `sudo apt install python3 python3-venv python3-pip`

Check it worked:

```bash
python3 --version      # macOS / Linux
python --version       # Windows
```

## Step 2 - Get the code

With git:

```bash
git clone https://github.com/YOUR-USERNAME/PyLight.git
cd PyLight
```

Or press **Code > Download ZIP** on the GitHub page, unzip it, and open a terminal in that folder.

## Step 3 - Make a virtual environment (keeps the install tidy)

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

When it is active you will see `(.venv)` at the start of the terminal line.

> Windows says "running scripts is disabled"? Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again. Or use Command Prompt and `.venv\Scripts\activate.bat`.

## Step 4 - Install the packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

For HEIC / iPhone photos (optional):

```bash
pip install pillow-heif
```

## Step 5 - Run it

```bash
python pylight.py
```

(use `python3` on macOS / Linux if `python` is not found)

Next time you only need to activate the environment again (Step 3, second command) and run `python pylight.py`.

## Using it

| Action | Shortcut |
|---|---|
| Open a photo | `Cmd/Ctrl + O` or drag a photo into the window |
| Export | `Cmd/Ctrl + E` |
| Next / previous photo in the folder | `Right` / `Left` |
| Crop | `R` (`Enter` to apply, `Esc` to cancel) |
| Masks | `L` / `O` / `B` |
| Double-click a slider | reset it to default |
| Double-click a slider's number | type an exact value |
| Histogram | hover = enlarge, tap = next view, right-click = pick a view |

Want the normal operating-system title bar instead of the custom traffic-light window?

```bash
# macOS / Linux
PYLIGHT_NATIVE_FRAME=1 python pylight.py

# Windows PowerShell
$env:PYLIGHT_NATIVE_FRAME=1; python pylight.py
```

## Recommended editor: PyCharm

1. Download **PyCharm** (the free Community edition is enough) from <https://www.jetbrains.com/pycharm/download/>.
2. **File > Open** and choose the PyLight folder.
3. If PyCharm offers to create a virtual environment, accept it. Otherwise go to **Settings > Project > Python Interpreter > Add Interpreter > Add Local Interpreter > Existing** and pick `.venv`.
4. Open `requirements.txt` and click **Install requirements** in the yellow bar (or run the `pip install` line in PyCharm's Terminal tab).
5. Right-click `pylight.py` and choose **Run 'pylight'**.

VS Code with the Python extension works well too.

## Project layout

```
PyLight/
├── pylight.py        main window + editing logic (run this)
├── engine.py         image-processing engine (light, colour, blur, detail...)
├── ui_shell.py       layout, histogram, drawers, tabs, animations
├── ui_kit.py         sliders, icons, image view, slider lists
├── png_convert.py    any-image-to-PNG converter (RAW / HEIC / TIFF ...)
├── assets/
│   └── background.png   window background (optional - a gradient is used if missing)
├── requirements.txt
└── README.md
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'PySide6'` | The virtual environment is not active, or Step 4 was skipped. Activate it and run `pip install -r requirements.txt`. |
| `pip install` fails on `rawpy` or `PySide6` | You are probably on a very new Python. Install Python 3.12 and make the environment again. |
| HEIC photos will not convert | `pip install pillow-heif` (on a Mac, PyLight falls back to the built-in `sips` tool). |
| Window opens but the background is plain | Put your picture at `assets/background.png`. |
| Linux: Qt "xcb" plugin error | `sudo apt install libxcb-cursor0 libxkbcommon-x11-0` |
| Everything is blank on macOS after an update | Re-create the environment (delete `.venv`, repeat Steps 3 and 4). |

## License

Add a license of your choice (for example MIT) - GitHub can create one for you via **Add file > Create new file > LICENSE**.
# PyLight
