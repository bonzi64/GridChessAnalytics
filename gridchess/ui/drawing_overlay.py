"""DrawingOverlay — a transparent, click-through, always-on-top layer that renders
smooth antialiased instructional arrows (A -> B) over the calibrated board.

Click-through is achieved with two layers of defence (see decisions.md D6):
  * Qt: ``WindowTransparentForInput`` + ``WA_TransparentForMouseEvents``.
  * Win32: extended styles ``WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE``
    applied via ctypes, which reliably passes mouse events through to windows below.
"""

from __future__ import annotations

import math
import sys
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QWidget

from .. import config

# (from_square, to_square) in algebraic notation, e.g. ("e2", "e4").
Arrow = Tuple[str, str]


class BoardGeometry:
    """Maps algebraic squares to screen pixels given a calibrated region."""

    def __init__(self, x: int, y: int, w: int, h: int, flipped: bool = False) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h
        self.flipped = flipped

    @property
    def square_w(self) -> float:
        return self.w / config.GRID_SIZE

    @property
    def square_h(self) -> float:
        return self.h / config.GRID_SIZE

    def square_center(self, square: str) -> QPointF:
        """Global-pixel centre of a square such as 'e4'."""
        file_idx = "abcdefgh".index(square[0].lower())
        rank = int(square[1])
        if self.flipped:
            col = config.GRID_SIZE - 1 - file_idx
            row = rank - 1
        else:
            col = file_idx
            row = config.GRID_SIZE - rank
        cx = self.x + (col + 0.5) * self.square_w
        cy = self.y + (row + 0.5) * self.square_h
        return QPointF(cx, cy)


class DrawingOverlay(QWidget):
    """Full-desktop, input-transparent arrow renderer."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._geometry: Optional[BoardGeometry] = None
        self._arrows: List[Arrow] = []
        self._cover_virtual_desktop()

    def _cover_virtual_desktop(self) -> None:
        geo = QRect()
        for screen in QGuiApplication.screens():
            geo = geo.united(screen.geometry())
        self.setGeometry(geo)
        self._virtual_origin = geo.topLeft()

    # -- public API ----------------------------------------------------- #
    def set_board_geometry(self, x: int, y: int, w: int, h: int, flipped: bool = False) -> None:
        """Register the calibrated board region (global pixels)."""
        self._geometry = BoardGeometry(x, y, w, h, flipped)
        self.update()

    def set_arrows(self, arrows: List[Arrow]) -> None:
        """Replace the set of arrows to draw."""
        self._arrows = list(arrows)
        self.update()

    def add_move_arrow(self, uci_move: str) -> None:
        """Convenience: draw an arrow from a UCI move like 'e2e4' (ignores promotion)."""
        if uci_move and len(uci_move) >= 4:
            self.set_arrows([(uci_move[:2], uci_move[2:4])])

    def clear(self) -> None:
        self._arrows = []
        self.update()

    # -- platform click-through reinforcement --------------------------- #
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_win32_click_through()

    def _apply_win32_click_through(self) -> None:
        """On Windows, force extended styles so clicks always pass through."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes

            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                current
                | WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE,
            )
        except Exception:
            # Non-fatal: the Qt flags already provide click-through on their own.
            pass

    # -- painting ------------------------------------------------------- #
    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._geometry or not self._arrows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for frm, to in self._arrows:
            try:
                self._draw_arrow(p, frm, to)
            except (ValueError, IndexError):
                # Skip malformed square references rather than crashing the overlay.
                continue
        p.end()

    def _draw_arrow(self, p: QPainter, from_sq: str, to_sq: str) -> None:
        geo = self._geometry
        assert geo is not None
        origin = self._virtual_origin
        a = geo.square_center(from_sq) - QPointF(origin.x(), origin.y())
        b = geo.square_center(to_sq) - QPointF(origin.x(), origin.y())

        sq = min(geo.square_w, geo.square_h)
        shaft_w = max(4.0, sq * config.ARROW_WIDTH_RATIO)
        head_len = max(10.0, sq * config.ARROWHEAD_RATIO)

        color = QColor(config.ARROW_COLOR)
        color.setAlpha(config.ARROW_ALPHA)

        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return
        ux, uy = dx / length, dy / length  # unit direction

        # Shorten the shaft so it stops at the base of the arrowhead.
        shaft_end = QPointF(b.x() - ux * head_len, b.y() - uy * head_len)

        # Shaft — rounded caps for a smooth vector look.
        pen = QPen(color, shaft_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, shaft_end)

        # Arrowhead — filled triangle centred on the target square.
        px, py = -uy, ux  # perpendicular
        half = head_len * 0.55
        tip = QPointF(b.x(), b.y())
        left = QPointF(shaft_end.x() + px * half, shaft_end.y() + py * half)
        right = QPointF(shaft_end.x() - px * half, shaft_end.y() - py * half)
        head = QPolygonF([tip, left, right])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        path = QPainterPath()
        path.addPolygon(head)
        path.closeSubpath()
        p.drawPath(path)
