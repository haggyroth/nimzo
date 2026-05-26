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

# K-factor schedule: high for new players, decays with experience.
# Lower K = more rating stability; raise K_INITIAL for faster early calibration.
K_INITIAL      = 32.0   # games < K_THRESH_PROVISIONAL
K_MID          = 24.0   # games < K_THRESH_ESTABLISHED
K_STABLE       = 16.0   # games ≥ K_THRESH_ESTABLISHED
K_THRESH_PROVISIONAL  = 20
K_THRESH_ESTABLISHED  = 40


def dynamic_k_factor(games_played: int) -> float:
    """K decays as a player accumulates experience."""
    if games_played < K_THRESH_PROVISIONAL:
        return K_INITIAL
    elif games_played < K_THRESH_ESTABLISHED:
        return K_MID
    else:
        return K_STABLE


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def new_elo(
    player_elo: float,
    opponent_elo: float,
    score: float,           # 1.0 win / 0.5 draw / 0.0 loss
    games_played: int = 0,
) -> float:
    """Return the updated ELO for a player after a single game result."""
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
    """Return (new_white_elo, new_black_elo) after a game with the given result."""
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
    deep = detect_opening_depth(pgn_string)
    if deep is None:
        return None
    eco, name, _ = deep
    return (eco, name)


def detect_opening_depth(pgn_string: str) -> tuple[str, str, int] | None:
    """
    Like detect_opening but also returns the ply count at which theory was
    last matched. Useful for awarding 'Theorist' achievements.
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
        last_match: tuple[str, str, int] | None = None
        for ply, move in enumerate(game.mainline_moves(), start=1):
            board.push(move)
            epd = board.epd()
            entry = openings.get(epd)
            if entry:
                last_match = (entry["eco"], entry["name"], ply)
        return last_match
    except Exception:
        return None


# ── Tutor / Judge configuration ──────────────────────────────────────────

@dataclass
class TutorConfig:
    """Connection config for the tutor model that generates post-game lessons."""

    backend: str = "lmstudio"              # "lmstudio" | "anthropic"
    model_id: str = ""                     # e.g. "qwen3-30b" or "claude-haiku-4-5-20251001"
    base_url: str = "http://localhost:1234/v1"
    api_key: Optional[str] = None


# JudgeConfig is structurally identical to TutorConfig; a separate type makes
# call-sites self-documenting and lets the two be configured independently.
@dataclass
class JudgeConfig:
    """Connection config for the judge model that scores reasoning coherence."""

    backend: str = "lmstudio"
    model_id: str = ""
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

# Lighter prompt for draws — still useful signal but lower stakes
_DRAW_LESSON_TEMPLATE = """Game result: Draw ({termination})
Player: {player_name} ({player_color})
{opening_line}
Move quality summary:
{quality_summary}

Write ONE coaching note for {player_name} in EXACTLY this format (no preamble):

IMPROVE:
- <the single most important moment to improve — reference the move>

STRENGTH:
- <one thing done well>

One bullet each. Be specific."""

# Compression prompt — consolidates many raw lessons into a strategic profile
_COMPRESSION_TEMPLATE = """You are reviewing {player_name}'s coaching history across {game_count} chess games.

All lessons recorded so far:

AREAS TO IMPROVE:
{improve_lessons}

CONSISTENT STRENGTHS:
{strength_lessons}

Distill these into a concise strategic profile. Remove duplicates and contradictions. \
Identify the 2–4 most persistent weaknesses and 1–3 most reliable strengths.

Write in EXACTLY this format (no preamble):

WEAKNESSES:
- <core persistent weakness #1>
- <core persistent weakness #2>
(up to 4 — only include if clearly recurring)

STRENGTHS:
- <core consistent strength #1>
(up to 3 — only include if clearly recurring)

Each bullet must be a concrete, actionable chess principle, not vague praise. \
Do not include one-off observations that appeared in only one game."""


# ── Reasoning coherence scoring ──────────────────────────────────────────

_JUDGE_SYSTEM = (
    "You are a chess move-reasoning evaluator. "
    "Judge whether a player's stated reasoning genuinely justifies their chosen move. "
    "Respond with a single integer from 0 to 10 and nothing else."
)

_JUDGE_TEMPLATE = """Position (FEN): {fen}

Stockfish candidates (ranked best to worst for the player):
{candidates}

Chosen move: {san}

Player's reasoning:
{reasoning}

Score the reasoning from 0–10 based on how well it justifies choosing {san}:
  10 — reasoning directly and accurately explains why {san} is the best choice
   7 — reasoning is correct in spirit but missing key tactical detail
   4 — reasoning is partially relevant but contains clear factual errors
   1 — reasoning is generic, irrelevant, or contradicts the move chosen
   0 — reasoning explicitly claims to play a different move

