"""Custom presentation widgets: eval bar, status dot, and macOS-style window controls."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QPropertyAnimation, QRectF, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from .. import config


class SegmentedToggle(QWidget):
    """Premium pill-style segmented control (exclusive two-or-more options).

    Emits ``valueChanged(str)`` with the option's value when the selection changes.
    """

    valueChanged = pyqtSignal(str)

    def __init__(self, options, parent: Optional[QWidget] = None) -> None:
        """``options``: iterable of (value, label) pairs; first one starts selected."""
        super().__init__(parent)
        self.setObjectName("SegmentBox")
        self.setStyleSheet(
            f"""
            QWidget#SegmentBox {{
                background-color: {config.COLOR_SURFACE_2};
                border: 1px solid {config.COLOR_BORDER};
                border-radius: 10px;
            }}
            QWidget#SegmentBox QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                margin: 2px;
                padding: 8px 10px;
                color: {config.COLOR_TEXT_DIM};
                font-weight: 600;
            }}
            QWidget#SegmentBox QPushButton:hover:!checked {{ color: {config.COLOR_TEXT}; }}
            QWidget#SegmentBox QPushButton:checked {{
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #9A8FE6, stop:1 #7D71D2);
                color: #101014;
            }}
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._value: str = ""
        for i, (value, label) in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("segmentValue", value)
            self._group.addButton(btn)
            lay.addWidget(btn, 1)
            if i == 0:
                btn.setChecked(True)
                self._value = value
        self._group.buttonClicked.connect(self._on_clicked)

    def _on_clicked(self, button: QPushButton) -> None:
        value = button.property("segmentValue")
        if value != self._value:
            self._value = value
            self.valueChanged.emit(value)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        """Select ``value`` without emitting valueChanged (programmatic restore)."""
        for btn in self._group.buttons():
            if btn.property("segmentValue") == value:
                btn.setChecked(True)
                self._value = value
                return


class TrafficLightButton(QPushButton):
    """macOS-style round window control (close / minimise / maximise).

    Matte coloured dot that brightens on hover and reveals its glyph (×, −, +).
    The glyph is always present but transparent until :hover — this keeps layout
    stable and needs no event-filter machinery.
    """

    _KINDS = {
        "close": (config.TRAFFIC_CLOSE, config.TRAFFIC_CLOSE_HOVER, "×"),
        "min": (config.TRAFFIC_MIN, config.TRAFFIC_MIN_HOVER, "−"),
        "max": (config.TRAFFIC_MAX, config.TRAFFIC_MAX_HOVER, "+"),
    }

    def __init__(self, kind: str, parent: Optional[QWidget] = None) -> None:
        base, hover, glyph = self._KINDS[kind]
        super().__init__(glyph, parent)
        self.setFixedSize(14, 14)
        self.setFlat(True)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {base};
                border: 1px solid rgba(0, 0, 0, 70);
                border-radius: 7px;
                color: transparent;
                font: 700 10px "Segoe UI";
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {hover};
                color: rgba(25, 20, 20, 220);
            }}
            QPushButton:pressed {{
                background-color: {base};
            }}
            """
        )


class EvalBar(QWidget):
    """Vertical evaluation bar, White at the bottom (streaming convention).

    Accepts centipawns / mate from White's perspective, converts to a win-probability
    fill, and animates smoothly between values. Also renders a compact numeric label.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(46)
        self._fill = 0.5           # fraction shown as White (0..1), animated property
        self._label = "0.0"
        self._anim = QPropertyAnimation(self, b"fill", self)
        self._anim.setDuration(360)

    # animated property ------------------------------------------------- #
    def _get_fill(self) -> float:
        return self._fill

    def _set_fill(self, value: float) -> None:
        self._fill = max(0.0, min(1.0, float(value)))
        self.update()

    fill = pyqtProperty(float, fget=_get_fill, fset=_set_fill)

    # public API -------------------------------------------------------- #
    def set_evaluation(self, cp: Optional[int], mate: Optional[int]) -> None:
        """Update the bar from a White-perspective cp/mate value."""
        if mate is not None:
            target = 1.0 if mate > 0 else 0.0
            self._label = f"M{abs(mate)}"
        elif cp is not None:
            # Logistic win-probability mapping (~+4 pawns ≈ 94% for White).
            target = 1.0 / (1.0 + math.exp(-0.004 * cp))
            self._label = f"{cp / 100.0:+.1f}"
        else:
            target = 0.5
            self._label = "–"
        self._animate_to(target)

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._fill)
        self._anim.setEndValue(max(0.0, min(1.0, target)))
        self._anim.start()

    # painting ---------------------------------------------------------- #
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = 10.0
        rect = QRectF(0, 0, w, h)

        # Black background (top portion).
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0D0D0D"))
        p.drawRoundedRect(rect, radius, radius)

        # White fill grows from the bottom.
        fill_h = h * self._fill
        white_rect = QRectF(0, h - fill_h, w, fill_h)
        grad = QLinearGradient(0, h - fill_h, 0, h)
        grad.setColorAt(0.0, QColor("#F5F5F7"))
        grad.setColorAt(1.0, QColor("#D8D8DE"))
        p.save()
        clip_path = _rounded_path(rect, radius)
        p.setClipPath(clip_path)
        p.setBrush(grad)
        p.drawRect(white_rect)
        p.restore()

        # Midline marker at the 50% point.
        p.setPen(QPen(QColor(config.COLOR_ACCENT), 1.4))
        mid_y = h / 2.0
        p.drawLine(int(w * 0.15), int(mid_y), int(w * 0.85), int(mid_y))

        # Numeric label — dark on the white side, light on the black side.
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        label_on_white = self._fill >= 0.5
        p.setPen(QColor("#121212") if label_on_white else QColor("#EDEDF0"))
        label_rect = (
            QRectF(0, h - 22, w, 20) if label_on_white else QRectF(0, 2, w, 20)
        )
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


def _rounded_path(rect: QRectF, radius: float):
    from PyQt6.QtGui import QPainterPath
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class StatusDot(QWidget):
    """Small coloured status indicator with three states: idle / busy / online / error."""

    _COLORS = {
        "idle": config.COLOR_TEXT_DIM,
        "busy": config.COLOR_WARN,
        "online": config.COLOR_GOOD,
        "error": config.COLOR_BAD,
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._state = "idle"

    def set_state(self, state: str) -> None:
        if state not in self._COLORS:
            state = "idle"
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._COLORS[self._state])
        # Soft halo.
        halo = QColor(color)
        halo.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(0, 0, 14, 14)
        p.setBrush(color)
        p.drawEllipse(3, 3, 8, 8)
        p.end()
