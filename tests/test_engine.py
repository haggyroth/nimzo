"""
Tests for StockfishEngine.evaluate_move_quality.

This is the only method in engine.py that is pure Python — no Stockfish
subprocess needed.  It categorises how good a chosen move was relative to
the engine's top pick, based on centipawn loss.

Boundary table (from engine.py):
    move == top_move              → "best"
    top or chosen score is None   → "good"
    loss < 10                     → "excellent"
    loss < 25                     → "good"
    loss < 50                     → "inaccuracy"
    loss < 150                    → "mistake"
    loss >= 150                   → "blunder"
"""
import chess

from engine import StockfishEngine


# Build a real engine instance without starting the subprocess — we only
# call evaluate_move_quality which doesn't touch self._engine.
def _engine() -> StockfishEngine:
    return StockfishEngine.__new__(StockfishEngine)


def _move(uci: str) -> chess.Move:
    return chess.Move.from_uci(uci)


# Convenience: build a candidates list with (move, score) pairs
def _cands(*pairs):
    return [(_move(uci), cp) for uci, cp in pairs]


class TestEvaluateMoveQuality:
    def setup_method(self):
        self.eng = _engine()
        self.board = chess.Board()  # starting position — only used for type; method ignores it

    # ── Empty / missing candidates ───────────────────────────────────────

    def test_empty_candidates_returns_unknown(self):
        assert self.eng.evaluate_move_quality(self.board, _move("e2e4"), []) == "unknown"

    # ── Top-move path ────────────────────────────────────────────────────

    def test_top_move_returns_best(self):
        cands = _cands(("e2e4", 30), ("d2d4", 20))
        assert self.eng.evaluate_move_quality(self.board, _move("e2e4"), cands) == "best"

    def test_top_move_with_none_score_still_best(self):
        """The top-move check fires before the None guard."""
        cands = _cands(("e2e4", None), ("d2d4", 20))
        assert self.eng.evaluate_move_quality(self.board, _move("e2e4"), cands) == "best"

    # ── None score guard ────────────────────────────────────────────────

    def test_none_top_score_returns_good(self):
        cands = _cands(("e2e4", None), ("d2d4", 20))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "good"

    def test_none_chosen_score_returns_good(self):
        """Chosen move is in the list but has no score."""
        cands = [(_move("e2e4"), 50), (_move("d2d4"), None)]
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "good"

    def test_both_scores_none_returns_good(self):
        cands = _cands(("e2e4", None), ("d2d4", None))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "good"

    # ── Move not in candidates list ──────────────────────────────────────

    def test_move_not_in_candidates_uses_none_path(self):
        """chosen_score will be None; function returns 'good'."""
        cands = _cands(("e2e4", 50), ("d2d4", 40))
        result = self.eng.evaluate_move_quality(self.board, _move("g1f3"), cands)
        assert result == "good"

    # ── Centipawn loss boundaries ────────────────────────────────────────

    def test_loss_0_is_excellent(self):
        """Non-top move with identical score is excellent (loss == 0 < 10)."""
        cands = _cands(("e2e4", 50), ("d2d4", 50))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "excellent"

    def test_loss_9_is_excellent(self):
        cands = _cands(("e2e4", 50), ("d2d4", 41))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "excellent"

    def test_loss_10_is_good(self):
        cands = _cands(("e2e4", 50), ("d2d4", 40))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "good"

    def test_loss_24_is_good(self):
        cands = _cands(("e2e4", 50), ("d2d4", 26))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "good"

    def test_loss_25_is_inaccuracy(self):
        cands = _cands(("e2e4", 50), ("d2d4", 25))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "inaccuracy"

    def test_loss_49_is_inaccuracy(self):
        cands = _cands(("e2e4", 100), ("d2d4", 51))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "inaccuracy"

    def test_loss_50_is_mistake(self):
        cands = _cands(("e2e4", 100), ("d2d4", 50))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "mistake"

    def test_loss_149_is_mistake(self):
        cands = _cands(("e2e4", 200), ("d2d4", 51))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "mistake"

    def test_loss_150_is_blunder(self):
        cands = _cands(("e2e4", 200), ("d2d4", 50))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "blunder"

    def test_loss_500_is_blunder(self):
        cands = _cands(("e2e4", 500), ("d2d4", 0))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "blunder"

    def test_negative_loss_treated_as_excellent(self):
        """If chosen score is somehow higher than top (e.g. multipv ordering artifact),
        loss is negative — still falls into the < 10 bucket (excellent)."""
        cands = _cands(("e2e4", 40), ("d2d4", 50))
        result = self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands)
        assert result == "excellent"

    # ── Mate scores (10000 / -10000) ────────────────────────────────────

    def test_forced_mate_top_then_miss_is_blunder(self):
        """Top candidate is a forced mate (10000cp); missing it is a blunder."""
        cands = _cands(("e2e4", 10000), ("d2d4", 50))
        assert self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands) == "blunder"

    def test_both_mates_top_is_best(self):
        cands = _cands(("e2e4", 10000), ("d2d4", 10000))
        assert self.eng.evaluate_move_quality(self.board, _move("e2e4"), cands) == "best"
