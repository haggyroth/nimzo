"""
ELO calculation and post-game adaptive learning.
Generates lessons for both players via a configurable tutor model.
Tutor can be any LM Studio / Ollama (OpenAI-compatible) endpoint or Anthropic cloud.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


# ── ELO ─────────────────────────────────────────────────────────────────

def dynamic_k_factor(games_played: int) -> float:
    """K decays as a player accumulates experience."""
    if games_played < 20:
        return 32.0
    elif games_played < 40:
        return 24.0
    else:
        return 16.0


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def new_elo(
    player_elo: float,
    opponent_elo: float,
    score: float,           # 1.0 win / 0.5 draw / 0.0 loss
    games_played: int = 0,
) -> float:
    k = dynamic_k_factor(games_played)
    expected = expected_score(player_elo, opponent_elo)
    return round(player_elo + k * (score - expected), 2)


def calculate_elos(
    white_elo: float,
    black_elo: float,
    result: str,                # '1-0' | '0-1' | '1/2-1/2'
    white_games: int = 0,
    black_games: int = 0,
) -> tuple[float, float]:
    if result == "1-0":
        w_score, b_score = 1.0, 0.0
    elif result == "0-1":
        w_score, b_score = 0.0, 1.0
    else:
        w_score, b_score = 0.5, 0.5

    new_white = new_elo(white_elo, black_elo, w_score, white_games)
    new_black = new_elo(black_elo, white_elo, b_score, black_games)
    return new_white, new_black


# ── Opening detection ────────────────────────────────────────────────────

_OPENINGS_PATH = Path(__file__).parent / "openings.json"


@lru_cache(maxsize=1)
def _load_openings() -> dict:
    """Load ECO lookup table once; returns {} if file missing."""
    if not _OPENINGS_PATH.exists():
        return {}
    with open(_OPENINGS_PATH) as f:
        return json.load(f)


def detect_opening(pgn_string: str) -> tuple[str, str] | None:
    """
    Replay the game and return the deepest ECO match as (code, name).
    Returns None if no opening is recognised or openings.json is absent.
    """
    import chess
    import chess.pgn
    import io

    openings = _load_openings()
    if not openings:
        return None

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_string))
        if game is None:
            return None
        board = game.board()
        last_match: tuple[str, str] | None = None
        for move in game.mainline_moves():
            board.push(move)
            epd = board.epd()
            entry = openings.get(epd)
            if entry:
                last_match = (entry["eco"], entry["name"])
        return last_match
    except Exception:
        return None


# ── Tutor configuration ──────────────────────────────────────────────────

@dataclass
class TutorConfig:
    backend: str = "lmstudio"              # "lmstudio" | "anthropic"
    model_id: str = ""                     # e.g. "qwen3-30b" or "claude-haiku-4-5-20251001"
    base_url: str = "http://localhost:1234/v1"
    api_key: Optional[str] = None


# ── Lesson prompts ───────────────────────────────────────────────────────

_TUTOR_SYSTEM = (
    "You are a concise chess coach. Analyze completed games and give players "
    "targeted, specific feedback based on their actual moves — not generic advice."
)

_LESSON_TEMPLATE = """Game result: {result} ({termination})
Player: {player_name} ({player_color}) — {outcome}
{opening_line}
PGN:
{pgn}

Move quality summary for {player_name}:
{quality_summary}

Write feedback for {player_name} in EXACTLY this format (no preamble):

IMPROVE:
- <one specific mistake from this game — reference the move in algebraic notation>
- <second improvement if clearly supported by the game>

STRENGTH:
- <one specific thing {player_name} did well — reference the move>
- <second strength if clearly supported>

