"""Persistent user settings — ``config.json`` in the per-user data directory.

Stores the locked calibration region and board options so the app starts ready to
scan without re-calibrating. Best-effort: any I/O problem degrades to defaults
rather than breaking the app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import resources


def settings_path() -> Path:
    return resources.user_data_dir() / "config.json"


def load() -> dict:
    """Read settings; {} when missing or unreadable."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict) -> None:
    """Write settings; silently ignored on failure (persistence is best-effort)."""
    try:
        settings_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def valid_region(value) -> Optional[tuple]:
    """Validate a stored region; returns (x, y, w, h) or None."""
    try:
        x, y, w, h = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if w < 16 or h < 16:
        return None
    return (x, y, w, h)
