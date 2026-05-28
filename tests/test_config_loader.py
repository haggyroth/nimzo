"""
Tests for config_loader.py — TOML config parsing.

These tests do NOT import arena.py directly; they rely on a minimal stub
so the circular-import guard in load_config() (which imports from arena)
doesn't trip up pytest.  We patch sys.modules to inject lightweight stand-ins.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────────────────
# Minimal arena stub so config_loader can do `from arena import ...`
# without needing a real uvicorn / stockfish installation.
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class _PlayerSpec:
    backend: str = "lmstudio"
    name: str = ""
    model_id: str = ""
    url: str = "http://localhost:1234/v1"
    thinking: bool = False
    candidate_count: Optional[int] = None
    style: str = ""
    blind_opening_moves: int = 0
    blind: bool = False


@dataclass
class _TournamentStartConfig:
    white_backend: str = "lmstudio"
    white_name: str = "White"
    white_model: str = ""
    white_url: str = "http://localhost:1234/v1"
    white_thinking: bool = False
    white_style: str = ""
    white_blind_opening_moves: int = 0
    white_blind: bool = False
    white_candidate_count: Optional[int] = None
    black_backend: str = "lmstudio"
    black_name: str = "Black"
    black_model: str = ""
    black_url: str = "http://localhost:1235/v1"
    black_thinking: bool = False
    black_style: str = ""
    black_blind_opening_moves: int = 0
    black_blind: bool = False
    black_candidate_count: Optional[int] = None
    tutor_backend: str = "lmstudio"
    tutor_model: str = ""
    tutor_url: str = "http://localhost:1234/v1"
    judge_backend: str = "lmstudio"
    judge_model: str = ""
    judge_url: str = "http://localhost:1234/v1"
    games: int = 1
    games_per_pair: int = 2
    format: str = "match"
    move_timeout: int = 0
    max_moves: int = 0
    human_assisted: bool = True
    adaptive_difficulty: bool = False
    opening_pgn: str = ""
    players: list = field(default_factory=list)


def _make_arena_stub():
    mod = types.ModuleType("arena")
    mod.TournamentStartConfig = _TournamentStartConfig
    mod.PlayerSpec = _PlayerSpec
    return mod


@pytest.fixture(autouse=True)
def _stub_arena():
    """Inject a minimal arena stub for every test in this module."""
    stub = _make_arena_stub()
    with patch.dict(sys.modules, {"arena": stub}):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "tournament.toml"
    p.write_text(content, encoding="utf-8")
    return p


def _load(path):
    from config_loader import load_config  # noqa: PLC0415
    return load_config(path)


# ──────────────────────────────────────────────────────────────────────────
# Tests: _load_toml low-level
# ──────────────────────────────────────────────────────────────────────────

class TestLoadToml:
    def test_parses_basic_toml(self, tmp_path):
        p = _write_toml(tmp_path, '[match]\ngames = 3\n')
        from config_loader import _load_toml  # noqa: PLC0415
        data = _load_toml(p)
        assert data["match"]["games"] == 3

    def test_missing_file_raises(self, tmp_path):
        from config_loader import _load_toml  # noqa: PLC0415
        with pytest.raises(FileNotFoundError):
            _load_toml(tmp_path / "nonexistent.toml")


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — missing file
# ──────────────────────────────────────────────────────────────────────────

class TestLoadConfigMissingFile:
    def test_raises_file_not_found(self, tmp_path):
        from config_loader import load_config  # noqa: PLC0415
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(tmp_path / "no_such_file.toml")


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — 2-player match mode
# ──────────────────────────────────────────────────────────────────────────

TWO_PLAYER_TOML = """
[match]
format       = "match"
games        = 5
move_timeout = 30

[tutor]
backend = "lmstudio"
model   = "qwen3-8b"
url     = "http://localhost:1234/v1"

[judge]
backend = "lmstudio"
model   = "judge-model"
url     = "http://localhost:1234/v1"

[white]
name    = "Qwen"
backend = "lmstudio"
model   = "qwen3-30b-a3b"
url     = "http://localhost:1234/v1"
thinking = false

