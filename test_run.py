#!/usr/bin/env python3
"""test_run.py — narzędzie do testowania i kalibracji detekcji GridChess bez pełnego GUI.

Najczęstszy przepływ pracy dla realnego, niestandardowego motywu figur:

  1) Zrób zrzut planszy w POZYCJI STARTOWEJ i zapisz jako np. board.png.
  2) Wyodrębnij realne szablony figur (pasujące 1:1 do motywu):
         python test_run.py --extract board.png                 # gdy obraz to sama plansza
         python test_run.py --extract shot.png --region X Y W H  # gdy to pełny zrzut ekranu
     (od razu przetnie planszę i pokaże wykryty FEN — powinien być pozycją startową)
  3) Testuj detekcję na dowolnym obrazie/ekranie:
         python test_run.py --image pozycja.png [--region X Y W H]
         python test_run.py --region X Y W H          # pętla na żywym ekranie
         python test_run.py                            # zaznacz obszar myszą, potem pętla

Opcje: --interval SEK (0.5), --black, --flip, --assets KAT (katalog szablonów / docelowy).

Wymaga: mss + opencv-python (tryb zaznaczania myszą używa okna OpenCV; --image/--region/
--extract działają też na opencv-python-headless). Do detekcji potrzebne są szablony figur.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def _utf8_console() -> None:
    """UTF-8 stdout/stderr, żeby polskie znaki nie wywracały konsoli cp1252."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def build_analyzer(assets_arg: str | None):
    """Utwórz BoardAnalyzer, rozwiązując katalog szablonów figur."""
    from gridchess.core.board_analyzer import BoardAnalyzer

    if assets_arg:
        assets_dir = Path(assets_arg)
    else:
        from gridchess import assets_gen
        try:
            assets_dir = assets_gen.resolve_assets_dir()
        except Exception as exc:  # brak szablonów i brak PyQt6 do ich wygenerowania
            print(
                "Nie udało się przygotować szablonów figur:\n"
                f"  {exc}\n"
                "Wyodrębnij je z realnej planszy:  python test_run.py --extract board.png",
                file=sys.stderr,
            )
            sys.exit(1)

    analyzer = BoardAnalyzer(assets_dir)
    print(f"[assets] katalog: {assets_dir}")
    print(f"[assets] wczytane typy figur: {analyzer.template_count}/6")
    if analyzer.template_count == 0:
        print(
            "Brak szablonów w katalogu — detekcja zwróci puste pola.\n"
            "Wyodrębnij je:  python test_run.py --extract board.png",
            file=sys.stderr,
        )
        sys.exit(1)
    return analyzer


def load_and_crop(path: str, region):
    """Wczytaj obraz BGR i (opcjonalnie) przytnij do obszaru planszy w pikselach obrazu."""
    import cv2

    image = cv2.imread(path)
    if image is None:
        print(f"Nie można wczytać obrazu: {path}", file=sys.stderr)
        return None
    if region:
        x, y, w, h = region
        image = image[y:y + h, x:x + w]
        if image.size == 0:
            print("Podany obszar (--region) jest poza obrazem.", file=sys.stderr)
            return None
    return image


def analyze_and_print(analyzer, image: np.ndarray, side: str, flip: bool) -> str:
    """Zanalizuj obraz BGR i wypisz FEN + liczbę wykrytych figur. Zwraca FEN."""
    result = analyzer.analyze(image, side_to_move=side, flipped=flip)
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] figur: {result.detected_pieces:2d}   FEN: {result.fen}")
    return result.fen


