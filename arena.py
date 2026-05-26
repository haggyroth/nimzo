"""
Nimzo — AI chess tournament server

GUI mode (default — recommended):
    python arena.py
    # Browser opens automatically at http://localhost:8765
    # Select models, configure options, and start from the UI

CLI mode (auto-starts tournament without opening the browser):
    python arena.py --white-model qwen3-30b --black-model llama-70b --games 5
    python arena.py --white-model qwen3-30b --black-model llama-70b --no-browser

Port conflicts are handled automatically — stale processes on the port
are cleared before binding.
"""

from __future__ import annotations

import os
import asyncio
import json
from typing import Optional
import argparse
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from models.human_player import HumanPlayer
from analysis import (
    TutorConfig,
    JudgeConfig,
    detect_opening_depth,
    derive_personality_traits,
    evaluate_achievements,
    ACHIEVEMENT_CATALOGUE,
)
from models.metadata import get_model_metadata
from models.portraits import generate_portrait
import db as database

# ── Portraits directory ───────────────────────────────────────────────────
_PORTRAITS_DIR = Path("portraits")
_PORTRAITS_DIR.mkdir(exist_ok=True)

# ── Named constants ───────────────────────────────────────────────────────
# Server
_DEFAULT_PORT           = 8765
_DEFAULT_LMSTUDIO_URL   = "http://localhost:1234/v1"
_DEFAULT_LMSTUDIO_URL_2 = "http://localhost:1235/v1"  # second LM Studio instance


# ── Global tournament state ───────────────────────────────────────────────

_connected_clients: set[WebSocket] = set()
_tournament_task: asyncio.Task | None = None
_pause_event: asyncio.Event = asyncio.Event()
_pause_event.set()   # set = running (not paused)
_stop_requested: bool = False

_state: dict = {
    "status": "idle",       # idle | running | paused | stopping | stopped
    "game_number": 0,
    "total_games": 0,
    "white": None,
    "black": None,
    "white_elo": None,
    "black_elo": None,
    # Human-play flags
    "white_is_human": False,
    "black_is_human": False,
    "human_assisted": True,
    # Tournament-mode fields (None in 2-player match mode)
    "format": None,           # "round_robin" | "gauntlet" | "match"
    "standings": None,        # list[dict] or None
    "tournament_id": None,
}
# ── _state mutation contract ──────────────────────────────────────────────
# All mutations MUST use a single `_state.update({...})` call, never a
# sequence of individual key assignments, so that each logical state
# transition is atomic at the Python dict level.  Because asyncio is
# cooperative (context switches only at `await` points), a single dict.update
# is never interrupted mid-flight.  Follow the pattern:
#
#     _state.update({"status": "running", "game_number": i, ...})
#     await broadcast({"type": "tournament_status", **_state})
#
# The broadcast is OUTSIDE the update so callers don't observe a half-updated
# dict between the update and the broadcast yield point.

# Set from CLI args before server start; triggers auto-start in lifespan
_cli_config: "TournamentStartConfig | None" = None

# Headless mode: skip WebSocket server, remove per-move delays, print to stdout
_headless: bool = False


# ── Tournament abort signal ───────────────────────────────────────────────

class TournamentAborted(Exception):
    pass


