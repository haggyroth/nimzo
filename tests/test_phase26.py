"""
tests/test_phase26.py — Phase 26: Wave A viewer polish.

Covers:
  W-1  db.get_game_moves now includes fen_after field
  W-2  build_bracket includes white_seed / black_seed in round-1 matches
  W-3  build_bracket seed values are 1-based and match ELO-seed order
  W-4  advance_bracket carries seed through to next round
  W-5  viewer.js tracks per-player avg elapsed_ms (gameState.elapsedSum/Count)
  W-6  viewer.js rpToggleAutoplay is defined
  W-7  viewer.js replay move list renders rp-elapsed badge
  W-8  viewer.js rpRender updates reasoning panel
  W-9  viewer.js renderBracket emits bracket-seed and bracket-champion
  W-10 viewer.html has p-latency elements for both players
  W-11 viewer.html has rpPlay autoplay button
  W-12 viewer.html has rpReasoning panel element
  W-13 HTTP: GET /api/games/<id>/moves returns fen_after
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import arena  # noqa: F401 — pre-init to avoid circular import


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_context(tmp_path: Path):
    import db as database
    db_path = tmp_path / "test.db"

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

    return database, _conn, db_path


_VIEWER_JS   = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_HTML = Path(__file__).parents[1] / "viewer.html"


# ── W-1: get_game_moves includes fen_after ────────────────────────────────────

class TestGetGameMovesHasFenAfter:
    def test_fen_after_in_select(self, tmp_path):
        """W-1: get_game_moves SELECT includes fen_after column."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            # Insert the minimal records needed
            db.upsert_player("model-a", "Alice", "lmstudio")
            db.upsert_player("model-b", "Bob",   "lmstudio")
            gid = db.record_game("model-a", "model-b", "1-0", "Checkmate", 10, "", 1200.0, 1200.0, 1232.0, 1168.0)
            db.record_move(
                game_id=gid, move_number=1, player_model_id="model-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="good", score_cp=30,
                reasoning="Central pawn", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                thinking_content="", coherence_score=None, timed_out=False, elapsed_ms=950,
            )

            moves = db.get_game_moves(gid)
            assert len(moves) == 1
            assert "fen_after" in moves[0]
            assert moves[0]["fen_after"] is not None
            assert "PPPPPPPP" not in moves[0]["fen_after"]  # not starting pos


# ── W-2 / W-3: build_bracket seed fields ─────────────────────────────────────

def _make_spec(name, model_id):
    from arena.models import PlayerSpec
    return PlayerSpec(name=name, model_id=model_id, backend="lmstudio")


