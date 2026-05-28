"""
tests/test_phase24.py — Phase 24: Puzzle Gauntlet mode.

Covers:
  G-1  _load_puzzles parses a valid positions.toml
  G-2  _load_puzzles raises FileNotFoundError for missing file
  G-3  _load_puzzles raises ValueError for missing fen/solution_uci fields
  G-4  PuzzleGauntletConfig Pydantic model defaults
  G-5  PuzzleGauntletConfig accepts custom values
  G-6  DB: create_puzzle_gauntlet / finish_puzzle_gauntlet roundtrip
  G-7  DB: record_puzzle_result and get_puzzle_gauntlet_results
  G-8  DB: get_puzzle_gauntlets returns aggregate scores
  G-9  run_puzzle_gauntlet broadcasts correct events and records correct scores
  G-10 run_puzzle_gauntlet handles TournamentAborted gracefully
  G-11 HTTP: POST /api/puzzle/start with no players returns 422
  G-12 HTTP: POST /api/puzzle/start with missing puzzle file returns 404
  G-13 HTTP: POST /api/puzzle/start with valid config returns 200
  G-14 HTTP: GET /api/puzzle/results returns list
  G-15 HTTP: GET /api/puzzle/puzzles lists puzzles from the default file
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

_SIMPLE_TOML = """\
[[puzzle]]
fen         = "8/8/8/8/8/8/4k3/4K2R w K - 0 1"
solution_uci = "h1h8"
description  = "Rook to 8th rank"

