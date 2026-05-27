"""
arena/routes/games.py — /api/games/* routes and _build_game_pgn helper.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

import db as database

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_game_pgn(game_row: dict, moves: list[dict], round_number: Optional[int] = None) -> str:
    """
    Build an annotated PGN string for a single game.

    Includes quality glyphs (??, ?, !?, !, !!) and {comment} blocks with the
    model's reasoning, move quality label, and candidate rank.  Used by both
    the single-game download endpoint and the bulk export endpoint.
    """
    _QUALITY_GLYPH = {
        "best":       "!!",
        "excellent":  "!",
        "inaccuracy": "?!",
        "mistake":    "?",
        "blunder":    "??",
    }
    tags = [
        '[Event "Nimzo Arena"]',
        '[Site "localhost"]',
        f'[Date "{game_row["played_at"][:10]}"]',
    ]
    if round_number is not None:
        tags.append(f'[Round "{round_number}"]')
    tags += [
        f'[White "{game_row["white_name"]}"]',
        f'[Black "{game_row["black_name"]}"]',
        f'[Result "{game_row["result"]}"]',
        f'[WhiteElo "{round(game_row["white_elo_before"])}"]',
        f'[BlackElo "{round(game_row["black_elo_before"])}"]',
        "",
    ]

    tokens: list[str] = []
    for m in moves:
        num   = m["move_number"]
        san   = m["move_san"]
        glyph = _QUALITY_GLYPH.get(m["quality"] or "", "")
        reason = (m["reasoning"] or "").strip().replace("{", "(").replace("}", ")")
        rank  = m["candidate_rank"]

        if num % 2 == 1:
            tokens.append(f"{(num + 1) // 2}.")

        tokens.append(san + glyph)

        comment_parts = []
        if reason and not reason.startswith("("):
            comment_parts.append(reason)
        if m["quality"] and m["quality"] != "good":
            comment_parts.append(m["quality"].capitalize())
        if rank:
            comment_parts.append(f"candidate #{rank}")
        if comment_parts:
            comment_content = " | ".join(comment_parts)
            # Wrap long comments internally so no line exceeds 80 chars
            comment_lines: list[str] = []
            cur = "{"
            for word in comment_content.split():
                candidate = (cur + " " + word) if cur != "{" else ("{ " + word)
                if len(candidate) <= 78:
                    cur = candidate
                else:
                    comment_lines.append(cur)
                    cur = "  " + word
            comment_lines.append(cur + " }")
            tokens.append("\n".join(comment_lines))

    tokens.append(game_row["result"])

    # Word-wrap at ~80 chars (tokens that are already multi-line are kept intact)
    body = ""
    line = ""
    for tok in tokens:
        if "\n" in tok:
            # Multi-line comment: flush current line, then emit comment as-is
            if line:
                body += line + "\n"
            body += tok + "\n"
            line = ""
        elif line and len(line) + 1 + len(tok) > 78:
            body += line + "\n"
            line = tok
        else:
            line = (line + " " + tok).lstrip()
    if line:
        body += line + "\n"

    return "\n".join(tags) + body


@router.get("/api/games/export")
async def api_games_export(model_id: Optional[str] = None, limit: int = 5000):
    """
    Bulk PGN export — all games as a single annotated PGN file.

    Query params:
      model_id — restrict to games where this model played (optional)
      limit    — max games to export (default 5 000)
    """
    rows = database.get_all_games(model_id=model_id, limit=limit)
    if not rows:
        return PlainTextResponse("# No games found\n", status_code=200)

    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        moves = database.get_game_moves(row["id"])
        parts.append(_build_game_pgn(row, moves, round_number=i))

    raw_name = "nimzo_export.pgn" if not model_id else f"nimzo_{model_id}_export.pgn"
    safe_name = quote(raw_name.replace(" ", "_"), safe="_-.")
    return PlainTextResponse(
        "\n".join(parts),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.get("/api/games")
async def api_games(limit: int = 20):
    return database.get_recent_games(limit)


# ── Per-game routes — parametric paths MUST come after static-prefix routes ──
# (FastAPI matches in registration order; "export" above would 422 if these
# were registered first — see REVIEW.md C-3.)

@router.get("/api/games/{game_id}")
async def api_game(game_id: int):
    """Return the game record for ``game_id``, or 404 if not found."""
    row = database.get_game(game_id)
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
    return row


@router.get("/api/games/{game_id}/moves")
async def api_game_moves(game_id: int):
    return database.get_game_moves(game_id)


@router.get("/api/games/{game_id}/pgn")
async def api_game_pgn(game_id: int):
    """Download a single game as an annotated PGN file."""
    game_row = database.get_game(game_id)
    if not game_row:
        return PlainTextResponse("Game not found", status_code=404)
    moves = database.get_game_moves(game_id)
    pgn = _build_game_pgn(game_row, moves)
    raw_name = (
        f"nimzo_{game_row['white_name']}_vs_{game_row['black_name']}_{game_id}.pgn"
        .replace(" ", "_")
    )
    safe_name = quote(raw_name, safe="_-.")
    return PlainTextResponse(
        pgn,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )
