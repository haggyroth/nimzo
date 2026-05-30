"""
tests/test_phase27.py — Phase 27: Wave B stats & routes.

Covers:
  B-1  db.get_recent_games returns white_model_id and black_model_id
  B-2  db.get_recent_games returns eco_code and opening_name fields
  B-3  viewer.html has H2H section elements (h2hSection, h2hPlayerA, h2hPlayerB, h2hBody)
  B-4  viewer.js defines runH2H function
  B-5  viewer.js loadLeaderboard populates h2hPlayerA / h2hPlayerB dropdowns
  B-6  viewer.js loadHistory renders game-opening tag from eco_code / opening_name
  B-7  viewer.js loadHistory renders game-pgn-btn button per row
  B-8  viewer.js defines downloadGamePgn function
  B-9  HTTP: GET /api/games/<id>/pgn returns valid PGN with Content-Disposition header
  B-10 HTTP: GET /api/models/<a>/h2h/<b> returns wins/draws/losses/total
  B-11 HTTP: GET /api/games?limit=N includes eco_code and opening_name in response
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import arena  # noqa: F401 — pre-init the package to avoid circular import


# ── Helpers ────────────────────────────────────────────────────────────────────

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


# ── B-1 / B-2: get_recent_games extra fields ───────────────────────────────────

class TestGetRecentGamesExtendedFields:
    def _seed(self, db, tmp_path):
        db_path = tmp_path / "test.db"
        with patch.object(db, "get_conn", _make_db_context(tmp_path)[1]):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)
            db.upsert_player("model-a", "Alice", "lmstudio")
            db.upsert_player("model-b", "Bob",   "lmstudio")
            return db.record_game(
                "model-a", "model-b", "1-0", "Checkmate", 20, "",
                1200.0, 1200.0, 1220.0, 1180.0,
                eco_code="B20", opening_name="Sicilian Defence",
            )

    def test_model_ids_present(self, tmp_path):
        """B-1: get_recent_games rows include white_model_id and black_model_id."""
        import db as database
        _, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            database.record_game(
                "model-a", "model-b", "1-0", "Checkmate", 20, "",
                1200.0, 1200.0, 1220.0, 1180.0,
            )
            rows = database.get_recent_games(10)
        assert len(rows) == 1
        assert rows[0]["white_model_id"] == "model-a"
        assert rows[0]["black_model_id"] == "model-b"

    def test_opening_fields_present(self, tmp_path):
        """B-2: get_recent_games rows include eco_code and opening_name."""
        import db as database
        _, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            database.record_game(
                "model-a", "model-b", "1-0", "Checkmate", 20, "",
                1200.0, 1200.0, 1220.0, 1180.0,
                eco_code="B20", opening_name="Sicilian Defence",
            )
            rows = database.get_recent_games(10)
        assert rows[0]["eco_code"]    == "B20"
        assert rows[0]["opening_name"] == "Sicilian Defence"

    def test_opening_fields_null_when_not_set(self, tmp_path):
        """B-2b: eco_code and opening_name are None when not stored."""
        import db as database
        _, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            database.record_game(
                "model-a", "model-b", "1-0", "Checkmate", 20, "",
                1200.0, 1200.0, 1220.0, 1180.0,
            )
            rows = database.get_recent_games(10)
        assert rows[0]["eco_code"]    is None
        assert rows[0]["opening_name"] is None


# ── B-3: viewer.html H2H section ───────────────────────────────────────────────

class TestViewerHtmlH2H:
    def _html(self):
        return _VIEWER_HTML.read_text()

    def test_h2h_section_present(self):
        """B-3a: viewer.html has h2hSection container."""
        assert "h2hSection" in self._html()

    def test_h2h_player_selects_present(self):
        """B-3b: viewer.html has h2hPlayerA and h2hPlayerB selects."""
        html = self._html()
        assert "h2hPlayerA" in html
        assert "h2hPlayerB" in html

    def test_h2h_body_present(self):
        """B-3c: viewer.html has h2hBody result container."""
        assert "h2hBody" in self._html()

    def test_h2h_compare_button_present(self):
        """B-3d: viewer.html has a Compare button wired to runH2H()."""
        assert "runH2H" in self._html()


# ── B-4 through B-8: viewer.js source checks ──────────────────────────────────

class TestViewerJsWaveB:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_run_h2h_defined(self):
        """B-4: runH2H function is defined in viewer.js."""
        src = self._src()
        assert "async function runH2H" in src

    def test_leaderboard_populates_h2h_dropdowns(self):
        """B-5: loadLeaderboard populates h2hPlayerA / h2hPlayerB."""
        src = self._src()
        assert "h2hPlayerA" in src
        assert "h2hPlayerB" in src
        # Both selects must be updated in the same loadLeaderboard code path
        lb_section = src[src.index("async function loadLeaderboard"):
                         src.index("async function loadHistory")]
        assert "h2hPlayerA" in lb_section
        assert "h2hPlayerB" in lb_section

    def test_load_history_renders_opening_tag(self):
        """B-6: loadHistory/_renderHistoryRows emits game-opening span for eco_code."""
        src = self._src()
        # Rendering moved to _renderHistoryRows which precedes loadHistory;
        # check the whole recent-games block up to downloadGamePgn.
        history_section = src[src.index("_renderHistoryRows"):
                               src.index("async function downloadGamePgn")]
        assert "game-opening" in history_section
        assert "eco_code" in history_section

    def test_load_history_renders_pgn_button(self):
        """B-7: loadHistory/_renderHistoryRows emits game-pgn-btn button per row."""
        src = self._src()
        history_section = src[src.index("_renderHistoryRows"):
                               src.index("async function downloadGamePgn")]
        assert "game-pgn-btn" in history_section
        assert "downloadGamePgn" in history_section

    def test_download_pgn_defined(self):
        """B-8: downloadGamePgn is defined in viewer.js."""
        src = self._src()
        assert "async function downloadGamePgn" in src
        # Should trigger a browser file download
        assert "download" in src[src.index("async function downloadGamePgn"):]


# ── B-9 through B-11: HTTP route tests ────────────────────────────────────────

@contextmanager
def _make_http_client(tmp_path: Path):
    """Spin up a TestClient with a seeded in-memory DB patched into db.get_conn."""
    from fastapi.testclient import TestClient
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
        database.upsert_player("model-a", "Alice", "lmstudio")
        database.upsert_player("model-b", "Bob",   "lmstudio")
        gid = database.record_game(
            "model-a", "model-b", "1-0", "Checkmate", 4,
            "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#",
            1200.0, 1200.0, 1220.0, 1180.0,
            eco_code="C20", opening_name="King's Pawn Game",
        )
        database.record_move(
            game_id=gid, move_number=1, player_model_id="model-a",
            move_uci="e2e4", move_san="e4",
            candidate_rank=1, quality="best", score_cp=20,
            reasoning="Central control",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            thinking_content="", coherence_score=None, timed_out=False, elapsed_ms=500,
        )

        from arena import app as _app
        with TestClient(_app, raise_server_exceptions=True) as client:
            yield client, gid


class TestHttpWaveB:
    """HTTP integration tests — require a fully initialised FastAPI app."""

    def test_pgn_download_returns_pgn(self, tmp_path):
        """B-9a: GET /api/games/<id>/pgn returns 200 with PGN text."""
        with _make_http_client(tmp_path) as (client, gid):
            resp = client.get(f"/api/games/{gid}/pgn")
        assert resp.status_code == 200
        body = resp.text
        assert "[Event" in body
        assert "[White" in body
        assert "e4" in body

    def test_pgn_download_has_content_disposition(self, tmp_path):
        """B-9b: GET /api/games/<id>/pgn sets Content-Disposition attachment header."""
        with _make_http_client(tmp_path) as (client, gid):
            resp = client.get(f"/api/games/{gid}/pgn")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".pgn" in cd

    def test_h2h_endpoint_returns_record(self, tmp_path):
        """B-10: GET /api/models/<a>/h2h/<b> returns wins/draws/losses/total."""
        with _make_http_client(tmp_path) as (client, _gid):
            resp = client.get("/api/models/model-a/h2h/model-b")
        assert resp.status_code == 200
        data = resp.json()
        assert "wins"   in data
        assert "draws"  in data
        assert "losses" in data
        assert "total"  in data
        assert data["wins"]  == 1
        assert data["total"] == 1

    def test_games_list_includes_opening_fields(self, tmp_path):
        """B-11: GET /api/games?limit=N rows include eco_code and opening_name."""
        with _make_http_client(tmp_path) as (client, _gid):
            resp = client.get("/api/games?limit=5")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) >= 1
        row = rows[0]
        assert "eco_code"     in row
        assert "opening_name" in row
        assert row["eco_code"]     == "C20"
        assert row["opening_name"] == "King's Pawn Game"
