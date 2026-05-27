"""
arena/models.py — Pydantic models: PlayerSpec, TournamentStartConfig, HumanMoveRequest.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from arena.state import _DEFAULT_LMSTUDIO_URL, _DEFAULT_LMSTUDIO_URL_2

# Valid personality style values (empty string = no style override)
_STYLE_VALUES = {"", "aggressive", "positional", "defensive"}


class HumanMoveRequest(BaseModel):
    uci: str


class PlayerSpec(BaseModel):
    """Per-player spec used in multi-player tournament start requests."""

    backend: str = "lmstudio"
    name: str = ""
    model_id: str = ""
    url: str = _DEFAULT_LMSTUDIO_URL
    thinking: bool = False
    candidate_count: Optional[int] = Field(
        default=None, ge=1, le=20,
        description="Stockfish candidates shown to the model (1–20). None = use server default.",
    )
    style: Literal["", "aggressive", "positional", "defensive"] = ""
    blind_opening_moves: int = Field(
        default=0, ge=0, le=40,
        description="Withhold Stockfish candidates for the first N full moves.",
    )


class TournamentStartConfig(BaseModel):
    """
    Request body for ``POST /api/tournament/start``.

    Covers both 2-player match mode (white/black fields) and multi-player
    bracket/round-robin mode (``players`` list with len >= 2).
    """

    white_backend: str = "lmstudio"
    white_name: str = "White"
    white_model: str = ""
    white_url: str = _DEFAULT_LMSTUDIO_URL
    white_thinking: bool = False
    black_backend: str = "lmstudio"
    black_name: str = "Black"
    black_model: str = ""
    black_url: str = _DEFAULT_LMSTUDIO_URL_2
    black_thinking: bool = False
    tutor_backend: str = "lmstudio"
    tutor_model: str = ""
    tutor_url: str = _DEFAULT_LMSTUDIO_URL
    # Reasoning coherence judge (defaults to same as tutor when model is "")
    judge_backend: str = "lmstudio"
    judge_model: str = ""
    judge_url: str = _DEFAULT_LMSTUDIO_URL
    games: int = Field(default=10, ge=1, le=1000)
    # Time control: seconds per move, 0 = no limit
    move_timeout: int = Field(default=0, ge=0, le=3600)
    # Human-play settings
    human_assisted: bool = True    # True = show Stockfish candidates; False = blind
    # Personality styles for 2-player mode
    white_style: Literal["", "aggressive", "positional", "defensive"] = ""
    black_style: Literal["", "aggressive", "positional", "defensive"] = ""
    # Opening blind mode: withhold Stockfish candidates for first N full moves
    white_blind_opening_moves: int = Field(default=0, ge=0, le=40)
    black_blind_opening_moves: int = Field(default=0, ge=0, le=40)
    # Turn cap: declare draw after this many half-moves (plies); 0 = no limit
    max_moves: int = Field(default=0, ge=0, le=1000)
    # Multi-player tournament fields (len >= 2 activates bracket mode)
    players: list[PlayerSpec] = []
    format: Literal["match", "round_robin", "gauntlet"] = "round_robin"
    games_per_pair: int = Field(default=2, ge=1, le=100)
    # Adaptive difficulty: auto-adjust candidate_count based on rolling win rate
    adaptive_difficulty: bool = False