class TestBuildBracketSeeds:
    def test_round1_has_seed_fields(self):
        """W-2: round-1 matches include white_seed and black_seed."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(4)]
        b = build_bracket(specs)
        for m in b["rounds"][0]["matches"]:
            assert "white_seed" in m
            assert "black_seed" in m

    def test_seed_values_are_1based(self):
        """W-3: seed 1 is highest ELO (first spec), seeds are 1-based ints."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(4)]
        b = build_bracket(specs)
        # Collect all seed values from round 1 (non-None)
        seeds = set()
        for m in b["rounds"][0]["matches"]:
            if m["white_seed"] is not None:
                seeds.add(m["white_seed"])
            if m["black_seed"] is not None:
                seeds.add(m["black_seed"])
        assert seeds == {1, 2, 3, 4}

    def test_bye_slot_has_none_seed(self):
        """W-3b: bye slots (None spec) get None seed."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(3)]
        b = build_bracket(specs)
        bye_match = next(m for m in b["rounds"][0]["matches"] if m["bye"])
        # The None slot in the bye match has None seed
        none_seed = bye_match["white_seed"] if bye_match["white"] is None else bye_match["black_seed"]
        assert none_seed is None


# ── W-4: advance_bracket carries seed ────────────────────────────────────────

class TestAdvanceBracketSeed:
    def test_seed_propagates_to_next_round(self):
        """W-4: winner's seed propagates to the next round's match slot."""
        from game import build_bracket, advance_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(4)]
        b = build_bracket(specs)

        m0 = b["rounds"][0]["matches"][0]
        winner_id   = m0["white"]
        winner_name = m0["white_name"]
        winner_seed = m0["white_seed"]

        b2 = advance_bracket(b, 0, 0, winner_id, winner_name, game_id=1, name_map={})
        # Upper slot (match_idx=0 is even) → propagates to white slot of next match
        next_m = b2["rounds"][1]["matches"][0]
        assert next_m["white"]      == winner_id
        assert next_m["white_seed"] == winner_seed


# ── W-5 through W-9: viewer.js source checks ─────────────────────────────────

class TestViewerJsWaveA:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_elapsed_sum_tracking(self):
        """W-5: viewer.js initialises and accumulates elapsedSum / elapsedCount."""
        src = self._src()
        assert "elapsedSum" in src
        assert "elapsedCount" in src

    def test_autoplay_function_defined(self):
        """W-6: rpToggleAutoplay is defined in viewer.js."""
        src = self._src()
        assert "rpToggleAutoplay" in src
        assert "_rpAutoplayTimer" in src

    def test_rp_elapsed_badge_rendered(self):
        """W-7: replay move list builds rp-elapsed spans."""
        src = self._src()
        assert "rp-elapsed" in src

    def test_reasoning_panel_updated(self):
        """W-8: rpRender updates rpReasoning element."""
        src = self._src()
        assert "rpReasoning" in src
        assert "rp-reas-text" in src

    def test_bracket_seed_and_champion(self):
        """W-9: renderBracket emits bracket-seed and bracket-champion classes."""
        src = self._src()
        assert "bracket-seed" in src
        assert "bracket-champion" in src


# ── W-10 through W-12: viewer.html checks ────────────────────────────────────

class TestViewerHtmlWaveA:
    def _html(self):
        return _VIEWER_HTML.read_text()

    def test_latency_elements_present(self):
        """W-10: viewer.html has p-latency divs for both white and black."""
        html = self._html()
        assert "latencyWhite" in html
        assert "latencyBlack" in html

    def test_autoplay_button_present(self):
        """W-11: viewer.html has rpPlay button."""
        html = self._html()
        assert "rpPlay" in html
        assert "rpToggleAutoplay" in html

    def test_reasoning_panel_present(self):
        """W-12: viewer.html has rpReasoning element."""
        html = self._html()
        assert "rpReasoning" in html


# ── W-13: HTTP route returns fen_after ───────────────────────────────────────

@contextmanager
def _make_client(tmp_path: Path):
    import db as database
    db_path = tmp_path / "test.db"

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

    with patch.object(database, "get_conn", _conn):
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        from fastapi.testclient import TestClient
        from arena import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, database, _conn


class TestMovesApiHasFenAfter:
    def test_moves_endpoint_returns_fen_after(self, tmp_path):
        """W-13: GET /api/games/<id>/moves returns fen_after for each move."""
        with _make_client(tmp_path) as (client, database, _conn):
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            gid = database.record_game("model-a", "model-b", "1-0", "Checkmate",
                                       10, "", 1200.0, 1200.0, 1232.0, 1168.0)
            database.record_move(
                game_id=gid, move_number=1, player_model_id="model-a",
                move_uci="e2e4", move_san="e4",
                candidate_rank=1, quality="good", score_cp=30,
                reasoning="Central", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                thinking_content="", coherence_score=None, timed_out=False, elapsed_ms=800,
            )

            resp = client.get(f"/api/games/{gid}/moves")
            assert resp.status_code == 200
            moves = resp.json()
            assert len(moves) == 1
            assert "fen_after" in moves[0]
            assert moves[0]["fen_after"] is not None
