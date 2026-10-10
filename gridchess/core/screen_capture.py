"""Fast screen-region capture via `mss`, returned as an OpenCV-friendly BGR array."""

from __future__ import annotations

from typing import Optional

import numpy as np

try:
    import mss  # type: ignore
except ImportError:  # pragma: no cover - dependency surfaced at runtime
    mss = None  # noqa: N816


class ScreenCapture:
    """Thin wrapper around a persistent `mss` instance.

    A single `mss.mss()` handle is reused across grabs (creating one per call is
    comparatively expensive), which keeps the Scan action snappy during a stream.
    """

    def __init__(self) -> None:
        if mss is None:
            raise RuntimeError(
                "The 'mss' package is required for screen capture. "
                "Install it with: pip install mss"
            )
        self._sct = mss.mss()

    def grab(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        """Capture a screen region and return it as a BGR uint8 array (H, W, 3).

        Coordinates are in virtual-desktop pixels (multi-monitor aware).
        """
        if w <= 0 or h <= 0:
            raise ValueError("Capture region must have positive width and height.")
        monitor = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        shot = self._sct.grab(monitor)
        # mss returns a BGRA buffer; take it directly and drop the alpha channel to
        # get BGR, which is OpenCV's native ordering.
        arr = np.array(shot, dtype=np.uint8)  # shape (h, w, 4) BGRA
        return arr[:, :, :3].copy()

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass

    def __del__(self) -> None:  # best-effort cleanup
        self.close()
