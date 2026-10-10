"""FEN generation from an 8x8 board matrix.

Pure standard-library module (no PyQt6 / OpenCV) so it can be unit-tested in isolation.
Board matrix convention:
    matrix[row][col], row 0 = rank 8 (top of the diagram), col 0 = file 'a' (left).
    Each cell is either ``None`` (empty) or a single FEN letter:
        white pieces uppercase  "K Q R B N P"
        black pieces lowercase  "k q r b n p"

Example — the standard starting position::

    matrix_to_fen(STARTING_MATRIX)
    -> "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1"
"""

from __future__ import annotations

from typing import List, Optional

Matrix = List[List[Optional[str]]]

VALID_LETTERS = set("KQRBNPkqrbnp")


# Placement field of the standard initial position (rank 8 -> 1).
STARTING_PLACEMENT = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"

# Ready-made sample structure: the standard initial position, useful as a template
# and as a unit-test fixture for the FEN generator.
STARTING_MATRIX: Matrix = [
    list("rnbqkbnr"),
    list("pppppppp"),
    [None] * 8,
    [None] * 8,
    [None] * 8,
    [None] * 8,
    list("PPPPPPPP"),
    list("RNBQKBNR"),
]


def empty_matrix() -> Matrix:
    """Return a fresh 8x8 matrix of empty squares."""
    return [[None for _ in range(8)] for _ in range(8)]


def _validate(matrix: Matrix) -> None:
    if len(matrix) != 8 or any(len(row) != 8 for row in matrix):
        raise ValueError("Board matrix must be 8x8.")
    for row in matrix:
        for cell in row:
            if cell is not None and cell not in VALID_LETTERS:
                raise ValueError(f"Invalid piece letter in matrix: {cell!r}")


def placement_field(matrix: Matrix) -> str:
    """Build only the piece-placement field of a FEN (ranks 8..1, '/'-separated)."""
    _validate(matrix)
    ranks: List[str] = []
    for row in matrix:
        rank_str = ""
        empty_run = 0
        for cell in row:
            if cell is None:
                empty_run += 1
            else:
                if empty_run:
                    rank_str += str(empty_run)
                    empty_run = 0
                rank_str += cell
        if empty_run:
            rank_str += str(empty_run)
        ranks.append(rank_str)
    return "/".join(ranks)


def matrix_to_fen(
    matrix: Matrix,
    side_to_move: str = "w",
    castling: str = "-",
    en_passant: str = "-",
    halfmove_clock: int = 0,
    fullmove_number: int = 1,
) -> str:
    """Assemble a complete FEN string from a board matrix and game-state fields.

    For static diagrams the non-visual fields (side to move, castling, en passant)
    cannot be inferred from the image, so sensible defaults are used and the caller
    (UI) may override side-to-move.
    """
    side = side_to_move.lower()
    if side not in ("w", "b"):
        raise ValueError("side_to_move must be 'w' or 'b'.")
    placement = placement_field(matrix)
    return (
        f"{placement} {side} {castling or '-'} {en_passant or '-'} "
        f"{int(halfmove_clock)} {int(fullmove_number)}"
    )


def infer_castling(matrix: Matrix) -> str:
    """Infer plausible castling rights from piece placement (home-square heuristic).

    A static diagram carries no move history, so we use the standard diagram-OCR
    assumption: if a king and its rook still stand on their home squares, the
    corresponding right is assumed intact. This matters for cloud engines that key
    positions by full FEN — a real game position almost always retains these rights,
    so '-' would look up a different (usually missing) position.
    """
    _validate(matrix)
    rights = ""
    if matrix[7][4] == "K":          # white king on e1
        if matrix[7][7] == "R":      # rook h1
            rights += "K"
        if matrix[7][0] == "R":      # rook a1
            rights += "Q"
    if matrix[0][4] == "k":          # black king on e8
        if matrix[0][7] == "r":      # rook h8
            rights += "k"
        if matrix[0][0] == "r":      # rook a8
            rights += "q"
    return rights or "-"


def position_key(fen: Optional[str]) -> Optional[tuple]:
    """Reduce a FEN to a comparison key: (placement, side-to-move).

    Ignores castling/en-passant and the halfmove/fullmove counters, so two scans of
    the same position always compare equal regardless of the bookkeeping fields.
    """
    if not fen:
        return None
    parts = fen.split()
    return tuple(parts[:2])


def square_name(row: int, col: int) -> str:
    """Convert matrix (row, col) to algebraic square, e.g. (0, 4) -> 'e8'."""
    if not (0 <= row < 8 and 0 <= col < 8):
        raise ValueError("row/col out of range")
    file_char = "abcdefgh"[col]
    rank_char = str(8 - row)
    return f"{file_char}{rank_char}"


def flip_matrix(matrix: Matrix) -> Matrix:
    """Rotate the board 180° (for boards drawn with Black on the bottom)."""
    _validate(matrix)
    return [list(reversed(row)) for row in reversed(matrix)]


if __name__ == "__main__":
    # Self-test — runnable with zero third-party dependencies.
    fen = matrix_to_fen(STARTING_MATRIX)
    expected = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1"
    assert fen == expected, f"FEN mismatch:\n  got {fen}\n  exp {expected}"
    assert square_name(0, 0) == "a8" and square_name(7, 7) == "h1"
    assert placement_field(empty_matrix()) == "8/8/8/8/8/8/8/8"
    print("fen.py self-test OK:", fen)
