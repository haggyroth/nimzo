"""
tests/test_phase22.py — Phase 22: asyncio.to_thread() wrappers for database calls.

Covers:
  A-1  Route GET /api/leaderboard uses asyncio.to_thread (source inspection)
  A-2  Route GET /api/games uses asyncio.to_thread
  A-3  Route GET /api/games/{id} uses asyncio.to_thread
  A-4  Route GET /api/games/{id}/moves uses asyncio.to_thread
  A-5  Route GET /api/games/{id}/pgn uses asyncio.to_thread
  A-6  Route GET /api/models/{id}/profile uses asyncio.to_thread
  A-7  Route GET /api/models/{id}/quality uses asyncio.to_thread
  A-8  Route GET /api/stats/moves uses asyncio.to_thread
  A-9  Route GET /api/tournament/history uses asyncio.to_thread
  A-10 play_game record_game is wrapped with asyncio.to_thread (source inspection)
  A-11 HTTP: GET /api/leaderboard returns 200 with correct shape
  A-12 HTTP: GET /api/games returns 200 with list
  A-13 HTTP: GET /api/games/{id} returns 404 for missing game
"""
from __future__ import annotations

import inspect
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

# ── Source-level checks that asyncio.to_thread is used ───────────────────────

class TestSourceUsesAsyncToThread:
    """Verify call sites use asyncio.to_thread instead of direct blocking calls."""

    def _get_source(self, module_path: str) -> str:
        import importlib
        mod = importlib.import_module(module_path)
        return inspect.getsource(mod)

    def test_stats_leaderboard_wrapped(self):
        """A-1: stats.py api_leaderboard uses asyncio.to_thread."""
        src = self._get_source("arena.routes.stats")
        # Should be wrapped, not bare call
        assert "asyncio.to_thread(database.get_leaderboard" in src

    def test_games_recent_wrapped(self):
        """A-2: games.py api_games uses asyncio.to_thread."""
        src = self._get_source("arena.routes.games")
        assert "asyncio.to_thread(database.get_recent_games" in src

    def test_games_single_wrapped(self):
        """A-3: games.py api_game uses asyncio.to_thread."""
        src = self._get_source("arena.routes.games")
        assert "asyncio.to_thread(database.get_game," in src

    def test_games_moves_wrapped(self):
        """A-4: games.py api_game_moves uses asyncio.to_thread."""
        src = self._get_source("arena.routes.games")
        assert "asyncio.to_thread(database.get_game_moves" in src

    def test_games_pgn_wrapped(self):
        """A-5: games.py api_game_pgn uses asyncio.to_thread."""
        src = self._get_source("arena.routes.games")
        # get_game and get_game_moves both wrapped for pgn endpoint
        assert src.count("asyncio.to_thread(database.get_game") >= 2

    def test_model_api_profile_wrapped(self):
        """A-6: model_api.py api_model_profile uses asyncio.to_thread."""
        src = self._get_source("arena.routes.model_api")
        assert "asyncio.to_thread(database.get_model_profile" in src

    def test_model_api_quality_wrapped(self):
        """A-7: model_api.py api_model_quality uses asyncio.to_thread."""
        src = self._get_source("arena.routes.model_api")
        assert "asyncio.to_thread(database.get_player_quality_stats" in src

    def test_stats_moves_wrapped(self):
        """A-8: stats.py api_stats_moves uses asyncio.to_thread."""
        src = self._get_source("arena.routes.stats")
        assert "asyncio.to_thread(database.get_player_move_stats" in src

    def test_tournament_history_wrapped(self):
        """A-9: tournament.py api_tournament_history uses asyncio.to_thread."""
        src = self._get_source("arena.routes.tournament")
        assert "asyncio.to_thread(database.get_tournament_history" in src

    def test_game_py_record_game_wrapped(self):
        """A-10: game.py play_game wraps database.record_game with asyncio.to_thread."""
        import game
        src = inspect.getsource(game)
        assert "asyncio.to_thread(\n        database.record_game" in src or \
               "asyncio.to_thread(database.record_game" in src or \
               "asyncio.to_thread(\n        database.record_game" in src


# ── HTTP integration tests ────────────────────────────────────────────────────


def _make_client(tmp_path):
    """Yield a TestClient with a fresh in-memory database."""
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


class TestAsyncRoutes:
    """Verify the wrapped routes still return correct responses."""

    def test_leaderboard_returns_200(self, tmp_path):
        """A-11: GET /api/leaderboard returns 200 with a list."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/leaderboard")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_games_returns_200(self, tmp_path):
        """A-12: GET /api/games returns 200 with a list."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/games")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_game_not_found_returns_404(self, tmp_path):
        """A-13: GET /api/games/99999 returns 404 for nonexistent game."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/games/99999")
            assert resp.status_code == 404

    def test_stats_moves_returns_200(self, tmp_path):
        """A-8b: GET /api/stats/moves returns 200."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/stats/moves")
            assert resp.status_code == 200

    def test_tournament_history_returns_200(self, tmp_path):
        """A-9b: GET /api/tournament/history returns 200 with list."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/tournament/history")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
