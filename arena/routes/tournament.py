"""
arena/routes/tournament.py — WebSocket endpoint, tournament control routes, human-move.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

import db as database
import arena.state as _st
from analysis import TutorConfig, JudgeConfig
from arena.models import HumanMoveRequest, TournamentStartConfig
from models.human_player import HumanPlayer

# game.py is safe to import here: by the time this module is imported from
# arena/__init__.py, all state symbols are already on the arena package object.
from game import (
    run_bracket_tournament,
    run_tournament,
    build_player,
    generate_pairings,
    compute_standings,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── WebSocket ─────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for live game events.

    Accepts same-origin connections only (rejects foreign ``Origin`` headers).
    Immediately pushes the current ``_state`` snapshot on connect so
    late-joining viewers are in sync without waiting for the next broadcast.
    """
    origin = websocket.headers.get("origin")
    if origin is not None:
        from urllib.parse import urlparse
        host = urlparse(origin).hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1"):
            await websocket.close(code=1008, reason="Cross-origin WebSocket not allowed")
            return
    await websocket.accept()
    _st._connected_clients.add(websocket)
    # Immediately push current state so late-joiners are in sync
    await websocket.send_text(json.dumps({"type": "state", **_st._state}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _st._connected_clients.discard(websocket)


# ── Tournament control ────────────────────────────────────────────────────

@router.post("/api/tournament/start")
async def api_start(config: TournamentStartConfig):
    """
    Start a new tournament or match.

    Rejects the request if a tournament is already running.  Dispatches to
    ``run_bracket_tournament`` for multi-player configs (``players`` len >= 2)
    or ``run_tournament`` for 2-player matches.
    """
    if _st._tournament_task and not _st._tournament_task.done():
        return {"error": "A tournament is already running"}

    _st._stop_requested = False
    _st._pause_event.set()

    tutor = TutorConfig(backend=config.tutor_backend, model_id=config.tutor_model, base_url=config.tutor_url)
    # Judge config: fall back to tutor settings when judge_model is blank
    _jm = config.judge_model or config.tutor_model
    judge = JudgeConfig(
        backend=config.judge_backend or config.tutor_backend,
        model_id=_jm,
        base_url=config.judge_url or config.tutor_url,
    ) if _jm else None

    # ── Multi-player tournament mode ──────────────────────────────────
    if len(config.players) >= 2:
        # Seed by current ELO (highest first).
        seeded = sorted(
            config.players,
            key=lambda ps: database.get_player_elo(ps.model_id),
            reverse=True,
        )

        players = [
            build_player(ps.backend, ps.name or ps.model_id.split("/")[-1].split("@")[0],
                         ps.model_id, ps.url, ps.thinking, move_timeout=config.move_timeout,
                         style=ps.style, blind_opening_moves=ps.blind_opening_moves)
            for ps in seeded
        ]
        pairings = generate_pairings(seeded, config.format, config.games_per_pair)
        total_games = len(pairings)
        standings = compute_standings(seeded, [])

        _st._state.update({
            "status":        "running",
            "game_number":   0,
            "total_games":   total_games,
            "white":         None,
            "black":         None,
            "white_elo":     None,
            "black_elo":     None,
            "format":        config.format,
            "standings":     standings,
            "tournament_id": None,
        })
        await _st.broadcast({"type": "tournament_status", **_st._state})

        player_map = {ps.model_id: pl for ps, pl in zip(seeded, players)}

        async def _run_bracket_and_catch():
            try:
                await run_bracket_tournament(
                    player_specs=seeded,
                    player_map=player_map,
                    pairings=pairings,
                    fmt=config.format,
                    tutor=tutor,
                    judge=judge,
                    adaptive_difficulty=config.adaptive_difficulty,
                    max_moves=config.max_moves,
                )
            except Exception as exc:
                logger.info("Tournament ended: %s", type(exc).__name__)
            finally:
                _st._stop_requested = False
                _st._pause_event.set()
                _st._state["status"] = "idle"
                try:
                    await _st.broadcast({"type": "tournament_status", **_st._state})
                except Exception:
                    pass

        _st._tournament_task = asyncio.create_task(_run_bracket_and_catch())
        return {"ok": True}

    # ── Classic 2-player match mode ───────────────────────────────────
    white = build_player(config.white_backend, config.white_name, config.white_model, config.white_url, config.white_thinking, move_timeout=config.move_timeout, style=config.white_style, blind_opening_moves=config.white_blind_opening_moves)
    black = build_player(config.black_backend, config.black_name, config.black_model, config.black_url, config.black_thinking, move_timeout=config.move_timeout, style=config.black_style, blind_opening_moves=config.black_blind_opening_moves)

    # Register any human players so /api/human-move can reach them.
    _st._active_human_players.clear()
    if isinstance(white, HumanPlayer):
        _st._active_human_players["white"] = white
    if isinstance(black, HumanPlayer):
        _st._active_human_players["black"] = black

    _st._state.update({
        "status":          "running",
        "game_number":     0,
        "total_games":     config.games,
        "white":           config.white_name,
        "black":           config.black_name,
        "white_elo":       round(white.elo),
        "black_elo":       round(black.elo),
        "white_is_human":  isinstance(white, HumanPlayer),
        "black_is_human":  isinstance(black, HumanPlayer),
        "human_assisted":  config.human_assisted,
        "format":          "match",
        "standings":       None,
        "tournament_id":   None,
    })
    await _st.broadcast({"type": "tournament_status", **_st._state})

    async def _run_and_catch():
        try:
            await run_tournament(white, black, config.games, tutor, judge, adaptive_difficulty=config.adaptive_difficulty, max_moves=config.max_moves)
        except Exception as exc:
            logger.info("Tournament ended: %s", type(exc).__name__)
        finally:
            _st._stop_requested = False
            _st._pause_event.set()
            _st._active_human_players.clear()
            _st._state.update({"status": "idle", "white_is_human": False, "black_is_human": False})
            try:
                await _st.broadcast({"type": "tournament_status", **_st._state})
            except Exception:
                pass

    _st._tournament_task = asyncio.create_task(_run_and_catch())
    return {"ok": True}


@router.get("/api/tournament/history")
async def api_tournament_history(limit: int = 20):
    return database.get_tournament_history(limit)


@router.post("/api/tournament/pause")
async def api_pause():
    """Pause the running tournament after the current move completes."""
    _st._pause_event.clear()
    _st._state["status"] = "paused"
    await _st.broadcast({"type": "tournament_status", **_st._state})
    return {"ok": True}


@router.post("/api/tournament/resume")
async def api_resume():
    """Resume a paused tournament."""
    _st._pause_event.set()
    _st._state["status"] = "running"
    await _st.broadcast({"type": "tournament_status", **_st._state})
    return {"ok": True}


@router.post("/api/tournament/stop")
async def api_stop():
    """Request a graceful stop; the tournament finishes the current game then halts."""
    _st._stop_requested = True
    _st._pause_event.set()   # unblock if paused
    _st._state["status"] = "stopping"
    await _st.broadcast({"type": "tournament_status", **_st._state})
    return {"ok": True}


@router.post("/api/human-move")
async def api_human_move(body: HumanMoveRequest):
    """
    Receive the human player's chosen move from the browser.
    Accepts the move for whichever color is currently awaiting input.
    """
    for color, hp in list(_st._active_human_players.items()):
        if hp.submit_move(body.uci):
            return {"ok": True, "color": color, "uci": body.uci}
    raise HTTPException(status_code=400, detail="No human player awaiting a move, or illegal move")


# ── Auto-start helper ─────────────────────────────────────────────────────

async def _auto_start(cfg: TournamentStartConfig):
    await asyncio.sleep(0.2)   # let server finish starting
    await api_start(cfg)
