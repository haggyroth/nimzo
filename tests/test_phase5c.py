"""
tests/test_phase5c.py — Phase 5c: Move explanation mode.

Covers:
  C-1  analysis.generate_move_explanation returns None when quality is not blunder/mistake
  C-2  analysis.generate_move_explanation returns None when tutor is unconfigured
  C-3  analysis.generate_move_explanation calls tutor and returns stripped text
  C-4  analysis.generate_move_explanation strips <think> blocks from output
  C-5  analysis.generate_move_explanation returns None for short/empty responses
  C-6  db.record_move accepts explanation parameter (no error)
  C-7  db.get_game_moves returns explanation field
  C-8  db.record_move with explanation=None stores NULL, returned as None
  C-9  HTTP: GET /api/games/<id>/moves includes explanation field
  C-10 viewer.js defines onMoveExplanation function
  C-11 viewer.js dispatches move_explanation WS event
  C-12 viewer.js addMoveCard sets data-move attribute
  C-13 viewer.js rpRender shows .rp-explanation block when explanation present
  C-14 viewer.css defines .move-explanation class
  C-15 viewer.css defines .rp-explanation class
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import arena  # noqa: F401 — pre-init the package


# ── Paths ──────────────────────────────────────────────────────────────────

_VIEWER_JS  = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_CSS = Path(__file__).parents[1] / "static" / "viewer.css"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_conn_factory(db_path: Path):
    @contextmanager
    def _conn(path_arg=None):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _conn


# ── C-1 / C-2 / C-3 / C-4 / C-5: analysis.generate_move_explanation ──────

class TestGenerateMoveExplanation:
    def _tutor(self):
        from analysis import TutorConfig
        return TutorConfig(backend="lmstudio", model_id="test-model")

    def test_returns_none_for_good_quality(self):
        """C-1: No explanation for 'good' or 'excellent' moves."""
        from analysis import generate_move_explanation
        for q in ("good", "excellent", "best", "inaccuracy"):
            result = generate_move_explanation(
                board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                played_san="e5",
                best_san="e5",
                cp_loss=5,
                quality=q,
                tutor=self._tutor(),
            )
            assert result is None, f"Expected None for quality={q!r}, got {result!r}"

    def test_returns_none_without_tutor(self):
        """C-2: Returns None when no tutor is configured."""
        from analysis import TutorConfig, generate_move_explanation
        result = generate_move_explanation(
            board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            played_san="Nc6",
            best_san="e5",
            cp_loss=200,
            quality="blunder",
            tutor=TutorConfig(backend="lmstudio", model_id=""),
        )
        assert result is None

    def test_calls_tutor_and_returns_text(self):
        """C-3: Calls _call_tutor_like and returns the stripped response."""
        from analysis import generate_move_explanation
        expected = "Playing Nc6 allows White's pawn fork on d5, winning a piece. Stockfish preferred e5, which contests the center immediately."
        with patch("analysis._call_tutor_like", return_value=expected) as mock_call:
            result = generate_move_explanation(
                board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                played_san="Nc6",
                best_san="e5",
                cp_loss=200,
                quality="blunder",
                tutor=self._tutor(),
            )
        assert result == expected
        assert mock_call.called

    def test_strips_think_blocks(self):
        """C-4: <think>…</think> blocks are removed from the response."""
        from analysis import generate_move_explanation
        raw = "<think>Let me think about this...</think>Nc6 walks into a fork."
        with patch("analysis._call_tutor_like", return_value=raw):
            result = generate_move_explanation(
                board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                played_san="Nc6", best_san="e5", cp_loss=200, quality="blunder",
                tutor=self._tutor(),
            )
        assert result == "Nc6 walks into a fork."
        assert "<think>" not in result

    def test_returns_none_for_short_response(self):
        """C-5: Returns None when the LLM produces a very short response."""
        from analysis import generate_move_explanation
        with patch("analysis._call_tutor_like", return_value="ok"):
            result = generate_move_explanation(
                board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                played_san="Nc6", best_san="e5", cp_loss=200, quality="blunder",
                tutor=self._tutor(),
            )
        assert result is None

    def test_works_for_mistake(self):
        """C-3b: Works for 'mistake' quality too."""
        from analysis import generate_move_explanation
        expected = "This knight move fails to contest the center, giving White a lasting advantage."
        with patch("analysis._call_tutor_like", return_value=expected):
            result = generate_move_explanation(
                board_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                played_san="Nc6", best_san="d5", cp_loss=80, quality="mistake",
                tutor=self._tutor(),
            )
        assert result == expected


# ── C-6 / C-7 / C-8: db layer ─────────────────────────────────────────────

class TestMoveExplanationDb:
    def _seed_game(self, database, db_path):
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        database.upsert_player("m-a", "Alice", "lmstudio")
        database.upsert_player("m-b", "Bob",   "lmstudio")
        return database.record_game(
            "m-a", "m-b", "1-0", "Checkmate", 4,
            "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#",
            1200.0, 1200.0, 1220.0, 1180.0,
        )

    def test_record_move_with_explanation(self, tmp_path):
        """C-6: record_move accepts explanation without error."""
        import db as database
        db_path = tmp_path / "expl.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed_game(database, db_path)
            database.record_move(
                game_id=game_id, move_number=1, player_model_id="m-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="best", score_cp=20,
                reasoning="Central control", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                explanation="The best central move, fighting for space.",
            )
            rows = database.get_game_moves(game_id)
        assert len(rows) == 1
        assert rows[0]["explanation"] == "The best central move, fighting for space."

    def test_get_game_moves_includes_explanation_field(self, tmp_path):
        """C-7: get_game_moves always returns explanation field."""
        import db as database
        db_path = tmp_path / "expl2.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed_game(database, db_path)
            database.record_move(
                game_id=game_id, move_number=1, player_model_id="m-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="blunder", score_cp=-80,
                reasoning="oops", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            )
            rows = database.get_game_moves(game_id)
        assert "explanation" in rows[0]

    def test_explanation_null_when_not_set(self, tmp_path):
        """C-8: explanation is None when not provided."""
        import db as database
        db_path = tmp_path / "expl3.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed_game(database, db_path)
            database.record_move(
                game_id=game_id, move_number=1, player_model_id="m-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="best", score_cp=20,
                reasoning="Good move", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            )
            rows = database.get_game_moves(game_id)
        assert rows[0]["explanation"] is None


# ── C-9: HTTP ──────────────────────────────────────────────────────────────

class TestMoveExplanationHttp:
    def test_moves_endpoint_includes_explanation(self, tmp_path):
        """C-9: GET /api/games/<id>/moves includes explanation field."""
        import db as database
        from fastapi.testclient import TestClient

        db_path = tmp_path / "http.db"
        _conn = _make_conn_factory(db_path)

        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("m-a", "Alice", "lmstudio")
            database.upsert_player("m-b", "Bob",   "lmstudio")
            gid = database.record_game(
                "m-a", "m-b", "1-0", "Checkmate", 2,
                "1. e4 e5 *", 1200.0, 1200.0, 1220.0, 1180.0,
            )
            database.record_move(
                game_id=gid, move_number=1, player_model_id="m-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="blunder", score_cp=-100,
                reasoning="bad idea", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                explanation="This was a terrible mistake.",
            )
            from arena import app as _app
            with TestClient(_app, raise_server_exceptions=True) as client:
                resp = client.get(f"/api/games/{gid}/moves")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "explanation" in data[0]
        assert data[0]["explanation"] == "This was a terrible mistake."


# ── C-10 / C-11 / C-12 / C-13: viewer.js ─────────────────────────────────

class TestViewerJsPhase5c:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_on_move_explanation_defined(self):
        """C-10: onMoveExplanation function is defined."""
        assert "function onMoveExplanation" in self._src()

    def test_move_explanation_in_dispatch(self):
        """C-11: move_explanation is wired in the WS dispatch switch."""
        src = self._src()
        assert "move_explanation" in src
        assert "onMoveExplanation" in src

    def test_add_move_card_sets_data_move(self):
        """C-12: addMoveCard sets data-move attribute on the card element."""
        src = self._src()
        # Find addMoveCard function body
        start = src.index("function addMoveCard")
        end   = src.index("// ── Right-panel tab")
        fn    = src[start:end]
        assert "data-move" in fn or "dataset.move" in fn

    def test_rp_render_shows_explanation_block(self):
        """C-13: rpRender emits .rp-explanation block when explanation is present."""
        src = self._src()
        assert "rp-explanation" in src
        assert "m.explanation" in src

    def test_move_explanation_block_in_addmovecard(self):
        """C-10b: onMoveExplanation targets .move-explanation class."""
        src = self._src()
        assert "move-explanation" in src


# ── C-14 / C-15: viewer.css ───────────────────────────────────────────────

class TestViewerCssPhase5c:
    def _css(self):
        return _VIEWER_CSS.read_text()

    def test_move_explanation_class_defined(self):
        """C-14: .move-explanation is defined in viewer.css."""
        assert ".move-explanation" in self._css()

    def test_rp_explanation_class_defined(self):
        """C-15: .rp-explanation is defined in viewer.css."""
        assert ".rp-explanation" in self._css()

    def test_move_expl_label_defined(self):
        """C-14b: .move-expl-label styling exists."""
        assert ".move-expl-label" in self._css()