Reply with a single integer (0–10) and nothing else."""


def score_reasoning_coherence(
    reasoning: str,
    move_san: str,
    board_fen: str,
    candidates: list[tuple],        # list of (move, score_cp) chess objects
    judge: "JudgeConfig",
) -> Optional[float]:
    """
    Ask a judge model whether the player's reasoning justifies their chosen
    move.  Returns a float 0.0–10.0, or None if the judge is unavailable /
    the player had no reasoning (human / API-error fallback).
    """
    import re

    # Skip scoring for human moves and fallback moves
    if not reasoning or reasoning.startswith("("):
        return None
    if not judge or not judge.model_id:
        return None

    # Format candidates as text
    import chess as _chess
    cand_lines = []
    for i, (mv, cp) in enumerate(candidates[:5], 1):
        san = _chess.Board(board_fen).san(mv) if hasattr(mv, "uci") else str(mv)
        score_str = f"{cp / 100:+.2f}" if cp is not None else "?"
        cand_lines.append(f"  {i}. {san} (eval: {score_str})")
    candidates_text = "\n".join(cand_lines) if cand_lines else "  (none)"

    prompt = _JUDGE_TEMPLATE.format(
        fen=board_fen,
        candidates=candidates_text,
        san=move_san,
        reasoning=reasoning.strip(),
    )

    try:
        # Thinking-capable models need more tokens to emit the think block before
        # producing the final integer; 600 is safe for all backends.
        raw = _call_tutor_like(judge, prompt, system=_JUDGE_SYSTEM, max_tokens=600)
        # Strip think blocks, then extract first integer 0–10
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
        m = re.search(r"\b(10|[0-9])\b", raw)
        if m:
            return float(m.group(1))
    except Exception as exc:
        print(f"  ⚠  Judge call failed ({type(exc).__name__}): {exc}")
    return None


def _call_tutor_like(
    cfg: "TutorConfig | JudgeConfig",
    prompt: str,
    system: str,
    max_tokens: int = 500,
) -> str:
    """Generic caller that works for both TutorConfig and JudgeConfig."""
    import os
    if cfg.backend == "anthropic":
        import anthropic
        client = anthropic.Anthropic(
            api_key=cfg.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        msg = client.messages.create(
            model=cfg.model_id or "claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    else:
        from openai import OpenAI
        client = OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key or os.environ.get("LMSTUDIO_API_KEY", "lm-studio"),
        )
        resp = client.chat.completions.create(
            model=cfg.model_id,
            max_tokens=max_tokens,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            extra_body={"enable_thinking": False},
        )
        return resp.choices[0].message.content or ""


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
    is_draw: bool = False,
    skip_if_clean_draw: bool = True,
) -> dict[str, list[str]]:
    """
    Generate lessons for one player from a completed game.

    Draws use a shorter single-bullet prompt. A draw with no blunders or
    mistakes produces very weak coaching signal — ``skip_if_clean_draw=True``
    (the default) returns empty lists rather than generating noise.

    Returns {"improve": [...], "strength": [...]} — empty lists if no tutor
    configured or if the game is a clean draw.
    """
    if tutor is None or not tutor.model_id:
        return {"improve": [], "strength": []}

    # Skip lesson generation for draws with clean play — no useful signal
    if is_draw and skip_if_clean_draw:
        if "blunder" not in quality_summary and "mistake" not in quality_summary:
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

    # Draws with some mistakes get a lighter prompt; decisive games get the full one
    template = _DRAW_LESSON_TEMPLATE if is_draw else _LESSON_TEMPLATE
    prompt = template.format(
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
        raw = _call_tutor_like(tutor, prompt, system=_TUTOR_SYSTEM)
        lessons = _parse_lessons(raw)
        if not lessons["improve"] and not lessons["strength"]:
            print(f"  ⚠  Tutor returned no parseable lessons. Raw response:\n{raw[:600]}")
        return lessons
    except Exception as e:
        print(f"  ⚠  Lesson generation failed ({tutor.backend}/{tutor.model_id}): {e}")
        return {"improve": [], "strength": []}


def compress_lessons(
    all_lessons: list[dict],   # [{"lesson": str, "lesson_type": "improve"|"strength"}, ...]
    player_name: str,
    game_count: int,
    tutor: Optional[TutorConfig] = None,
) -> Optional[str]:
    """
    Ask the tutor to distil all recorded lessons into a strategic profile.

    Returns the raw profile text on success, None if no tutor or the call fails.
    The profile is stored in the DB and injected into the player's system prompt
    instead of the raw lesson list, preventing context bloat.
    """
    if tutor is None or not tutor.model_id:
        return None
    if not all_lessons:
        return None

    improve = [l["lesson"] for l in all_lessons if l.get("lesson_type") == "improve"]
    strength = [l["lesson"] for l in all_lessons if l.get("lesson_type") == "strength"]

    if not improve and not strength:
        return None

    improve_text  = "\n".join(f"- {l}" for l in improve)  or "(none recorded)"
    strength_text = "\n".join(f"- {l}" for l in strength) or "(none recorded)"

    prompt = _COMPRESSION_TEMPLATE.format(
        player_name=player_name,
        game_count=game_count,
        improve_lessons=improve_text,
        strength_lessons=strength_text,
    )

    try:
        raw = _call_tutor_like(tutor, prompt, system=_TUTOR_SYSTEM)
        raw = raw.strip()
        if raw:
            print(f"  🗜  Compressed {len(all_lessons)} lessons → strategic profile for {player_name}")
        return raw or None
    except Exception as e:
        print(f"  ⚠  Lesson compression failed ({tutor.backend}/{tutor.model_id}): {e}")
        return None


ACHIEVEMENT_CATALOGUE: dict[str, dict] = {
    "flawless":     {"label": "Flawless",     "desc": "Played a game with no blunders or mistakes."},
    "comeback":     {"label": "Comeback",     "desc": "Won from a position 3+ pawns behind."},
    "crusher":      {"label": "Crusher",      "desc": "Won the game in 25 moves or fewer."},
    "grinder":      {"label": "Grinder",      "desc": "Won a game that lasted 70+ moves."},
    "tactician":    {"label": "Tactician",    "desc": "Played 5+ best moves in a row."},
    "iron_wall":    {"label": "Iron Wall",    "desc": "Held a draw against an opponent rated 100+ ELO above."},
    "giant_killer": {"label": "Giant Killer", "desc": "Beat an opponent rated 100+ ELO above."},
    "theorist":     {"label": "Theorist",     "desc": "Stayed in opening theory for 12+ ply."},
}


def evaluate_achievements(
    *,
    color: str,                                  # 'white' | 'black'
    result: str,                                 # '1-0' | '0-1' | '1/2-1/2'
    total_moves: int,
    move_qualities: list[tuple[str, str]],       # (san, quality)
    score_history_white: list[float | None],     # per-move score_cp from White's POV
    player_elo_before: float,
    opp_elo_before: float,
    opening_ply: int | None = None,
) -> list[str]:
    """
    Returns a list of achievement codes earned by `color` in this game.
    All inputs are derived from data already collected during the game.
    """
    earned: list[str] = []

    won  = (color == "white" and result == "1-0") or (color == "black" and result == "0-1")
    drew = result == "1/2-1/2"

    # Flawless — no blunders or mistakes anywhere in the player's moves
    qualities = [q for _, q in move_qualities]
    has_blunder = any(q in ("blunder", "mistake") for q in qualities)
    if qualities and not has_blunder:
        earned.append("flawless")

    # Tactician — 5 best moves in a row
    streak = best_streak = 0
    for q in qualities:
        if q == "best":
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    if best_streak >= 5:
        earned.append("tactician")

    # Crusher / Grinder — only on wins
    if won and total_moves <= 25:
        earned.append("crusher")
    if won and total_moves >= 70:
        earned.append("grinder")

    # Comeback — player was ≤ -300cp from their POV at some point, then won
    if won and score_history_white:
        # Convert White-POV scores to this player's POV
        sign = 1 if color == "white" else -1
        worst = min(
            (sign * cp for cp in score_history_white if cp is not None),
            default=None,
        )
        if worst is not None and worst <= -300:
            earned.append("comeback")

    # Upset achievements vs higher-rated opponent
    elo_diff = opp_elo_before - player_elo_before
    if elo_diff >= 100:
        if won:
            earned.append("giant_killer")
        elif drew:
            earned.append("iron_wall")

    # Theorist — opening theory matched for 12+ ply
    if opening_ply and opening_ply >= 12:
        earned.append("theorist")

    return earned


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


def bad_move_rate(move_qualities: list[tuple[str, str]]) -> float | None:
    """
    Fraction of moves that are blunders or mistakes.
    Returns None if no moves.  Used to track lesson effectiveness over time.
    """
    if not move_qualities:
        return None
    bad = sum(1 for _, q in move_qualities if q in ("blunder", "mistake"))
    return round(bad / len(move_qualities), 4)


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
