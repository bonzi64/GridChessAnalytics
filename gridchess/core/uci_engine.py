"""Minimal UCI client for a local Stockfish fallback (stdlib only).

Used when Cloud Eval has no entry for a scanned position: any legal position can be
analysed locally, with no network at all.

The engine runs as ONE persistent process for the whole session (module singleton):
Stockfish loads its NNUE network at startup (~0.4 s), so spawning per query would pay
that cost on every move. Protocol access is serialised with a lock; a query already
in progress can be accelerated from another thread via :func:`interrupt_current`
(UCI ``stop``), which is how superseded analyses are cancelled cooperatively —
no thread/process is ever killed mid-protocol. If the engine process dies, the next
query respawns it once and retries.

Score convention: UCI engines report ``score cp``/``mate`` from the SIDE TO MOVE's
perspective; results are normalised to White's perspective to match the rest of the
app (EvalBar, cloud results).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

from .. import config, resources, settings


def find_stockfish() -> Optional[Path]:
    """Locate a Stockfish executable. Returns None when unavailable.

    Search order:
      1. Explicit ``stockfish_path`` in config.json (user override).
      2. ``engine/`` in the per-user data directory (where tools/get_stockfish.py puts it).
      3. ``engine/`` next to the app / project root.
      4. ``stockfish`` on the system PATH.
    """
    override = settings.load().get("stockfish_path")
    if override:
        p = Path(override)
        if p.is_file():
            return p

    exe_glob = "stockfish*.exe" if sys.platform.startswith("win") else "stockfish*"
    for folder in (
        resources.user_data_dir() / config.ENGINE_DIRNAME,
        resources.resource_path(config.ENGINE_DIRNAME),
    ):
        if folder.is_dir():
            for candidate in sorted(folder.glob(exe_glob)):
                if candidate.is_file():
                    return candidate

    which = shutil.which("stockfish")
    return Path(which) if which else None


class PersistentEngine:
    """One long-lived Stockfish process, protocol-serialised with a lock."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()        # serialises whole queries
        self._write_lock = threading.Lock()  # guards stdin (interrupt vs query)
        self._spawn()

    # -- process / protocol plumbing ------------------------------------ #
    def _spawn(self) -> None:
        creationflags = 0x08000000 if sys.platform.startswith("win") else 0  # no console
        try:
            self._proc = subprocess.Popen(
                [str(self._path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
        except OSError as exc:
            self._proc = None
            raise RuntimeError(f"Nie można uruchomić silnika: {exc}") from exc
        self._send("uci")
        self._read_until("uciok")
        self._send(f"setoption name Threads value {config.STOCKFISH_THREADS}")
        self._send(f"setoption name Hash value {config.STOCKFISH_HASH_MB}")
        self._send("isready")
        self._read_until("readyok")

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _send(self, cmd: str) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("Silnik nie jest uruchomiony.")
        with self._write_lock:
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()

    def _read_until(self, token: str, limit: int = 8192) -> List[str]:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("Silnik nie jest uruchomiony.")
        lines: List[str] = []
        for _ in range(limit):
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("Silnik zakończył się przedwcześnie.")
            line = line.strip()
            lines.append(line)
            if line.startswith(token):
                return lines
        raise RuntimeError("Przekroczono limit odpowiedzi UCI.")

    # -- public API ------------------------------------------------------ #
    def interrupt(self) -> None:
        """Ask the engine to end the current search now (safe when idle)."""
        try:
            self._send("stop")
        except Exception:
            pass

    def analyse(self, fen: str, movetime_ms: int) -> dict:
        """Fixed-time analysis; retries once on a dead engine process."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    if not self._alive():
                        self._spawn()
                    # Re-sync before each query; drains any leftovers cheaply.
                    self._send("isready")
                    self._read_until("readyok")
                    self._send(f"position fen {fen}")
                    self._send(f"go movetime {int(movetime_ms)}")
                    lines = self._read_until("bestmove")
                    return _parse_output(fen, lines)
                except RuntimeError:
                    if attempt == 2:
                        raise
                    self.close()  # dead / desynced -> respawn on retry

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                with self._write_lock:
                    proc.stdin.write("quit\n")
                    proc.stdin.flush()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---- module-level singleton ------------------------------------------- #
_instance: Optional[PersistentEngine] = None
_instance_lock = threading.Lock()


def get_engine(path: Path) -> PersistentEngine:
    """Return the shared engine instance (spawned on first use)."""
    global _instance
    with _instance_lock:
        if _instance is None or _instance._path != Path(path) or not _instance._alive():
            if _instance is not None:
                _instance.close()
            _instance = PersistentEngine(path)
        return _instance


def interrupt_current() -> None:
    """Accelerate/cancel whatever the shared engine is currently searching."""
    inst = _instance
    if inst is not None:
        inst.interrupt()


def shutdown() -> None:
    """Quit the shared engine process (app exit)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
            _instance = None


def analyse_position(
    engine_path: Path,
    fen: str,
    movetime_ms: int = config.STOCKFISH_MOVETIME_MS,
) -> dict:
    """Analyse via the persistent engine; returns a cloud-compatible result dict."""
    return get_engine(engine_path).analyse(fen, movetime_ms)


def _parse_output(fen: str, lines: List[str]) -> dict:
    """Extract the last full info line + bestmove into a cloud-compatible dict."""
    depth = None
    cp = None
    mate = None
    pv: List[str] = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "info" and "pv" in parts and "score" in parts:
            try:
                if "depth" in parts:
                    depth = int(parts[parts.index("depth") + 1])
                s = parts.index("score")
                kind, value = parts[s + 1], int(parts[s + 2])
                cp, mate = (value, None) if kind == "cp" else (None, value)
                pv = parts[parts.index("pv") + 1:]
            except (ValueError, IndexError):
                continue
        elif parts[0] == "bestmove":
            best = parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
            if best and (not pv or pv[0] != best):
                pv = [best] + pv[1:] if pv else [best]

    if not pv:
        raise RuntimeError("Silnik nie zwrócił żadnej linii.")

    # UCI scores are from the side to move — normalise to White's perspective.
    side = (fen.split() + ["w"])[1]
    if side == "b":
        cp = -cp if cp is not None else None
        mate = -mate if mate is not None else None

    return {
        "fen": fen,
        "best_move_uci": pv[0],
        "pv": pv,
        "cp": cp,
        "mate": mate,
        "depth": depth,
        "knodes": None,
        "source": "local",
    }