Be concrete. One line per bullet. Do not write more than two bullets per section."""


# ── Backend callers ───────────────────────────────────────────────────────

def _call_lmstudio(tutor: TutorConfig, prompt: str) -> str:
    import os
    from openai import OpenAI
    client = OpenAI(
        base_url=tutor.base_url,
        api_key=tutor.api_key or os.environ.get("LMSTUDIO_API_KEY", "lm-studio"),
    )
    resp = client.chat.completions.create(
        model=tutor.model_id,
        max_tokens=500,
        temperature=0.4,
        messages=[
            {"role": "system", "content": _TUTOR_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        extra_body={"enable_thinking": False},
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(tutor: TutorConfig, prompt: str) -> str:
    import os
    import anthropic
    client = anthropic.Anthropic(
        api_key=tutor.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    msg = client.messages.create(
        model=tutor.model_id or "claude-haiku-4-5-20251001",
        max_tokens=500,
        system=_TUTOR_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ── Lesson parser ─────────────────────────────────────────────────────────

def _parse_lessons(raw: str) -> dict[str, list[str]]:
    """Parse IMPROVE: and STRENGTH: sections from raw tutor output.

    Handles: <think>…</think> blocks, markdown bold (**IMPROVE:**),
    numbered bullets (1.), lettered bullets, and mixed capitalisation.
    """
    import re

    # Strip <think>…</think> reasoning blocks (Qwen3, DeepSeek-R1, etc.)
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()

    improve: list[str] = []
    strength: list[str] = []
    section = None

    for line in text.splitlines():
        stripped = line.strip()
        # Strip markdown bold/italic wrappers and trailing punctuation for section detection
        clean = re.sub(r"[*_`#]", "", stripped).strip().upper()

        if re.match(r"IMPROVE", clean):
            section = "improve"
        elif re.match(r"STRENGTH", clean):
            section = "strength"
        elif section:
            # Accept lines starting with -, *, •, numbers, or letters as bullets
            bullet = re.match(r"^[-*•]|^\d+[.)]\s|^[a-z][.)]\s", stripped, re.IGNORECASE)
            if bullet:
                text_part = re.sub(r"^[-*•\d.)(a-z]\s*", "", stripped, count=1, flags=re.IGNORECASE).strip()
                if text_part:
                    if section == "improve":
                        improve.append(text_part)
                    else:
                        strength.append(text_part)

    return {"improve": improve[:2], "strength": strength[:2]}


# ── Public API ────────────────────────────────────────────────────────────

def generate_lessons(
    pgn: str,
    player_name: str,
    player_color: str,      # "White" | "Black"
    result: str,
    termination: str,
    quality_summary: str,
    tutor: Optional[TutorConfig] = None,
    opening: Optional[tuple[str, str]] = None,   # (eco_code, name) or None
) -> dict[str, list[str]]:
    """
    Generate lessons for one player from a completed game.
    Returns {"improve": [...], "strength": [...]} — empty lists if no tutor configured.
    """
    if tutor is None or not tutor.model_id:
        return {"improve": [], "strength": []}

    if result == "1-0":
        outcome = "won" if player_color == "White" else "lost"
    elif result == "0-1":
        outcome = "lost" if player_color == "White" else "won"
    else:
        outcome = "drew"

    opening_line = (
        f"Opening: {opening[1]} ({opening[0]})\n"
        if opening else ""
    )

    prompt = _LESSON_TEMPLATE.format(
        result=result,
        termination=termination,
        player_name=player_name,
        player_color=player_color,
        outcome=outcome,
        opening_line=opening_line,
        pgn=pgn,
        quality_summary=quality_summary,
    )

    try:
        if tutor.backend == "anthropic":
            raw = _call_anthropic(tutor, prompt)
        else:
            raw = _call_lmstudio(tutor, prompt)
        result = _parse_lessons(raw)
        if not result["improve"] and not result["strength"]:
            print(f"  ⚠  Tutor returned no parseable lessons. Raw response:\n{raw[:600]}")
        return result
    except Exception as e:
        print(f"  ⚠  Lesson generation failed ({tutor.backend}/{tutor.model_id}): {e}")
        return {"improve": [], "strength": []}


def derive_personality_traits(profile: dict) -> list[dict]:
    """
    Turn a model profile dict (from db.get_model_profile) into a short list of
    descriptive traits, each {label, detail}. Pure heuristic — no LLM call.
    """
    if not profile:
        return []
    moves    = profile.get("moves")    or {}
    castling = profile.get("castling") or {}
    color    = profile.get("color")    or {}
    games    = profile.get("games")    or {}

    total_moves = moves.get("total_moves") or 0
    if total_moves < 10:
        return [{"label": "New face", "detail": "Not enough games yet to read a style."}]

    traits: list[dict] = []

    # Stockfish alignment — how often does this model pick candidate #1?
    top_rate = (moves.get("picked_top") or 0) / total_moves
    avg_rank = moves.get("avg_rank")
    if top_rate >= 0.80:
        traits.append({
            "label":  "Stockfish loyalist",
            "detail": f"picks the top candidate {top_rate * 100:.0f}% of moves",
        })
    elif top_rate <= 0.45:
        traits.append({
            "label":  "Free spirit",
            "detail": f"deviates from Stockfish's pick {(1 - top_rate) * 100:.0f}% of moves"
                      + (f" (avg rank {avg_rank})" if avg_rank else ""),
        })

    # Tactical aggression — capture rate
    cap_rate = (moves.get("captures") or 0) / total_moves
    if cap_rate >= 0.22:
        traits.append({
            "label":  "Trade-happy",
            "detail": f"captures on {cap_rate * 100:.0f}% of moves",
        })
    elif cap_rate <= 0.10 and total_moves >= 50:
        traits.append({
            "label":  "Positional",
            "detail": f"captures on only {cap_rate * 100:.0f}% of moves",
        })

    # Check rate — attacking style
    chk_rate = (moves.get("checks") or 0) / total_moves
    if chk_rate >= 0.12:
        traits.append({
            "label":  "Attacker",
            "detail": f"delivers check on {chk_rate * 100:.0f}% of moves",
        })

    # Castling profile
    games_castled = castling.get("games_castled") or 0
    total_games   = games.get("total_games") or 0
    if total_games and games_castled / total_games < 0.4:
        traits.append({
            "label":  "King in the open",
            "detail": f"castles in only {games_castled}/{total_games} games",
        })
    elif castling.get("queenside", 0) >= castling.get("kingside", 0) and games_castled >= 2:
        traits.append({
            "label":  "Queenside",
            "detail": f"prefers O-O-O ({castling['queenside']} of {games_castled})",
        })
    else:
        avg_cm = castling.get("avg_castle_move")
        if avg_cm and avg_cm <= 10 and games_castled >= 2:
            traits.append({
                "label":  "Fast castler",
                "detail": f"castles by move {avg_cm} on average",
            })

    # Colour bias
    w_games  = (color.get("white_wins") or 0) + (color.get("white_draws") or 0) + (color.get("white_losses") or 0)
    b_games  = (color.get("black_wins") or 0) + (color.get("black_draws") or 0) + (color.get("black_losses") or 0)
    if w_games >= 3 and b_games >= 3:
        w_score = (color.get("white_wins") or 0) + 0.5 * (color.get("white_draws") or 0)
        b_score = (color.get("black_wins") or 0) + 0.5 * (color.get("black_draws") or 0)
        w_rate = w_score / w_games
        b_rate = b_score / b_games
        if w_rate - b_rate >= 0.2:
            traits.append({
                "label":  "White-favoured",
                "detail": f"{w_rate * 100:.0f}% as White vs {b_rate * 100:.0f}% as Black",
            })
        elif b_rate - w_rate >= 0.2:
            traits.append({
                "label":  "Black-favoured",
                "detail": f"{b_rate * 100:.0f}% as Black vs {w_rate * 100:.0f}% as White",
            })

    # Blunder rate
    bl_rate = (moves.get("q_blunder") or 0) / total_moves
    if bl_rate >= 0.05:
        traits.append({
            "label":  "Streaky",
            "detail": f"blunders on {bl_rate * 100:.1f}% of moves",
        })
    elif bl_rate == 0 and total_moves >= 50:
        traits.append({
            "label":  "Blunder-free",
            "detail": f"no blunders across {total_moves} moves",
        })

    return traits[:5]   # cap at 5 traits for the card


def build_quality_summary(move_qualities: list[tuple[str, str]]) -> str:
    """Readable quality breakdown for one player's moves."""
    counts = Counter(q for _, q in move_qualities)
    lines = [f"{q}: {n}" for q, n in sorted(counts.items())]
    blunders = [m for m, q in move_qualities if q == "blunder"]
    mistakes = [m for m, q in move_qualities if q == "mistake"]
    bests    = [m for m, q in move_qualities if q == "best"]
    summary = "Move quality: " + ", ".join(lines)
    if blunders:
        summary += f"\nBlunders: {', '.join(blunders)}"
    if mistakes:
        summary += f"\nMistakes: {', '.join(mistakes)}"
    if bests:
        summary += f"\nBest moves (Stockfish top): {', '.join(bests[:6])}"
    return summary
