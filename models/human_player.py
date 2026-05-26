"""
Human player — waits for a move submitted via the /api/human-move endpoint
rather than calling an LLM.  Used in Human vs LLM match mode.
"""

from __future__ import annotations

import threading
import chess

from models.base import ChessPlayer, MoveDecision, PlayerConfig


class HumanPlayer(ChessPlayer):
    """
    Blocking choose_move() that yields to human input via the browser.

    The game loop calls choose_move() inside a ThreadPoolExecutor thread,
    so blocking here keeps the asyncio event loop free for WebSocket
    broadcasts and the /api/human-move REST endpoint.

    Flow:
      1. choose_move() stores the board, resets _move_ready, and waits.
      2. Browser shows the board; human clicks a piece then a destination.
      3. Browser POSTs to /api/human-move { "uci": "e2e4" }.
      4. API endpoint calls submit_move(uci).
      5. submit_move() validates legality, stores the UCI, and sets _move_ready.
      6. choose_move() resumes and returns a MoveDecision.
    """

    def __init__(self, config: PlayerConfig):
        super().__init__(config)
        self._move_ready  = threading.Event()
        self._pending_uci: str | None = None
        self._current_board: chess.Board | None = None
        self._current_candidates: list[tuple[chess.Move, float | None]] = []

    # ── Called by the game loop ───────────────────────────────────────────

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float | None]],
        game_history_pgn: str,
    ) -> MoveDecision:
        """
        Block until the human submits a move via the browser UI.

        Stores board state and candidates so the viewer can display them,
        then waits on ``_move_ready`` for up to 5 minutes.  Falls back to
        Stockfish's top candidate on timeout.
        """
        self._current_board     = board.copy()
        self._current_candidates = list(candidates)
        self._pending_uci       = None
        self._move_ready.clear()

        # Wait up to 5 minutes for the human to move; time-out gracefully.
        if not self._move_ready.wait(timeout=300):
            fallback = candidates[0][0].uci() if candidates else "0000"
            return MoveDecision(
                move_uci=fallback,
                reasoning="(human timed out — fell back to top Stockfish candidate)",
                candidate_rank=1,
                raw_response="",
            )

        uci  = self._pending_uci
        move = chess.Move.from_uci(uci)

        # Determine candidate rank (1-based); moves outside the list get N+1.
        rank = next(
            (i + 1 for i, (m, _) in enumerate(candidates) if m == move),
            len(candidates) + 1,
        )
        return MoveDecision(
            move_uci=uci,
            reasoning="(human move)",
            candidate_rank=rank,
            raw_response="",
        )

    # ── Called by the /api/human-move endpoint ────────────────────────────

    def submit_move(self, uci: str) -> bool:
        """
        Deliver the human's chosen move.
        Returns False if no move is currently awaited, or the move is illegal.
        """
        if self._current_board is None:
            return False
        if self._move_ready.is_set():
            return False  # move already submitted (shouldn't happen normally)
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            return False
        if move not in self._current_board.legal_moves:
            return False
        self._pending_uci = uci
        self._move_ready.set()
        return True

    def get_legal_uci_moves(self) -> list[str]:
        """All legal UCI moves on the current board (sent to the viewer for highlighting)."""
        if self._current_board is None:
            return []
        return [m.uci() for m in self._current_board.legal_moves]

    def get_candidate_uci_moves(self) -> list[str]:
        """UCI moves restricted to Stockfish candidates (for assisted mode)."""
        return [m.uci() for m, _ in self._current_candidates]
