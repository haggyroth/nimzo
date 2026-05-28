"""
Stockfish wrapper for guided mode.
Generates ranked candidate moves for the LLM players to choose from.
Also used for post-game analysis.
"""

import chess
import chess.engine
from dataclasses import dataclass
from typing import Optional
import os


def _find_stockfish() -> str:
    """
    Resolve the Stockfish binary path.

    Priority:
    1. STOCKFISH_PATH env var (explicit override)
    2. ``which stockfish`` — Homebrew / system PATH
    3. Common hard-coded install locations (Homebrew Intel/ARM, apt, snap)
    4. Fall back to '/usr/games/stockfish' so the original error message is preserved
       if none of the above exist (will raise FileNotFoundError on first use).
    """
    explicit = os.environ.get("STOCKFISH_PATH")
    if explicit:
        return explicit

    import shutil
    on_path = shutil.which("stockfish")
    if on_path:
        return on_path

    candidates = [
        "/opt/homebrew/bin/stockfish",   # Homebrew ARM (Apple Silicon)
        "/usr/local/bin/stockfish",      # Homebrew Intel
        "/usr/bin/stockfish",            # apt
        "/snap/bin/stockfish",           # snap
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return "/usr/games/stockfish"  # apt default — will fail with a clear error


DEFAULT_STOCKFISH_PATH = _find_stockfish()

# Move-quality centipawn-loss thresholds (vs Stockfish's top candidate).
# Tune these to adjust how harshly moves are graded.
CP_LOSS_EXCELLENT   =  10   # < 10 cp loss  → excellent
CP_LOSS_GOOD        =  25   # < 25 cp loss  → good
CP_LOSS_INACCURACY  =  50   # < 50 cp loss  → inaccuracy
CP_LOSS_MISTAKE     = 150   # < 150 cp loss → mistake  (≥ 150 → blunder)


@dataclass
class AnalysisResult:
    """Full Stockfish analysis for a single position."""

    best_move: chess.Move
    score_cp: Optional[int]         # centipawns (positive = good for current player)
    mate_in: Optional[int]          # None if not a forced mate
    depth: int
    pv: list[chess.Move]            # principal variation


class StockfishEngine:
    """
    Thin wrapper around a Stockfish subprocess.

    Use as a context manager — the engine process is started on ``__enter__``
    and shut down on ``__exit__``::

        with StockfishEngine() as sf:
            candidates = sf.get_candidates(board, n=5)
    """

    def __init__(
        self,
        path: str = DEFAULT_STOCKFISH_PATH,
        depth: int = 15,
        candidate_depth: int = 10,
    ):
        self.path = path
        self.depth = depth
        self.candidate_depth = candidate_depth
        self._engine: Optional[chess.engine.SimpleEngine] = None

    def __enter__(self):
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
        return self

    def __exit__(self, *args):
        if self._engine:
            try:
                self._engine.quit()
            except Exception:
                pass   # engine may already be dead (e.g. Ctrl+C mid-game)

    def get_candidates(
        self,
        board: chess.Board,
        n: int = 5,
    ) -> list[tuple[chess.Move, Optional[float]]]:
        """
        Return top N moves ranked by Stockfish, each with its centipawn score.
        Score is from the perspective of the side to move (positive = better).
        """
        if self._engine is None:
            raise RuntimeError("Engine not started — use as context manager")

        legal = list(board.legal_moves)
        if len(legal) == 0:
            return []

        n = min(n, len(legal))

        result = self._engine.analyse(
            board,
            chess.engine.Limit(depth=self.candidate_depth),
            multipv=n,
        )

        candidates = []
        for info in result:
            move = info.get("pv", [None])[0]
            if move is None:
                continue
            score = info.get("score")
            cp = None
            if score is not None:
                pov = score.pov(board.turn)
                if pov.is_mate():
                    # Treat forced mate as very high/low value
                    mate = pov.mate()
                    cp = 10000 if mate > 0 else -10000
                else:
                    cp = pov.score()
            candidates.append((move, cp))

        return candidates

    def analyse_position(self, board: chess.Board) -> AnalysisResult:
        """Deep analysis of the current position."""
        if self._engine is None:
            raise RuntimeError("Engine not started — use as context manager")

        info = self._engine.analyse(board, chess.engine.Limit(depth=self.depth))
        best_move = info["pv"][0]
        score = info["score"].pov(board.turn)

        cp = None
        mate_in = None
        if score.is_mate():
            mate_in = score.mate()
        else:
            cp = score.score()

        return AnalysisResult(
            best_move=best_move,
            score_cp=cp,
            mate_in=mate_in,
            depth=info.get("depth", self.depth),
            pv=info.get("pv", []),
        )

    def score_move(
        self,
        board: chess.Board,
        move: chess.Move,
    ) -> Optional[float]:
        """
        Ask Stockfish for the centipawn score of a specific move (current-player POV).
        Used to evaluate blind-mode moves that fall outside the pre-computed candidate list.
        Returns None if the engine is unavailable or the query fails.
        """
        if getattr(self, "_engine", None) is None:
            return None
        try:
            info = self._engine.analyse(
                board,
                chess.engine.Limit(depth=self.candidate_depth),
                root_moves=[move],
            )
            score = info.get("score")
            if score is None:
                return None
            pov = score.pov(board.turn)
            if pov.is_mate():
                return 10000 if pov.mate() > 0 else -10000
            return pov.score()
        except Exception:
            return None

    def evaluate_move_quality(
        self,
        board: chess.Board,
        move: chess.Move,
        candidates: list[tuple[chess.Move, Optional[float]]],
    ) -> str:
        """
        Categorize how good the chosen move was relative to Stockfish's top pick.
        Returns: 'best' | 'excellent' | 'good' | 'inaccuracy' | 'mistake' | 'blunder'

        When the chosen move is not in the pre-computed candidate list (e.g. blind
        mode), it is scored on-demand via a dedicated Stockfish query so that blind
        moves receive accurate quality labels instead of 'unknown'.
        """
        if not candidates:
            return "unknown"

        top_move, top_score = candidates[0]
        in_candidates = any(m == move for m, _ in candidates)
        chosen_score  = next((s for m, s in candidates if m == move), None)

        if move == top_move:
            return "best"

        if top_score is None:
            return "unknown"

        # Move not in the candidate list at all (common in blind mode) — score
        # it on-demand so we give an accurate label instead of 'unknown'.
        # If it was in the list but had a None score, we leave it as 'unknown'
        # (Stockfish couldn't score it reliably; no point re-querying).
        if chosen_score is None and not in_candidates:
            chosen_score = self.score_move(board, move)

        if chosen_score is None:
            return "unknown"

        loss = top_score - chosen_score  # centipawns lost vs best candidate

        if loss < CP_LOSS_EXCELLENT:
            return "excellent"
        elif loss < CP_LOSS_GOOD:
            return "good"
        elif loss < CP_LOSS_INACCURACY:
            return "inaccuracy"
        elif loss < CP_LOSS_MISTAKE:
            return "mistake"
        else:
            return "blunder"