# ── FastAPI app ───────────────────────────────────────────────────────────

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
    All missing portraits are generated concurrently (up to the thread-pool limit).
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return
    players = database.get_all_players()
    missing = [p for p in players if not p.get("portrait_path")]
    if not missing:
        return
    print(f"[portraits] Pre-generating portraits for {len(missing)} model(s)…")
    loop = asyncio.get_running_loop()

    async def _gen_one(mid: str) -> None:
        path = await loop.run_in_executor(
            None, generate_portrait, mid, api_key, _PORTRAITS_DIR
        )
        if path:
            database.set_portrait_path(mid, path)
            print(f"[portraits] ✓ {mid}")

    await asyncio.gather(*[_gen_one(p["model_id"]) for p in missing])
    print("[portraits] Pre-generation complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    if not database.has_any_achievements():
        n = backfill_achievements()
        if n:
            print(f"🏅 Backfilled {n} achievements from existing games.")
    # Pre-generate portraits for all known players in the background
    asyncio.create_task(_pregenerate_portraits())
    if _cli_config is not None:
        asyncio.create_task(_auto_start(_cli_config))
    yield

app = FastAPI(title="Nimzo", lifespan=lifespan)
app.mount("/portraits", StaticFiles(directory=str(_PORTRAITS_DIR)), name="portraits")
# Serve extracted viewer CSS/JS and the js/ utilities directory.
# All paths are anchored to __file__'s parent so the server works regardless
# of the working directory from which `python arena.py` is launched.
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # Reject cross-origin connections.  The viewer is served by the same
    # origin so legitimate browsers always send a matching Origin header.
    # curl / scripts that omit Origin are still allowed (origin is None).
    origin = websocket.headers.get("origin")
    if origin is not None:
        from urllib.parse import urlparse
        host = urlparse(origin).hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1"):
            await websocket.close(code=1008, reason="Cross-origin WebSocket not allowed")
            return
    await websocket.accept()
    _connected_clients.add(websocket)
    # Immediately push current state so late-joiners are in sync
    await websocket.send_text(json.dumps({"type": "state", **_state}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connected_clients.discard(websocket)


async def broadcast(event: dict):
    if _headless or not _connected_clients:
        return
    msg = json.dumps(event)
    dead = set()
    for ws in list(_connected_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connected_clients.discard(ws)


# ── Static viewer ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_viewer():
    return (Path(__file__).parent / "viewer.html").read_text()


# ── REST API ──────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return _state


@app.get("/api/leaderboard")
async def api_leaderboard():
    return database.get_leaderboard()


@app.get("/api/elo-history/{model_id:path}")
async def api_elo_history(model_id: str):
    return database.get_elo_history(model_id)


@app.get("/api/stats/moves")
async def api_stats_moves():
    return database.get_player_move_stats()


@app.get("/api/stats/colors")
async def api_stats_colors():
    return database.get_color_stats()


@app.get("/api/stats/h2h")
async def api_stats_h2h():
    return database.get_head_to_head()


@app.get("/stats", response_class=HTMLResponse)
async def stats_page():
    return (Path(__file__).parent / "stats.html").read_text()


@app.get("/api/models/{model_id:path}/profile")
async def api_model_profile(model_id: str):
    profile = database.get_model_profile(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Model not found")
    profile["traits"] = derive_personality_traits(profile)
    profile["achievements"] = [
        {
            "code":  a["code"],
            "times": a["times"],
            **ACHIEVEMENT_CATALOGUE.get(a["code"], {"label": a["code"], "desc": ""}),
        }
        for a in database.get_player_achievements(model_id)
    ]
    # Run HF fetch off the event loop so a slow HF response can't stall the UI.
    loop = asyncio.get_running_loop()
    profile["metadata"] = await loop.run_in_executor(
        None, get_model_metadata, model_id,
    )
    # Include portrait URL if already generated
    portrait_path = database.get_portrait_path(model_id)
    profile["portrait_url"] = f"/{portrait_path}" if portrait_path else None
    return profile


@app.get("/api/models/{model_id:path}/lesson-effectiveness")
async def api_lesson_effectiveness(model_id: str):
    return database.get_lesson_effectiveness(model_id)


@app.get("/api/models/{model_id:path}/coherence")
async def api_coherence_stats(model_id: str):
    """Average reasoning coherence score and timeout rate for a model."""
    return database.get_coherence_stats(model_id)


@app.get("/api/models/{model_id:path}/quality")
async def api_model_quality(model_id: str):
    """
    Move-quality breakdown for a single model.

    Returns quality counts and rates (0-1), avg candidate rank, avg centipawn
    score, and bad-move rate (mistakes + blunders).  404 if model unknown or
    has no recorded moves.
    """
    stats = database.get_player_quality_stats(model_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Model not found or no moves recorded")
    return stats


@app.post("/api/models/{model_id:path}/portrait")
async def api_generate_portrait(model_id: str):
    """
    Generate (or retrieve cached) portrait for a model.

    Returns ``{portrait_url: "/portraits/abc.png"}`` on success,
    ``{portrait_url: null}`` if no API key or generation fails.
    Runs the blocking Imagen call in a thread-pool executor.
    """
    # Reject unknown model IDs — prevents unbounded paid API calls for ghost IDs
    if not database.player_exists(model_id):
        raise HTTPException(status_code=404, detail="Model not found")

    # Return cached path without regenerating
    existing = database.get_portrait_path(model_id)
    if existing and Path(existing).exists():
        return {"portrait_url": f"/{existing}"}

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return {"portrait_url": None}

    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(
        None, generate_portrait, model_id, api_key, _PORTRAITS_DIR
    )

    if path:
        database.set_portrait_path(model_id, path)

    return {"portrait_url": f"/{path}" if path else None}


@app.get("/api/achievements/catalogue")
async def api_achievement_catalogue():
    return ACHIEVEMENT_CATALOGUE


@app.get("/api/games/{game_id}")
async def api_game(game_id: int):
    row = database.get_game(game_id)
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
    return row


@app.get("/api/games/{game_id}/moves")
async def api_game_moves(game_id: int):
    return database.get_game_moves(game_id)


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


@app.get("/api/games/{game_id}/pgn")
async def api_game_pgn(game_id: int):
    from fastapi.responses import PlainTextResponse
    game_row = database.get_game(game_id)
    if not game_row:
        return PlainTextResponse("Game not found", status_code=404)
    moves = database.get_game_moves(game_id)
    pgn = _build_game_pgn(game_row, moves)
    filename = (
        f"nimzo_{game_row['white_name']}_vs_{game_row['black_name']}_{game_id}.pgn"
        .replace(" ", "_")
    )
    return PlainTextResponse(
        pgn,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/games/export")
async def api_games_export(model_id: Optional[str] = None, limit: int = 5000):
    """
    Bulk PGN export — all games as a single annotated PGN file.

    Query params:
      model_id — restrict to games where this model played (optional)
      limit    — max games to export (default 5 000)
    """
    from fastapi.responses import PlainTextResponse
    rows = database.get_all_games(model_id=model_id, limit=limit)
    if not rows:
        return PlainTextResponse("# No games found\n", status_code=200)

    parts: list[str] = []
    for i, row in enumerate(rows, 1):
        moves = database.get_game_moves(row["id"])
        parts.append(_build_game_pgn(row, moves, round_number=i))

    filename = "nimzo_export.pgn" if not model_id else f"nimzo_{model_id}_export.pgn"
    filename = filename.replace("/", "_").replace(" ", "_")
    return PlainTextResponse(
        "\n".join(parts),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/games")
async def api_games(limit: int = 20):
    return database.get_recent_games(limit)


class HumanMoveRequest(BaseModel):
    uci: str


@app.post("/api/human-move")
async def api_human_move(body: HumanMoveRequest):
    """
    Receive the human player's chosen move from the browser.
    Accepts the move for whichever color is currently awaiting input.
    """
    for color, hp in list(_active_human_players.items()):
        if hp.submit_move(body.uci):
            return {"ok": True, "color": color, "uci": body.uci}
    raise HTTPException(status_code=400, detail="No human player awaiting a move, or illegal move")


@app.get("/api/models")
async def api_models(url: str = _DEFAULT_LMSTUDIO_URL):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/models")
            return resp.json()
    except Exception as exc:
        return {"data": [], "error": str(exc)}


class PlayerSpec(BaseModel):
    backend: str = "lmstudio"
    name: str = ""
    model_id: str = ""
    url: str = _DEFAULT_LMSTUDIO_URL
    thinking: bool = False
    candidate_count: Optional[int] = None   # override default 5; None = use default
    style: str = ""                         # "aggressive" | "positional" | "defensive" | ""


# ── Active human player registry ─────────────────────────────────────────
# Keyed by "white" or "black"; populated at game start, cleared after.
_active_human_players: dict[str, HumanPlayer] = {}


class TournamentStartConfig(BaseModel):
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
    games: int = 10
    # Time control: seconds per move, 0 = no limit
    move_timeout: int = 0
    # Human-play settings
    human_assisted: bool = True    # True = show Stockfish candidates; False = blind
    # Personality styles for 2-player mode
    white_style: str = ""          # "aggressive" | "positional" | "defensive" | ""
    black_style: str = ""
    # Multi-player tournament fields (len >= 2 activates bracket mode)
    players: list[PlayerSpec] = []
    format: str = "round_robin"   # "round_robin" | "gauntlet"
    games_per_pair: int = 2       # games per head-to-head matchup
    # Adaptive difficulty: auto-adjust candidate_count based on rolling win rate
    adaptive_difficulty: bool = False


@app.post("/api/tournament/start")
async def api_start(config: TournamentStartConfig):
    global _tournament_task, _stop_requested
    if _tournament_task and not _tournament_task.done():
        return {"error": "A tournament is already running"}

    _stop_requested = False
    _pause_event.set()

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
        # Seed by current ELO (highest first).  For gauntlet the first player
        # is champion, so the top-rated model defends.  For round-robin this
        # is mostly cosmetic but gives a natural display order.
        seeded = sorted(
            config.players,
            key=lambda ps: database.get_player_elo(ps.model_id),
            reverse=True,
        )

        players = [
            build_player(ps.backend, ps.name or ps.model_id.split("/")[-1].split("@")[0],
                         ps.model_id, ps.url, ps.thinking, move_timeout=config.move_timeout,
                         style=ps.style)
            for ps in seeded
        ]
        pairings = generate_pairings(seeded, config.format, config.games_per_pair)
        total_games = len(pairings)
        standings = compute_standings(seeded, [])

        _state.update({
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
        await broadcast({"type": "tournament_status", **_state})

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
                )
            except Exception as exc:
                print(f"\n  Tournament ended: {type(exc).__name__}")
            finally:
                global _stop_requested
                _stop_requested = False
                _pause_event.set()
                _state["status"] = "idle"
                try:
                    await broadcast({"type": "tournament_status", **_state})
                except Exception:
                    pass

        _tournament_task = asyncio.create_task(_run_bracket_and_catch())
        return {"ok": True}

    # ── Classic 2-player match mode ───────────────────────────────────
    white = build_player(config.white_backend, config.white_name, config.white_model, config.white_url, config.white_thinking, move_timeout=config.move_timeout, style=config.white_style)
    black = build_player(config.black_backend, config.black_name, config.black_model, config.black_url, config.black_thinking, move_timeout=config.move_timeout, style=config.black_style)

    # Register any human players so /api/human-move can reach them.
    _active_human_players.clear()
    if isinstance(white, HumanPlayer):
        _active_human_players["white"] = white
    if isinstance(black, HumanPlayer):
        _active_human_players["black"] = black

    _state.update({
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
    await broadcast({"type": "tournament_status", **_state})

    async def _run_and_catch():
        try:
            await run_tournament(white, black, config.games, tutor, judge, adaptive_difficulty=config.adaptive_difficulty)
        except Exception as exc:
            # Absorb any stray exceptions (e.g. engine death on Ctrl+C,
            # a model timeout, etc) so the task doesn't surface as
            # "exception was never retrieved". Reset the state machine
            # and broadcast so the UI exits the running/stopping state.
            print(f"\n  Tournament ended: {type(exc).__name__}")
        finally:
            global _stop_requested
            _stop_requested = False
            _pause_event.set()
            _active_human_players.clear()
            _state.update({"status": "idle", "white_is_human": False, "black_is_human": False})
            try:
                await broadcast({"type": "tournament_status", **_state})
            except Exception:
                pass

    _tournament_task = asyncio.create_task(_run_and_catch())
    return {"ok": True}


@app.get("/api/tournament/history")
async def api_tournament_history(limit: int = 20):
    return database.get_tournament_history(limit)


@app.post("/api/tournament/pause")
async def api_pause():
    _pause_event.clear()
    _state["status"] = "paused"
    await broadcast({"type": "tournament_status", **_state})
    return {"ok": True}


@app.post("/api/tournament/resume")
async def api_resume():
    _pause_event.set()
    _state["status"] = "running"
    await broadcast({"type": "tournament_status", **_state})
    return {"ok": True}


@app.post("/api/tournament/stop")
async def api_stop():
    global _stop_requested
    _stop_requested = True
    _pause_event.set()   # unblock if paused
    _state["status"] = "stopping"
    await broadcast({"type": "tournament_status", **_state})
    return {"ok": True}

# ── Game logic (circular-safe import) ────────────────────────────────────
# game.py imports `arena` for broadcast/state; we import it here for the
# runner functions.  Python resolves the cycle because game.py's
# `import arena as _arena` executes against the already-complete arena module.
from game import (  # noqa: E402
    play_game,              # noqa: F401 — re-exported for `from arena import play_game`
    run_bracket_tournament,
    run_tournament,
    build_player,
    generate_pairings,
    compute_standings,
)


# ── Auto-start from CLI config ────────────────────────────────────────────

async def _auto_start(cfg: TournamentStartConfig):
    await asyncio.sleep(0.2)   # let server finish starting
    await api_start(cfg)


# ── Entry point ───────────────────────────────────────────────────────────

def _free_port(port: int) -> bool:
    """Kill whatever is holding the port. Returns True if anything was killed."""
    import signal
    import subprocess
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    if not pids:
        return False
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Nimzo — AI chess tournament server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "GUI mode (recommended):\n"
            "  python arena.py\n"
            "  → opens http://localhost:8765 — configure everything in the browser\n\n"
            "CLI mode (auto-starts tournament):\n"
            "  python arena.py --white-model qwen3-30b --black-model llama-70b\n\n"
            "Config file mode:\n"
            "  python arena.py --config tournament.toml\n\n"
            "Headless benchmarking:\n"
            "  python arena.py --config tournament.toml --headless\n"
        ),
    )
    # --config loads everything from a TOML file; individual flags still override
    parser.add_argument("--config",        default="",
                        help="Path to a tournament.toml config file")
    # Model IDs intentionally NOT read from env vars — they must be passed
    # explicitly to trigger CLI mode.  Connection URLs and other non-model
    # settings are still env-configurable for convenience.
    parser.add_argument("--white-backend", default=os.environ.get("WHITE_BACKEND", "lmstudio"))
    parser.add_argument("--white-name",    default="")
    parser.add_argument("--white-model",   default="")   # explicit only — no env fallback
    parser.add_argument("--white-url",     default=os.environ.get("WHITE_URL", os.environ.get("LMSTUDIO_BASE_URL", _DEFAULT_LMSTUDIO_URL)))
    parser.add_argument("--black-backend", default=os.environ.get("BLACK_BACKEND", "lmstudio"))
    parser.add_argument("--black-name",    default="")
    parser.add_argument("--black-model",   default="")   # explicit only — no env fallback
    parser.add_argument("--black-url",     default=os.environ.get("BLACK_URL",     _DEFAULT_LMSTUDIO_URL))
    parser.add_argument("--tutor-backend", default=os.environ.get("TUTOR_BACKEND", "lmstudio"))
    parser.add_argument("--tutor-model",   default=os.environ.get("TUTOR_MODEL",   ""))
    parser.add_argument("--tutor-url",     default=os.environ.get("TUTOR_URL",     _DEFAULT_LMSTUDIO_URL))
    parser.add_argument("--judge-model",   default=os.environ.get("JUDGE_MODEL",   ""),
                        help="Model for reasoning coherence scoring (defaults to tutor model)")
    parser.add_argument("--games",         type=int, default=int(os.environ.get("GAMES", 1)))
    parser.add_argument("--move-timeout",  type=int, default=0,
                        help="Per-move timeout in seconds (0 = no limit)")
    parser.add_argument("--thinking",      action="store_true", default=False,
                        help="Enable extended thinking for both players (LM Studio)")
    parser.add_argument("--headless",      action="store_true", default=False,
                        help="Run without HTTP server or browser — DB only, fast benchmarking")
    parser.add_argument("--port",          type=int, default=int(os.environ.get("PORT", _DEFAULT_PORT)))
    parser.add_argument("--listen",        default=os.environ.get("NIMZO_HOST", "127.0.0.1"),
                        metavar="HOST",
                        help="Interface to bind (default 127.0.0.1; use 0.0.0.0 to expose on LAN)")
    parser.add_argument("--no-browser",    action="store_true", default=False,
                        help="Don't auto-open the browser on startup")
    args = parser.parse_args()

    # ── Config file mode ──────────────────────────────────────────────
    if args.config:
        from config_loader import load_config as _load_config
        _cli_config = _load_config(args.config)
        # CLI flags override config file values when explicitly non-default
        if args.move_timeout:
            _cli_config.move_timeout = args.move_timeout
        if args.headless:
            _headless = True
    else:
        _headless = args.headless

    port = args.port
    host = args.listen

    if _headless:
        # ── Headless mode: skip uvicorn entirely ──────────────────────
        import asyncio as _asyncio

        database.init_db()

        cli_mode = bool(args.config or (args.white_model and args.black_model))
        if not cli_mode:
            parser.error("--headless requires --config or --white-model/--black-model")

        if not args.config:
            _cli_config = TournamentStartConfig(
                white_backend=args.white_backend,
                white_name=args.white_name or args.white_model.split("/")[-1].split("@")[0].split(":")[0],
                white_model=args.white_model,
                white_url=args.white_url,
                white_thinking=args.thinking,
                black_backend=args.black_backend,
                black_name=args.black_name or args.black_model.split("/")[-1].split("@")[0].split(":")[0],
                black_model=args.black_model,
                black_url=args.black_url,
                black_thinking=args.thinking,
                tutor_backend=args.tutor_backend,
                tutor_model=args.tutor_model,
                tutor_url=args.tutor_url,
                judge_model=args.judge_model,
                games=args.games,
                move_timeout=args.move_timeout,
            )

        w = _cli_config.white_name or _cli_config.white_model
        b = _cli_config.black_name or _cli_config.black_model
        g = _cli_config.games
        print(f"⚡ Nimzo headless  ·  {w} vs {b}  ·  {g} game(s)")

        async def _run_headless():
            _pause_event.set()
            await api_start(_cli_config)
            # Wait for the task to finish
            if _tournament_task:
                await _tournament_task

        _asyncio.run(_run_headless())
        raise SystemExit(0)

    # ── Normal (GUI) mode ─────────────────────────────────────────────

    # Free the port if something is already holding it
    if _free_port(port):
        print(f"⚠  Port {port} was in use — cleared stale process.")
        import time
        time.sleep(0.4)   # brief pause for OS to release the socket

    cli_mode = bool(args.white_model and args.black_model) or bool(args.config)

    if cli_mode and not args.config:
        _cli_config = TournamentStartConfig(
            white_backend=args.white_backend,
            white_name=args.white_name or args.white_model.split("/")[-1].split("@")[0].split(":")[0],
            white_model=args.white_model,
            white_url=args.white_url,
            white_thinking=args.thinking,
            black_backend=args.black_backend,
            black_name=args.black_name or args.black_model.split("/")[-1].split("@")[0].split(":")[0],
            black_model=args.black_model,
            black_url=args.black_url,
            black_thinking=args.thinking,
            tutor_backend=args.tutor_backend,
            tutor_model=args.tutor_model,
            tutor_url=args.tutor_url,
            judge_model=args.judge_model,
            games=args.games,
            move_timeout=args.move_timeout,
        )

    display_host = "localhost" if host in ("127.0.0.1", "::1") else host
    if _cli_config:
        w = _cli_config.white_name or _cli_config.white_model
        b = _cli_config.black_name or _cli_config.black_model
        g = _cli_config.games
        print(f"🌐  Nimzo  →  http://{display_host}:{port}")
        print(f"♟   {w} vs {b}  ·  {g} game(s)")
        if _cli_config.tutor_model:
            print(f"🎓  Tutor: {_cli_config.tutor_model}")
        if _cli_config.move_timeout:
            print(f"⏱  Move timeout: {_cli_config.move_timeout}s")
    else:
        print(f"🌐  Nimzo  →  http://{display_host}:{port}")
        print("    Open the browser to configure and start a tournament.")

    # Auto-open browser unless suppressed or in CLI mode with --no-browser
    if not args.no_browser:
        import threading
        import webbrowser
        def _open_browser():
            import time
            time.sleep(1.2)   # wait for uvicorn to be ready
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
