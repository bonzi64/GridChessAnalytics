"""GridChess Analytics — application entry point (PyInstaller-ready).

Boot sequence:
    1. Enable High-DPI-friendly rendering.
    2. Create the QApplication.
    3. Ensure piece templates exist (generated on first run into user data dir).
    4. Show the main control panel.

Run from source:   python main.py
Package:           pyinstaller gridchess.spec
"""

from __future__ import annotations

import sys


def _run_detect(argv) -> int:
    """Headless: analyse a board image with the bundled templates and print the FEN.

    Usage: --detect <image.png> [--black] [--flip]. No GUI / Qt needed — handy for
    verifying a build's bundled templates against a screenshot.
    """
    import cv2

    from gridchess import assets_gen
    from gridchess.core.board_analyzer import BoardAnalyzer

    try:
        path = argv[argv.index("--detect") + 1]
    except (ValueError, IndexError):
        print("Użycie: --detect <obraz.png> [--black] [--flip]", file=sys.stderr)
        return 2
    image = cv2.imread(path)
    if image is None:
        print(f"Nie można wczytać obrazu: {path}", file=sys.stderr)
        return 1
    analyzer = BoardAnalyzer(assets_gen.resolve_assets_dir())
    side = "b" if "--black" in argv else "w"
    res = analyzer.analyze(image, side_to_move=side, flipped="--flip" in argv)
    print(f"figur: {res.detected_pieces}  FEN: {res.fen}")
    return 0


def _install_excepthook() -> None:
    """Log unhandled exceptions instead of letting PyQt6 abort the process.

    With the DEFAULT sys.excepthook, PyQt6 treats an unhandled Python exception in
    a Qt slot as fatal (qFatal -> silent process abort — the window just vanishes).
    Installing a custom hook downgrades that to a logged error: the traceback goes
    to stderr AND to gridchess.log in the user data directory, and the app lives on.
    """
    import traceback
    from datetime import datetime

    def hook(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[GridChess] NIEOBSŁUŻONY WYJĄTEK:\n{text}", file=sys.stderr, flush=True)
        try:
            from gridchess import resources

            log_path = resources.user_data_dir() / "gridchess.log"
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] UNHANDLED\n{text}")
        except Exception:
            pass

    sys.excepthook = hook


def _run_analyze(argv) -> int:
    """Headless: evaluate a FEN through the full engine chain (cloud -> local).

    Usage: --analyze "<fen>". Prints the source, best move, eval and PV — handy for
    verifying cloud availability and the local Stockfish fallback from a terminal.
    """
    from PyQt6.QtCore import QCoreApplication, QTimer

    from gridchess.core.engine_thread import EngineThread

    try:
        fen = argv[argv.index("--analyze") + 1]
    except (ValueError, IndexError):
        print('Użycie: --analyze "<fen>"', file=sys.stderr)
        return 2

    app = QCoreApplication(argv[:1])
    outcome: dict = {}

    def on_result(data: dict) -> None:
        outcome.update(data)
        app.quit()

    def on_failed(message: str) -> None:
        outcome["error"] = message
        app.quit()

    thread = EngineThread(fen)
    thread.resultReady.connect(on_result)
    thread.failed.connect(on_failed)
    thread.start()
    QTimer.singleShot(30000, app.quit)
    app.exec()
    thread.wait(2000)

    if "error" in outcome:
        print(f"BŁĄD: {outcome['error']}", file=sys.stderr)
        return 1
    if not outcome:
        print("BŁĄD: przekroczono limit czasu analizy.", file=sys.stderr)
        return 1
    print(
        f"źródło={outcome.get('source')}  ruch={outcome.get('best_move_uci')}  "
        f"cp={outcome.get('cp')}  mate={outcome.get('mate')}  gł={outcome.get('depth')}\n"
        f"pv: {' '.join(outcome.get('pv', [])[:8])}"
    )
    return 0


def main() -> int:
    # UTF-8 console so any Polish diagnostic text doesn't crash a cp1252 terminal.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    _install_excepthook()

    # Headless modes (no GUI) — useful for verifying templates and the engine chain.
    if "--detect" in sys.argv:
        return _run_detect(sys.argv)
    if "--analyze" in sys.argv:
        return _run_analyze(sys.argv)

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication

    # Crisp rendering on fractional-scaling / multi-monitor setups.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    from gridchess import assets_gen, config
    from gridchess.ui.main_panel import MainPanel

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.ORG_NAME)
    # Keep the app alive while only always-on-top tool windows are visible.
    app.setQuitOnLastWindowClosed(True)

    # Generate piece templates up front so the first Scan is instant. Non-fatal on
    # failure — the analyzer will simply report zero detected pieces.
    try:
        assets_gen.resolve_assets_dir()
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[GridChess] Ostrzeżenie: nie udało się przygotować szablonów figur: {exc}")

    panel = MainPanel()

    # Non-interactive smoke test: construct everything, then quit immediately. Lets a
    # frozen build be verified (imports, assets, UI wiring) without opening a window.
    if "--selftest" in sys.argv:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, app.quit)
        app.exec()
        print("[selftest] OK — GridChess uruchamia się poprawnie.")
        return 0

    panel.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
