"""
arena/routes/ladder.py — ELO auto-scheduler (ladder) routes.

POST /api/ladder/start   — start a continuous round-robin ladder
GET  /api/ladder/status  — current ladder state snapshot
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

import arena.state as _st
from analysis import TutorConfig, JudgeConfig
from arena.models import LadderConfig
from game import build_player, run_ladder

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/ladder/start")
async def api_ladder_start(config: LadderConfig):
    """
    Start a continuous round-robin ELO ladder.

    Rejects if a tournament or ladder is already running.  Builds all player
    objects, then fires ``run_ladder`` as a background task.

    Returns ``{"ok": True}`` on success, ``{"error": "…"}`` if busy.
    """
    if _st._tournament_task and not _st._tournament_task.done():
        return {"error": "A tournament or ladder is already running"}

    if len(config.players) < 2:
        raise HTTPException(status_code=400, detail="A ladder requires at least 2 players")

    _st._stop["requested"] = False
    _st._pause_event.set()

    players = [
        build_player(
            ps.backend,
            ps.name or ps.model_id.split("/")[-1].split("@")[0],
            ps.model_id,
            ps.url,
            ps.thinking,
            candidate_count=ps.candidate_count,
            temperature=ps.temperature,
            move_timeout=config.move_timeout,
            style=ps.style,
            blind_opening_moves=ps.blind_opening_moves,
            blind=ps.blind,
        )
        for ps in config.players
    ]

    tutor = TutorConfig(
        backend=config.tutor_backend,
        model_id=config.tutor_model,
        base_url=config.tutor_url,
    )
    _jm = config.judge_model or config.tutor_model
    judge = JudgeConfig(
        backend=config.judge_backend or config.tutor_backend,
        model_id=_jm,
        base_url=config.judge_url or config.tutor_url,
    ) if _jm else None

    _st._state.update({
        "status":      "running",
        "game_number": 0,
        "total_games": 0,
        "format":      "ladder",
        "standings":   None,
        "white":       None,
        "black":       None,
        "white_elo":   None,
        "black_elo":   None,
    })
    await _st.broadcast({"type": "tournament_status", **_st._state})

    async def _run():
        try:
            await run_ladder(
                players=players,
                tutor=tutor,
                judge=judge,
                games_per_pair=config.games_per_pair,
                adaptive_difficulty=config.adaptive_difficulty,
                max_moves=config.max_moves,
            )
        except Exception as exc:
            logger.warning("Ladder ended: %s: %s", type(exc).__name__, exc)
        finally:
            _st._stop["requested"] = False
            _st._pause_event.set()
            _st._state["status"] = "idle"
            try:
                await _st.broadcast({"type": "tournament_status", **_st._state})
            except Exception:
                pass

    _st._tournament_task = asyncio.create_task(_run())
    return {"ok": True}


@router.get("/api/ladder/status")
async def api_ladder_status():
    """Snapshot of the current ladder/tournament state."""
    return {
        "status":      _st._state.get("status"),
        "game_number": _st._state.get("game_number"),
        "format":      _st._state.get("format"),
        "white":       _st._state.get("white"),
        "black":       _st._state.get("black"),
        "white_elo":   _st._state.get("white_elo"),
        "black_elo":   _st._state.get("black_elo"),
    }
