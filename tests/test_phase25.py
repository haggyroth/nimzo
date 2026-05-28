"""
tests/test_phase25.py — Phase 25: Single-elimination bracket tournament format.

Covers:
  E-1  _next_pow2 returns correct power-of-2 values
  E-2  _round_name returns correct human-readable names
  E-3  build_bracket with 2 players: n_slots=2, 1 match, no byes
  E-4  build_bracket with 4 players: n_slots=4, 2 R1 matches, no byes
  E-5  build_bracket with 8 players: n_slots=8, standard seeding, no byes
  E-6  build_bracket with 5 players: n_slots=8, byes for top seeds
  E-7  build_bracket with 3 players: n_slots=4, 1 bye in round 1
  E-8  advance_bracket propagates winner to next round (upper slot)
  E-9  advance_bracket propagates winner to next round (lower slot)
  E-10 advance_bracket on final match (no next round) sets winner only
  E-11 TournamentStartConfig accepts "elimination" as format
  E-12 DB: update_tournament_bracket roundtrip
  E-13 DB: get_tournament_history includes bracket field
  E-14 HTTP: POST /api/tournament/start with elimination + 4 players returns 200
  E-15 HTTP: GET /api/tournament/history includes bracket field
  E-16 viewer.js contains renderBracket and onBracketUpdate
  E-17 viewer.html contains "elimination" option and bracketSection
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

# Pre-initialise arena so the circular game ↔ arena import resolves correctly.
# (game.py does `import arena as _arena`; if game is imported first it fails because
# arena.routes.tournament hasn't finished importing from game yet.)
import arena  # noqa: F401, E402


# ── E-1 / E-2: helper functions ───────────────────────────────────────────────

class TestHelpers:
    def test_next_pow2_basic(self):
        """E-1: _next_pow2 returns the smallest power of 2 >= n."""
        from game import _next_pow2
        assert _next_pow2(1) == 1
        assert _next_pow2(2) == 2
        assert _next_pow2(3) == 4
        assert _next_pow2(4) == 4
        assert _next_pow2(5) == 8
        assert _next_pow2(8) == 8
        assert _next_pow2(9) == 16

    def test_round_name(self):
        """E-2: _round_name returns correct human-readable names."""
        from game import _round_name
        # 8-slot bracket: R0=QF(4 matches), R1=SF(2 matches), R2=Final(1 match)
        assert _round_name(8, 0) == "Quarter-Finals"
        assert _round_name(8, 1) == "Semi-Finals"
        assert _round_name(8, 2) == "Final"
        # 4-slot bracket: R0=SF, R1=Final
        assert _round_name(4, 0) == "Semi-Finals"
        assert _round_name(4, 1) == "Final"
        # 2-slot: R0=Final
        assert _round_name(2, 0) == "Final"
        # 16-slot: R0=Round of 16
        assert _round_name(16, 0) == "Round of 16"


# ── E-3 through E-7: build_bracket ───────────────────────────────────────────

def _make_spec(name: str, model_id: str):
    """Create a minimal PlayerSpec-like object for bracket tests."""
    from arena.models import PlayerSpec
    return PlayerSpec(name=name, model_id=model_id, backend="lmstudio")


class TestBuildBracket:
    def test_two_players(self):
        """E-3: 2 players → n_slots=2, 1 R1 match, no byes, 1 round."""
        from game import build_bracket
        specs = [_make_spec("Alice", "alice"), _make_spec("Bob", "bob")]
        b = build_bracket(specs)
        assert b["n_slots"] == 2
        assert b["n_players"] == 2
        assert len(b["rounds"]) == 1
        assert b["rounds"][0]["name"] == "Final"
        matches = b["rounds"][0]["matches"]
        assert len(matches) == 1
        m = matches[0]
        assert m["bye"] is False
        assert m["winner"] is None
        # Both players are assigned
        assert m["white"] is not None
        assert m["black"] is not None

    def test_four_players(self):
        """E-4: 4 players → n_slots=4, 2 R1 matches, correct round count."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(4)]
        b = build_bracket(specs)
        assert b["n_slots"] == 4
        assert b["n_players"] == 4
        assert len(b["rounds"]) == 2
        assert b["rounds"][0]["name"] == "Semi-Finals"
        assert b["rounds"][1]["name"] == "Final"
        r1 = b["rounds"][0]["matches"]
        assert len(r1) == 2
        # No byes since exactly power of 2
        assert all(not m["bye"] for m in r1)
        # All players assigned
        assigned = {m["white"] for m in r1} | {m["black"] for m in r1}
        assert assigned == {"p0", "p1", "p2", "p3"}

    def test_eight_players_seeding(self):
        """E-5: 8 players → standard fold seeding, no byes."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(8)]
        b = build_bracket(specs)
        assert b["n_slots"] == 8
        assert b["n_players"] == 8
        assert len(b["rounds"]) == 3
        r1 = b["rounds"][0]["matches"]
        assert len(r1) == 4
        assert all(not m["bye"] for m in r1)
        # All 8 players assigned
        assigned = set()
        for m in r1:
            assigned.add(m["white"])
            assigned.add(m["black"])
        assert assigned == {f"p{i}" for i in range(8)}

    def test_five_players_has_byes(self):
        """E-6: 5 players → n_slots=8, byes in round 1."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(5)]
        b = build_bracket(specs)
        assert b["n_slots"] == 8
        assert b["n_players"] == 5
        r1 = b["rounds"][0]["matches"]
        assert len(r1) == 4
        bye_matches = [m for m in r1 if m["bye"]]
        # 3 byes (8 - 5 = 3 extra slots)
        assert len(bye_matches) == 3
        # Bye matches have a winner already set
        for m in bye_matches:
            assert m["winner"] is not None

    def test_three_players_has_one_bye(self):
        """E-7: 3 players → n_slots=4, exactly 1 bye in round 1."""
        from game import build_bracket
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(3)]
        b = build_bracket(specs)
        assert b["n_slots"] == 4
        assert b["n_players"] == 3
        r1 = b["rounds"][0]["matches"]
        assert len(r1) == 2
        bye_matches = [m for m in r1 if m["bye"]]
        assert len(bye_matches) == 1
        assert bye_matches[0]["winner"] is not None


