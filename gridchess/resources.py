"""Path resolution that works both from source and from a PyInstaller bundle.

- `resource_path()` resolves files shipped inside the app (read-only when frozen).
- `user_data_dir()` / `user_assets_dir()` give a writable per-user location for
  auto-generated piece templates and any future persisted state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import config


def _base_path() -> Path:
    """Directory that shipped resources are relative to.

    When frozen by PyInstaller, data files are unpacked to ``sys._MEIPASS``.
    From source, resources are relative to the project root (parent of this package).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # gridchess/resources.py -> project root is one level up from the package dir.
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource (e.g. ``resource_path('assets')``)."""
    return _base_path().joinpath(*parts)


def user_data_dir() -> Path:
    """Writable per-user data directory, created on demand.

    Windows -> %LOCALAPPDATA%; macOS -> ~/Library/Application Support;
    Linux   -> $XDG_DATA_HOME or ~/.local/share.
    """
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = Path(root) / config.APP_DATA_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_assets_dir() -> Path:
    """Writable assets directory (piece templates), created on demand."""
    path = user_data_dir() / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_assets_dir() -> Path:
    """Assets directory shipped alongside the app (may be empty from source)."""
    return resource_path("assets")
