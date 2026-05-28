"""
tests/test_phase29.py — Phase 29: Wave D leaderboard & overlay polish.

Covers:
  D-1  db.get_leaderboard rows include recent_form field
  D-2  recent_form is a list of W/L/D strings in chronological order
  D-3  recent_form is empty list when player has no games
  D-4  viewer.js defines _lbSortFn and _renderLeaderboard
  D-5  viewer.js renders form-dot spans in leaderboard rows
  D-6  viewer.js leaderboard table headers are sortable (lb-sortable class)
  D-7  viewer.js onGameOver renders ov-elo-delta chip
  D-8  viewer.js loadHistory has _historyLimit and load-more button
  D-9  viewer.css has .ov-elo-delta with pos/neg/zero variants
  D-10 viewer.css has .form-dot with win/loss/draw variants
  D-11 viewer.css has .lb-sortable styles
  D-12 viewer.css has .hist-more-btn styles
  D-13 HTTP: GET /api/leaderboard rows include recent_form
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import arena  # noqa: F401 — pre-init to avoid circular import


_VIEWER_JS  = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_CSS = Path(__file__).parents[1] / "static" / "viewer.css"


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


# ── D-1 through D-3: db.get_leaderboard recent_form ──────────────────────────

class TestLeaderboardRecentForm:
    def _seed(self, database, _conn, db_path):
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            # 3 games: Alice wins 2, loses 1
            database.record_game("model-a", "model-b", "1-0", "Checkmate", 10, "",
                                 1200.0, 1200.0, 1215.0, 1185.0)
            database.record_game("model-a", "model-b", "0-1", "Checkmate", 10, "",
                                 1215.0, 1185.0, 1202.0, 1198.0)
            database.record_game("model-a", "model-b", "1-0", "Checkmate", 10, "",
                                 1202.0, 1198.0, 1218.0, 1182.0)
            database._leaderboard_cache = None  # ensure fresh
            return database.get_leaderboard()

    def test_recent_form_field_present(self, tmp_path):
        """D-1: get_leaderboard rows include recent_form field."""
        db, _conn, db_path = _make_db_context(tmp_path)
        rows = self._seed(db, _conn, db_path)
        assert len(rows) > 0
        for row in rows:
            assert "recent_form" in row

    def test_recent_form_is_wld_list(self, tmp_path):
        """D-2: recent_form entries are W, L, or D strings in chronological order."""
        db, _conn, db_path = _make_db_context(tmp_path)
        rows = self._seed(db, _conn, db_path)
        alice = next(r for r in rows if r["model_id"] == "model-a")
        form = alice["recent_form"]
        assert isinstance(form, list)
        assert all(x in ("W", "L", "D") for x in form)
        # Alice played 3 games: W, L, W (chronological)
        assert form == ["W", "L", "W"]

    def test_recent_form_empty_for_no_games(self, tmp_path):
        """D-3: recent_form is [] when a player has no games."""
        import db as database
        _, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database._leaderboard_cache = None
            rows = database.get_leaderboard()
        alice = next((r for r in rows if r["model_id"] == "model-a"), None)
        assert alice is not None
        assert alice["recent_form"] == []

    def test_recent_form_max_5(self, tmp_path):
        """D-2b: recent_form is capped at 5 entries."""
        import db as database
        _, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("model-a", "Alice", "lmstudio")
            database.upsert_player("model-b", "Bob",   "lmstudio")
            elo = 1200.0
            for _ in range(7):
                database.record_game("model-a", "model-b", "1-0", "Checkmate", 10, "",
                                     elo, elo, elo+10, elo-10)
                elo += 10
            database._leaderboard_cache = None
            rows = database.get_leaderboard()
        alice = next(r for r in rows if r["model_id"] == "model-a")
        assert len(alice["recent_form"]) <= 5


# ── D-4 through D-8: viewer.js source checks ─────────────────────────────────

class TestViewerJsWaveD:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_render_leaderboard_and_sort_fn_defined(self):
        """D-4: _renderLeaderboard and _lbSortFn are defined."""
        src = self._src()
        assert "function _renderLeaderboard" in src
        assert "function _lbSortFn" in src

    def test_form_dots_rendered(self):
        """D-5: _renderLeaderboard emits form-dot spans."""
        src = self._src()
        fn_start = src.index("function _renderLeaderboard")
        fn_body  = src[fn_start:fn_start + 3000]
        assert "form-dot" in fn_body
        assert "recent_form" in fn_body

    def test_sortable_headers(self):
        """D-6: leaderboard table headers use lb-sortable class."""
        src = self._src()
        fn_start = src.index("function _renderLeaderboard")
        fn_body  = src[fn_start:fn_start + 3000]
        assert "lb-sortable" in fn_body
        assert "_lbSortFn" in fn_body

    def test_elo_delta_chip_in_game_over(self):
        """D-7: onGameOver renders ov-elo-delta chip."""
        src = self._src()
        go_start = src.index("function onGameOver")
        go_body  = src[go_start:go_start + 2000]
        assert "ov-elo-delta" in go_body

    def test_load_more_history(self):
        """D-8: loadHistory has _historyLimit variable and load-more button."""
        src = self._src()
        assert "_historyLimit" in src
        assert "hist-more-btn" in src
        assert "load more" in src


# ── D-9 through D-12: viewer.css checks ──────────────────────────────────────

class TestViewerCssWaveD:
    def _css(self):
        return _VIEWER_CSS.read_text()

    def test_elo_delta_styles(self):
        """D-9: viewer.css has .ov-elo-delta with pos/neg/zero variants."""
        css = self._css()
        assert ".ov-elo-delta" in css
        assert ".ov-elo-delta.pos" in css
        assert ".ov-elo-delta.neg" in css
        assert ".ov-elo-delta.zero" in css

    def test_form_dot_styles(self):
        """D-10: viewer.css has .form-dot with win/loss/draw variants."""
        css = self._css()
        assert ".form-dot" in css
        assert ".form-dot.win"  in css
        assert ".form-dot.loss" in css
        assert ".form-dot.draw" in css

    def test_lb_sortable_styles(self):
        """D-11: viewer.css has .lb-sortable styles."""
        assert ".lb-sortable" in self._css()

    def test_hist_more_btn_styles(self):
        """D-12: viewer.css has .hist-more-btn styles."""
        assert ".hist-more-btn" in self._css()


# ── D-13: HTTP route test ─────────────────────────────────────────────────────

@contextmanager
def _make_http_client(tmp_path: Path):
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
        database.record_game("model-a", "model-b", "1-0", "Checkmate", 10, "",
                             1200.0, 1200.0, 1215.0, 1185.0)
        database.record_game("model-b", "model-a", "1-0", "Checkmate", 10, "",
                             1185.0, 1215.0, 1200.0, 1200.0)
        database._leaderboard_cache = None  # ensure fresh for HTTP call

        from arena import app as _app
        with TestClient(_app, raise_server_exceptions=True) as client:
            yield client


class TestHttpWaveD:
    def test_leaderboard_includes_recent_form(self, tmp_path):
        """D-13: GET /api/leaderboard rows include recent_form list."""
        with _make_http_client(tmp_path) as client:
            resp = client.get("/api/leaderboard")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) >= 1
        for row in rows:
            assert "recent_form" in row
            assert isinstance(row["recent_form"], list)
            assert all(x in ("W", "L", "D") for x in row["recent_form"])
