"""Piece-template generation.

Template Matching needs reference silhouettes for the 12 pieces. Rather than ship
binary PNGs, we render them from filled Unicode chess glyphs with QPainter — white
pieces as light silhouettes with a dark outline, black pieces as dark silhouettes with
a light outline — onto a transparent background. Clean, uniform silhouettes are exactly
what TM_CCOEFF_NORMED matches best.

`ensure_assets()` is called on first run (a QApplication must already exist) and writes
any missing templates into a writable per-user directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import config


def _pick_symbol_font() -> str:
    """Choose a font family that carries the chess glyphs for the current platform."""
    if sys.platform.startswith("win"):
        return "Segoe UI Symbol"
    if sys.platform == "darwin":
        return "Apple Symbols"
    return "DejaVu Sans"


def render_piece(fen_letter: str, size: int = config.TEMPLATE_SIZE):
    """Render a single piece to a transparent ``QImage``.

    ``fen_letter`` uppercase -> white piece, lowercase -> black piece.
    """
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import (
        QColor,
        QFont,
        QFontMetricsF,
        QImage,
        QPainter,
        QPainterPath,
        QPen,
    )

    glyph = config.GLYPHS[fen_letter.upper()]
    is_white = fen_letter.isupper()

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    font = QFont(_pick_symbol_font())
    font.setPixelSize(int(size * 0.82))
    metrics = QFontMetricsF(font)

    # Build a vector path for the glyph and centre it in the tile.
    path = QPainterPath()
    text_width = metrics.horizontalAdvance(glyph)
    baseline_x = (size - text_width) / 2.0
    baseline_y = size - (size - metrics.ascent()) / 2.0 - metrics.descent() / 2.0
    path.addText(QPointF(baseline_x, baseline_y), font, glyph)

    if is_white:
        fill = QColor("#f4f6ff")
        outline = QColor("#0e0f16")
    else:
        fill = QColor("#12141c")
        outline = QColor("#e6e9f2")

    painter.fillPath(path, fill)
    pen = QPen(outline, max(1.5, size * 0.02))
    painter.strokePath(path, pen)
    painter.end()
    return image


def ensure_assets(target_dir: Optional[Path] = None, force: bool = False) -> Path:
    """Generate any missing piece templates into ``target_dir``.

    Returns the directory that ended up holding the templates. Requires a live
    ``QGuiApplication`` (present at runtime after the app boots).
    """
    from . import resources

    if target_dir is None:
        target_dir = resources.user_assets_dir()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for base in config.PIECE_CODES:
        for fen_letter in (base.upper(), base.lower()):
            out_path = target_dir / config.template_filename(fen_letter)
            if out_path.exists() and not force:
                continue
            image = render_piece(fen_letter)
            image.save(str(out_path), "PNG")
    return target_dir


# Which square (row, col) each piece is sampled from in a STANDARD starting position
# (White on the bottom, files a..h = columns 0..7). Chosen to avoid squares that carry
# board coordinate overlays (the a-file rank digits and the rank-1 file letters on
# lichess/chess.com), which would otherwise contaminate the templates. Black back-rank
# and pawn samples are fully coordinate-free; white back-rank pieces only exist on rank 1,
# so their labels are handled by the square inset instead.
STARTING_SAMPLES = {
    "wP": (6, 1), "wR": (7, 7), "wN": (7, 6), "wB": (7, 5), "wQ": (7, 3), "wK": (7, 4),
    "bP": (1, 1), "bR": (0, 7), "bN": (0, 6), "bB": (0, 5), "bQ": (0, 3), "bK": (0, 4),
}


def extract_templates_from_board(board_bgr, out_dir, flipped: bool = False) -> int:
    """Cut real piece templates from a STARTING-POSITION board image.

    Slices the board into 8x8 and saves the piece standing on each known starting
    square as a template (wP.png … bK.png). The result matches the exact theme shown
    on screen — far more reliable than synthetic glyphs for custom piece sets.

    Parameters
    ----------
    board_bgr:
        BGR image cropped to exactly the 8x8 board (no surrounding UI).
    out_dir:
        Directory to write the 12 PNG templates into.
    flipped:
        True if the board is shown with Black on the bottom; the image is rotated
        180° so the standard sampling map applies.

    Returns the number of templates written.
    """
    import cv2  # local import keeps assets_gen importable without OpenCV

    if flipped:
        board_bgr = cv2.rotate(board_bgr, cv2.ROTATE_180)

    h, w = board_bgr.shape[:2]
    n = config.GRID_SIZE
    xs = [round(w * i / n) for i in range(n + 1)]
    ys = [round(h * i / n) for i in range(n + 1)]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for code, (r, c) in STARTING_SAMPLES.items():
        cell = board_bgr[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        ch, cw = cell.shape[:2]
        # Trim a small inset to drop grid lines / borders (mirrors BoardAnalyzer).
        ix, iy = int(cw * config.SQUARE_INSET), int(ch * config.SQUARE_INSET)
        crop = cell[iy:ch - iy, ix:cw - ix]
        if crop.size == 0:
            crop = cell
        fen_letter = code[1] if code[0] == "w" else code[1].lower()
        cv2.imwrite(str(out_dir / config.template_filename(fen_letter)), crop)
        written += 1
    return written


def resolve_assets_dir() -> Path:
    """Return the best assets directory, generating templates if none exist yet.

    Preference order (decisions.md D5):
        1. Bundled assets shipped with the app (if they already contain templates).
        2. Source mode: generate into the project ./assets folder (writable, bundled).
        3. Existing per-user assets, else freshly generated per-user templates (frozen).
    """
    from . import resources

    bundled = resources.bundled_assets_dir()
    if _has_templates(bundled):
        return bundled

    # Source (non-frozen) mode: generate straight into the project ./assets folder so
    # the glyphs sit exactly where PyInstaller bundles from and the app works out of the
    # box. Skipped when frozen because _MEIPASS is read-only (see decisions.md D5).
    if not getattr(sys, "frozen", False):
        try:
            return ensure_assets(bundled)
        except Exception:
            pass  # not writable — fall back to the per-user directory below

    user_dir = resources.user_assets_dir()
    if _has_templates(user_dir):
        return user_dir

    return ensure_assets(user_dir)


def _has_templates(directory: Path) -> bool:
    if not directory.exists():
        return False
    # Consider it populated if at least the six white templates are present.
    return all(
        (directory / config.template_filename(letter)).exists()
        for letter in config.PIECE_CODES
    )
