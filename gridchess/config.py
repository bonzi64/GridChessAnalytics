"""Central configuration: palette, layout constants, engine endpoint, detection tuning.

Everything tunable lives here so the rest of the codebase stays declarative and the
app can be re-skinned or re-pointed at a different eval API from one place.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
#  Identity
# --------------------------------------------------------------------------- #
APP_NAME = "GridChess Analytics"
ORG_NAME = "GridChess"
APP_DATA_DIRNAME = "GridChessAnalytics"

# --------------------------------------------------------------------------- #
#  Board / grid geometry
# --------------------------------------------------------------------------- #
GRID_SIZE = 8                 # 8x8 chessboard
TEMPLATE_SIZE = 96            # px; square + template are normalised to this before matching

# --------------------------------------------------------------------------- #
#  Piece template naming.  Files live in assets/ as e.g. "wK.png", "bp.png".
#  Key = single-char FEN letter (uppercase = white, lowercase = black).
# --------------------------------------------------------------------------- #
PIECE_CODES = ["K", "Q", "R", "B", "N", "P"]          # base letters
# Filename for a FEN letter: white -> "w<UPPER>.png", black -> "b<UPPER>.png"
def template_filename(fen_letter: str) -> str:
    colour = "w" if fen_letter.isupper() else "b"
    return f"{colour}{fen_letter.upper()}.png"

# Unicode filled glyphs used by the asset generator (solid silhouettes match best).
GLYPHS = {
    "K": "♚",  # ♚
    "Q": "♛",  # ♛
    "R": "♜",  # ♜
    "B": "♝",  # ♝
    "N": "♞",  # ♞
    "P": "♟",  # ♟
}

# --------------------------------------------------------------------------- #
#  Detection tuning  (values calibrated against a real lichess-style board)
# --------------------------------------------------------------------------- #
# Fraction of the square trimmed on each side before analysis. Also removes the small
# board-coordinate overlays (rank digits / file letters) that hug the square corners.
SQUARE_INSET = 0.08
# Contrast normalisation (CLAHE) applied to the grayscale square AND the template
# before edge detection. This puts screen captures and stored templates on identical
# brightness/contrast footing, so GPU colour processing (digital vibrance, gamma,
# saturation boosts) altering captured pixels cannot desynchronise the matching.
# Set the clip limit to 0 to disable.
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = 8
# Canny edge-detection thresholds. Matching on edge outlines (not raw pixels) makes
# detection robust to coloured square highlights (yellow/green last-move backgrounds).
CANNY_LOW = 50
CANNY_HIGH = 150
# Thin 1-px edge rings barely overlap under correlation, so we dilate both the square
# and template edge maps by this many iterations (3x3 kernel) to give matching
# tolerance to small scale/position mismatch. 0 disables dilation.
EDGE_DILATE_ITER = 2
# Templates are scaled to this fraction of the cell so cv2.matchTemplate has a small
# search window to localise the piece (rather than a single fixed 1x1 comparison).
TEMPLATE_SEARCH_SCALE = 0.90
# A square is treated as empty when the fraction of Canny edge pixels is below this.
# Tuned so a lone coordinate digit on an empty square does not read as a piece.
EMPTY_EDGE_FRACTION = 0.05
# Minimum TM_CCOEFF_NORMED score (on edge maps) to accept a piece match. Empty squares
# are already removed by the edge-fraction filter, and wrong shapes score near zero or
# negative, so this sits low to catch weak silhouettes; real pieces score well above it.
MATCH_THRESHOLD = 0.09

# --- Piece colour classification (hybrid: edges give shape, brightness gives colour) --
# Edge matching finds the piece TYPE but cannot tell a white piece from a black one
# (same silhouette). Colour is decided from the grayscale square instead.
# Corner patch size (fraction of the square) sampled to estimate the board-square colour.
PIECE_COLOR_CORNER_FRAC = 0.18
# Brightness margin (0..255, applied AFTER percentile tone-normalisation) beyond the
# background for a centre pixel to count as part of a bright/dark piece body.
PIECE_COLOR_MARGIN = 22
# Absolute brightness cutoffs (post-normalisation) — secondary cue that carries white
# pieces on light squares, where the body barely clears the relative margin.
PIECE_COLOR_BRIGHT_ABS = 190
PIECE_COLOR_DARK_ABS = 70

# --------------------------------------------------------------------------- #
#  Cloud engine
# --------------------------------------------------------------------------- #
CLOUD_EVAL_URL = "https://lichess.org/api/cloud-eval"
CLOUD_EVAL_MULTIPV = 1
HTTP_TIMEOUT = 5.0            # seconds — a slow cloud reply must not stall the flow
HTTP_USER_AGENT = f"{APP_NAME}/1.0 (static-diagram study tool)"
# After this many consecutive cloud misses the position is clearly out of book —
# skip the guaranteed-404 round trips and go straight to the local engine. The
# counter resets when the starting position is detected (new game) or on success.
CLOUD_MISS_LIMIT = 2
# On HTTP 429 (rate limit) the lichess API asks clients to pause for a full minute;
# cloud queries are suspended for this long and the local engine covers the gap.
CLOUD_BACKOFF_S = 60.0

# Auto-scan loop interval (ms). The loop only queries the engine when the detected
# FEN actually changes (state control), so this cadence is safe for rate limits.
AUTO_SCAN_INTERVAL_MS = 500

# --------------------------------------------------------------------------- #
#  Local engine fallback (Stockfish via UCI)
# --------------------------------------------------------------------------- #
# Used when Cloud Eval has no entry for the position (or the network is down).
# The executable is looked up in: config.json "stockfish_path" -> the user data
# dir's engine/ folder -> ./engine next to the app -> the system PATH.
ENGINE_DIRNAME = "engine"
STOCKFISH_MOVETIME_MS = 800    # thinking time per position (depth ~20 — plenty)
STOCKFISH_THREADS = 2
STOCKFISH_HASH_MB = 128

# Interpretation of the cloud "cp"/"mate" sign. "white" = value is from White's
# perspective; "stm" = value is from the side-to-move's perspective.  The eval bar
# always renders from White's perspective, normalising as needed.  See notes.md R2.
EVAL_PERSPECTIVE = "white"

# --------------------------------------------------------------------------- #
#  Palette (ultra-modern matte black, macOS-inspired)
# --------------------------------------------------------------------------- #
COLOR_BG = "#121212"             # deep matte black
COLOR_SURFACE = "#161616"        # main card surface
COLOR_SURFACE_2 = "#1E1E1E"      # interactive elements (buttons, fields)
COLOR_SURFACE_HOVER = "#242426"  # interactive elements on hover
COLOR_BORDER = "#2A2A2A"         # hairline borders
COLOR_BORDER_HOVER = "#3D3D40"   # hairline border on hover
COLOR_TEXT = "#EDEDF0"
COLOR_TEXT_DIM = "#8E8E93"
COLOR_ACCENT = "#8A7FD6"         # muted violet — used sparingly
COLOR_ACCENT_HOVER = "#9B91E0"
COLOR_ACCENT_2 = "#5E9ED6"       # muted blue, secondary
COLOR_GOOD = "#3BA55C"
COLOR_WARN = "#D9A439"
COLOR_BAD = "#DE5650"

# macOS-style traffic lights (matte base -> brightens on hover)
TRAFFIC_CLOSE = "#D9544D"
TRAFFIC_CLOSE_HOVER = "#FF5F57"
TRAFFIC_MIN = "#D9A032"
TRAFFIC_MIN_HOVER = "#FEBC2E"
TRAFFIC_MAX = "#2E9E43"
TRAFFIC_MAX_HOVER = "#28C840"

# Main window corner radius (px) — mirrored by the QSS on #Card.
PANEL_RADIUS = 12

# Arrow rendering (DrawingOverlay)
ARROW_COLOR = "#8A7FD6"
ARROW_ALPHA = 210            # 0..255
ARROW_WIDTH_RATIO = 0.18     # relative to square size
ARROWHEAD_RATIO = 0.42       # relative to square size
