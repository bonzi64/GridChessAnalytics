"""MainPanel — the modern dark side panel that orchestrates the whole app.

Responsibilities:
  * Calibrate  -> spawn CalibrationOverlay, store the board region.
  * Scan       -> capture region, run BoardAnalyzer -> FEN, launch EngineThread,
                  draw the engine's best move as an arrow on the DrawingOverlay.
  * Clear      -> remove arrows from the overlay.
  * Present the eval bar, manual-eval slider, network status, FEN and best line.

The window is frameless with a custom title bar (drag + minimise + close) to match the
rounded, translucent aesthetic requested in the brief.
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import assets_gen, config, resources, settings
from ..core import fen as fenlib
from ..core import uci_engine
from ..core.auto_scan import AutoScanThread
from ..core.board_analyzer import BoardAnalyzer
from ..core.engine_thread import EngineThread
from ..core.screen_capture import ScreenCapture
from .calibration_overlay import CalibrationOverlay
from .drawing_overlay import DrawingOverlay
from .style import build_stylesheet
from .widgets import EvalBar, SegmentedToggle, StatusDot, TrafficLightButton


class MainPanel(QWidget):
    """Top-level control panel window."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("RootPanel")
        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(340, 620)

        # -- runtime state ---------------------------------------------- #
        self._region: Optional[tuple[int, int, int, int]] = None
        self._capture = ScreenCapture()
        self._analyzer: Optional[BoardAnalyzer] = None    # lazy — needs assets ready
        self._engine: Optional[EngineThread] = None
        self._calibration: Optional[CalibrationOverlay] = None
        self._drag_pos: Optional[QPoint] = None
        # State control: the last FEN we actually sent to the engine (anti-spam guard).
        self.last_fen: Optional[str] = None
        # Consecutive cloud misses — past CLOUD_MISS_LIMIT the game is out of book
        # and queries go straight to the local engine (no guaranteed-404 latency).
        self._cloud_misses = 0
        # Which colour the player runs. Drives BOTH the board orientation (chess sites
        # show your colour at the bottom) and the hint side (you scan on your turn).
        self._player_color = "w"

        # Persistent click-through arrow overlay.
        self._overlay = DrawingOverlay()

        # Auto-scan worker (created on demand; owns its own mss handle). The GUI only
        # talks to it through queued pyqtSignals — see gridchess/core/auto_scan.py.
        self._auto_thread: Optional[AutoScanThread] = None
        self._log_path = resources.user_data_dir() / "gridchess.log"

        self._build_ui()
        self.setStyleSheet(build_stylesheet())

        # Restore the locked calibration + board options saved in config.json, so the
        # app is ready to scan immediately after start (no re-calibration each run).
        self._load_settings()

    # ================================================================== #
    #  UI construction
    # ================================================================== #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        card = QWidget(objectName="Card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 160))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(14)

        root.addLayout(self._build_titlebar())
        root.addWidget(self._divider())

        # Body: eval bar (left) + controls (right).
        body = QHBoxLayout()
        body.setSpacing(14)

        self.eval_bar = EvalBar()
        body.addWidget(self.eval_bar)

        controls = QVBoxLayout()
        controls.setSpacing(12)
        controls.addLayout(self._build_buttons())
        controls.addWidget(self._build_color_select())
        controls.addWidget(self._build_readout())
        controls.addStretch(1)
        controls.addLayout(self._build_status())
        body.addLayout(controls, 1)

        root.addLayout(body)

    def _build_titlebar(self) -> QHBoxLayout:
        """macOS-style title bar: traffic-light dots on the left, then the title."""
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.setContentsMargins(2, 4, 2, 2)

        btn_close = TrafficLightButton("close")
        btn_close.clicked.connect(self.close)
        btn_min = TrafficLightButton("min")
        btn_min.clicked.connect(self.showMinimized)
        btn_max = TrafficLightButton("max")
        btn_max.clicked.connect(self._toggle_maximize)
        bar.addWidget(btn_close)
        bar.addWidget(btn_min)
        bar.addWidget(btn_max)
        bar.addSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(config.APP_NAME, objectName="Title")
        subtitle = QLabel("Static diagram studio", objectName="Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        bar.addLayout(title_box)
        bar.addStretch(1)
        return bar

    def _toggle_maximize(self) -> None:
        """Green traffic light: expand to full screen size or restore."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _build_buttons(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(8)

        self.btn_calibrate = QPushButton("◱  Kalibracja")
        self.btn_calibrate.clicked.connect(self.on_calibrate)

        self.btn_scan = QPushButton("⟲  Skanuj pozycję", objectName="Primary")
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_scan.setEnabled(False)

        self.btn_auto = QPushButton("▶  Auto-skan (500 ms)")
        self.btn_auto.setCheckable(True)
        self.btn_auto.toggled.connect(self.on_toggle_autoscan)
        self.btn_auto.setEnabled(False)

        self.btn_clear = QPushButton("✕  Wyczyść strzałki")
        self.btn_clear.clicked.connect(self.on_clear)

        box.addWidget(self.btn_calibrate)
        box.addWidget(self.btn_scan)
        box.addWidget(self.btn_auto)
        box.addWidget(self.btn_clear)
        return box

    def _build_color_select(self) -> QWidget:
        """One selector instead of two coupled checkboxes: the player's colour drives
        both the board orientation and the side hints are generated for."""
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(QLabel("GRAM KOLOREM", objectName="SectionLabel"))
        self.color_select = SegmentedToggle([("w", "♔  Białe"), ("b", "♚  Czarne")])
        self.color_select.valueChanged.connect(self._on_color_changed)
        lay.addWidget(self.color_select)
        return wrap

    def _build_readout(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(QLabel("POZYCJA (FEN)", objectName="SectionLabel"))
        self.fen_label = QLabel("—", objectName="FenValue")
        self.fen_label.setWordWrap(True)
        self.fen_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        lay.addWidget(self.fen_label)

        lay.addWidget(QLabel("NAJLEPSZA LINIA", objectName="SectionLabel"))
        self.best_line_label = QLabel("—", objectName="BestLine")
        self.best_line_label.setWordWrap(True)
        lay.addWidget(self.best_line_label)
        return wrap

    def _build_status(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.status_dot = StatusDot()
        self.status_label = QLabel("Gotowy — najpierw skalibruj obszar")
        self.status_label.setObjectName("Subtitle")
        row.addWidget(self.status_dot)
        row.addWidget(self.status_label, 1)
        return row

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {config.COLOR_BORDER}; background: {config.COLOR_BORDER};")
        line.setFixedHeight(1)
        return line

    # ================================================================== #
    #  Actions
    # ================================================================== #
    def on_calibrate(self) -> None:
        """Show the region selector overlay."""
        self._set_status("busy", "Zaznacz diagram na ekranie…")
        self._calibration = CalibrationOverlay()
        self._calibration.regionSelected.connect(self._on_region_selected)
        self._calibration.cancelled.connect(
            lambda: self._set_status("idle", "Kalibracja anulowana")
        )
        # show() (not showFullScreen) preserves the virtual-desktop geometry so the
        # selector spans every monitor; activate it so Esc/key events are received.
        self._calibration.show()
        self._calibration.raise_()
        self._calibration.activateWindow()
        self._calibration.setFocus()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        """Lock the calibrated region: fixed coordinates, persisted to config.json.

        From here on the region is immutable — nothing in the scanning pipeline ever
        re-detects or resets it; scans only ever crop this exact rectangle.
        """
        self._region = (x, y, w, h)
        self._overlay.set_board_geometry(x, y, w, h, flipped=self._player_color == "b")
        # A new region invalidates state control so the next scan always evaluates.
        self.last_fen = None
        self.btn_scan.setEnabled(True)
        self.btn_auto.setEnabled(True)
        self._save_settings()
        self._log(f"kalibracja zablokowana: x={x} y={y} w={w} h={h} (zapisano w config.json)")
        self._restart_auto_if_running()
        self._set_status("online", f"Obszar {w}×{h}px zablokowany — gotowy do skanu")

    def on_scan(self) -> None:
        """Manual Scan: capture, detect, and always evaluate (explicit user action)."""
        if not self._region:
            self._set_status("error", "Brak skalibrowanego obszaru")
            return
        try:
            result = self._scan_current_position()
        except Exception as exc:  # capture/analysis errors surfaced to the user
            self._log(f"skan ręczny: BŁĄD {exc!r}")
            self._set_status("error", f"Błąd skanowania: {exc}")
            return
        if result is not None:
            self._log(f"skan ręczny: {result.detected_pieces} figur -> {result.fen}")
            self._on_auto_position(result)

    def on_toggle_autoscan(self, checked: bool) -> None:
        """Start/stop the continuous auto-scan worker thread."""
        if checked:
            if not self._region:
                self.btn_auto.setChecked(False)
                self._set_status("error", "Najpierw skalibruj obszar")
                return
            try:
                self._ensure_analyzer()
            except Exception as exc:
                self.btn_auto.setChecked(False)
                self._set_status("error", f"Błąd analizatora: {exc}")
                return
            self._start_auto()
        else:
            self._stop_auto()
            self._set_status(
                "online" if self._region else "idle", "Auto-skan zatrzymany"
            )

    # ================================================================== #
    #  Auto-scan worker lifecycle
    # ================================================================== #
    def _start_auto(self) -> None:
        """Spawn the worker with the LOCKED region and current board options."""
        self._stop_auto(quiet=True)
        # Reset state control so the worker's first detection always evaluates.
        self.last_fen = None
        self._auto_thread = AutoScanThread(
            region=self._region,
            analyzer=self._analyzer,
            side_to_move=self._player_color,
            flipped=self._player_color == "b",
            parent=self,
        )
        self._auto_thread.positionChanged.connect(self._on_auto_position)
        self._auto_thread.heartbeat.connect(self._on_auto_heartbeat)
        self._auto_thread.start()
        self.btn_auto.setText("⏸  Zatrzymaj auto-skan")
        self._set_status("busy", "Auto-skan aktywny — śledzę zmiany pozycji…")

    def _stop_auto(self, quiet: bool = False) -> None:
        thread = self._auto_thread
        if thread is None:
            return
        try:
            thread.positionChanged.disconnect()
            thread.heartbeat.disconnect()
        except (TypeError, RuntimeError):
            pass
        thread.stop()
        self._auto_thread = None
        if not quiet:
            self.btn_auto.setText("▶  Auto-skan (500 ms)")
            self._log("auto-skan zatrzymany")

    def _restart_auto_if_running(self) -> None:
        """Apply new region/side/flip to a running worker (its params are immutable)."""
        if self._auto_thread is not None:
            self._log("restart auto-skanu z nowymi parametrami")
            self._start_auto()

    def _on_auto_position(self, result) -> None:
        """Worker detected a new position — update UI and query the engine."""
        # Starting position = new game = back in book: re-arm cloud-first queries.
        if result.fen.split(" ")[0] == fenlib.STARTING_PLACEMENT:
            self._cloud_misses = 0
        self.last_fen = result.fen
        self.fen_label.setText(result.fen)
        self._set_status(
            "busy", f"Wykryto {result.detected_pieces} figur — analiza w chmurze…"
        )
        self.best_line_label.setText("…")
        self._start_engine(result.fen)

    def _on_auto_heartbeat(self, message: str) -> None:
        self._log(f"[auto] {message}")

    # ================================================================== #
    #  Settings persistence + logging
    # ================================================================== #
    def _log(self, message: str) -> None:
        """Console print + append to gridchess.log (windowed exe has no console)."""
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _load_settings(self) -> None:
        data = settings.load()
        # Player colour, with migration from the legacy two-checkbox settings.
        color = data.get("player_color")
        if color not in ("w", "b"):
            color = "b" if data.get("flipped") else "w"
        self._player_color = color
        self.color_select.set_value(color)  # silent — no re-save/restart during init
        region = settings.valid_region(data.get("region"))
        if region:
            x, y, w, h = region
            self._region = region
            self._overlay.set_board_geometry(x, y, w, h, flipped=color == "b")
            self.btn_scan.setEnabled(True)
            self.btn_auto.setEnabled(True)
            self._log(f"wczytano kalibrację z config.json: x={x} y={y} w={w} h={h}")
            self._set_status("online", f"Kalibracja wczytana ({w}×{h}px) — gotowy")

    def _save_settings(self) -> None:
        settings.save({
            "region": list(self._region) if self._region else None,
            "player_color": self._player_color,
        })

    def _on_color_changed(self, color: str) -> None:
        """The player's colour drives orientation (flip) AND the hint side at once."""
        self._player_color = color
        if self._region:
            x, y, w, h = self._region
            self._overlay.set_board_geometry(x, y, w, h, flipped=color == "b")
        self._overlay.clear()  # arrows mapped for the old orientation are now wrong
        self.last_fen = None
        self._save_settings()
        self._restart_auto_if_running()
        name = "czarnymi" if color == "b" else "białymi"
        self._log(f"zmiana koloru gracza: gram {name}")
        self._set_status(
            "online" if self._region else "idle",
            f"Grasz {name} — plansza i podpowiedzi ustawione",
        )

    def _scan_current_position(self):
        """Capture the calibrated region and run board analysis. Returns the
        :class:`AnalysisResult` or ``None`` when no region is set."""
        if not self._region:
            return None
        self._ensure_analyzer()
        x, y, w, h = self._region
        image = self._capture.grab(x, y, w, h)
        return self._analyzer.analyze(
            image,
            side_to_move=self._player_color,
            flipped=self._player_color == "b",
        )

    def on_clear(self) -> None:
        self._overlay.clear()
        self.best_line_label.setText("—")
        # Forget the last position so an identical re-scan will evaluate again.
        self.last_fen = None
        self._set_status("online" if self._region else "idle", "Strzałki wyczyszczone")

    # ================================================================== #
    #  Engine
    # ================================================================== #
    def _stop_engine(self) -> None:
        """Retire the in-flight query cooperatively — no terminate().

        Signals are disconnected (and cancel() mutes any late emission), the local
        search is cut short via UCI ``stop``, and the thread finishes on its own
        within the move time, cleaning up with deleteLater. Cooperative shutdown is
        required now that the local engine is a persistent shared process — killing
        a thread mid-protocol could leave it desynchronised.
        """
        engine = self._engine
        if engine is None:
            return
        try:
            engine.resultReady.disconnect()
            engine.failed.disconnect()
        except (TypeError, RuntimeError):
            pass  # nothing connected / already gone
        engine.cancel()
        engine.finished.connect(engine.deleteLater)
        self._engine = None

    def _start_engine(self, fen: str) -> None:
        # Retire any previous query to prevent races, then launch the new one.
        self._stop_engine()
        skip_cloud = self._cloud_misses >= config.CLOUD_MISS_LIMIT
        if skip_cloud:
            self._log(
                f"chmura pomijana ({self._cloud_misses} chybień z rzędu) — "
                "od razu lokalny silnik"
            )
        self._engine = EngineThread(fen, skip_cloud=skip_cloud, parent=self)
        self._engine.resultReady.connect(self._on_engine_result)
        self._engine.failed.connect(self._on_engine_failed)
        self._engine.start()

    def _on_engine_result(self, data: dict) -> None:
        # Ignore stale results from a thread we already replaced.
        if self.sender() is not None and self.sender() is not self._engine:
            return
        self._log(
            f"silnik[{data.get('source')}]: ruch={data.get('best_move_uci')} "
            f"cp={data.get('cp')} mate={data.get('mate')} gł={data.get('depth')} "
            f"czas={data.get('elapsed_ms')} ms"
        )
        # Out-of-book tracking: a cloud hit re-arms cloud-first; a local result that
        # had to fall through a cloud 404 counts towards skipping the cloud entirely.
        if data.get("source") == "cloud":
            self._cloud_misses = 0
        elif data.get("cloud_missed"):
            self._cloud_misses += 1
        best = data.get("best_move_uci")
        pv = data.get("pv") or []
        cp, mate = data.get("cp"), data.get("mate")

        self.eval_bar.set_evaluation(cp, mate)

        if best:
            self._overlay.add_move_arrow(best)
            self._overlay.show()

        pv_text = " ".join(pv[:6]) if pv else "(brak linii)"
        depth = data.get("depth")
        suffix = f"  ·  gł. {depth}" if depth else ""
        local = data.get("source") == "local"
        if local:
            suffix += "  ·  Stockfish"
        self.best_line_label.setText(pv_text + suffix)
        self._set_status(
            "online", "Analiza gotowa (lokalny Stockfish)" if local else "Analiza gotowa"
        )

    def _on_engine_failed(self, message: str) -> None:
        # Ignore stale failures from a thread we already replaced.
        if self.sender() is not None and self.sender() is not self._engine:
            return
        self._log(f"silnik: NIEPOWODZENIE — {message}")
        # A stale arrow from the previous position is worse than none — clear it.
        self._overlay.clear()
        self.best_line_label.setText("—")
        self._set_status("error", message)

    # ================================================================== #
    #  Helpers
    # ================================================================== #
    def _ensure_analyzer(self) -> None:
        """Lazily create the BoardAnalyzer once assets are guaranteed on disk."""
        if self._analyzer is None:
            assets_dir = assets_gen.resolve_assets_dir()
            self._analyzer = BoardAnalyzer(assets_dir)

    def _set_status(self, state: str, message: str) -> None:
        self.status_dot.set_state(state)
        self.status_label.setText(message)

    # ================================================================== #
    #  Frameless window dragging
    # ================================================================== #
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None

    # ================================================================== #
    #  Teardown
    # ================================================================== #
    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_auto(quiet=True)
        self._stop_engine()
        uci_engine.shutdown()  # quit the persistent Stockfish process
        self._overlay.close()
        if self._calibration is not None:
            self._calibration.close()
        self._capture.close()
        QApplication.quit()
        super().closeEvent(event)
