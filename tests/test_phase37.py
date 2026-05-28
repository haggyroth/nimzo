"""
tests/test_phase37.py — Phase 37: asymmetric candidate_count (handicap matches).

Covers:
  H-1  TournamentStartConfig accepts white_candidate_count and black_candidate_count
  H-2  Defaults to None (use server default) when not supplied
  H-3  Validation: ge=1 rejects 0; le=20 rejects 21
  H-4  build_player() uses the override when supplied
  H-5  build_player() uses default 5 when None
  H-6  config_loader reads candidate_count from TOML [white]/[black]
  H-7  HTTP: POST /api/tournament/start with mismatched counts is accepted
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest


# ── H-1 / H-2 / H-3: Pydantic model validation ───────────────────────────────


class TestTournamentStartConfigHandicap:
    def test_accepts_candidate_count_fields(self):
        """H-1: white_candidate_count and black_candidate_count are accepted."""
        from arena.models import TournamentStartConfig
        cfg = TournamentStartConfig(
            white_model="a", black_model="b",
            white_candidate_count=8, black_candidate_count=3,
        )
        assert cfg.white_candidate_count == 8
        assert cfg.black_candidate_count == 3

    def test_defaults_to_none(self):
        """H-2: both default to None when omitted."""
        from arena.models import TournamentStartConfig
        cfg = TournamentStartConfig(white_model="a", black_model="b")
        assert cfg.white_candidate_count is None
        assert cfg.black_candidate_count is None

    def test_rejects_zero(self):
        """H-3a: 0 is invalid (ge=1)."""
        from arena.models import TournamentStartConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TournamentStartConfig(white_model="a", black_model="b",
                                  white_candidate_count=0)

    def test_rejects_above_twenty(self):
        """H-3b: values above 20 are invalid (le=20)."""
        from arena.models import TournamentStartConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TournamentStartConfig(white_model="a", black_model="b",
                                  black_candidate_count=21)

    def test_accepts_boundary_values(self):
        """H-3c: 1 and 20 are both valid."""
        from arena.models import TournamentStartConfig
        cfg = TournamentStartConfig(white_model="a", black_model="b",
                                    white_candidate_count=1,
                                    black_candidate_count=20)
        assert cfg.white_candidate_count == 1
        assert cfg.black_candidate_count == 20


# ── H-4 / H-5: build_player candidate_count wiring ───────────────────────────


class TestBuildPlayerCandidateCount:
    def test_uses_override_when_supplied(self):
        """H-4: build_player() sets config.candidate_count from the argument."""
        from game import build_player
        p = build_player("lmstudio", "Tester", "test-model",
                         candidate_count=8)
        assert p.config.candidate_count == 8

    def test_uses_default_when_none(self):
        """H-5: build_player() uses default (5) when candidate_count is None."""
        from game import build_player
        p = build_player("lmstudio", "Tester", "test-model",
                         candidate_count=None)
        assert p.config.candidate_count == 5

    def test_asymmetric_counts_are_independent(self):
        """H-4b: two players can have different counts."""
        from game import build_player
        white = build_player("lmstudio", "White", "m1", candidate_count=8)
        black = build_player("lmstudio", "Black", "m2", candidate_count=3)
        assert white.config.candidate_count == 8
        assert black.config.candidate_count == 3
        assert white.config.candidate_count != black.config.candidate_count


# ── H-6: config_loader TOML support ──────────────────────────────────────────


class TestConfigLoaderHandicap:
    def test_reads_candidate_count_from_toml(self, tmp_path):
        """H-6: TOML [white] candidate_count is parsed correctly."""
        toml_content = """\
[match]
games = 1

[white]
name = "Stronger"
model = "big-model"
candidate_count = 3

[black]
name = "Weaker"
model = "small-model"
candidate_count = 8
"""
        toml_path = tmp_path / "test.toml"
        toml_path.write_text(toml_content)
        from config_loader import load_config
        cfg = load_config(str(toml_path))
        assert cfg.white_candidate_count == 3
        assert cfg.black_candidate_count == 8

    def test_candidate_count_absent_gives_none(self, tmp_path):
        """H-6b: omitting candidate_count in TOML gives None (server default)."""
        toml_content = """\
[match]
games = 1

[white]
name = "W"
model = "m1"

[black]
name = "B"
model = "m2"
"""
        toml_path = tmp_path / "test.toml"
        toml_path.write_text(toml_content)
        from config_loader import load_config
        cfg = load_config(str(toml_path))
        assert cfg.white_candidate_count is None
        assert cfg.black_candidate_count is None


# ── H-7: HTTP route accepts asymmetric counts ─────────────────────────────────


class TestHandicapHTTPRoute:
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
                yield c

    def test_post_start_accepts_handicap_counts(self, tmp_path):
        """H-7: POST /api/tournament/start with mismatched candidate counts is accepted."""
        for client in self._client(tmp_path):
            resp = client.post("/api/tournament/start", json={
                "white_model": "model-a",
                "black_model": "model-b",
                "white_backend": "lmstudio",
                "black_backend": "lmstudio",
                "white_candidate_count": 8,
                "black_candidate_count": 3,
                "games": 1,
            })
            # 200 means the body was accepted (tournament may or may not start
            # cleanly without Stockfish, but the request schema was valid)
            assert resp.status_code == 200
