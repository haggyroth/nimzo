"""
Tests for M5 — optional X-API-Key authentication middleware.

A-1  GET requests are always permitted, regardless of key config.
A-2  POST requests pass when no key is configured (loopback mode).
A-3  POST requests return 401 when a key is configured and the header is absent.
A-4  POST requests return 401 when a key is configured and the header is wrong.
A-5  POST requests pass when a key is configured and the header matches exactly.
A-6  401 response body mentions "Unauthorized" or "X-API-Key".
A-7  WebSocket upgrade (method=GET) is not blocked by the middleware.
A-8  HEAD / OPTIONS requests are always permitted.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patched_db(tmp_path):
    import db as database

    db_path = tmp_path / "m5_test.db"

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
        yield database


@pytest.fixture()
def client_no_auth(_patched_db):
    """TestClient with no API key configured (loopback / default mode)."""
    import arena.state as _st
    from fastapi.testclient import TestClient
    from arena import app

    original_key = _st._api_key
    _st._api_key = None
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        _st._api_key = original_key


@pytest.fixture()
def client_with_auth(_patched_db):
    """TestClient with a fixed API key set (LAN / non-loopback mode)."""
    import arena.state as _st
    from fastapi.testclient import TestClient
    from arena import app

    original_key = _st._api_key
    _st._api_key = "test-secret-key-1234"
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        _st._api_key = original_key


_GOOD_KEY = "test-secret-key-1234"


# ── A-1: GET always passes ────────────────────────────────────────────────────


class TestGetAlwaysPasses:
    """A-1 — GET requests pass regardless of key configuration."""

    def test_get_leaderboard_no_key(self, client_no_auth):
        assert client_no_auth.get("/api/leaderboard").status_code == 200

    def test_get_leaderboard_with_auth_configured_no_header(self, client_with_auth):
        """Even with auth enabled, GET should not require a key."""
        assert client_with_auth.get("/api/leaderboard").status_code == 200

    def test_get_leaderboard_with_auth_configured_wrong_header(self, client_with_auth):
        resp = client_with_auth.get("/api/leaderboard", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 200


# ── A-2: POST passes when no key configured ───────────────────────────────────


class TestPostNoKeyConfigured:
    """A-2 — POST requests pass freely when _api_key is None."""

    def test_tournament_stop_no_auth(self, client_no_auth):
        """POST /api/tournament/stop should not require a key in loopback mode."""
        resp = client_no_auth.post("/api/tournament/stop")
        # Either 200 or 409 (nothing running) — not 401
        assert resp.status_code != 401

    def test_tournament_pause_no_auth(self, client_no_auth):
        resp = client_no_auth.post("/api/tournament/pause")
        assert resp.status_code != 401


# ── A-3: POST returns 401 when key set and header absent ─────────────────────


class TestPostMissingKey:
    """A-3 — 401 when key is configured and X-API-Key header is not sent."""

    def test_tournament_stop_missing_key(self, client_with_auth):
        assert client_with_auth.post("/api/tournament/stop").status_code == 401

    def test_tournament_pause_missing_key(self, client_with_auth):
        assert client_with_auth.post("/api/tournament/pause").status_code == 401

    def test_tournament_resume_missing_key(self, client_with_auth):
        assert client_with_auth.post("/api/tournament/resume").status_code == 401

    def test_tournament_start_missing_key(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/tournament/start",
            json={"white_model": "a", "black_model": "b"},
        )
        assert resp.status_code == 401


# ── A-4: POST returns 401 for wrong key ──────────────────────────────────────


class TestPostWrongKey:
    """A-4 — 401 when the supplied key does not match."""

    def test_wrong_key_rejected(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/tournament/stop",
            headers={"X-API-Key": "definitely-wrong"},
        )
        assert resp.status_code == 401

    def test_empty_key_rejected(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/tournament/stop",
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401


# ── A-5: POST passes with correct key ────────────────────────────────────────


class TestPostCorrectKey:
    """A-5 — Valid key is accepted and the request proceeds."""

    def test_correct_key_passes(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/tournament/stop",
            headers={"X-API-Key": _GOOD_KEY},
        )
        # Either 200 or 409 (nothing running) — not 401
        assert resp.status_code != 401

    def test_correct_key_on_pause(self, client_with_auth):
        resp = client_with_auth.post(
            "/api/tournament/pause",
            headers={"X-API-Key": _GOOD_KEY},
        )
        assert resp.status_code != 401


# ── A-6: 401 body is informative ─────────────────────────────────────────────


class TestUnauthorizedBody:
    """A-6 — The 401 response body should mention what's wrong."""

    def test_401_detail_field_present(self, client_with_auth):
        resp = client_with_auth.post("/api/tournament/stop")
        assert resp.status_code == 401
        body = resp.json()
        assert "detail" in body

    def test_401_detail_mentions_key(self, client_with_auth):
        resp = client_with_auth.post("/api/tournament/stop")
        detail = resp.json().get("detail", "").lower()
        assert "unauthorized" in detail or "x-api-key" in detail or "api" in detail


# ── A-7: WebSocket upgrade is not blocked ─────────────────────────────────────


class TestWebSocketNotBlocked:
    """A-7 — WS upgrade arrives as GET; must not be blocked by auth middleware."""

    def test_ws_connect_allowed_no_auth(self, client_no_auth):
        with client_no_auth.websocket_connect("/ws") as _ws:
            # If we get here the upgrade was not rejected by auth middleware.
            # Close immediately.
            pass  # TestClient raises on error, so success = no exception

    def test_ws_connect_allowed_with_auth_configured(self, client_with_auth):
        """WS should still connect even when API key auth is enabled."""
        with client_with_auth.websocket_connect("/ws") as _ws:
            pass


# ── A-8: HEAD / OPTIONS are not blocked ──────────────────────────────────────


class TestSafeMethodsNotBlocked:
    """A-8 — HEAD and OPTIONS bypass the auth check."""

    def test_head_leaderboard(self, client_with_auth):
        resp = client_with_auth.head("/api/leaderboard")
        assert resp.status_code != 401

    def test_options_not_blocked(self, client_with_auth):
        resp = client_with_auth.options("/api/leaderboard")
        # 405 Method Not Allowed is fine; 401 is not
        assert resp.status_code != 401