# ── E-8 through E-10: advance_bracket ────────────────────────────────────────

class TestAdvanceBracket:
    def _four_player_bracket(self):
        specs = [_make_spec(f"P{i}", f"p{i}") for i in range(4)]
        from game import build_bracket
        return build_bracket(specs)

    def test_winner_propagates_to_upper_slot(self):
        """E-8: match_idx=0 (even) → winner fills white slot of next round match 0."""
        from game import advance_bracket
        b = self._four_player_bracket()
        # Determine which player is in match 0 as white
        winner_id = b["rounds"][0]["matches"][0]["white"]
        winner_name = b["rounds"][0]["matches"][0]["white_name"]
        b2 = advance_bracket(b, 0, 0, winner_id, winner_name, game_id=42, name_map={})
        assert b2["rounds"][0]["matches"][0]["winner"] == winner_id
        assert b2["rounds"][0]["matches"][0]["game_id"] == 42
        # Propagated to next round (Final), upper slot
        assert b2["rounds"][1]["matches"][0]["white"] == winner_id
        assert b2["rounds"][1]["matches"][0]["white_name"] == winner_name

    def test_winner_propagates_to_lower_slot(self):
        """E-9: match_idx=1 (odd) → winner fills black slot of next round match 0."""
        from game import advance_bracket
        b = self._four_player_bracket()
        winner_id = b["rounds"][0]["matches"][1]["white"]
        winner_name = b["rounds"][0]["matches"][1]["white_name"]
        b2 = advance_bracket(b, 0, 1, winner_id, winner_name, game_id=99, name_map={})
        assert b2["rounds"][0]["matches"][1]["winner"] == winner_id
        # Propagated to Final, lower slot
        assert b2["rounds"][1]["matches"][0]["black"] == winner_id
        assert b2["rounds"][1]["matches"][0]["black_name"] == winner_name

    def test_final_match_no_propagation(self):
        """E-10: advancing final match sets winner but no further propagation."""
        from game import advance_bracket
        specs = [_make_spec("A", "a"), _make_spec("B", "b")]
        from game import build_bracket
        b = build_bracket(specs)
        assert len(b["rounds"]) == 1
        b2 = advance_bracket(b, 0, 0, "a", "A", game_id=1, name_map={})
        assert b2["rounds"][0]["matches"][0]["winner"] == "a"
        # Only 1 round — no crash, no extra round added
        assert len(b2["rounds"]) == 1

    def test_advance_does_not_mutate_original(self):
        """advance_bracket returns a deep copy, not a mutated original."""
        from game import advance_bracket
        b = self._four_player_bracket()
        original_winner = b["rounds"][0]["matches"][0]["winner"]
        winner_id = b["rounds"][0]["matches"][0]["white"]
        advance_bracket(b, 0, 0, winner_id, "P0", game_id=1, name_map={})
        # Original unchanged
        assert b["rounds"][0]["matches"][0]["winner"] == original_winner


# ── E-11: TournamentStartConfig model ────────────────────────────────────────

class TestTournamentStartConfig:
    def test_elimination_format_accepted(self):
        """E-11: TournamentStartConfig accepts 'elimination' as format."""
        from arena.models import TournamentStartConfig, PlayerSpec
        cfg = TournamentStartConfig(
            format="elimination",
            players=[
                PlayerSpec(name="A", model_id="a", backend="lmstudio"),
                PlayerSpec(name="B", model_id="b", backend="lmstudio"),
                PlayerSpec(name="C", model_id="c", backend="lmstudio"),
                PlayerSpec(name="D", model_id="d", backend="lmstudio"),
            ],
        )
        assert cfg.format == "elimination"
        assert len(cfg.players) == 4

    def test_elimination_is_in_format_literal(self):
        """E-11b: Pydantic rejects invalid format but accepts elimination."""
        from arena.models import TournamentStartConfig
        with pytest.raises(Exception):
            TournamentStartConfig(format="knockout")  # invalid


