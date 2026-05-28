"""
arena/routes/puzzle.py — Puzzle gauntlet endpoints.

POST /api/puzzle/start           — start a new puzzle gauntlet
GET  /api/puzzle/results         — list recent gauntlets with per-player scores
GET  /api/puzzle/results/{id}    — per-puzzle detail for one gauntlet
GET  /api/puzzle/puzzles         — list puzzles in a given file
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

import db as database
import arena.state as _st
from arena.models import PuzzleGauntletConfig
from game import build_player, run_puzzle_gauntlet
from puzzle_loader import load_puzzles as _load_puzzles

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/puzzle/start")
async def api_puzzle_start(config: PuzzleGauntletConfig):
    """
    Start a puzzle gauntlet.

    Rejects if a tournament or gauntlet is already running.
    Requires at least one player in ``config.players``.
    """
    if _st._tournament_task and not _st._tournament_task.done():
        return {"error": "A tournament or gauntlet is already running"}

    if not config.players:
        raise HTTPException(status_code=422, detail="At least one player is required")

    # Validate the puzzle file exists and is well-formed before starting
    try:
        puzzles = _load_puzzles(config.puzzles_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    _st._stop["requested"] = False
    _st._pause_event.set()

    players = [
        build_player(
            ps.backend,
            ps.name or ps.model_id.split("/")[-1].split("@")[0],
            ps.model_id,
            ps.url,
            ps.thinking,
            candidate_count=config.candidate_count,
            move_timeout=config.move_timeout,
        )
        for ps in config.players
    ]

    _st._state.update({
        "status":       "puzzle",
        "gauntlet_id":  None,
        "puzzle_total": len(puzzles),
        "puzzle_index": 0,
    })
    await _st.broadcast({"type": "tournament_status", **_st._state})

    async def _run_and_catch():
        from engine import StockfishEngine
        try:
            with StockfishEngine() as sf:
                await run_puzzle_gauntlet(
                    players=players,
                    stockfish=sf,
                    puzzles_file=config.puzzles_file,
                    candidate_count=config.candidate_count,
                    move_timeout=config.move_timeout,
                )
        except Exception as exc:
            logger.info("Puzzle gauntlet ended: %s", type(exc).__name__)
        finally:
            _st._stop["requested"] = False
            _st._pause_event.set()
            _st._state.update({"status": "idle"})
            try:
                await _st.broadcast({"type": "tournament_status", **_st._state})
            except Exception:
                pass

    _st._tournament_task = asyncio.create_task(_run_and_catch())
    return {"ok": True}


@router.get("/api/puzzle/results")
async def api_puzzle_results(limit: int = 20):
    """List recent puzzle gauntlets with per-player aggregate scores."""
    return await asyncio.to_thread(database.get_puzzle_gauntlets, limit)


@router.get("/api/puzzle/results/{gauntlet_id}")
async def api_puzzle_detail(gauntlet_id: int):
    """Per-puzzle per-player breakdown for a single gauntlet."""
    rows = await asyncio.to_thread(database.get_puzzle_gauntlet_results, gauntlet_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Gauntlet not found or has no results")
    return rows


@router.get("/api/puzzle/puzzles")
async def api_list_puzzles(file: str = "positions.toml"):
    """Return the list of puzzle descriptions in a given file (for the UI preview)."""
    try:
        puzzles = await asyncio.to_thread(_load_puzzles, file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Strip FENs for the preview — no need to send full FENs for listing
    return [
        {"index": i, "description": p["description"], "fen": p["fen"], "solution_uci": p["solution_uci"]}
        for i, p in enumerate(puzzles)
    ]
