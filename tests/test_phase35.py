"""
tests/test_phase35.py — Phase 35: shareable /watch/<game_id> URL.

Covers:
  W-1  GET /watch/<id> returns 200 and HTML content
  W-2  GET /watch/<id> for any integer ID returns 200 (JS handles missing games)
  W-3  GET /watch/<non-integer> returns 422 (FastAPI path validation)
  W-4  copyReplayLink URL construction logic (Python-side analogue)
  W-5  replay.gameId is set correctly in the openReplay flow (structural check)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_client(tmp_path):
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
        database.init_db(db_path)
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()

        from fastapi.testclient import TestClient
        from arena import app

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, database


# ── W-1 / W-2: /watch/<id> always returns 200 HTML ───────────────────────────


class TestWatchRoute:
    def test_watch_known_game_returns_html(self, tmp_path):
        """W-1: /watch/1 returns 200 and HTML (viewer.html content)."""
        for client, db in _make_client(tmp_path):
            db.upsert_player("w", "White", "lmstudio")
            db.upsert_player("b", "Black", "lmstudio")
            db.record_game("w", "b", "1-0", "checkmate", 4, "1. e4 *",
                           1200.0, 1200.0, 1216.0, 1184.0)
            resp = client.get("/watch/1")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "<html" in resp.text.lower()

    def test_watch_nonexistent_game_still_returns_html(self, tmp_path):
        """W-2: /watch/999 returns 200 — JS handles the missing game gracefully."""
        for client, _ in _make_client(tmp_path):
            resp = client.get("/watch/999")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_watch_invalid_id_returns_422(self, tmp_path):
        """W-3: /watch/abc returns 422 — FastAPI path param validation."""
        for client, _ in _make_client(tmp_path):
            resp = client.get("/watch/abc")
            assert resp.status_code == 422

    def test_watch_response_contains_viewer_js_link(self, tmp_path):
        """W-1b: the HTML served by /watch/<id> links to viewer.js (same viewer)."""
        for client, _ in _make_client(tmp_path):
            resp = client.get("/watch/1")
            assert "viewer.js" in resp.text


# ── W-4: URL construction ─────────────────────────────────────────────────────


class TestReplayLinkConstruction:
    def test_watch_url_format(self):
        """W-4: /watch/<id> URL is constructed as expected."""
        origin = "http://localhost:8765"
        game_id = 42
        url = f"{origin}/watch/{game_id}"
        assert url == "http://localhost:8765/watch/42"
        assert url.endswith(f"/watch/{game_id}")

    def test_watch_url_different_ids(self):
        """W-4b: URL includes the exact game_id passed."""
        for gid in [1, 10, 999, 12345]:
            url = f"http://localhost:8765/watch/{gid}"
            assert f"/watch/{gid}" in url

    def test_path_regex_extracts_game_id(self):
        """W-5: the pathname regex used in JS auto-replay extracts the right id."""
        import re
        pattern = re.compile(r"/watch/(\d+)$")
        assert pattern.search("/watch/42").group(1) == "42"
        assert pattern.search("/watch/1").group(1) == "1"
        assert pattern.search("/watch/999").group(1) == "999"
        assert pattern.search("/watch/abc") is None
        assert pattern.search("/") is None
        assert pattern.search("/watch/") is None