[[puzzle]]
fen         = "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1"
solution_uci = "e1e8"
description  = "Back rank mate"
"""


def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test_puzzles.toml"
    p.write_text(content)
    return p


def _make_db_context(tmp_path: Path):
    """Return a patched get_conn context manager using a fresh SQLite DB."""
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


# ── G-1 through G-3: _load_puzzles ───────────────────────────────────────────

class TestLoadPuzzles:
    def test_parses_valid_toml(self, tmp_path):
        """G-1: valid positions.toml is parsed correctly."""
        pth = _write_toml(tmp_path, _SIMPLE_TOML)
        from puzzle_loader import load_puzzles as _load_puzzles
        puzzles = _load_puzzles(str(pth))
        assert len(puzzles) == 2
        assert puzzles[0]["solution_uci"] == "h1h8"
        assert puzzles[1]["description"] == "Back rank mate"

    def test_missing_file_raises(self, tmp_path):
        """G-2: missing file raises FileNotFoundError."""
        from puzzle_loader import load_puzzles as _load_puzzles
        with pytest.raises(FileNotFoundError):
            _load_puzzles(str(tmp_path / "nope.toml"))

    def test_missing_field_raises(self, tmp_path):
        """G-3: puzzle missing required field raises ValueError."""
        bad = "[[puzzle]]\nfen = \"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1\"\n"
        pth = _write_toml(tmp_path, bad)
        from puzzle_loader import load_puzzles as _load_puzzles
        with pytest.raises(ValueError):
            _load_puzzles(str(pth))


# ── G-4 / G-5: PuzzleGauntletConfig ─────────────────────────────────────────

class TestPuzzleGauntletConfig:
    def test_defaults(self):
        """G-4: default values are applied correctly."""
        from arena.models import PuzzleGauntletConfig
        cfg = PuzzleGauntletConfig()
        assert cfg.candidate_count == 5
        assert cfg.puzzles_file == "positions.toml"
        assert cfg.move_timeout == 30
        assert cfg.players == []

    def test_custom_values(self):
        """G-5: custom values are accepted."""
        from arena.models import PuzzleGauntletConfig, PlayerSpec
        cfg = PuzzleGauntletConfig(
            candidate_count=8,
            puzzles_file="custom.toml",
            move_timeout=60,
            players=[PlayerSpec(model_id="test-model", name="Test")],
        )
        assert cfg.candidate_count == 8
        assert cfg.move_timeout == 60
        assert len(cfg.players) == 1


# ── G-6 through G-8: Database functions ──────────────────────────────────────

class TestPuzzleDB:
    def test_create_finish_gauntlet(self, tmp_path):
        """G-6: create and finish a gauntlet roundtrip."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            gid = db.create_puzzle_gauntlet(["model-a", "model-b"], 10)
            assert isinstance(gid, int)

            db.finish_puzzle_gauntlet(gid)

            with _conn() as conn:
                row = conn.execute(
                    "SELECT status FROM puzzle_gauntlets WHERE id = ?", (gid,)
                ).fetchone()
            assert row["status"] == "finished"

    def test_record_and_retrieve_result(self, tmp_path):
        """G-7: record_puzzle_result stores and get_puzzle_gauntlet_results retrieves."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            player_id = db.upsert_player("model-a", "Alice", "lmstudio")
            gid = db.create_puzzle_gauntlet(["model-a"], 1)
            db.record_puzzle_result(
                gauntlet_id=gid,
                player_id=player_id,
                puzzle_index=0,
                puzzle_fen="8/8/8/8/8/8/4k3/4K2R w K - 0 1",
                solution_uci="h1h8",
                chosen_uci="h1h8",
                solved=True,
                candidate_rank=1,
                elapsed_ms=500,
                reasoning="Obvious rook move",
            )
            results = db.get_puzzle_gauntlet_results(gid)
            assert len(results) == 1
            assert results[0]["solved"] == 1
            assert results[0]["chosen_uci"] == "h1h8"

    def test_get_puzzle_gauntlets_aggregate(self, tmp_path):
        """G-8: get_puzzle_gauntlets returns aggregate scores per player."""
        db, _conn, db_path = _make_db_context(tmp_path)
        with patch.object(db, "get_conn", _conn):
            db._leaderboard_cache = None
            db._migrate_column_cache.clear()
            db.init_db(db_path)

            pid_a = db.upsert_player("model-a", "Alice", "lmstudio")
            pid_b = db.upsert_player("model-b", "Bob", "lmstudio")
            gid = db.create_puzzle_gauntlet(["model-a", "model-b"], 2)

            # Alice solves both puzzles
            for idx in range(2):
                db.record_puzzle_result(gid, pid_a, idx, "fen", "e2e4", "e2e4",
                                        True, 1, 100, "")
            # Bob solves 1
            db.record_puzzle_result(gid, pid_b, 0, "fen", "e2e4", "e2e4",
                                    True, 1, 200, "")
            db.record_puzzle_result(gid, pid_b, 1, "fen", "e2e4", "d2d4",
                                    False, 2, 200, "")

            db.finish_puzzle_gauntlet(gid)
            gauntlets = db.get_puzzle_gauntlets(limit=5)
            assert len(gauntlets) == 1
            scores = {s["model_id"]: s for s in gauntlets[0]["scores"]}
            assert scores["model-a"]["solved"] == 2
            assert scores["model-b"]["solved"] == 1
            assert scores["model-a"]["fraction"] == 1.0
            assert scores["model-b"]["fraction"] == 0.5


# ── G-9 / G-10: run_puzzle_gauntlet ──────────────────────────────────────────

def _fake_stockfish_for_puzzle():
    """Stockfish mock that returns two candidates for any board."""
    sf = MagicMock()
    sf.get_candidates.side_effect = lambda board, n: [
        (move, 100 - i * 10)
        for i, move in enumerate(list(board.legal_moves)[:n])
    ]
    return sf


def _fake_puzzle_player(name: str, always_choose_first: bool = True):
    """Mock ChessPlayer for puzzle testing."""
    from models.base import PlayerConfig, MoveDecision

    cfg = PlayerConfig(
        name=name,
        model_id=f"test-{name.lower()}",
        backend="lmstudio",
        base_url="http://localhost:1234/v1",
        candidate_count=5,
    )
    player = MagicMock()
    player.config = cfg
    player.elo = 1200.0

    def _choose(board, candidates, pgn):
        # Choose first candidate (index 0) if always_choose_first
        move = candidates[0][0] if candidates else next(iter(board.legal_moves))
        return MoveDecision(move_uci=move.uci(), reasoning="test", candidate_rank=1, raw_response="")

    player.choose_move.side_effect = _choose
    return player


class TestRunPuzzleGauntlet:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_broadcasts_start_and_over(self, tmp_path):
        """G-9: run_puzzle_gauntlet broadcasts start and over events, records scores."""
        import arena as _arena
        from game import run_puzzle_gauntlet

        toml_path = _write_toml(tmp_path, _SIMPLE_TOML)
        events = []

        async def fake_broadcast(msg):
            events.append(msg)

        player = _fake_puzzle_player("Alice")
        sf = _fake_stockfish_for_puzzle()

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

        with patch.object(database, "get_conn", _conn), \
             patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": False}), \
             patch.dict(_arena._mode, {"headless": True}), \
             patch.dict(_arena._state, {}):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            result = self._run(run_puzzle_gauntlet(
                players=[player],
                stockfish=sf,
                puzzles_file=str(toml_path),
                candidate_count=3,
            ))

        types = [e["type"] for e in events]
        assert "puzzle_gauntlet_start" in types
        assert "puzzle_gauntlet_over" in types
        assert types.count("puzzle_result") == 2   # 2 puzzles × 1 player

        assert result["gauntlet_id"] is not None
        assert len(result["scores"]) == 1
        assert result["scores"][0]["total"] == 2

    def test_aborted_gauntlet_status(self, tmp_path):
        """G-10: TournamentAborted marks gauntlet as aborted in DB."""
        import arena as _arena
        from game import run_puzzle_gauntlet

        toml_path = _write_toml(tmp_path, _SIMPLE_TOML)

        player = _fake_puzzle_player("Bob")
        sf = _fake_stockfish_for_puzzle()

        # Make stop requested so gauntlet aborts on first iteration
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

        gauntlet_id_holder = []

        async def fake_broadcast(msg):
            if msg.get("type") == "puzzle_gauntlet_start":
                gauntlet_id_holder.append(msg.get("gauntlet_id"))

        with patch.object(database, "get_conn", _conn), \
             patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": True}), \
             patch.dict(_arena._mode, {"headless": True}), \
             patch.dict(_arena._state, {}):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            with pytest.raises(_arena.TournamentAborted):
                asyncio.run(run_puzzle_gauntlet(
                    players=[player],
                    stockfish=sf,
                    puzzles_file=str(toml_path),
                ))

        if gauntlet_id_holder:
            with _conn() as conn:
                row = conn.execute(
                    "SELECT status FROM puzzle_gauntlets WHERE id = ?",
                    (gauntlet_id_holder[0],),
                ).fetchone()
            assert row["status"] == "aborted"


# ── G-11 through G-15: HTTP routes ───────────────────────────────────────────

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


class TestPuzzleHTTPRoutes:
    def test_start_no_players_returns_422(self, tmp_path):
        """G-11: POST /api/puzzle/start with empty players returns 422."""
        for client in _make_client(tmp_path):
            resp = client.post("/api/puzzle/start", json={
                "players": [],
                "puzzles_file": "positions.toml",
            })
            assert resp.status_code == 422

    def test_start_missing_file_returns_404(self, tmp_path):
        """G-12: POST /api/puzzle/start with missing puzzle file returns 404."""
        for client in _make_client(tmp_path):
            resp = client.post("/api/puzzle/start", json={
                "players": [{"model_id": "test", "name": "T", "backend": "lmstudio"}],
                "puzzles_file": "/nonexistent/path/puzzles.toml",
            })
            assert resp.status_code == 404

    def test_start_valid_config_returns_200(self, tmp_path):
        """G-13: POST /api/puzzle/start with valid config returns 200."""
        for client in _make_client(tmp_path):
            # The positions.toml is present in the project root (resolved from game.py dir)
            resp = client.post("/api/puzzle/start", json={
                "players": [{"model_id": "test-model", "name": "TestPlayer", "backend": "lmstudio"}],
                "puzzles_file": "positions.toml",
                "candidate_count": 3,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("ok") is True or data.get("error") is not None

    def test_results_returns_list(self, tmp_path):
        """G-14: GET /api/puzzle/results returns a list."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/puzzle/results")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_list_puzzles_returns_list(self, tmp_path):
        """G-15: GET /api/puzzle/puzzles returns puzzle list from default file."""
        for client in _make_client(tmp_path):
            resp = client.get("/api/puzzle/puzzles")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert "fen" in data[0]
            assert "solution_uci" in data[0]
