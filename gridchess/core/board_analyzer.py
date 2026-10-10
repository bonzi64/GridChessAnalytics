"""BoardAnalyzer — slice a captured diagram into an 8x8 grid, detect pieces by
Template Matching against ``assets/``, and emit a board matrix + FEN string.

Pipeline per Scan:
    capture (BGR) -> square slices -> per-square (empty? / which piece?) -> matrix -> FEN

Detection strategy (see decisions.md D7 / D9):
    1. Trim a small inset off each square to remove grid lines / borders.
    2. Convert the square to grayscale, normalise contrast with CLAHE (so GPU colour
       processing such as digital vibrance / gamma on screen captures cannot drift away
       from the stored templates), then run Canny edge detection. Matching on edge
       *outlines* — not raw pixels — makes the analyzer robust to coloured square
       highlights (e.g. yellow/green last-move backgrounds on demo boards): a solid
       coloured fill produces no interior edges, so only the piece silhouette remains.
    3. Fast empty-square filter: a square whose edge-pixel fraction is below a
       threshold holds no piece.
    4. For non-empty squares, dynamically resize each piece template to the actual
       cell dimensions (cell_w, cell_h), edge-detect it, and run cv2.matchTemplate;
       accept the best score if it clears MATCH_THRESHOLD. This yields the piece TYPE.
    5. Edge outlines cannot separate a white piece from a black one (same silhouette),
       so piece COLOUR is decided from the grayscale square's brightness: the central
       piece region is compared to the board-square background sampled at the corners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - surfaced at runtime
    cv2 = None  # noqa: N816

from .. import config
from . import fen as fenlib


@dataclass
class AnalysisResult:
    """Everything a Scan produces, ready for the UI and the engine."""

    matrix: fenlib.Matrix
    fen: str
    confidence: List[List[float]] = field(default_factory=list)
    detected_pieces: int = 0


class BoardAnalyzer:
    """Turns a board image into a FEN using Template Matching.

    Parameters
    ----------
    assets_dir:
        Directory holding piece templates named per ``config.template_filename``
        (e.g. ``wK.png``, ``bp.png``). Templates are loaded once and cached.
    match_threshold / empty_edge_fraction:
        Detection tuning; defaults come from :mod:`gridchess.config`.
    """

    def __init__(
        self,
        assets_dir: Path,
        match_threshold: float = config.MATCH_THRESHOLD,
        empty_edge_fraction: float = config.EMPTY_EDGE_FRACTION,
    ) -> None:
        if cv2 is None:
            raise RuntimeError(
                "The 'opencv-python' package is required for board analysis. "
                "Install it with: pip install opencv-python"
            )
        self.assets_dir = Path(assets_dir)
        self.match_threshold = float(match_threshold)
        self.empty_edge_fraction = float(empty_edge_fraction)
        # FEN letter (both colours, up to 12) -> grayscale template (uint8, TEMPLATE_SIZE²).
        # Matching uses the TYPE of the best-scoring template; colour is decided separately.
        self._templates: Dict[str, np.ndarray] = {}
        # Cache of edge templates resized to a given cell size:
        #   (fen_letter, cell_w, cell_h) -> edge map (uint8). Avoids re-resizing +
        #   re-running Canny on every one of the 64 cells (and every auto-scan tick).
        self._edge_cache: Dict[Tuple[str, int, int], np.ndarray] = {}
        # CLAHE normaliser shared by squares and templates (created once; reusable).
        self._clahe = (
            cv2.createCLAHE(
                clipLimit=config.CLAHE_CLIP_LIMIT,
                tileGridSize=(config.CLAHE_TILE_GRID, config.CLAHE_TILE_GRID),
            )
            if config.CLAHE_CLIP_LIMIT > 0
            else None
        )
        self.load_templates()

    # ------------------------------------------------------------------ #
    #  Template loading
    # ------------------------------------------------------------------ #
    def load_templates(self) -> Dict[str, np.ndarray]:
        """Load every available piece template from ``assets_dir``, keyed by FEN letter.

        Both colour variants of each type are loaded (up to 12). Matching considers all
        of them and takes the TYPE of the best match — this matters for real themes where
        black pieces (dark fill) lose interior detail edges against their outlines, so a
        white-piece template alone would poorly match its black counterpart. Missing
        pieces are skipped silently. Alpha channels are composited onto neutral grey.
        """
        self._templates.clear()
        self._edge_cache.clear()
        for base in config.PIECE_CODES:
            for fen_letter in (base.upper(), base.lower()):
                path = self.assets_dir / config.template_filename(fen_letter)
                if not path.exists():
                    continue
                tmpl = self._load_template_image(path)
                if tmpl is not None:
                    self._templates[fen_letter] = tmpl
        return self._templates

    @staticmethod
    def _load_template_image(path: Path) -> Optional[np.ndarray]:
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            return None
        size = config.TEMPLATE_SIZE
        if raw.ndim == 3 and raw.shape[2] == 4:
            # Composite RGBA over neutral grey to preserve silhouette contrast.
            bgr = raw[:, :, :3].astype(np.float32)
            alpha = (raw[:, :, 3].astype(np.float32) / 255.0)[:, :, None]
            grey_bg = np.full_like(bgr, 128.0)
            composited = bgr * alpha + grey_bg * (1.0 - alpha)
            gray = cv2.cvtColor(composited.astype(np.uint8), cv2.COLOR_BGR2GRAY)
        elif raw.ndim == 3:
            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        else:
            gray = raw
        return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)

    @property
    def template_count(self) -> int:
        """Number of distinct piece TYPES available (0..6)."""
        return len({letter.upper() for letter in self._templates})

    # ------------------------------------------------------------------ #
    #  Slicing
    # ------------------------------------------------------------------ #
    def slice_board(self, image: np.ndarray) -> List[List[np.ndarray]]:
        """Split a board image into an 8x8 grid of square sub-images (BGR).

        Uses floating-point boundaries rounded per-cell so rounding error never
        accumulates across the 8 columns/rows.
        """
        h, w = image.shape[:2]
        n = config.GRID_SIZE
        xs = [round(w * i / n) for i in range(n + 1)]
        ys = [round(h * i / n) for i in range(n + 1)]
        grid: List[List[np.ndarray]] = []
        for r in range(n):
            row: List[np.ndarray] = []
            for c in range(n):
                row.append(image[ys[r]:ys[r + 1], xs[c]:xs[c + 1]])
            grid.append(row)
        return grid

    # ------------------------------------------------------------------ #
    #  Per-square detection (edge-based, highlight-robust)
    # ------------------------------------------------------------------ #
    def _edge(self, gray: np.ndarray) -> np.ndarray:
        """Grayscale image -> contrast-normalised Canny edge map, dilated for tolerance.

        CLAHE histogram equalisation runs first, on BOTH the captured square and the
        template (this is the single shared entry point for each), so brightness and
        contrast are identical regardless of GPU colour processing — digital vibrance,
        gamma or saturation tweaks on the capture side cannot desynchronise matching.
        Dilation then thickens the thin 1-px Canny outlines so that a template and a
        square whose silhouettes differ by a couple of pixels in scale/position still
        overlap under correlation — without it, matching thin rings is essentially noise.
        """
        if self._clahe is not None:
            gray = self._clahe.apply(gray)
            # CLAHE amplifies quantisation noise inside uniform regions; a light blur
            # suppresses it before Canny so flat areas stay edge-free.
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(gray, config.CANNY_LOW, config.CANNY_HIGH)
        if config.EDGE_DILATE_ITER > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            edges = cv2.dilate(edges, kernel, iterations=config.EDGE_DILATE_ITER)
        return edges

    def _prepare_square(self, square_bgr: np.ndarray) -> np.ndarray:
        """Inset and grayscale a square, keeping its natural (cell) dimensions.

        The inset trims grid lines / borders. We intentionally do NOT resize to a
        fixed size here — matching happens at the cell's real dimensions so templates
        can be scaled to it (requirement: dynamic template scaling to cell_w/cell_h).
        """
        h, w = square_bgr.shape[:2]
        inset_x = int(w * config.SQUARE_INSET)
        inset_y = int(h * config.SQUARE_INSET)
        cropped = square_bgr[inset_y:h - inset_y, inset_x:w - inset_x]
        if cropped.size == 0:
            cropped = square_bgr
        return cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

    def _edge_template_for(self, type_letter: str, cell_w: int, cell_h: int) -> np.ndarray:
        """Return the piece template as an edge map scaled to the cell dimensions.

        The template is scaled to ``TEMPLATE_SEARCH_SCALE`` of (cell_w, cell_h) so it is
        slightly smaller than the square, leaving cv2.matchTemplate a small search window
        to localise the piece. Results are cached per (letter, size) so the resize + Canny
        cost is paid once per distinct cell size, not for every square / auto-scan tick.
        """
        key = (type_letter, cell_w, cell_h)
        cached = self._edge_cache.get(key)
        if cached is not None:
            return cached
        base = self._templates[type_letter]
        tw = max(4, int(cell_w * config.TEMPLATE_SEARCH_SCALE))
        th = max(4, int(cell_h * config.TEMPLATE_SEARCH_SCALE))
        resized = cv2.resize(base, (tw, th), interpolation=cv2.INTER_AREA)
        edges = self._edge(resized)
        self._edge_cache[key] = edges
        return edges

    def _classify_color(self, gray: np.ndarray) -> str:
        """Decide piece colour ('w' or 'b') from the grayscale square (pre-Canny).

        The central piece region is compared to the board-square background sampled
        from the four corners: white pieces read brighter than the square, black
        pieces darker. Absolute brightness extremes are added as a secondary cue so
        the decision still holds when the square carries a coloured highlight.
        """
        # Tone-normalise the square first (percentile stretch to full range) so global
        # brightness/contrast/gamma shifts — GPU digital vibrance, screen dimming —
        # cannot break the relative colour decision or the absolute bright/dark cues.
        lo, hi = np.percentile(gray, (2.0, 98.0))
        if hi - lo > 5.0:
            gray = np.clip(
                (gray.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255
            ).astype(np.uint8)

        h, w = gray.shape[:2]
        cs = max(2, int(min(h, w) * config.PIECE_COLOR_CORNER_FRAC))
        corners = np.concatenate([
            gray[:cs, :cs].ravel(), gray[:cs, -cs:].ravel(),
            gray[-cs:, :cs].ravel(), gray[-cs:, -cs:].ravel(),
        ])
        bg = float(np.median(corners))

        y0, y1 = int(h * 0.20), int(h * 0.80)
        x0, x1 = int(w * 0.20), int(w * 0.80)
        center = gray[y0:y1, x0:x1].astype(np.int16)
        if center.size == 0:
            return "w"

        # Voting: pixels deviating from the background (relative cue) plus absolute
        # bright/dark extremes. The absolute cue is what carries white pieces sitting
        # on light squares, where the body barely clears the background margin —
        # verified empirically against the real board theme; the percentile stretch
        # above keeps these absolute thresholds meaningful under tone shifts.
        margin = config.PIECE_COLOR_MARGIN
        bright = int(np.count_nonzero(center > bg + margin))
        dark = int(np.count_nonzero(center < bg - margin))
        bright += int(np.count_nonzero(center > config.PIECE_COLOR_BRIGHT_ABS))
        dark += int(np.count_nonzero(center < config.PIECE_COLOR_DARK_ABS))

        if bright == dark:
            return "w" if float(center.mean()) >= bg else "b"
        return "w" if bright > dark else "b"

    def detect_piece(self, square_bgr: np.ndarray) -> Tuple[Optional[str], float]:
        """Return ``(fen_letter | None, confidence)`` for one square image.

        Piece TYPE comes from Canny edge matching (robust to coloured backgrounds);
        piece COLOUR (upper/lower case) is then decided from grayscale brightness.
        """
        gray = self._prepare_square(square_bgr)
        cell_h, cell_w = gray.shape[:2]
        if cell_w < 4 or cell_h < 4:
            return None, 0.0

        square_edges = self._edge(gray)

        # Empty-square shortcut: too few edge pixels means no piece silhouette.
        edge_fraction = float(np.count_nonzero(square_edges)) / float(square_edges.size)
        if edge_fraction < self.empty_edge_fraction:
            return None, 0.0

        if not self._templates:
            return None, 0.0

        best_letter: Optional[str] = None
        best_score = -1.0
        for fen_letter in self._templates:
            template_edges = self._edge_template_for(fen_letter, cell_w, cell_h)
            res = cv2.matchTemplate(square_edges, template_edges, cv2.TM_CCOEFF_NORMED)
            score = float(res.max())
            if score > best_score:
                best_score = score
                best_letter = fen_letter

        if best_letter is None or best_score < self.match_threshold:
            return None, best_score

        # The best-matching template gives the TYPE (both colour variants competed);
        # the final colour is decided independently from brightness.
        detected_type = best_letter.upper()
        colour = self._classify_color(gray)
        return (detected_type if colour == "w" else detected_type.lower()), best_score

    # ------------------------------------------------------------------ #
    #  Full analysis
    # ------------------------------------------------------------------ #
    def analyze(
        self,
        image: np.ndarray,
        side_to_move: str = "w",
        flipped: bool = False,
    ) -> AnalysisResult:
        """Analyse a full board image and produce an :class:`AnalysisResult`.

        Parameters
        ----------
        side_to_move:
            'w' or 'b' — cannot be inferred from a static diagram, set by the user.
        flipped:
            True if the diagram is drawn with Black on the bottom rank.
        """
        grid = self.slice_board(image)
        matrix = fenlib.empty_matrix()
        confidence = [[0.0] * config.GRID_SIZE for _ in range(config.GRID_SIZE)]
        detected = 0
        for r in range(config.GRID_SIZE):
            for c in range(config.GRID_SIZE):
                letter, score = self.detect_piece(grid[r][c])
                matrix[r][c] = letter
                confidence[r][c] = score
                if letter is not None:
                    detected += 1

        if flipped:
            matrix = fenlib.flip_matrix(matrix)
            confidence = [list(reversed(row)) for row in reversed(confidence)]

        # Castling rights are inferred from home squares (see fen.infer_castling):
        # cloud engines key positions by full FEN, and '-' would miss the database
        # entry for virtually every real game position.
        fen = fenlib.matrix_to_fen(
            matrix,
            side_to_move=side_to_move,
            castling=fenlib.infer_castling(matrix),
        )
        return AnalysisResult(
            matrix=matrix, fen=fen, confidence=confidence, detected_pieces=detected
        )
