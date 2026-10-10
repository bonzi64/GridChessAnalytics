# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for GridChess Analytics — one-file, windowed (.exe).

Build:
    pip install pyinstaller
    pyinstaller gridchess.spec
    # -> dist/GridChessAnalytics.exe   (single stable file, no console)

The spec auto-generates the piece templates before packaging (best-effort) and bundles
the assets/ folder plus any QSS style files, so the .exe works with zero manual setup.
"""

import importlib.util
import os
import subprocess
import sys

from PyInstaller.utils.hooks import collect_submodules

# --------------------------------------------------------------------------- #
#  Pre-build: ensure piece templates exist in ./assets so they get bundled.
#  If real templates (extracted from a board screenshot) are already present, keep
#  them untouched — only fall back to generating synthetic glyphs when assets/ is empty.
# --------------------------------------------------------------------------- #
def _assets_ready(directory):
    if not os.path.isdir(directory):
        return False
    need = ["wP.png", "wR.png", "wN.png", "wB.png", "wQ.png", "wK.png"]
    return all(os.path.exists(os.path.join(directory, f)) for f in need)


if _assets_ready("assets"):
    print("[spec] Wykryto realne szablony w assets/ — zostawiam bez zmian.")
else:
    try:
        subprocess.run(
            [sys.executable, os.path.join("tools", "generate_assets.py")],
            check=False,
        )
    except Exception as exc:  # never let asset generation break the build
        print(f"[spec] Ostrzezenie: nie udalo sie wygenerowac assetow: {exc}")

# --------------------------------------------------------------------------- #
#  Data files: the whole assets/ folder and any QSS style files under ui/.
#  (Styles currently live in ui/style.py as generated QSS; the glob below still
#   bundles any standalone *.qss that may be added later.)
# --------------------------------------------------------------------------- #
datas = []
if os.path.isdir("assets"):
    datas.append(("assets", "assets"))

ui_dir = os.path.join("gridchess", "ui")
if os.path.isdir(ui_dir):
    for name in os.listdir(ui_dir):
        if name.endswith(".qss"):
            datas.append((os.path.join(ui_dir, name), ui_dir))

# --------------------------------------------------------------------------- #
#  Hidden imports: force-include critical libraries so PyInstaller's static
#  analysis cannot drop them.
# --------------------------------------------------------------------------- #
hiddenimports = collect_submodules("gridchess") + [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "cv2",
    "mss",
    "numpy",
    "chess",          # python-chess
]
# We use urllib (stdlib) for HTTP, but include requests too if it is installed,
# per the build requirements, so it is never dropped.
if importlib.util.find_spec("requests") is not None:
    hiddenimports.append("requests")

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-file build: all binaries/zip/datas are folded into a single EXE (no COLLECT).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GridChessAnalytics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX can corrupt Qt/OpenCV DLLs — off for a stable one-file exe
    runtime_tmpdir=None,
    console=False,        # windowed application (no console window)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
