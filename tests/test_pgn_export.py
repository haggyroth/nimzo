"""
Tests for PGN export:
  - _build_game_pgn()  — header tags, move body, quality glyphs, comment blocks,
                         round number, line wrapping, fallback reasoning suppression
  - db.get_all_games() — no filter, model_id filter, limit, ordering
  - /api/games/export  — route reachable (regression for REVIEW.md C-3)
"""

import pytest

from arena import _build_game_pgn


# ── Fixtures ──────────────────────────────────────────────────────────────────

GAME_ROW = {
    "played_at":       "2026-01-15T10:00:00",
    "white_name":      "Qwen",
    "black_name":      "Llama",
    "result":          "1-0",
    "white_elo_before": 1250.0,
    "black_elo_before": 1180.0,
}

def _move(num, san, quality="good", reasoning="Solid central control.", rank=2):
    return {
        "move_number":   num,
        "move_san":      san,
        "quality":       quality,
        "reasoning":     reasoning,
        "candidate_rank": rank,
    }


# ── _build_game_pgn: header tags ──────────────────────────────────────────────

class TestBuildGamePgnHeaders:
    def test_contains_event_tag(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[Event "Nimzo Arena"]' in pgn

    def test_contains_site_tag(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[Site "localhost"]' in pgn

    def test_date_tag_uses_iso_date_only(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[Date "2026-01-15"]' in pgn

    def test_white_tag(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[White "Qwen"]' in pgn

    def test_black_tag(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[Black "Llama"]' in pgn

    def test_result_tag(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[Result "1-0"]' in pgn

    def test_white_elo_tag_rounded(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[WhiteElo "1250"]' in pgn

    def test_black_elo_tag_rounded(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert '[BlackElo "1180"]' in pgn

    def test_no_round_tag_by_default(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert "[Round" not in pgn

    def test_round_tag_included_when_set(self):
        pgn = _build_game_pgn(GAME_ROW, [], round_number=3)
        assert '[Round "3"]' in pgn

    def test_result_appears_in_body(self):
        pgn = _build_game_pgn(GAME_ROW, [])
        assert "1-0" in pgn.split("\n\n", 1)[-1]  # in the movetext section


# ── _build_game_pgn: move body ────────────────────────────────────────────────

class TestBuildGamePgnMoves:
    def test_white_move_has_number_prefix(self):
        moves = [_move(1, "e4")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "1. e4" in pgn

    def test_black_move_has_no_own_number(self):
        moves = [_move(1, "e4"), _move(2, "e5")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        # Black's move should follow white's without an intermediate number
        body = pgn.split("\n\n", 1)[-1]
        assert "e5" in body
        assert "2. e5" not in body   # black doesn't get "2." prefix

    def test_next_white_move_gets_new_number(self):
        moves = [_move(1, "e4"), _move(2, "e5"), _move(3, "Nf3")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "2. Nf3" in pgn

    def test_quality_glyph_blunder(self):
        moves = [_move(1, "Qh5", quality="blunder")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Qh5??" in pgn

    def test_quality_glyph_mistake(self):
        moves = [_move(1, "Bc4", quality="mistake")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Bc4?" in pgn

    def test_quality_glyph_inaccuracy(self):
        moves = [_move(1, "Nc3", quality="inaccuracy")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Nc3?!" in pgn

    def test_quality_glyph_best(self):
        moves = [_move(1, "e4", quality="best")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "e4!!" in pgn

    def test_quality_glyph_excellent(self):
        moves = [_move(1, "d4", quality="excellent")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "d4!" in pgn

    def test_good_quality_has_no_glyph(self):
        moves = [_move(1, "c4", quality="good")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        body = pgn.split("\n\n", 1)[-1]
        assert "c4" in body
        assert "c4?" not in body
        assert "c4!" not in body


# ── _build_game_pgn: comment blocks ──────────────────────────────────────────

class TestBuildGamePgnComments:
    def test_reasoning_in_comment(self):
        moves = [_move(1, "e4", reasoning="Controls the center.")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Controls the center." in pgn
        assert "{" in pgn

    def test_candidate_rank_in_comment(self):
        moves = [_move(1, "e4", rank=3)]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "candidate #3" in pgn

    def test_good_quality_not_in_comment(self):
        """'good' is the baseline — not worth cluttering comments with it."""
        moves = [_move(1, "e4", quality="good", reasoning="Fine move.", rank=1)]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Good" not in pgn

    def test_non_good_quality_appears_in_comment(self):
        moves = [_move(1, "Qh5", quality="blunder", reasoning="Attack.", rank=4)]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "Blunder" in pgn

    def test_paren_reasoning_suppressed(self):
        """Human / fallback moves start with '(' — should not appear in comments."""
        moves = [_move(1, "e4", reasoning="(human move)", rank=1, quality="good")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "(human move)" not in pgn

    def test_braces_in_reasoning_escaped(self):
        """Curly braces in reasoning are stripped (not converted to parens) for
        PGN safety — MN-14 fix: stripping preserves readability and avoids the
        false-positive suppression caused by the old { → ( replacement."""
        moves = [_move(1, "e4", reasoning="A {good} move.")]
        pgn = _build_game_pgn(GAME_ROW, moves)
        assert "{good}" not in pgn     # literal braces must not appear in comment
        assert "A good move." in pgn   # content preserved after stripping braces

    def test_no_comment_block_when_no_content(self):
        """Rank=0, quality=good, no reasoning → no comment at all."""
        moves = [_move(1, "e4", quality="good", reasoning="", rank=0)]
        pgn = _build_game_pgn(GAME_ROW, moves)
        body = pgn.split("\n\n", 1)[-1]
        assert "{" not in body

    def test_result_token_appended(self):
        pgn = _build_game_pgn(GAME_ROW, [_move(1, "e4")])
        assert pgn.strip().endswith("1-0")


# ── _build_game_pgn: line wrapping ────────────────────────────────────────────

class TestBuildGamePgnLineWrap:
    def test_no_line_exceeds_80_chars(self):
        moves = [_move(i * 2 - 1, "Nf3", reasoning="Long reasoning " * 5, rank=2)
                 for i in range(1, 11)]
        pgn = _build_game_pgn(GAME_ROW, moves)
        body = pgn.split("\n\n", 1)[-1]
        for ln in body.splitlines():
            assert len(ln) <= 80, f"line too long ({len(ln)}): {ln!r}"


# ── db.get_all_games ──────────────────────────────────────────────────────────

def _make_game(db, white_mid, black_mid, result="1-0"):
    db.upsert_player(model_id=white_mid, name=white_mid, backend="lmstudio")
    db.upsert_player(model_id=black_mid, name=black_mid, backend="lmstudio")
    return db.record_game(
        white_model_id=white_mid, black_model_id=black_mid,
        result=result, termination="checkmate", total_moves=10,
        pgn="1. e4 e5 *", white_elo_before=1200, black_elo_before=1200,
        white_elo_after=1216, black_elo_after=1184,
    )


class TestGetAllGames:
    def test_empty_returns_empty_list(self, tmp_db):
        assert tmp_db.get_all_games() == []

    def test_returns_all_games(self, tmp_db):
        _make_game(tmp_db, "qa", "qb")
        _make_game(tmp_db, "qa", "qb")
        rows = tmp_db.get_all_games()
        assert len(rows) == 2

    def test_ordered_oldest_first(self, tmp_db):
        id1 = _make_game(tmp_db, "qa", "qb")
        id2 = _make_game(tmp_db, "qa", "qb")
        rows = tmp_db.get_all_games()
        assert rows[0]["id"] == id1
        assert rows[1]["id"] == id2

    def test_model_id_filter_white(self, tmp_db):
        _make_game(tmp_db, "alpha", "beta")
        _make_game(tmp_db, "gamma", "delta")
        rows = tmp_db.get_all_games(model_id="alpha")
        assert len(rows) == 1
        assert rows[0]["white_model_id"] == "alpha"

    def test_model_id_filter_black(self, tmp_db):
        _make_game(tmp_db, "alpha", "beta")
        _make_game(tmp_db, "gamma", "delta")
        rows = tmp_db.get_all_games(model_id="beta")
        assert len(rows) == 1
        assert rows[0]["black_model_id"] == "beta"

    def test_model_id_filter_both_colours(self, tmp_db):
        """Model plays as both white and black across different games."""
        _make_game(tmp_db, "pivot", "opponent")
        _make_game(tmp_db, "opponent", "pivot")
        rows = tmp_db.get_all_games(model_id="pivot")
        assert len(rows) == 2

    def test_model_id_filter_no_match_returns_empty(self, tmp_db):
        _make_game(tmp_db, "qa", "qb")
        assert tmp_db.get_all_games(model_id="nonexistent") == []

    def test_limit_respected(self, tmp_db):
        for _ in range(5):
            _make_game(tmp_db, "qa", "qb")
        rows = tmp_db.get_all_games(limit=3)
        assert len(rows) == 3

    def test_row_includes_model_ids(self, tmp_db):
        _make_game(tmp_db, "model-w", "model-b")
        row = tmp_db.get_all_games()[0]
        assert row["white_model_id"] == "model-w"
        assert row["black_model_id"] == "model-b"


# ── Regression: /api/games/export route reachable (REVIEW.md C-3) ────────────

class TestGamesExportRoute:
    """
    Verify that GET /api/games/export returns 200 and not 422.
    Prior to Phase-23 the route was shadowed by /api/games/{game_id}, causing
    FastAPI to try to coerce "export" to int and return 422.
    """

    @pytest.fixture(autouse=True)
    def _init_db(self, tmp_path, monkeypatch):
        """Wire the db module to a fresh temp DB for every test in this class."""
        import db as database
        import sqlite3
        from unittest.mock import patch
        from contextlib import contextmanager

        db_path = tmp_path / "export_test.db"

        @contextmanager
        def _patched_get_conn(db_path_arg=None):
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

        with patch.object(database, "get_conn", _patched_get_conn):
            database.init_db(db_path)
            yield

    def test_export_route_returns_200_not_422(self):
        from fastapi.testclient import TestClient
        from arena import app
        client = TestClient(app)
        resp = client.get("/api/games/export?limit=1")
        assert resp.status_code == 200, (
            f"Expected 200 from /api/games/export, got {resp.status_code}. "
            "Route ordering regression — export route must be registered before "
            "{game_id} parametric routes."
        )

    def test_export_route_returns_plain_text(self):
        from fastapi.testclient import TestClient
        from arena import app
        client = TestClient(app)
        resp = client.get("/api/games/export?limit=1")
        ct = resp.headers.get("content-type", "")
        assert "text/plain" in ct, f"Expected text/plain content-type, got {ct!r}"

    def test_export_route_content_disposition_when_games_exist(self):
        """When games exist the response has a Content-Disposition attachment header."""
        import db as database
        _make_game(database, "w-model", "b-model")

        from fastapi.testclient import TestClient
        from arena import app
        client = TestClient(app)
        resp = client.get("/api/games/export?limit=10")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