[black]
name    = "Llama"
backend = "lmstudio"
model   = "llama-3.1-70b"
url     = "http://localhost:1235/v1"
thinking = true
"""


class TestTwoPlayerConfig:
    @pytest.fixture
    def cfg(self, tmp_path):
        p = _write_toml(tmp_path, TWO_PLAYER_TOML)
        return _load(p)

    def test_white_fields(self, cfg):
        assert cfg.white_name == "Qwen"
        assert cfg.white_model == "qwen3-30b-a3b"
        assert cfg.white_backend == "lmstudio"
        assert cfg.white_url == "http://localhost:1234/v1"
        assert cfg.white_thinking is False

    def test_black_fields(self, cfg):
        assert cfg.black_name == "Llama"
        assert cfg.black_model == "llama-3.1-70b"
        assert cfg.black_url == "http://localhost:1235/v1"
        assert cfg.black_thinking is True

    def test_match_fields(self, cfg):
        assert cfg.games == 5
        assert cfg.move_timeout == 30
        assert cfg.format == "match"

    def test_tutor_fields(self, cfg):
        assert cfg.tutor_model == "qwen3-8b"
        assert cfg.tutor_backend == "lmstudio"
        assert cfg.tutor_url == "http://localhost:1234/v1"

    def test_judge_fields(self, cfg):
        assert cfg.judge_model == "judge-model"
        assert cfg.judge_backend == "lmstudio"

    def test_no_players_list(self, cfg):
        assert cfg.players == []


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — judge defaults to tutor when absent
# ──────────────────────────────────────────────────────────────────────────

NO_JUDGE_TOML = """
[match]
games = 1

[tutor]
backend = "lmstudio"
model   = "qwen3-8b"
url     = "http://localhost:1234/v1"

[white]
name    = "A"
model   = "model-a"

[black]
name    = "B"
model   = "model-b"
"""


class TestJudgeDefaultsToTutor:
    def test_judge_model_falls_back_to_tutor(self, tmp_path):
        p = _write_toml(tmp_path, NO_JUDGE_TOML)
        cfg = _load(p)
        assert cfg.judge_model == "qwen3-8b"
        assert cfg.judge_backend == "lmstudio"
        assert cfg.judge_url == "http://localhost:1234/v1"


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — multi-player bracket mode
# ──────────────────────────────────────────────────────────────────────────

MULTI_PLAYER_TOML = """
[match]
format       = "round_robin"
games        = 2
move_timeout = 0

[tutor]
model = "qwen3-8b"

[[players]]
name    = "Qwen"
backend = "lmstudio"
model   = "qwen3-30b-a3b"
url     = "http://localhost:1234/v1"

[[players]]
name    = "Llama"
backend = "lmstudio"
model   = "llama-3.1-70b"
url     = "http://localhost:1235/v1"

[[players]]
name    = "Gemma"
backend = "lmstudio"
model   = "gemma-3-27b-it"
url     = "http://localhost:1234/v1"
"""


class TestMultiPlayerConfig:
    @pytest.fixture
    def cfg(self, tmp_path):
        p = _write_toml(tmp_path, MULTI_PLAYER_TOML)
        return _load(p)

    def test_players_count(self, cfg):
        assert len(cfg.players) == 3

    def test_player_names(self, cfg):
        names = [p.name for p in cfg.players]
        assert "Qwen" in names
        assert "Llama" in names
        assert "Gemma" in names

    def test_player_model_ids(self, cfg):
        models = [p.model_id for p in cfg.players]
        assert "qwen3-30b-a3b" in models
        assert "llama-3.1-70b" in models

    def test_format_round_robin(self, cfg):
        assert cfg.format == "round_robin"

    def test_games_per_pair(self, cfg):
        assert cfg.games_per_pair == 2

    def test_two_player_fields_empty(self, cfg):
        # Multi-player mode should not set white/black fields
        assert cfg.white_model == ""
        assert cfg.black_model == ""


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — defaults when sections are absent
# ──────────────────────────────────────────────────────────────────────────

MINIMAL_TOML = """
[white]
name  = "A"
model = "model-a"