def run_extract(image_path: str, region, flip: bool, assets_arg: str | None, side: str) -> int:
    """Wyodrębnij realne szablony z planszy w pozycji startowej, potem pokaż wykryty FEN."""
    from gridchess import assets_gen

    image = load_and_crop(image_path, region)
    if image is None:
        return 1

    out_dir = Path(assets_arg) if assets_arg else (PROJECT_ROOT / "assets")
    written = assets_gen.extract_templates_from_board(image, out_dir, flipped=flip)
    print(f"[extract] Wyodrębniono {written} realnych szablonów do: {out_dir}")

    print("[extract] Kontrola — detekcja tej samej planszy nowymi szablonami:")
    analyzer = build_analyzer(str(out_dir))
    fen = analyze_and_print(analyzer, image, side, flip)
    expected = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    if fen.split(" ")[0] == expected:
        print("[extract] OK — rozpoznano pozycję startową. Szablony gotowe do użycia.")
    else:
        print("[extract] Uwaga: to nie wygląda na pozycję startową — sprawdź --region / --flip.")
    return 0


def run_image(path: str, analyzer, side: str, flip: bool, region) -> int:
    image = load_and_crop(path, region)
    if image is None:
        return 1
    analyze_and_print(analyzer, image, side, flip)
    print("Wklej FEN na https://lichess.org/analysis, aby zweryfikować pozycję.")
    return 0


def pick_region_with_mouse():
    """Zaznacz obszar szachownicy myszą na zrzucie całego pulpitu (okno OpenCV)."""
    import cv2
    import mss

    with mss.mss() as sct:
        mon = sct.monitors[0]  # cały wirtualny pulpit (wszystkie monitory)
        shot = np.array(sct.grab(mon), dtype=np.uint8)[:, :, :3]

    print("Zaznacz prostokąt na szachownicy i naciśnij ENTER (lub C, aby anulować)…")
    x, y, w, h = cv2.selectROI("GridChess — zaznacz szachownicę", shot, showCrosshair=True)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        return None
    # Współrzędne z selectROI są względem zrzutu; przelicz na absolutne piksele ekranu.
    return (x + mon["left"], y + mon["top"], w, h)


def run_loop(region, analyzer, side: str, flip: bool, interval: float) -> int:
    from gridchess.core.screen_capture import ScreenCapture

    x, y, w, h = region
    print(f"[region] x={x} y={y} w={w} h={h}   interwał={interval}s")
    print("Pętla skanowania uruchomiona. Zmień pozycję na planszy, aby zobaczyć nowy FEN.")
    print("Zatrzymaj: Ctrl+C\n")

    capture = ScreenCapture()
    last_fen = None  # kontrola stanu: wypisuj tylko przy zmianie pozycji
    try:
        while True:
            image = capture.grab(x, y, w, h)
            result = analyzer.analyze(image, side_to_move=side, flipped=flip)
            if result.fen != last_fen:
                last_fen = result.fen
                stamp = time.strftime("%H:%M:%S")
                print(f"[{stamp}] ZMIANA — figur: {result.detected_pieces:2d}   FEN: {result.fen}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nZatrzymano.")
    finally:
        capture.close()
    return 0


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description="Test i kalibracja detekcji GridChess.")
    parser.add_argument("--extract", metavar="OBRAZ",
                        help="wytnij realne szablony ze zrzutu pozycji startowej")
    parser.add_argument("--image", metavar="PLIK", help="zanalizuj pojedynczy zrzut z pliku")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                        help="obszar planszy: w pikselach obrazu (--image/--extract) "
                             "lub na ekranie (pętla na żywo)")
    parser.add_argument("--interval", type=float, default=0.5, help="odstęp skanów (s)")
    parser.add_argument("--black", action="store_true", help="czarne na ruchu")
    parser.add_argument("--flip", action="store_true", help="plansza obrócona")
    parser.add_argument("--assets", metavar="KAT", help="katalog szablonów figur / docelowy")
    args = parser.parse_args(argv)

    side = "b" if args.black else "w"
    region = tuple(args.region) if args.region else None

    if args.extract:
        return run_extract(args.extract, region, args.flip, args.assets, side)

    analyzer = build_analyzer(args.assets)

    if args.image:
        return run_image(args.image, analyzer, side, args.flip, region)

    if region is None:
        region = pick_region_with_mouse()
        if region is None:
            print("Anulowano — nie wybrano obszaru.")
            return 0

    return run_loop(region, analyzer, side, args.flip, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
