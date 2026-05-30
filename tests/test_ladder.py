"""
test_ladder.py — Tests for ELO auto-scheduler (ladder) feature.

Covers:
  - LadderConfig Pydantic model validation
  - /api/ladder/start endpoint: success, conflict, too-few-players
  - /api/ladder/status endpoint
  - run_ladder pair selection logic (pair ordering, color alternation)
  - run_ladder stops when games_per_pair reached
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db as database


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "ladder_test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    yield


@pytest.fixture()
def client(tmp_path):
    """FastAPI TestClient wired to a fresh temp DB."""
    db_path = tmp_path / "ladder_api.db"

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
        from fastapi.testclient import TestClient
        from arena import app
        yield TestClient(app)


# ── LadderConfig model validation ─────────────────────────────────────────────


class TestLadderConfig:
    def test_defaults(self):
        from arena.models import LadderConfig
        cfg = LadderConfig(players=[])
        assert cfg.games_per_pair == 0
        assert cfg.move_timeout == 0
        assert cfg.max_moves == 0
        assert cfg.adaptive_difficulty is False

    def test_games_per_pair_zero_means_infinite(self):
        from arena.models import LadderConfig
        cfg = LadderConfig(players=[], games_per_pair=0)
        assert cfg.games_per_pair == 0

    def test_games_per_pair_positive(self):
        from arena.models import LadderConfig
        cfg = LadderConfig(players=[], games_per_pair=5)
        assert cfg.games_per_pair == 5

    def test_invalid_negative_games_per_pair(self):
        from arena.models import LadderConfig
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            LadderConfig(players=[], games_per_pair=-1)

    def test_player_spec_in_ladder(self):
        from arena.models import LadderConfig, PlayerSpec
        p = PlayerSpec(backend="lmstudio", name="Model A", model_id="model-a")
        cfg = LadderConfig(players=[p])
        assert len(cfg.players) == 1
        assert cfg.players[0].model_id == "model-a"


# ── /api/ladder/start endpoint ────────────────────────────────────────────────


class TestLadderStartEndpoint:
    def test_too_few_players_returns_400(self, client):
        payload = {
            "players": [
                {"backend": "lmstudio", "name": "Solo", "model_id": "model-a",
                 "url": "http://localhost:1234/v1"},
            ],
            "games_per_pair": 0,
        }
        resp = client.post("/api/ladder/start", json=payload)
        assert resp.status_code == 400

    def test_start_with_two_players_returns_ok(self, client):
        payload = {
            "players": [
                {"backend": "lmstudio", "name": "A", "model_id": "model-a",
                 "url": "http://localhost:1234/v1"},
                {"backend": "lmstudio", "name": "B", "model_id": "model-b",
                 "url": "http://localhost:1234/v1"},
            ],
            "games_per_pair": 2,
        }
        # Patch run_ladder so it doesn't actually run
        with patch("arena.routes.ladder.run_ladder", new_callable=AsyncMock) as mock_run, \
             patch("arena.routes.ladder.build_player") as mock_build:
            mock_player = MagicMock()
            mock_player.elo = 1500.0
            mock_player.config.name = "Model"
            mock_player.config.model_id = "model-a"
            mock_build.return_value = mock_player
            mock_run.return_value = None

            resp = client.post("/api/ladder/start", json=payload)
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

    def test_start_while_running_returns_error(self, client):
        """If a tournament task is already running, /start returns error."""
        import asyncio
        from arena import state as _st

        # Simulate a running task
        loop = asyncio.new_event_loop()
        try:
            never_done = loop.create_task(asyncio.sleep(9999))
            _st._tournament_task = never_done

            payload = {
                "players": [
                    {"backend": "lmstudio", "name": "A", "model_id": "model-a",
                     "url": "http://localhost:1234/v1"},
                    {"backend": "lmstudio", "name": "B", "model_id": "model-b",
                     "url": "http://localhost:1234/v1"},
                ],
            }
            resp = client.post("/api/ladder/start", json=payload)
            assert resp.json().get("error")
        finally:
            never_done.cancel()
            loop.close()
            _st._tournament_task = None


# ── /api/ladder/status endpoint ───────────────────────────────────────────────


class TestLadderStatusEndpoint:
    def test_status_returns_state_fields(self, client):
        resp = client.get("/api/ladder/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "game_number" in data
        assert "format" in data


# ── run_ladder pair selection logic ──────────────────────────────────────────


class TestRunLadderPairSelection:
    """Tests for the pair-picking and color-alternation logic in run_ladder."""

    def _make_player(self, name, model_id, elo=1500.0):
        p = MagicMock()
        p.config.name = name
        p.config.model_id = model_id
        p.elo = elo
        return p

    def test_games_per_pair_zero_exits_immediately_when_stopped(self):
        """With _stop requested before first iteration, run_ladder exits cleanly."""
        from game import run_ladder
        import arena.state as _st

        players = [self._make_player("A", "a"), self._make_player("B", "b")]

        _st._stop["requested"] = True
        _st._pause_event.set()

        async def _run():
            await run_ladder(players=players, games_per_pair=0)

        with patch("game.StockfishEngine") as mock_sf:
            mock_sf.return_value.__enter__ = lambda s: MagicMock()
            mock_sf.return_value.__exit__ = MagicMock(return_value=False)
            asyncio.run(_run())

        _st._stop["requested"] = False

    def test_games_per_pair_stops_after_limit(self):
        """games_per_pair=1 with 2 players → exactly 1 game played."""
        from game import run_ladder
        import arena.state as _st

        games_played = []

        async def _fake_play(white, black, stockfish, game_num, tutor, judge,
                             adaptive_difficulty=False, max_moves=500, opening_pgn=""):
            games_played.append((white.config.name, black.config.name))
            return {"result": "1-0", "moves": 20}

        players = [self._make_player("A", "a"), self._make_player("B", "b")]

        _st._stop["requested"] = False
        _st._pause_event.set()

        with patch("game.play_game", side_effect=_fake_play), \
             patch("game.StockfishEngine") as mock_sf:
            mock_sf.return_value.__enter__ = lambda s: MagicMock()
            mock_sf.return_value.__exit__ = MagicMock(return_value=False)
            asyncio.run(run_ladder(players=players, games_per_pair=1))

        assert len(games_played) == 1

    def test_three_players_games_per_pair_one(self):
        """3 players, games_per_pair=1 → exactly 3 games (one per pair)."""
        from game import run_ladder
        import arena.state as _st

        games_played = []

        async def _fake_play(white, black, stockfish, game_num, tutor, judge,
                             adaptive_difficulty=False, max_moves=500, opening_pgn=""):
            games_played.append((white.config.name, black.config.name))
            return {"result": "1-0", "moves": 20}

        players = [
            self._make_player("A", "a"),
            self._make_player("B", "b"),
            self._make_player("C", "c"),
        ]

        _st._stop["requested"] = False
        _st._pause_event.set()

        with patch("game.play_game", side_effect=_fake_play), \
             patch("game.StockfishEngine") as mock_sf:
            mock_sf.return_value.__enter__ = lambda s: MagicMock()
            mock_sf.return_value.__exit__ = MagicMock(return_value=False)
            asyncio.run(run_ladder(players=players, games_per_pair=1))

        assert len(games_played) == 3
        # Every pair should be covered
        pairs_played = {frozenset(g) for g in games_played}
        assert pairs_played == {frozenset({"A", "B"}), frozenset({"A", "C"}), frozenset({"B", "C"})}

    def test_color_alternates_for_repeated_pair(self):
        """For 2 players and games_per_pair=2, colors swap on second game."""
        from game import run_ladder
        import arena.state as _st

        colors = []  # (white_name, black_name)

        async def _fake_play(white, black, stockfish, game_num, tutor, judge,
                             adaptive_difficulty=False, max_moves=500, opening_pgn=""):
            colors.append((white.config.name, black.config.name))
            return {"result": "1-0", "moves": 20}

        players = [self._make_player("A", "a"), self._make_player("B", "b")]

        _st._stop["requested"] = False
        _st._pause_event.set()

        with patch("game.play_game", side_effect=_fake_play), \
             patch("game.StockfishEngine") as mock_sf:
            mock_sf.return_value.__enter__ = lambda s: MagicMock()
            mock_sf.return_value.__exit__ = MagicMock(return_value=False)
            asyncio.run(run_ladder(players=players, games_per_pair=2))

        assert len(colors) == 2
        # Game 1: A=white, B=black; Game 2: B=white, A=black
        assert colors[0] == ("A", "B")
        assert colors[1] == ("B", "A")