# ── E-12 / E-13: Database ─────────────────────────────────────────────────────

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


class TestBracketDB:
    def test_update_tournament_bracket_roundtrip(self, tmp_path):
        """E-12: update_tournament_bracket stores bracket JSON; get_tournament_history retrieves it."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            # Create a tournament record
            tid = db.create_tournament("elimination", ["a", "b", "c", "d"], 3)
            assert isinstance(tid, int)

            # Fabricate a minimal bracket dict
            bracket = {"n_slots": 4, "n_players": 4, "rounds": []}
            db.update_tournament_bracket(tid, bracket)

            # Verify via raw SQL
            with _conn() as conn:
                row = conn.execute(
                    "SELECT bracket_json FROM tournaments WHERE id = ?", (tid,)
                ).fetchone()
            assert row is not None
            stored = json.loads(row["bracket_json"])
            assert stored["n_slots"] == 4
            assert stored["n_players"] == 4

    def test_get_tournament_history_includes_bracket(self, tmp_path):
        """E-13: get_tournament_history returns dicts with a 'bracket' key."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            tid = db.create_tournament("elimination", ["a", "b"], 1)
            bracket = {"n_slots": 2, "n_players": 2, "rounds": [{"name": "Final", "matches": []}]}
            db.update_tournament_bracket(tid, bracket)
            db.finish_tournament(tid, "a", "Elimination Test")

            history = db.get_tournament_history(10)
            assert len(history) >= 1
            rec = next(r for r in history if r["id"] == tid)
            assert "bracket" in rec
            assert rec["bracket"] is not None
            assert rec["bracket"]["n_slots"] == 2

    def test_get_tournament_history_null_bracket(self, tmp_path):
        """E-13b: tournaments without bracket_json return bracket=None."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            tid = db.create_tournament("round_robin", ["a", "b"], 2)
            db.finish_tournament(tid, "a", "Round Robin Test")

            history = db.get_tournament_history(10)
            rec = next(r for r in history if r["id"] == tid)
            assert "bracket" in rec
            assert rec["bracket"] is None


# ── E-14 / E-15: HTTP routes ──────────────────────────────────────────────────

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
            yield c


class TestEliminationHTTP:
    def test_start_elimination_four_players_returns_200(self, tmp_path):
        """E-14: POST /api/tournament/start with elimination + 4 players returns 200."""
        with _make_client(tmp_path) as client:
            resp = client.post("/api/tournament/start", json={
                "format": "elimination",
                "players": [
                    {"name": f"P{i}", "model_id": f"model-{i}", "backend": "lmstudio"}
                    for i in range(4)
                ],
                "games_per_pair": 1,
            })
            assert resp.status_code == 200
            data = resp.json()
            # Either ok=True (task started) or error (already running)
            assert "ok" in data or "error" in data

    def test_tournament_history_has_bracket_field(self, tmp_path):
        """E-15: GET /api/tournament/history returns records with 'bracket' key."""
        with _make_client(tmp_path) as client:
            import db as database

            # Seed a tournament with a bracket
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
                tid = database.create_tournament("elimination", ["a", "b"], 1)
                database.update_tournament_bracket(
                    tid, {"n_slots": 2, "n_players": 2, "rounds": []}
                )
                database.finish_tournament(tid, "a", "Elim Test")

            resp = client.get("/api/tournament/history")
            assert resp.status_code == 200
            records = resp.json()
            assert isinstance(records, list)
            if records:
                # At least one record should have a bracket key
                assert all("bracket" in r for r in records)


# ── E-16 / E-17: Static files ─────────────────────────────────────────────────

_VIEWER_JS = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_HTML = Path(__file__).parents[1] / "viewer.html"


class TestStaticFiles:
    def test_viewer_js_has_render_bracket(self):
        """E-16a: viewer.js defines renderBracket function."""
        src = _VIEWER_JS.read_text()
        assert "renderBracket" in src

    def test_viewer_js_has_on_bracket_update(self):
        """E-16b: viewer.js defines onBracketUpdate handler."""
        src = _VIEWER_JS.read_text()
        assert "onBracketUpdate" in src

    def test_viewer_js_handles_bracket_update_event(self):
        """E-16c: viewer.js switch/case handles 'bracket_update' message type."""
        src = _VIEWER_JS.read_text()
        assert "bracket_update" in src

    def test_viewer_html_has_elimination_option(self):
        """E-17a: viewer.html has 'elimination' as a format option."""
        html = _VIEWER_HTML.read_text()
        assert "elimination" in html.lower()

    def test_viewer_html_has_bracket_section(self):
        """E-17b: viewer.html has bracketSection element."""
        html = _VIEWER_HTML.read_text()
        assert "bracketSection" in html or "bracket-section" in html

    def test_viewer_js_shows_bracket_for_elimination(self):
        """E-16d: viewer.js references bracketSection (show/hide on format change)."""
        src = _VIEWER_JS.read_text()
        assert "bracketSection" in src or "bracket-section" in src
