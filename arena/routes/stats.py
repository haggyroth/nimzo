"""
arena/routes/stats.py — /api/stats/*, /api/leaderboard, serve_viewer, stats_page, etc.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import db as database
from analysis import ACHIEVEMENT_CATALOGUE
from arena.state import _state

logger = logging.getLogger(__name__)

router = APIRouter()

# Viewer HTML is two levels up from routes/ (repo root)
_VIEWER_HTML = Path(__file__).parent.parent.parent / "viewer.html"
_STATS_HTML  = Path(__file__).parent.parent.parent / "stats.html"


@router.get("/", response_class=HTMLResponse)
async def serve_viewer():
    return _VIEWER_HTML.read_text()


@router.get("/watch/{game_id}", response_class=HTMLResponse)
async def watch_game(game_id: int):
    """Serve the viewer pre-seeded to a specific completed game in replay mode.

    The JS detects ``/watch/<game_id>`` in the URL path on load and
    automatically opens the replay modal for that game.
    """
    return _VIEWER_HTML.read_text()


@router.get("/stats", response_class=HTMLResponse)
async def stats_page():
    return _STATS_HTML.read_text()


@router.get("/api/status")
async def api_status():
    return _state


@router.get("/api/leaderboard")
async def api_leaderboard():
    return await asyncio.to_thread(database.get_leaderboard)


@router.get("/api/elo-history/{model_id:path}")
async def api_elo_history(model_id: str):
    return await asyncio.to_thread(database.get_elo_history, model_id)


@router.get("/api/stats/moves")
async def api_stats_moves():
    return await asyncio.to_thread(database.get_player_move_stats)


@router.get("/api/stats/colors")
async def api_stats_colors():
    return await asyncio.to_thread(database.get_color_stats)


@router.get("/api/stats/h2h")
async def api_stats_h2h():
    return await asyncio.to_thread(database.get_head_to_head)


@router.get("/api/achievements/catalogue")
async def api_achievement_catalogue():
    return ACHIEVEMENT_CATALOGUE
