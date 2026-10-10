"""EngineThread — query the Lichess Cloud Eval API off the GUI thread.

A ready FEN (from a static capture) is sent to a free, public cloud-eval endpoint to
retrieve the best tactical line for demonstration. Running inside a QThread keeps the
UI responsive (no GUI freeze) while the (blocking) HTTP call is in flight.

Signals:
    resultReady(dict)  — parsed evaluation (see EvalResult.as_dict)
    failed(str)        — human-readable error / "position not in cloud database"
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from .. import config
from . import uci_engine

# Shared across queries: when lichess answers 429 (rate limit), cloud requests are
# suspended until this monotonic deadline and the local engine covers the gap.
_cloud_backoff_until = 0.0


@dataclass
class EvalResult:
    """Normalised cloud-eval response."""

    fen: str
    best_move_uci: Optional[str] = None      # e.g. "e2e4"
    pv: List[str] = field(default_factory=list)  # full principal variation, UCI moves
    cp: Optional[int] = None                 # centipawns, White's perspective (normalised)
    mate: Optional[int] = None               # mate-in-N, White's perspective (normalised)
    depth: Optional[int] = None
    knodes: Optional[int] = None
    source: str = "cloud"

    def as_dict(self) -> dict:
        return {
            "fen": self.fen,
            "best_move_uci": self.best_move_uci,
            "pv": self.pv,
            "cp": self.cp,
            "mate": self.mate,
            "depth": self.depth,
            "knodes": self.knodes,
            "source": self.source,
        }


class EngineThread(QThread):
    """One-shot evaluation of a single FEN: cloud first, local Stockfish fallback.

    ``skip_cloud=True`` goes straight to the local engine — used once the game has
    left the cloud database (consecutive-miss heuristic in the panel), where cloud
    round trips would be guaranteed-404 latency.

    Cancellation is cooperative: :meth:`cancel` mutes the signals and interrupts the
    shared engine's search (UCI ``stop``), so the thread winds down on its own within
    the move time — it is never terminated mid-protocol.
    """

    resultReady = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, fen: str, skip_cloud: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._fen = fen
        self._skip_cloud = skip_cloud
        self._cancelled = False

    # -- public API ----------------------------------------------------- #
    def cancel(self) -> None:
        """Discard this query: mute emissions and cut the local search short."""
        self._cancelled = True
        uci_engine.interrupt_current()

    # -- QThread entry -------------------------------------------------- #
    def run(self) -> None:  # noqa: D401 - Qt override
        global _cloud_backoff_until
        t0 = time.perf_counter()
        engine = uci_engine.find_stockfish()

        def emit_result(data: dict, cloud_missed: bool) -> None:
            if self._cancelled:
                return
            data["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            data["cloud_missed"] = cloud_missed
            self.resultReady.emit(data)

        # Respect a 429 backoff window as long as the local engine can serve instead.
        in_backoff = time.monotonic() < _cloud_backoff_until

        cloud_problem: Optional[str] = None
        if not ((self._skip_cloud or in_backoff) and engine is not None):
            # The cloud database keys positions by full FEN, and castling rights in a
            # scanned FEN are a heuristic (fen.infer_castling). Try the FEN as given;
            # on a 404 retry once with the rights stripped, covering the case where
            # the home-square assumption granted rights the game no longer has.
            candidates = [self._fen]
            stripped = self._strip_castling(self._fen)
            if stripped != self._fen:
                candidates.append(stripped)

            for fen in candidates:
                if self._cancelled:
                    return
                try:
                    payload = self._fetch(fen)
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        cloud_problem = "notfound"
                        continue  # not in the database under this key — try next
                    if exc.code == 429:
                        # Rate-limited: the API asks for a full-minute pause.
                        _cloud_backoff_until = time.monotonic() + config.CLOUD_BACKOFF_S
                        cloud_problem = "Limit zapytań Cloud Eval (HTTP 429) — pauza 60 s."
                        break
                    cloud_problem = f"Błąd HTTP {exc.code} z serwera analizy."
                    break
                except urllib.error.URLError as exc:
                    cloud_problem = f"Brak połączenia z serwerem analizy: {exc.reason}"
                    break
                except (TimeoutError, OSError) as exc:
                    cloud_problem = f"Przekroczono limit czasu / błąd sieci: {exc}"
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    cloud_problem = f"Nieprawidłowa odpowiedź serwera: {exc}"
                    break

                result = self._parse(fen, payload)
                emit_result(result.as_dict(), cloud_missed=False)
                return

        # Cloud skipped, empty for this position, or unreachable — run the local
        # Stockfish, which analyses ANY position with no network at all.
        if engine is not None and not self._cancelled:
            try:
                data = uci_engine.analyse_position(engine, self._fen)
            except Exception as exc:
                if not self._cancelled:
                    self.failed.emit(f"Lokalny silnik zawiódł: {exc}")
                return
            emit_result(data, cloud_missed=(cloud_problem == "notfound"))
            return

        if self._cancelled:
            return
        if cloud_problem == "notfound":
            self.failed.emit(
                "Pozycja spoza bazy Cloud Eval, a lokalnego Stockfisha nie znaleziono. "
                "Pobierz go poleceniem: python tools/get_stockfish.py"
            )
        else:
            self.failed.emit(cloud_problem or "Nieznany błąd analizy.")

    @staticmethod
    def _strip_castling(fen: str) -> str:
        """Return the FEN with the castling field forced to '-'."""
        parts = fen.split()
        if len(parts) >= 3:
            parts[2] = "-"
        return " ".join(parts)

    # -- internals ------------------------------------------------------ #
    def _fetch(self, fen: str) -> dict:
        query = urllib.parse.urlencode({"fen": fen, "multiPv": config.CLOUD_EVAL_MULTIPV})
        url = f"{config.CLOUD_EVAL_URL}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": config.HTTP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)

    @staticmethod
    def _normalise_sign(value: Optional[int], side_to_move: str) -> Optional[int]:
        """Convert a raw cloud value into White's perspective for the eval bar.

        If the API reports from the side-to-move's perspective, flip when Black is
        on move. Controlled by ``config.EVAL_PERSPECTIVE`` (see decisions.md D3).
        """
        if value is None:
            return None
        if config.EVAL_PERSPECTIVE == "stm" and side_to_move == "b":
            return -value
        return value

    def _parse(self, fen: str, payload: dict) -> EvalResult:
        side_to_move = (fen.split(" ") + ["w"])[1]
        result = EvalResult(fen=fen, depth=payload.get("depth"), knodes=payload.get("knodes"))

        pvs = payload.get("pvs") or []
        if pvs:
            first = pvs[0]
            moves = (first.get("moves") or "").split()
            result.pv = moves
            result.best_move_uci = moves[0] if moves else None
            result.cp = self._normalise_sign(first.get("cp"), side_to_move)
            result.mate = self._normalise_sign(first.get("mate"), side_to_move)
        return result
