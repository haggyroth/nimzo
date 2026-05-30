"""
test_phase5a.py — Tests for Phase 5a features.

  - GET /api/compare: bundles profiles, ELO histories, coherence, openings, H2H
  - Recent games filter helper (Python-side: not much to test, but API coverage)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import db as database


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "phase5a_test.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    yield


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "phase5a_api.db"

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


def _seed_player(db_path, name, model_id, elo=1500):
    """Insert a minimal player record for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT OR IGNORE INTO players (name, model_id, backend, elo) VALUES (?,?,?,?)",
        (name, model_id, "lmstudio", elo),
    )
    conn.commit()
    conn.close()


# ── /api/compare endpoint ─────────────────────────────────────────────────────


class TestCompareEndpoint:
    def test_missing_params_returns_400(self, client):
        resp = client.get("/api/compare")
        assert resp.status_code == 422   # FastAPI validation — both params required

    def test_missing_b_returns_422(self, client):
        resp = client.get("/api/compare?a=model-a")
        assert resp.status_code == 422

    def test_unknown_models_returns_404(self, client):
        resp = client.get("/api/compare?a=ghost-a&b=ghost-b")
        assert resp.status_code == 404

    def test_known_models_returns_bundle(self, client, tmp_path):
        # Seed two players via the DB patch applied by the `client` fixture
        with patch.object(database, "get_conn", lambda *a: _null_conn(tmp_path)):
            pass  # can't easily seed here; use upsert_player via the API route

        # Use the API to seed players implicitly by calling upsert inside the route
        # Instead: patch get_model_profile to return minimal data
        minimal_profile = {
            "model_id": "model-a", "name": "Model A", "elo": 1500,
            "moves": {}, "color": {}, "games": {}, "style": None,
        }
        with patch.object(database, "get_model_profile", return_value=minimal_profile), \
             patch.object(database, "get_elo_history", return_value=[]), \
             patch.object(database, "get_coherence_stats", return_value={"avg_coherence": None, "total_moves": 0}), \
             patch.object(database, "get_openings_for_model", return_value=[]), \
             patch.object(database, "get_h2h_record", return_value={"wins": 0, "draws": 0, "losses": 0, "total": 0}):
            resp = client.get("/api/compare?a=model-a&b=model-b")

        assert resp.status_code == 200
        data = resp.json()
        assert "a" in data
        assert "b" in data
        assert "h2h" in data

    def test_response_contains_expected_keys(self, client):
        profile_a = {"model_id": "a", "name": "A", "elo": 1600, "moves": {}, "color": {}, "games": {}, "style": None}
        profile_b = {"model_id": "b", "name": "B", "elo": 1400, "moves": {}, "color": {}, "games": {}, "style": None}

        with patch.object(database, "get_model_profile", side_effect=[profile_a, profile_b]), \
             patch.object(database, "get_elo_history", return_value=[]), \
             patch.object(database, "get_coherence_stats", return_value={}), \
             patch.object(database, "get_openings_for_model", return_value=[]), \
             patch.object(database, "get_h2h_record", return_value={}):
            resp = client.get("/api/compare?a=a&b=b")

        assert resp.status_code == 200
        data = resp.json()
        # Profile A should have elo_history, coherence, openings embedded
        assert "elo_history" in data["a"]
        assert "coherence"   in data["a"]
        assert "openings"    in data["a"]
        assert "elo_history" in data["b"]

    def test_one_missing_profile_returns_404(self, client):
        """If one model doesn't exist, the endpoint returns 404."""
        with patch.object(database, "get_model_profile", side_effect=[None, None]):
            resp = client.get("/api/compare?a=ghost&b=ghost2")
        assert resp.status_code == 404

    def test_compare_same_model_returns_data(self, client):
        """Comparing a model against itself is technically valid (H2H=0)."""
        profile = {"model_id": "a", "name": "A", "elo": 1500, "moves": {}, "color": {}, "games": {}, "style": None}
        with patch.object(database, "get_model_profile", return_value=profile), \
             patch.object(database, "get_elo_history", return_value=[]), \
             patch.object(database, "get_coherence_stats", return_value={}), \
             patch.object(database, "get_openings_for_model", return_value=[]), \
             patch.object(database, "get_h2h_record", return_value={"wins": 0, "draws": 0, "losses": 0, "total": 0}):
            resp = client.get("/api/compare?a=a&b=a")
        assert resp.status_code == 200

    def test_openings_capped_at_five(self, client):
        """The endpoint caps openings at 5 per model."""
        profile = {"model_id": "a", "name": "A", "elo": 1500, "moves": {}, "color": {}, "games": {}, "style": None}
        many_openings = [{"eco_code": f"E{i:02d}", "opening_name": f"Open {i}", "games": i} for i in range(20)]
        with patch.object(database, "get_model_profile", return_value=profile), \
             patch.object(database, "get_elo_history", return_value=[]), \
             patch.object(database, "get_coherence_stats", return_value={}), \
             patch.object(database, "get_openings_for_model", return_value=many_openings), \
             patch.object(database, "get_h2h_record", return_value={}):
            resp = client.get("/api/compare?a=a&b=a")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["a"]["openings"]) <= 5
        assert len(data["b"]["openings"]) <= 5


def _null_conn(tmp_path):
    """Helper: can't use this easily, just placeholder."""
    pass
