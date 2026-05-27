"""
Load a tournament.toml config file into a TournamentStartConfig.

Supports Python 3.11+ tomllib (stdlib) with a fallback to the `tomli`
third-party package for older runtimes.

Example tournament.toml
-----------------------

[match]
format        = "round_robin"   # "match" | "round_robin" | "gauntlet"
games         = 5               # games (match) or games_per_pair (tournament)
move_timeout  = 60              # seconds per move, 0 = no limit
human_assisted = true

[tutor]
backend = "lmstudio"
model   = "qwen3-8b"
url     = "http://localhost:1234/v1"

[judge]
backend = "lmstudio"
model   = "qwen3-8b"
url     = "http://localhost:1234/v1"

# 2-player match form (overrides [[players]] when only white/black present)
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
thinking = false

# OR multi-player form (activates bracket mode)
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
"""

from __future__ import annotations

import sys
from pathlib import Path


def _load_toml(path: Path) -> dict:
    """Parse a TOML file using stdlib tomllib (3.11+) or the tomli package."""
    if sys.version_info >= (3, 11):
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    try:
        import tomli  # type: ignore[import]
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        raise RuntimeError(
            "TOML support requires Python 3.11+ or `pip install tomli`"
        )


def load_config(path: str | Path):
    """
    Parse a tournament.toml file and return a TournamentStartConfig.

    Imported lazily to avoid circular imports (arena imports this module).
    """
    # Local import to avoid circular dependency
    from arena import TournamentStartConfig, PlayerSpec  # type: ignore

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = _load_toml(path)

    match_cfg  = raw.get("match", {})
    tutor_cfg  = raw.get("tutor", {})
    judge_cfg  = raw.get("judge", {})
    white_cfg  = raw.get("white", {})
    black_cfg  = raw.get("black", {})
    players_list = raw.get("players", [])

    fmt          = match_cfg.get("format", "match")
    move_timeout = int(match_cfg.get("move_timeout", 0))
    max_moves    = int(match_cfg.get("max_moves", 0))

    adaptive_difficulty = bool(match_cfg.get("adaptive_difficulty", False))

    # ── Multi-player bracket mode ─────────────────────────────────────────
    if len(players_list) >= 2:
        players = [
            PlayerSpec(
                backend             = p.get("backend", "lmstudio"),
                name                = p.get("name", ""),
                model_id            = p.get("model", ""),
                url                 = p.get("url", "http://localhost:1234/v1"),
                thinking            = bool(p.get("thinking", False)),
                candidate_count     = int(p.get("candidate_count", 5)) or None,
                style               = p.get("style", ""),
                blind_opening_moves = int(p.get("blind_opening_moves", 0)),
            )
            for p in players_list
        ]
        return TournamentStartConfig(
            tutor_backend       = tutor_cfg.get("backend", "lmstudio"),
            tutor_model         = tutor_cfg.get("model", ""),
            tutor_url           = tutor_cfg.get("url", "http://localhost:1234/v1"),
            judge_backend       = judge_cfg.get("backend", tutor_cfg.get("backend", "lmstudio")),
            judge_model         = judge_cfg.get("model", tutor_cfg.get("model", "")),
            judge_url           = judge_cfg.get("url", tutor_cfg.get("url", "http://localhost:1234/v1")),
            players             = players,
            format              = fmt,
            games_per_pair      = int(match_cfg.get("games", 2)),
            move_timeout        = move_timeout,
            max_moves           = max_moves,
            human_assisted      = bool(match_cfg.get("human_assisted", True)),
            adaptive_difficulty = adaptive_difficulty,
        )

    # ── 2-player match mode ───────────────────────────────────────────────
    return TournamentStartConfig(
        white_backend               = white_cfg.get("backend", "lmstudio"),
        white_name                  = white_cfg.get("name", "White"),
        white_model                 = white_cfg.get("model", ""),
        white_url                   = white_cfg.get("url", "http://localhost:1234/v1"),
        white_thinking              = bool(white_cfg.get("thinking", False)),
        white_style                 = white_cfg.get("style", ""),
        white_blind_opening_moves   = int(white_cfg.get("blind_opening_moves", 0)),
        black_backend               = black_cfg.get("backend", "lmstudio"),
        black_name                  = black_cfg.get("name", "Black"),
        black_model                 = black_cfg.get("model", ""),
        black_url                   = black_cfg.get("url", "http://localhost:1235/v1"),
        black_thinking              = bool(black_cfg.get("thinking", False)),
        black_style                 = black_cfg.get("style", ""),
        black_blind_opening_moves   = int(black_cfg.get("blind_opening_moves", 0)),
        tutor_backend               = tutor_cfg.get("backend", "lmstudio"),
        tutor_model                 = tutor_cfg.get("model", ""),
        tutor_url                   = tutor_cfg.get("url", "http://localhost:1234/v1"),
        judge_backend               = judge_cfg.get("backend", tutor_cfg.get("backend", "lmstudio")),
        judge_model                 = judge_cfg.get("model", tutor_cfg.get("model", "")),
        judge_url                   = judge_cfg.get("url", tutor_cfg.get("url", "http://localhost:1234/v1")),
        games                       = int(match_cfg.get("games", 1)),
        move_timeout                = move_timeout,
        max_moves                   = max_moves,
        human_assisted              = bool(match_cfg.get("human_assisted", True)),
        adaptive_difficulty         = adaptive_difficulty,
    )
