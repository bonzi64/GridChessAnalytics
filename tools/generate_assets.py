"""CLI: produce piece templates into the project ``assets/`` folder.

Two modes:

  * Default — render synthetic glyph templates with QPainter (works headless).
        python tools/generate_assets.py [out_dir]

  * From a real board image — cut templates directly out of a screenshot of the
    STARTING position, so they match the exact on-screen theme (recommended for
    custom piece sets). This does NOT need PyQt6, only OpenCV.
        python tools/generate_assets.py --from-board board.png
        python tools/generate_assets.py --from-board shot.png --region X Y W H
        python tools/generate_assets.py --from-board shot.png --region X Y W H --flip --out assets
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Render off-screen so glyph mode works on headless / CI machines too.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Make the project package importable when run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def _run_from_board(image_path: str, region, flip: bool, out_dir: Path) -> int:
    """Cut real templates out of a starting-position board image."""
    import cv2

    from gridchess import assets_gen

    image = cv2.imread(image_path)
    if image is None:
        print(f"Nie można wczytać obrazu: {image_path}", file=sys.stderr)
        return 1

    if region:
        x, y, w, h = region
        image = image[y:y + h, x:x + w]
        if image.size == 0:
            print("Podany obszar (--region) jest poza obrazem.", file=sys.stderr)
            return 1

    written = assets_gen.extract_templates_from_board(image, out_dir, flipped=flip)
    print(f"[generate_assets] Wyodrębniono {written} realnych szablonów do: {out_dir}")
    print("Szablony pasują teraz do motywu z Twojego zrzutu — uruchom detekcję ponownie.")
    return 0


def _run_glyphs(out_dir: Path) -> int:
    """Render synthetic glyph templates (fallback / default)."""
    from PyQt6.QtGui import QGuiApplication

    from gridchess import assets_gen

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    written = assets_gen.ensure_assets(out_dir, force=True)
    count = len(list(written.glob("*.png")))
    print(f"[generate_assets] Zapisano {count} syntetycznych szablonów do: {written}")
    del app
    return 0


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="Generowanie szablonów figur GridChess.")
    parser.add_argument("--from-board", metavar="OBRAZ",
                        help="wytnij szablony ze zrzutu pozycji startowej")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                        help="obszar szachownicy w obrazie (piksele)")
    parser.add_argument("--flip", action="store_true", help="plansza obrócona (czarne u dołu)")
    parser.add_argument("--out", metavar="KAT", help="katalog docelowy (domyślnie ./assets)")
    parser.add_argument("out_dir_pos", nargs="?", help="(tryb glify) katalog docelowy")
    args = parser.parse_args(argv)

    out_dir = Path(args.out or args.out_dir_pos or (PROJECT_ROOT / "assets"))

    if args.from_board:
        region = tuple(args.region) if args.region else None
        return _run_from_board(args.from_board, region, args.flip, out_dir)
    return _run_glyphs(out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