[black]
name  = "B"
model = "model-b"
"""


class TestMinimalConfig:
    @pytest.fixture
    def cfg(self, tmp_path):
        p = _write_toml(tmp_path, MINIMAL_TOML)
        return _load(p)

    def test_default_games(self, cfg):
        assert cfg.games == 1

    def test_default_move_timeout(self, cfg):
        assert cfg.move_timeout == 0

    def test_default_human_assisted(self, cfg):
        assert cfg.human_assisted is True

    def test_default_format(self, cfg):
        assert cfg.format == "match"

    def test_default_tutor_model_empty(self, cfg):
        assert cfg.tutor_model == ""


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — human_assisted flag
# ──────────────────────────────────────────────────────────────────────────

class TestHumanAssisted:
    def test_human_assisted_false(self, tmp_path):
        toml = "[match]\nhuman_assisted = false\n[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.human_assisted is False

    def test_human_assisted_true_explicit(self, tmp_path):
        toml = "[match]\nhuman_assisted = true\n[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.human_assisted is True


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — new M-4 fields: style and adaptive_difficulty
# ──────────────────────────────────────────────────────────────────────────

class TestStyleAndAdaptiveDifficulty:
    """Regression for REVIEW.md M-4: config_loader was not parsing style or
    adaptive_difficulty from TOML, despite both being documented."""

    def test_white_style_parsed(self, tmp_path):
        toml = (
            "[match]\n[white]\nname='A'\nmodel='m'\nstyle='aggressive'\n"
            "[black]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.white_style == "aggressive"

    def test_black_style_parsed(self, tmp_path):
        toml = (
            "[match]\n[white]\nname='A'\nmodel='m'\n"
            "[black]\nname='B'\nmodel='n'\nstyle='defensive'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.black_style == "defensive"

    def test_style_defaults_to_empty(self, tmp_path):
        toml = "[match]\n[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.white_style == ""
        assert cfg.black_style == ""

    def test_adaptive_difficulty_parsed(self, tmp_path):
        toml = (
            "[match]\nadaptive_difficulty = true\n"
            "[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.adaptive_difficulty is True

    def test_adaptive_difficulty_defaults_false(self, tmp_path):
        toml = "[match]\n[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.adaptive_difficulty is False

    def test_player_style_parsed_in_multi_player_mode(self, tmp_path):
        toml = (
            "[match]\nformat = 'round_robin'\ngames = 1\n"
            "[[players]]\nname='A'\nmodel='m'\nstyle='positional'\n"
            "[[players]]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.players[0].style == "positional"
        assert cfg.players[1].style == ""

    def test_adaptive_difficulty_in_multi_player_mode(self, tmp_path):
        toml = (
            "[match]\nformat = 'round_robin'\ngames = 1\nadaptive_difficulty = true\n"
            "[[players]]\nname='A'\nmodel='m'\n"
            "[[players]]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.adaptive_difficulty is True


# ──────────────────────────────────────────────────────────────────────────
# Tests: load_config — full-game blind mode (phase-28)
# ──────────────────────────────────────────────────────────────────────────

class TestBlindMode:
    """Regression tests for TOML blind = true in 2-player and multi-player modes."""

    def test_white_blind_parsed(self, tmp_path):
        toml = (
            "[match]\n[white]\nname='A'\nmodel='m'\nblind=true\n"
            "[black]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.white_blind is True

    def test_black_blind_parsed(self, tmp_path):
        toml = (
            "[match]\n[white]\nname='A'\nmodel='m'\n"
            "[black]\nname='B'\nmodel='n'\nblind=true\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.black_blind is True

    def test_blind_defaults_false(self, tmp_path):
        toml = "[match]\n[white]\nname='A'\nmodel='m'\n[black]\nname='B'\nmodel='n'\n"
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.white_blind is False
        assert cfg.black_blind is False

    def test_player_blind_parsed_in_multi_player_mode(self, tmp_path):
        toml = (
            "[match]\nformat = 'round_robin'\ngames = 1\n"
            "[[players]]\nname='A'\nmodel='m'\nblind=true\n"
            "[[players]]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.players[0].blind is True
        assert cfg.players[1].blind is False

    def test_blind_and_opening_moves_coexist(self, tmp_path):
        """blind and blind_opening_moves are independent TOML fields."""
        toml = (
            "[match]\n[white]\nname='A'\nmodel='m'\nblind=true\nblind_opening_moves=5\n"
            "[black]\nname='B'\nmodel='n'\n"
        )
        p = _write_toml(tmp_path, toml)
        cfg = _load(p)
        assert cfg.white_blind is True
        assert cfg.white_blind_opening_moves == 5
