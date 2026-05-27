"""
tests/test_phase36.py — Phase 36: opening repertoire stats, coherence trend,
and ROADMAP-ticking of blind mode (already implemented).

Covers:
  O-1  eco_code / opening_name columns exist after migration
  O-2  record_game() stores eco_code and opening_name
  O-3  get_openings_for_model() returns correct W/D/L counts
  O-4  get_openings_for_model() handles model with no games
  O-5  get_openings_for_model() only includes games with eco_code set
  O-6  get_openings_for_model() orders by games descending

  C-1  get_coherence_history() returns per-game avg correctly
  C-2  get_coherence_history() excludes games with no scored moves
  C-3  get_coherence_history() returns [] for unknown model
  C-4  get_coherence_history() game_number increments sequentially

  R-1  GET /api/models/{id}/openings returns list
  R-2  GET /api/models/{id}/coherence-history returns list
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _fresh(tmp_path):
    """Yield (db_module, game_id_factory) on a fresh temp DB."""
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
        database.upsert_player("w", "White", "lmstudio")
        database.upsert_player("b", "Black", "lmstudio")
        yield database


def _game(db, result="1-0", eco=None, opening=None):
    return db.record_game(
        "w", "b", result, "checkmate", 4, "1. e4 *",
        1200.0, 1200.0, 1216.0, 1184.0,
        eco_code=eco, opening_name=opening,
    )


# ── O-1 / O-2 / O-3: eco_code stored and retrieved ───────────────────────────


class TestOpeningColumns:
    def test_columns_exist_after_migration(self, tmp_path):
        """O-1: eco_code and opening_name columns are present in games table."""
        for db in _fresh(tmp_path):
            with db.get_conn() as conn:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
            assert "eco_code" in cols
            assert "opening_name" in cols

    def test_record_game_stores_eco(self, tmp_path):
        """O-2: record_game() stores eco_code and opening_name."""
        for db in _fresh(tmp_path):
            gid = _game(db, eco="B20", opening="Sicilian Defence")
            with db.get_conn() as conn:
                row = conn.execute("SELECT eco_code, opening_name FROM games WHERE id=?", (gid,)).fetchone()
            assert row["eco_code"] == "B20"
            assert row["opening_name"] == "Sicilian Defence"

    def test_record_game_eco_nullable(self, tmp_path):
        """O-2b: eco_code defaults to NULL when not provided."""
        for db in _fresh(tmp_path):
            gid = _game(db)
            with db.get_conn() as conn:
                row = conn.execute("SELECT eco_code FROM games WHERE id=?", (gid,)).fetchone()
            assert row["eco_code"] is None


class TestGetOpeningsForModel:
    def test_returns_wdl_breakdown(self, tmp_path):
        """O-3: W/D/L totals are correct per opening."""
        for db in _fresh(tmp_path):
            _game(db, result="1-0", eco="B20", opening="Sicilian")
            _game(db, result="0-1", eco="B20", opening="Sicilian")
            _game(db, result="1/2-1/2", eco="B20", opening="Sicilian")
            rows = db.get_openings_for_model("w")
            assert len(rows) == 1
            r = rows[0]
            assert r["eco_code"] == "B20"
            assert r["games"] == 3
            assert r["wins"] == 1    # white won game 1
            assert r["draws"] == 1
            assert r["losses"] == 1  # black won game 2, so white lost

    def test_empty_for_unknown_model(self, tmp_path):
        """O-4: returns [] for a model with no games."""
        for db in _fresh(tmp_path):
            assert db.get_openings_for_model("nonexistent") == []

    def test_excludes_games_without_eco(self, tmp_path):
        """O-5: games without eco_code are excluded."""
        for db in _fresh(tmp_path):
            _game(db, eco="E60", opening="King's Indian")
            _game(db)  # no ECO
            rows = db.get_openings_for_model("w")
            assert len(rows) == 1  # only the ECO-tagged game

    def test_ordered_by_games_descending(self, tmp_path):
        """O-6: openings with more games appear first."""
        for db in _fresh(tmp_path):
            for _ in range(3):
                _game(db, eco="E60", opening="King's Indian")
            _game(db, eco="B20", opening="Sicilian")
            rows = db.get_openings_for_model("w")
            assert rows[0]["eco_code"] == "E60"
            assert rows[1]["eco_code"] == "B20"


# ── C-1 / C-2 / C-3 / C-4: coherence history ─────────────────────────────────


def _move_with_coherence(db, game_id, player_mid, score, move_num=1):
    """Helper: record a move with a coherence score."""
    with db.get_conn() as conn:
        pid = conn.execute("SELECT id FROM players WHERE model_id=?", (player_mid,)).fetchone()["id"]
        conn.execute(
            """INSERT INTO moves
               (game_id, player_id, move_number, move_san, move_uci,
                quality, candidate_rank, reasoning, fen_after, coherence_score)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                game_id, pid, move_num, "e4", "e2e4",
                "best", 1, "centre",
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                score,
            ),
        )


class TestCoherenceHistory:
    def test_per_game_avg(self, tmp_path):
        """C-1: avg_coherence is the mean of moves' scores in that game."""
        for db in _fresh(tmp_path):
            g1 = _game(db)
            _move_with_coherence(db, g1, "w", 8.0, move_num=1)
            _move_with_coherence(db, g1, "w", 6.0, move_num=3)
            hist = db.get_coherence_history("w")
            assert len(hist) == 1
            assert hist[0]["avg_coherence"] == 7.0

    def test_excludes_games_without_coherence(self, tmp_path):
        """C-2: games with no coherence scores are excluded."""
        for db in _fresh(tmp_path):
            g1 = _game(db)
            _game(db)  # g2 has no coherence scores
            _move_with_coherence(db, g1, "w", 9.0)
            hist = db.get_coherence_history("w")
            assert len(hist) == 1
            assert hist[0]["game_id"] == g1

    def test_empty_for_unknown_model(self, tmp_path):
        """C-3: returns [] for unknown model."""
        for db in _fresh(tmp_path):
            assert db.get_coherence_history("nobody") == []

    def test_game_number_sequential(self, tmp_path):
        """C-4: game_number is 1-indexed and sequential."""
        for db in _fresh(tmp_path):
            g1 = _game(db)
            g2 = _game(db)
            _move_with_coherence(db, g1, "w", 7.0)
            _move_with_coherence(db, g2, "w", 5.0)
            hist = db.get_coherence_history("w")
            assert hist[0]["game_number"] == 1
            assert hist[1]["game_number"] == 2


# ── R-1 / R-2: HTTP routes ─────────────────────────────────────────────────────


class TestNewRoutes:
    def _client(self, tmp_path):
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
                yield c, database

    def test_openings_route_returns_list(self, tmp_path):
        """R-1: GET /api/models/{id}/openings returns a JSON list."""
        for client, db in self._client(tmp_path):
            db.upsert_player("m", "Model", "lmstudio")
            resp = client.get("/api/models/m/openings")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_coherence_history_route_returns_list(self, tmp_path):
        """R-2: GET /api/models/{id}/coherence-history returns a JSON list."""
        for client, db in self._client(tmp_path):
            db.upsert_player("m", "Model", "lmstudio")
            resp = client.get("/api/models/m/coherence-history")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
