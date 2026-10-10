"""Pobierz oficjalnego Stockfisha (GitHub: official-stockfish) do katalogu silnika.

Ściąga archiwum z oficjalnych wydań, wypakowuje stockfish*.exe do
%LOCALAPPDATA%/GridChessAnalytics/engine/ i wypisuje ścieżkę. Aplikacja znajdzie
go tam automatycznie (patrz gridchess/core/uci_engine.find_stockfish).

Użycie:
    python tools/get_stockfish.py            # wariant AVX2 (współczesne CPU)
    python tools/get_stockfish.py sse41      # starsze CPU bez AVX2
"""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RELEASES = "https://github.com/official-stockfish/Stockfish/releases/download"
VARIANTS = {
    "avx2": "stockfish-windows-x86-64-avx2",
    "sse41": "stockfish-windows-x86-64-sse41-popcnt",
}
# Newest first; the loop falls back if a tag's asset is missing.
TAGS = ["sf_17.1", "sf_17", "sf_16.1"]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    from gridchess import config, resources

    variant = VARIANTS.get(sys.argv[1] if len(sys.argv) > 1 else "avx2")
    if variant is None:
        print(f"Nieznany wariant. Dostępne: {', '.join(VARIANTS)}", file=sys.stderr)
        return 2

    target_dir = resources.user_data_dir() / config.ENGINE_DIRNAME
    target_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(target_dir.glob("stockfish*.exe"))
    if existing:
        print(f"Stockfish już jest: {existing[0]}")
        return 0

    zip_path = target_dir / "stockfish.zip"
    last_error: Exception | None = None
    for tag in TAGS:
        url = f"{RELEASES}/{tag}/{variant}.zip"
        print(f"Pobieram: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GridChess/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            break
        except Exception as exc:  # 404 for missing tag asset, network issues, ...
            last_error = exc
            print(f"  nieudane ({exc}) — próbuję starszy tag…")
    else:
        print(f"Nie udało się pobrać Stockfisha: {last_error}", file=sys.stderr)
        return 1

    print("Wypakowuję…")
    exe_path: Path | None = None
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".exe") and "stockfish" in name.lower():
                data = zf.read(name)
                exe_path = target_dir / Path(name).name
                exe_path.write_bytes(data)
                break
    zip_path.unlink(missing_ok=True)

    if exe_path is None:
        print("W archiwum nie znaleziono pliku .exe.", file=sys.stderr)
        return 1
    print(f"Gotowe: {exe_path}")
    print("Aplikacja użyje go automatycznie, gdy pozycji nie będzie w Cloud Eval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
