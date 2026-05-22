"""
ELO calculation and post-game adaptive learning.
Generates lessons for the losing (or struggling) player via LLM analysis.
"""

import math
import chess
import chess.pgn
import anthropic
import os
from io import StringIO


# --- ELO ---------------------------------------------------------------

K_FACTOR = 32  # Standard K for developing players; tune down as games accumulate


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def new_elo(
    player_elo: float,
    opponent_elo: float,
    score: float,  # 1.0 = win, 0.5 = draw, 0.0 = loss
) -> float:
    expected = expected_score(player_elo, opponent_elo)
    return round(player_elo + K_FACTOR * (score - expected), 2)


def calculate_elos(
    white_elo: float,
    black_elo: float,
    result: str,  # '1-0' | '0-1' | '1/2-1/2'
) -> tuple[float, float]:
    if result == "1-0":
        w_score, b_score = 1.0, 0.0
    elif result == "0-1":
        w_score, b_score = 0.0, 1.0
    else:
        w_score, b_score = 0.5, 0.5

    new_white = new_elo(white_elo, black_elo, w_score)
    new_black = new_elo(black_elo, white_elo, b_score)
    return new_white, new_black


# --- Post-game lesson generation ----------------------------------------

LESSON_PROMPT = """You are a chess coach analyzing a completed game.

The losing player was: {loser_color} ({loser_name})
Game result: {result}
Termination: {termination}

Full PGN with reasoning annotations:
{annotated_pgn}

Move quality summary for {loser_name}:
{quality_summary}

Write 2-3 concise, actionable lessons for {loser_name} to improve.
Each lesson should identify a SPECIFIC pattern or mistake from THIS game.
Format: one lesson per line, starting with a dash.
Example:
- Neglected king safety after move 18; avoid leaving the king on e1 after the center opens.
- Allowed a knight outpost on d5 by not playing c5 on move 12.

Do not add any preamble. Output only the lesson lines."""


def generate_lessons(
    pgn: str,
    loser_name: str,
    loser_color: str,
    result: str,
    termination: str,
    quality_summary: str,
    model: str = "claude-haiku-4-5-20251001",
) -> list[str]:
    """
    Use Claude Haiku to generate improvement lessons from a completed game.
    Uses Haiku to keep costs low — this runs after every game.
    Returns empty list if ANTHROPIC_API_KEY is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return []
    client = anthropic.Anthropic(api_key=api_key)

    prompt = LESSON_PROMPT.format(
        loser_color=loser_color,
        loser_name=loser_name,
        result=result,
        termination=termination,
        annotated_pgn=pgn,
        quality_summary=quality_summary,
    )

    message = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    lessons = [
        line.lstrip("- ").strip()
        for line in raw.strip().splitlines()
        if line.strip().startswith("-")
    ]
    return lessons[:3]  # cap at 3


def build_quality_summary(move_qualities: list[tuple[str, str]]) -> str:
    """
    move_qualities: list of (move_san, quality) for one player.
    Returns a readable summary string.
    """
    from collections import Counter
    counts = Counter(q for _, q in move_qualities)
    lines = [f"{q}: {n}" for q, n in sorted(counts.items())]
    blunders = [m for m, q in move_qualities if q == "blunder"]
    mistakes = [m for m, q in move_qualities if q == "mistake"]
    summary = "Move quality: " + ", ".join(lines)
    if blunders:
        summary += f"\nBlunders: {', '.join(blunders)}"
    if mistakes:
        summary += f"\nMistakes: {', '.join(mistakes)}"
    return summary
