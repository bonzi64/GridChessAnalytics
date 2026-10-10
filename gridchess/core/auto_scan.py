"""AutoScanThread — the continuous scanning loop, isolated in its own QThread.

Design goals (in response to the auto-scan "falls asleep" bug):
  * The loop NEVER touches the GUI directly — all communication goes through
    pyqtSignals, which Qt delivers safely to the main thread.
  * Every cycle is wrapped in its own try/except: a single bad frame / capture
    hiccup logs a heartbeat and the loop keeps running. Nothing can silently kill it.
  * The thread owns a private ``ScreenCapture`` (mss) instance — mss handles are not
    thread-safe to share, and the main thread keeps its own for manual scans.
  * The calibrated region is passed in ONCE and treated as immutable for the whole
    run ("locked calibration") — the loop only ever crops that fixed rectangle.
    Changing region/side/flip means restarting the thread with new parameters.
  * Position change detection uses :func:`gridchess.core.fen.position_key`, i.e. the
    FEN placement + side-to-move only, ignoring the bookkeeping counters.
"""

from __future__ import annotations

import time
from typing import Tuple

from PyQt6.QtCore import QThread, pyqtSignal

from .. import config
from . import fen as fenlib
from .board_analyzer import BoardAnalyzer
from .screen_capture import ScreenCapture


class AutoScanThread(QThread):
    """Continuously scan a locked screen region and report position changes."""

    # Emitted when the detected position (placement+side) differs from the last one.
    positionChanged = pyqtSignal(object)   # -> AnalysisResult
    # One line per cycle (and lifecycle events) for console/file logging.
    heartbeat = pyqtSignal(str)

    def __init__(
        self,
        region: Tuple[int, int, int, int],
        analyzer: BoardAnalyzer,
        side_to_move: str,
        flipped: bool,
        interval_ms: int = config.AUTO_SCAN_INTERVAL_MS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._region = tuple(int(v) for v in region)
        self._analyzer = analyzer
        self._side = side_to_move
        self._flipped = bool(flipped)
        self._interval = max(100, int(interval_ms))

    def stop(self, timeout_ms: int = 3000) -> None:
        """Cooperatively stop the loop and wait for the thread to finish."""
        self.requestInterruption()
        self.wait(timeout_ms)

    # -- QThread entry --------------------------------------------------- #
    def run(self) -> None:  # noqa: D401 - Qt override
        log = self.heartbeat.emit
        try:
            capture = ScreenCapture()
        except Exception as exc:
            log(f"start NIEUDANY — brak przechwytywania ekranu: {exc!r}")
            return

        x, y, w, h = self._region
        log(
            f"start — zablokowany region x={x} y={y} w={w} h={h}, "
            f"interwał {self._interval} ms, strona={self._side}, flip={self._flipped}"
        )
        last_key = None
        cycle = 0
        try:
            while not self.isInterruptionRequested():
                cycle += 1
                t0 = time.perf_counter()
                try:
                    frame = capture.grab(x, y, w, h)
                    result = self._analyzer.analyze(
                        frame, side_to_move=self._side, flipped=self._flipped
                    )
                    ms = int((time.perf_counter() - t0) * 1000)
                    key = fenlib.position_key(result.fen)
                    if key != last_key:
                        last_key = key
                        log(
                            f"cykl {cycle}: ZMIANA pozycji "
                            f"({result.detected_pieces} figur, {ms} ms) -> {result.fen}"
                        )
                        self.positionChanged.emit(result)
                    else:
                        log(
                            f"cykl {cycle}: żyję, bez zmian "
                            f"({result.detected_pieces} figur, {ms} ms)"
                        )
                except Exception as exc:
                    # One bad frame must never end the loop.
                    log(f"cykl {cycle}: BŁĄD {exc!r} — pętla działa dalej")
                self.msleep(self._interval)
        finally:
            capture.close()
            log(f"stop po {cycle} cyklach")
