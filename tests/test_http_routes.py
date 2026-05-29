"""
HTTP-layer tests — T-1 through T-7.

Covers every route that was untested before Wave 5:
  T-1  /api/games/export       — 200, plain-text, no-games case, routing regression
  T-2  /api/games/{id}         — 200 when found, 404 when absent
  T-3  /api/games/{id}/moves   — list of move dicts
  T-4  /api/games/{id}/pgn     — single-game PGN download
  T-5  /api/leaderboard        — list, stable when empty
  T-6  /api/elo-history/{id}   — list for known model, empty for unknown
  T-7  /api/models SSRF guard  — 403 for external host, pass for localhost

Uses FastAPI TestClient so no real server or Stockfish is needed.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patched_db(tmp_path):
    """
    Wire every DB call to a fresh temp SQLite file for each test.
    Returns the patched `db` module so helpers can seed data.
    """
    import db as database

    db_path = tmp_path / "routes_test.db"

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
def client(_patched_db):
    """TestClient wired to the same patched DB."""
    from fastapi.testclient import TestClient
    from arena import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Seed helpers ──────────────────────────────────────────────────────────────


def _seed_game(db, white_id="w-bot", black_id="b-bot", result="1-0"):
    db.upsert_player(model_id=white_id, name=white_id, backend="lmstudio")
    db.upsert_player(model_id=black_id, name=black_id, backend="lmstudio")
    return db.record_game(
        white_model_id=white_id,
        black_model_id=black_id,
        result=result,
        termination="checkmate",
        total_moves=4,
        pgn="1. e4 e5 2. Nf3 Nc6 1-0",
        white_elo_before=1200,
        black_elo_before=1200,
        white_elo_after=1216,
        black_elo_after=1184,
    )


def _seed_move(db, game_id: int, player_model_id: str = "w-bot", move_number: int = 1):
    with db.get_conn() as conn:
        pid = conn.execute(
            "SELECT id FROM players WHERE model_id=?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO moves
               (game_id, player_id, move_number, move_san, move_uci,
                quality, candidate_rank, reasoning, fen_after)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                game_id, pid, move_number, "e4", "e2e4",
                "best", 1, "Controls center.",
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            ),
        )


# ── T-1: /api/games/export ────────────────────────────────────────────────────


class TestGamesExport:
    """T-1 — bulk PGN export endpoint."""

    def test_empty_db_returns_200(self, client):
        assert client.get("/api/games/export").status_code == 200

    def test_empty_db_content_type_is_plain_text(self, client):
        resp = client.get("/api/games/export")
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_empty_db_has_no_attachment_header(self, client):
        resp = client.get("/api/games/export")
        assert "attachment" not in resp.headers.get("content-disposition", "")

    def test_with_games_has_attachment_header(self, client, _patched_db):
        _seed_game(_patched_db)
        resp = client.get("/api/games/export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_model_id_filter_includes_filename(self, client, _patched_db):
        _seed_game(_patched_db, white_id="alpha", black_id="beta")
        resp = client.get("/api/games/export?model_id=alpha")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "alpha" in cd

    def test_not_confused_with_game_id_route(self, client):
        """Regression T-1f: /api/games/export must not be captured by
        /api/games/{game_id} and return 422 (non-integer path param)."""
        resp = client.get("/api/games/export")
        assert resp.status_code != 422, (
            "/api/games/export returned 422 — route ordering regression "
            "(parametric {game_id} route is capturing 'export')"
        )


# ── T-2: /api/games/{game_id} ────────────────────────────────────────────────


class TestGameById:
    """T-2 — single-game fetch."""

    def test_existing_game_returns_200(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        resp = client.get(f"/api/games/{gid}")
        assert resp.status_code == 200

    def test_response_has_correct_game_id(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        data = client.get(f"/api/games/{gid}").json()
        assert data["id"] == gid

    def test_response_has_result_field(self, client, _patched_db):
        gid = _seed_game(_patched_db, result="0-1")
        data = client.get(f"/api/games/{gid}").json()
        assert data["result"] == "0-1"

    def test_missing_game_returns_404(self, client):
        assert client.get("/api/games/99999").status_code == 404


# ── T-3: /api/games/{game_id}/moves ──────────────────────────────────────────


class TestGameMoves:
    """T-3 — per-game move list."""

    def test_returns_list(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        resp = client.get(f"/api/games/{gid}/moves")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_no_moves_returns_empty_list(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        assert client.get(f"/api/games/{gid}/moves").json() == []

    def test_seeded_move_appears_in_response(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        _seed_move(_patched_db, gid)
        moves = client.get(f"/api/games/{gid}/moves").json()
        assert len(moves) == 1

    def test_move_fields_present(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        _seed_move(_patched_db, gid)
        m = client.get(f"/api/games/{gid}/moves").json()[0]
        for field in ("move_san", "quality", "candidate_rank", "reasoning"):
            assert field in m, f"Missing field {field!r} in move response"


# ── T-4: /api/games/{game_id}/pgn ────────────────────────────────────────────


class TestGamePgn:
    """T-4 — single-game PGN download."""

    def test_existing_game_returns_200(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        assert client.get(f"/api/games/{gid}/pgn").status_code == 200

    def test_content_type_is_plain_text(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        resp = client.get(f"/api/games/{gid}/pgn")
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_pgn_contains_result_tag(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        resp = client.get(f"/api/games/{gid}/pgn")
        assert "[Result" in resp.text

    def test_pgn_has_attachment_header(self, client, _patched_db):
        gid = _seed_game(_patched_db)
        resp = client.get(f"/api/games/{gid}/pgn")
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_missing_game_returns_404(self, client):
        assert client.get("/api/games/99999/pgn").status_code == 404


# ── T-5: /api/leaderboard ────────────────────────────────────────────────────


class TestLeaderboard:
    """T-5 — leaderboard endpoint."""

    def test_empty_db_returns_list(self, client):
        resp = client.get("/api/leaderboard")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_players_appear_after_game(self, client, _patched_db):
        _seed_game(_patched_db, white_id="alpha", black_id="beta")
        board = client.get("/api/leaderboard").json()
        ids = [r["model_id"] for r in board]
        assert "alpha" in ids
        assert "beta" in ids

    def test_winner_ranked_above_loser(self, client, _patched_db):
        """After a decisive game the winner (higher ELO) should rank first."""
        _seed_game(_patched_db, white_id="winner", black_id="loser", result="1-0")
        board = client.get("/api/leaderboard").json()
        ids = [r["model_id"] for r in board]
        if "winner" in ids and "loser" in ids:
            assert ids.index("winner") <= ids.index("loser"), (
                "Winner should appear before loser on the leaderboard"
            )


# ── T-6: /api/elo-history/{model_id} ─────────────────────────────────────────


class TestEloHistory:
    """T-6 — ELO history endpoint."""

    def test_unknown_model_returns_empty_list(self, client):
        resp = client.get("/api/elo-history/nonexistent-bot")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_known_model_returns_history(self, client, _patched_db):
        # ELO history is derived from the games table
        _seed_game(_patched_db, white_id="elo-test", black_id="elo-opp")
        resp = client.get("/api/elo-history/elo-test")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "elo_after" in data[0] or "elo" in data[0]

    def test_model_id_with_slash(self, client, _patched_db):
        """Model IDs containing slashes (e.g. 'owner/repo') must work via
        the :path converter on the route."""
        _seed_game(_patched_db, white_id="owner/model", black_id="other")
        resp = client.get("/api/elo-history/owner/model")
        assert resp.status_code == 200


# ── T-6b: /api/elo-history/batch ─────────────────────────────────────────────


class TestEloHistoryBatch:
    """T-6b — batch ELO history endpoint (m8 wave-4 fix)."""

    def test_empty_ids_returns_empty_dict(self, client):
        resp = client.get("/api/elo-history/batch")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_unknown_ids_return_empty_lists(self, client):
        resp = client.get("/api/elo-history/batch?ids=ghost1&ids=ghost2")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"ghost1": [], "ghost2": []}

    def test_known_models_return_history(self, client, _patched_db):
        _seed_game(_patched_db, white_id="batch-w", black_id="batch-b")
        resp = client.get("/api/elo-history/batch?ids=batch-w&ids=batch-b")
        assert resp.status_code == 200
        data = resp.json()
        assert "batch-w" in data
        assert "batch-b" in data
        assert len(data["batch-w"]) >= 1
        assert "elo_after" in data["batch-w"][0]

    def test_mixed_known_and_unknown(self, client, _patched_db):
        """Known model gets history; unknown model gets empty list."""
        _seed_game(_patched_db, white_id="real-bot", black_id="other-bot")
        resp = client.get("/api/elo-history/batch?ids=real-bot&ids=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["real-bot"]) >= 1
        assert data["nonexistent"] == []

    def test_single_id_matches_individual_endpoint(self, client, _patched_db):
        """Batch result for a single ID should match the per-ID endpoint."""
        _seed_game(_patched_db, white_id="solo", black_id="solo-opp")
        single = client.get("/api/elo-history/solo").json()
        batch  = client.get("/api/elo-history/batch?ids=solo").json()
        assert batch["solo"] == single

    def test_batch_does_not_collide_with_path_route(self, client):
        """'batch' must not be captured by /api/elo-history/{model_id:path}."""
        resp = client.get("/api/elo-history/batch")
        # If routing is wrong this would return a 200 list instead of a dict
        assert isinstance(resp.json(), dict), (
            "/api/elo-history/batch was captured by the {model_id:path} route"
        )


# ── T-7: /api/models SSRF guard ──────────────────────────────────────────────


class TestModelProxySsrf:
    """T-7 — SSRF allowlist on the /api/models proxy endpoint."""

    def test_localhost_not_blocked(self, client):
        """localhost is in the default allowlist; must not return 403.
        (The actual request may fail with a connection error — that's fine.)"""
        resp = client.get("/api/models?url=http://localhost:1234/v1")
        assert resp.status_code != 403

    def test_127_0_0_1_not_blocked(self, client):
        resp = client.get("/api/models?url=http://127.0.0.1:1234/v1")
        assert resp.status_code != 403

    def test_external_host_returns_403(self, client):
        resp = client.get("/api/models?url=http://evil.example.com/v1")
        assert resp.status_code == 403

    def test_403_detail_mentions_allowlist(self, client):
        resp = client.get("/api/models?url=http://evil.example.com/v1")
        assert "allowlist" in resp.json().get("detail", "").lower()

    def test_default_url_not_blocked(self, client):
        """No ?url param → default localhost URL → must pass the guard."""
        resp = client.get("/api/models")
        assert resp.status_code != 403

    def test_allowlist_extended_via_monkeypatch(self, client, monkeypatch):
        """Patching _PROXY_ALLOWED_HOSTS at runtime extends the set."""
        import arena.routes.model_api as _m

        original = _m._PROXY_ALLOWED_HOSTS
        monkeypatch.setattr(
            _m,
            "_PROXY_ALLOWED_HOSTS",
            frozenset(original | {"trusted.internal"}),
        )
        resp = client.get("/api/models?url=http://trusted.internal:1234/v1")
        assert resp.status_code != 403
