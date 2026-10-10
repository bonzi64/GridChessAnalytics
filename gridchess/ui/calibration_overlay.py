"""CalibrationOverlay — a frameless, translucent full-desktop window for selecting the
screen region that contains a static chess diagram.

The user drags a rubber-band rectangle over the board; on release the region is emitted
as ``(x, y, w, h)`` in virtual-desktop pixels. Esc cancels.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .. import config


class CalibrationOverlay(QWidget):
    """Full-desktop selector. Emits ``regionSelected(x, y, w, h)`` on completion."""

    regionSelected = pyqtSignal(int, int, int, int)
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._selecting = False
        self._cover_virtual_desktop()

    def _cover_virtual_desktop(self) -> None:
        """Size the overlay to span every connected screen."""
        geo = QRect()
        for screen in QGuiApplication.screens():
            geo = geo.united(screen.geometry())
        self.setGeometry(geo)
        self._virtual_origin = geo.topLeft()

    # -- interaction ---------------------------------------------------- #
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._selecting:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            rect = self._selection_rect()
            if rect.width() >= 16 and rect.height() >= 16:
                # Translate widget-local coords to global virtual-desktop pixels.
                gx = rect.x() + self._virtual_origin.x()
                gy = rect.y() + self._virtual_origin.y()
                self.regionSelected.emit(gx, gy, rect.width(), rect.height())
                self.close()
            else:
                # Too small — treat as an accidental click, keep the overlay open.
                self._origin = self._current = None
                self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def _selection_rect(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    # -- painting ------------------------------------------------------- #
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = self.rect()

        # Dim the whole desktop.
        p.fillRect(full, QColor(10, 12, 18, 120))

        rect = self._selection_rect()
        if rect.isNull() or rect.width() == 0:
            self._draw_hint(p, full)
            p.end()
            return

        # Punch a clear "hole" over the selected board.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(rect, Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Selection border + 8x8 preview grid.
        accent = QColor(config.COLOR_ACCENT)
        p.setPen(QPen(accent, 2))
        p.drawRect(rect)
        self._draw_preview_grid(p, rect)

        # Dimension readout near the top-left corner of the selection.
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.setPen(QColor(config.COLOR_TEXT))
        badge = f"{rect.width()} × {rect.height()} px"
        p.drawText(rect.x() + 6, max(rect.y() - 8, 14), badge)
        p.end()

    def _draw_preview_grid(self, p: QPainter, rect: QRect) -> None:
        pen = QPen(QColor(config.COLOR_ACCENT))
        pen.setWidthF(0.8)
        pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)
        for i in range(1, config.GRID_SIZE):
            x = rect.x() + rect.width() * i / config.GRID_SIZE
            y = rect.y() + rect.height() * i / config.GRID_SIZE
            p.drawLine(int(x), rect.y(), int(x), rect.y() + rect.height())
            p.drawLine(rect.x(), int(y), rect.x() + rect.width(), int(y))

    def _draw_hint(self, p: QPainter, full: QRect) -> None:
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.DemiBold))
        p.setPen(QColor(config.COLOR_TEXT))
        p.drawText(
            full,
            Qt.AlignmentFlag.AlignCenter,
            "Przeciągnij prostokąt nad diagramem szachowym\n(Esc — anuluj)",
        )
