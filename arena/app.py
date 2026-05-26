"""
arena/app.py — FastAPI app object, lifespan, startup utilities.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import db as database
from analysis import detect_opening_depth, evaluate_achievements
from models.portraits import generate_portrait
from arena.state import _PORTRAITS_DIR

logger = logging.getLogger(__name__)


def backfill_achievements() -> int:
    """One-time pass to evaluate achievements for games that predate the feature."""
    n_total = 0
    for g in database.games_for_backfill():
        moves = database.get_game_moves(g["id"])
        if not moves:
            continue
        score_history = [m.get("score_cp") for m in moves]
        # move_number is per-ply; odd = White, even = Black
        white_quals = [(m["move_san"], m["quality"]) for m in moves if m["move_number"] % 2 == 1]
        black_quals = [(m["move_san"], m["quality"]) for m in moves if m["move_number"] % 2 == 0]

        opening_deep = detect_opening_depth(g["pgn"]) if g.get("pgn") else None
        opening_ply  = opening_deep[2] if opening_deep else None

        for color, quals, elo_b, opp_b, model_id in [
            ("white", white_quals, g["white_elo_before"], g["black_elo_before"], g["white_model_id"]),
            ("black", black_quals, g["black_elo_before"], g["white_elo_before"], g["black_model_id"]),
        ]:
            codes = evaluate_achievements(
                color=color,
                result=g["result"],
                total_moves=g["total_moves"] or 0,
                move_qualities=quals,
                score_history_white=score_history,
                player_elo_before=elo_b or 1200.0,
                opp_elo_before=opp_b   or 1200.0,
                opening_ply=opening_ply,
            )
            if codes:
                database.record_achievements(model_id, g["id"], codes)
                n_total += len(codes)
    return n_total


async def _pregenerate_portraits():
    """
    Background task: generate portraits for any known player that doesn't
    have one yet.  Runs once at startup, fully non-blocking.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return
    players = database.get_all_players()
    missing = [p for p in players if not p.get("portrait_path") and not database.is_user_provided_portrait(p["model_id"])]
    if not missing:
        return
    logger.info("Pre-generating portraits for %d model(s)…", len(missing))
    loop = asyncio.get_running_loop()

    async def _gen_one(mid: str) -> None:
        path = await loop.run_in_executor(
            None, generate_portrait, mid, api_key, _PORTRAITS_DIR
        )
        if path:
            database.set_portrait_path(mid, path)
            logger.info("Portrait generated: %s", mid)

    await asyncio.gather(*[_gen_one(p["model_id"]) for p in missing])
    logger.info("Portrait pre-generation complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialise DB, backfill achievements, kick off background tasks."""
    import arena.state as _st

    database.init_db()
    if not database.has_any_achievements():
        n = backfill_achievements()
        if n:
            logger.info("Backfilled %d achievements from existing games.", n)
    # Pre-generate portraits for all known players in the background
    asyncio.create_task(_pregenerate_portraits())
    if _st._cli_config is not None:
        from arena.routes.tournament import _auto_start
        asyncio.create_task(_auto_start(_st._cli_config))
    yield


# ── FastAPI app ───────────────────────────────────────────────────────────

app = FastAPI(title="Nimzo", lifespan=lifespan)

app.mount("/portraits", StaticFiles(directory=str(_PORTRAITS_DIR)), name="portraits")

_STATIC_DIR = Path(__file__).parent.parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
