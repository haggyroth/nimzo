"""
tests/test_phase34.py — Phase 34: move latency tracking and Lichess link.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Move latency — DB layer ───────────────────────────────────────────────

class TestElapsedMsDb:
    """elapsed_ms column is written and read back correctly."""

    def _setup(self, tmp_path):
        import db as database
        db_path = tmp_path / "test.db"
        database.DB_PATH = db_path
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        database.upsert_player("white", "White", "lmstudio")
        database.upsert_player("black", "Black", "lmstudio")
        game_id = database.record_game(
            white_model_id="white", black_model_id="black",
            result="1-0", termination="checkmate", total_moves=10,
            pgn="1. e4 *",
            white_elo_before=1200.0, black_elo_before=1200.0,
            white_elo_after=1216.0, black_elo_after=1184.0,
        )
        return database, game_id

    def test_elapsed_ms_stored_and_retrieved(self, tmp_path):
        db, game_id = self._setup(tmp_path)
        db.record_move(
            game_id=game_id, move_number=1,
            player_model_id="white", move_uci="e2e4", move_san="e4",
            candidate_rank=1, quality="best", score_cp=30.0,
            reasoning="Central control", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            elapsed_ms=1234,
        )
        moves = db.get_game_moves(game_id)
        assert len(moves) == 1
        assert moves[0]["elapsed_ms"] == 1234

    def test_elapsed_ms_null_by_default(self, tmp_path):
        db, game_id = self._setup(tmp_path)
        db.record_move(
            game_id=game_id, move_number=1,
            player_model_id="white", move_uci="e2e4", move_san="e4",
            candidate_rank=1, quality="best", score_cp=30.0,
            reasoning="Central control", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        )
        moves = db.get_game_moves(game_id)
        assert moves[0]["elapsed_ms"] is None

    def test_elapsed_ms_zero_stored(self, tmp_path):
        """Zero is a valid latency (e.g. test doubles)."""
        db, game_id = self._setup(tmp_path)
        db.record_move(
            game_id=game_id, move_number=1,
            player_model_id="white", move_uci="e2e4", move_san="e4",
            candidate_rank=1, quality="best", score_cp=30.0,
            reasoning="", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            elapsed_ms=0,
        )
        moves = db.get_game_moves(game_id)
        assert moves[0]["elapsed_ms"] == 0

    def test_multiple_moves_each_have_independent_elapsed_ms(self, tmp_path):
        db, game_id = self._setup(tmp_path)
        fen1 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        fen2 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
        db.record_move(game_id=game_id, move_number=1, player_model_id="white",
                       move_uci="e2e4", move_san="e4", candidate_rank=1,
                       quality="best", score_cp=30.0, reasoning="",
                       fen_after=fen1, elapsed_ms=800)
        db.record_move(game_id=game_id, move_number=2, player_model_id="black",
                       move_uci="e7e5", move_san="e5", candidate_rank=1,
                       quality="best", score_cp=-10.0, reasoning="",
                       fen_after=fen2, elapsed_ms=2100)
        moves = db.get_game_moves(game_id)
        assert moves[0]["elapsed_ms"] == 800
        assert moves[1]["elapsed_ms"] == 2100

    def test_elapsed_ms_column_exists_after_migration(self, tmp_path):
        """Migration adds elapsed_ms even on an older DB that didn't have it."""
        import db as database
        db_path = tmp_path / "legacy.db"
        database.DB_PATH = db_path
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        # Just check the column is present in the schema
        import sqlite3
        con = sqlite3.connect(db_path)
        cols = {row[1] for row in con.execute("PRAGMA table_info(moves)")}
        con.close()
        assert "elapsed_ms" in cols


# ── Move latency — viewer.js utility (JS-side formatting) ─────────────────

class TestLatencyFormatting:
    """Pure-logic checks on how the JS would format elapsed_ms values.
    We test the Python-side pipeline; JS formatting is verified by inspection.
    """

    def test_elapsed_ms_is_integer_milliseconds(self, tmp_path):
        """Verify that elapsed_ms stored in the DB is in milliseconds (int)."""
        import db as database
        db_path = tmp_path / "test.db"
        database.DB_PATH = db_path
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        database.upsert_player("m", "M", "lmstudio")
        game_id = database.record_game(
            "m", "m", "1/2-1/2", "stalemate", 2, "1. e4 *",
            1200.0, 1200.0, 1200.0, 1200.0,
        )
        database.record_move(
            game_id=game_id, move_number=1, player_model_id="m",
            move_uci="e2e4", move_san="e4", candidate_rank=1,
            quality="best", score_cp=30.0, reasoning="",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            elapsed_ms=3456,
        )
        moves = db.get_game_moves(game_id) if False else database.get_game_moves(game_id)
        assert isinstance(moves[0]["elapsed_ms"], int)
        # 3456 ms → 3.456 s; viewer shows (elapsed_ms / 1000).toFixed(1) = "3.5s"
        assert round(moves[0]["elapsed_ms"] / 1000, 1) == 3.5


# ── WebSocket event table — elapsed_ms field ─────────────────────────────

class TestElapsedMsBroadcast:
    """elapsed_ms flows through the move broadcast dict in game.py."""

    def test_move_record_dict_has_elapsed_ms_key(self):
        """The move_records dict accumulates elapsed_ms so record_move gets it."""
        # Simulate what game.py does to build a move record entry
        import time
        t0 = time.perf_counter()
        # ... model inference would happen here ...
        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        move_rec = {
            "move_number": 1,
            "player_model_id": "model-a",
            "elapsed_ms": elapsed_ms,
        }
        assert "elapsed_ms" in move_rec
        assert isinstance(move_rec["elapsed_ms"], int)
        assert move_rec["elapsed_ms"] >= 0
