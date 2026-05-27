"""
Integration tests for the arena game loop.

These tests use a StubPlayer (returns the first candidate every time) and a
MockStockfishEngine (generates legal moves with dummy scores) to exercise
play_game() end-to-end without a real Stockfish binary or LLM backend.

Coverage targets: L3 from review.md
  - play_game returns a valid result summary
  - result is always one of "1-0", "0-1", "1/2-1/2"
  - game records are written to the DB
  - move records are written to the DB with quality labels
  - adaptive_difficulty adjusts candidate_count after a lopsided win rate
  - TournamentAborted is raised when _stop_requested is set mid-game
"""

from __future__ import annotations

import asyncio
import chess
import pytest

from models.base import ChessPlayer, MoveDecision, PlayerConfig
import db as database


# ── Stub helpers ─────────────────────────────────────────────────────────────

class StubPlayer(ChessPlayer):
    """Always picks the first candidate — no LLM call needed."""

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision:
        move = candidates[0][0]
        return MoveDecision(
            move_uci=move.uci(),
            reasoning="stub: first candidate",
            candidate_rank=1,
            raw_response="",
        )


class MockStockfishEngine:
    """
    Minimal engine stub.  Returns up to N legal moves with arbitrary scores
    so play_game() gets a valid candidates list every turn.
    """

    def get_candidates(
        self,
        board: chess.Board,
        n: int = 5,
    ) -> list[tuple[chess.Move, float]]:
        legal = list(board.legal_moves)[:n]
        # Assign fake centipawn scores descending from 100
        return [(m, 100 - i * 5) for i, m in enumerate(legal)]

    def analyse(self, board: chess.Board, depth: int = 15):
        """Stub — returns the first legal move with a constant score."""
        legal = list(board.legal_moves)
        if not legal:
            return None
        from engine import AnalysisResult
        return AnalysisResult(best_move=legal[0], score_cp=0)

    def evaluate_move_quality(
        self,
        board: chess.Board,
        move: chess.Move,
        candidates: list,
    ) -> str:
        return "good"

    # Context manager support (StockfishEngine uses `with`)
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _make_player(model_id: str, name: str) -> StubPlayer:
    cfg = PlayerConfig(
        name=name,
        model_id=model_id,
        backend="lmstudio",
        candidate_count=3,
    )
    return StubPlayer(cfg)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirect the DB to a temporary file for each test."""
    db_file = tmp_path / "test_arena.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    yield
    # DB file cleaned up with tmp_path automatically


@pytest.fixture(autouse=True)
def _reset_arena_state():
    """
    Reset arena global state before each test so tests are independent.
    Uses the mutable container directly — monkeypatch on a dict key is not
    needed and wouldn't survive the C-1 fix anyway.
    """
    import arena
    arena._stop["requested"] = False
    arena._pause_event.set()   # ensure unpaused
    yield
    arena._stop["requested"] = False
    arena._pause_event.set()


# ── play_game tests ───────────────────────────────────────────────────────────

class TestPlayGame:

    def _run(self, white=None, black=None, **kwargs):
        """Helper: run play_game synchronously in a fresh event loop."""
        from arena import play_game
        w = white or _make_player("white-bot", "White")
        b = black or _make_player("black-bot", "Black")
        engine = MockStockfishEngine()
        database.upsert_player(model_id=w.config.model_id, name=w.config.name, backend="lmstudio")
        database.upsert_player(model_id=b.config.model_id, name=b.config.name, backend="lmstudio")

        async def _go():
            return await play_game(w, b, engine, game_number=1, **kwargs)

        return asyncio.run(_go())

    def test_returns_dict_with_result(self):
        summary = self._run()
        assert isinstance(summary, dict)
        assert "result" in summary
        assert "game_id" in summary

    def test_result_is_valid(self):
        summary = self._run()
        assert summary["result"] in ("1-0", "0-1", "1/2-1/2")

    def test_game_record_written_to_db(self):
        summary = self._run()
        game = database.get_game(summary["game_id"])
        assert game is not None
        assert game["result"] in ("1-0", "0-1", "1/2-1/2")

    def test_move_records_written_to_db(self):
        summary = self._run()
        moves = database.get_game_moves(summary["game_id"])
        # A real game has at least one move before termination
        assert len(moves) >= 1

    def test_move_quality_labels_are_valid(self):
        valid = {"best", "excellent", "good", "inaccuracy", "mistake", "blunder", "unknown"}
        summary = self._run()
        moves = database.get_game_moves(summary["game_id"])
        for m in moves:
            assert m["quality"] in valid, f"unexpected quality: {m['quality']}"

    def test_elo_updated_after_game(self):
        w = _make_player("elo-white", "EloWhite")
        b = _make_player("elo-black", "EloBlack")
        database.upsert_player(model_id=w.config.model_id, name=w.config.name, backend="lmstudio")
        database.upsert_player(model_id=b.config.model_id, name=b.config.name, backend="lmstudio")
        initial_w = database.get_player_elo(w.config.model_id)
        initial_b = database.get_player_elo(b.config.model_id)

        from arena import play_game
        engine = MockStockfishEngine()

        async def _go():
            return await play_game(w, b, engine, game_number=1)

        summary = asyncio.run(_go())
        new_w = database.get_player_elo(w.config.model_id)
        new_b = database.get_player_elo(b.config.model_id)

        # ELOs must change — one wins, one loses (or they draw and swap points)
        result = summary["result"]
        if result == "1/2-1/2":
            # Draw at equal ELO → no change
            pass
        else:
            assert new_w != initial_w or new_b != initial_b, "ELO unchanged after decisive game"

    def test_no_tutor_no_lessons(self):
        self._run(tutor=None)
        lessons = database.get_player_lessons("white-bot")
        assert lessons == []

    def test_stop_requested_raises_tournament_aborted(self):
        """Setting _stop["requested"] mid-game should raise TournamentAborted.

        This test exercises the real production write path (mutating the dict)
        rather than monkeypatching arena._stop_requested, which was the path
        that masked the C-1 bug — see REVIEW.md.
        """
        import arena

        call_count = 0

        class StopAfterFirstMove(StubPlayer):
            def choose_move(self, board, candidates, pgn):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Signal stop via the mutable container (production path)
                    arena._stop["requested"] = True
                return super().choose_move(board, candidates, pgn)

        w = StopAfterFirstMove(PlayerConfig(
            name="StopBot", model_id="stop-white", backend="lmstudio", candidate_count=3,
        ))
        b = _make_player("stop-black", "StopBlack")
        database.upsert_player(model_id=w.config.model_id, name=w.config.name, backend="lmstudio")
        database.upsert_player(model_id=b.config.model_id, name=b.config.name, backend="lmstudio")

        from arena import play_game, TournamentAborted

        async def _go():
            return await play_game(w, b, MockStockfishEngine(), game_number=1)

        with pytest.raises(TournamentAborted):
            asyncio.run(_go())


class TestAdaptiveDifficulty:
    """play_game's adaptive_difficulty block adjusts candidate_count correctly."""

    def _seed_wins(self, model_id: str, opponent_id: str, n: int, result: str = "1-0"):
        """Seed n games with the given result for model_id as white."""
        for _ in range(n):
            database.record_game(
                white_model_id=model_id,
                black_model_id=opponent_id,
                result=result,
                termination="checkmate",
                total_moves=10,
                pgn="1. e4 e5 *",
                white_elo_before=1200, black_elo_before=1200,
                white_elo_after=1216, black_elo_after=1184,
            )

    def test_high_win_rate_reduces_candidates(self):
        """A win rate > 0.65 over 10 games should reduce candidate_count by 1."""
        wid, bid = "dominant", "fodder"
        database.upsert_player(model_id=wid, name=wid, backend="lmstudio")
        database.upsert_player(model_id=bid, name=bid, backend="lmstudio")
        # Seed 9 wins, 1 loss → 90% win rate
        self._seed_wins(wid, bid, n=9, result="1-0")
        self._seed_wins(bid, wid, n=1, result="1-0")  # 1 loss for wid

        w = _make_player(wid, "Dominant")
        b = _make_player(bid, "Fodder")
        w.config.candidate_count = 5

        from arena import play_game
        engine = MockStockfishEngine()

        async def _go():
            return await play_game(w, b, engine, game_number=1, adaptive_difficulty=True)

        asyncio.run(_go())
        assert w.config.candidate_count == 4, (
            f"Expected 4 candidates after high win rate, got {w.config.candidate_count}"
        )

    def test_low_win_rate_increases_candidates(self):
        """A win rate < 0.35 over 10 games should increase candidate_count by 1."""
        wid, bid = "struggling", "strong"
        database.upsert_player(model_id=wid, name=wid, backend="lmstudio")
        database.upsert_player(model_id=bid, name=bid, backend="lmstudio")
        # Seed 9 losses (as black, bid wins), 1 win
        self._seed_wins(bid, wid, n=9, result="1-0")  # wid loses
        self._seed_wins(wid, bid, n=1, result="1-0")   # wid wins once

        w = _make_player(wid, "Struggling")
        b = _make_player(bid, "Strong")
        w.config.candidate_count = 5

        from arena import play_game
        engine = MockStockfishEngine()

        async def _go():
            return await play_game(w, b, engine, game_number=1, adaptive_difficulty=True)

        asyncio.run(_go())
        assert w.config.candidate_count == 6, (
            f"Expected 6 candidates after low win rate, got {w.config.candidate_count}"
        )

    def test_no_change_when_insufficient_history(self):
        """Fewer than 10 games → win rate returns None → no adjustment."""
        wid, bid = "newbie", "also-new"
        database.upsert_player(model_id=wid, name=wid, backend="lmstudio")
        database.upsert_player(model_id=bid, name=bid, backend="lmstudio")
        # Only 3 games — not enough for the rolling window
        self._seed_wins(wid, bid, n=3, result="1-0")

        w = _make_player(wid, "Newbie")
        b = _make_player(bid, "AlsoNew")
        w.config.candidate_count = 5

        from arena import play_game
        engine = MockStockfishEngine()

        async def _go():
            return await play_game(w, b, engine, game_number=1, adaptive_difficulty=True)

        asyncio.run(_go())
        assert w.config.candidate_count == 5


# ── Regression tests for Phase-23 critical fixes ─────────────────────────────

class TestStopFlagAliasing:
    """
    Regression for REVIEW.md C-1: verify that writing to arena.state._stop
    is visible to arena._stop (they must be the same dict object, not two
    independent bool bindings created by `from arena.state import _stop_requested`).
    """

    def test_stop_dict_is_same_object_in_package_and_state(self):
        """arena._stop and arena.state._stop must be the same dict."""
        import arena
        import arena.state as state
        assert arena._stop is state._stop, (
            "arena._stop is a different object from arena.state._stop — "
            "the aliasing bug has returned."
        )

    def test_writing_via_state_visible_in_package(self):
        """Writing state._stop['requested'] must be visible as arena._stop['requested']."""
        import arena
        import arena.state as state
        state._stop["requested"] = True
        try:
            assert arena._stop["requested"] is True
        finally:
            state._stop["requested"] = False

    def test_mode_dict_is_same_object_in_package_and_state(self):
        """arena._mode and arena.state._mode must be the same dict (C-2)."""
        import arena
        import arena.state as state
        assert arena._mode is state._mode, (
            "arena._mode is a different object from arena.state._mode — "
            "headless aliasing bug has returned."
        )
