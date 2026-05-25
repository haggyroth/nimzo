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
import chess
import chess.pgn
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from engine import StockfishEngine
from models.base import ChessPlayer, PlayerConfig
from models.anthropic_player import AnthropicPlayer
from models.lmstudio_player import LMStudioPlayer
from models.human_player import HumanPlayer
from analysis import (
    TutorConfig,
    JudgeConfig,
    calculate_elos,
    generate_lessons,
    compress_lessons,
    build_quality_summary,
    bad_move_rate,
    detect_opening,
    detect_opening_depth,
    derive_personality_traits,
    evaluate_achievements,
    score_reasoning_coherence,
    ACHIEVEMENT_CATALOGUE,
)
from models.metadata import get_model_metadata
from models.portraits import generate_portrait
import db as database

# ── Portraits directory ───────────────────────────────────────────────────
_PORTRAITS_DIR = Path("portraits")
_PORTRAITS_DIR.mkdir(exist_ok=True)


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
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return
    players = database.get_all_players()
    missing = [p for p in players if not p.get("portrait_path")]
    if not missing:
        return
    print(f"[portraits] Pre-generating portraits for {len(missing)} model(s)…")
    loop = asyncio.get_event_loop()
    for p in missing:
        mid = p["model_id"]
        path = await loop.run_in_executor(
            None, generate_portrait, mid, api_key, _PORTRAITS_DIR
        )
        if path:
            database.set_portrait_path(mid, path)
            print(f"[portraits] ✓ {mid}")
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


# ── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
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


_QUALITY_GLYPH = {
    "best":       "!!",
    "excellent":  "!",
    "inaccuracy": "?!",
    "mistake":    "?",
    "blunder":    "??",
}

@app.get("/api/models/{model_id:path}/profile")
async def api_model_profile(model_id: str):
    profile = database.get_model_profile(model_id)
    if not profile:
        from fastapi import HTTPException
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
    loop = asyncio.get_event_loop()
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


@app.post("/api/models/{model_id:path}/portrait")
async def api_generate_portrait(model_id: str):
    """
    Generate (or retrieve cached) portrait for a model.

    Returns ``{portrait_url: "/portraits/abc.png"}`` on success,
    ``{portrait_url: null}`` if no API key or generation fails.
    Runs the blocking Imagen call in a thread-pool executor.
    """
    # Return cached path without regenerating
    existing = database.get_portrait_path(model_id)
    if existing and Path(existing).exists():
        return {"portrait_url": f"/{existing}"}

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return {"portrait_url": None}

    loop = asyncio.get_event_loop()
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Game not found")
    return row


@app.get("/api/games/{game_id}/moves")
async def api_game_moves(game_id: int):
    return database.get_game_moves(game_id)


@app.get("/api/games/{game_id}/pgn")
async def api_game_pgn(game_id: int):
    from fastapi.responses import PlainTextResponse
    game_row = database.get_game(game_id)
    if not game_row:
        return PlainTextResponse("Game not found", status_code=404)
    moves = database.get_game_moves(game_id)

    lines = [
        f'[Event "Nimzo Arena"]',
        f'[Site "localhost"]',
        f'[Date "{game_row["played_at"][:10]}"]',
        f'[White "{game_row["white_name"]}"]',
        f'[Black "{game_row["black_name"]}"]',
        f'[Result "{game_row["result"]}"]',
        f'[WhiteElo "{round(game_row["white_elo_before"])}"]',
        f'[BlackElo "{round(game_row["black_elo_before"])}"]',
        "",
    ]

    tokens: list[str] = []
    for m in moves:
        num     = m["move_number"]
        san     = m["move_san"]
        glyph   = _QUALITY_GLYPH.get(m["quality"] or "", "")
        reason  = (m["reasoning"] or "").strip().replace("{", "(").replace("}", ")")
        rank    = m["candidate_rank"]

        # Move number prefix for white moves (odd) and black's first token
        if num % 2 == 1:
            tokens.append(f"{(num + 1) // 2}.")

        tokens.append(san + glyph)

        comment_parts = []
        if reason and reason != "(no reasoning)" and reason != "(parse failed — defaulted to top candidate)":
            comment_parts.append(reason)
        if m["quality"] and m["quality"] != "good":
            comment_parts.append(m["quality"].capitalize())
        if rank:
            comment_parts.append(f"candidate #{rank}")
        if comment_parts:
            tokens.append("{ " + " | ".join(comment_parts) + " }")

    tokens.append(game_row["result"])

    # Wrap at ~80 chars
    pgn_body = ""
    line = ""
    for tok in tokens:
        if line and len(line) + 1 + len(tok) > 78:
            pgn_body += line + "\n"
            line = tok
        else:
            line = (line + " " + tok).lstrip()
    if line:
        pgn_body += line + "\n"

    filename = f"nimzo_{game_row['white_name']}_vs_{game_row['black_name']}_{game_id}.pgn".replace(" ", "_")
    return PlainTextResponse(
        "\n".join(lines) + pgn_body,
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
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail="No human player awaiting a move, or illegal move")


@app.get("/api/models")
async def api_models(url: str = "http://localhost:1234/v1"):
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
    url: str = "http://localhost:1234/v1"
    thinking: bool = False
    candidate_count: Optional[int] = None   # override default 5; None = use default


# ── Active human player registry ─────────────────────────────────────────
# Keyed by "white" or "black"; populated at game start, cleared after.
_active_human_players: dict[str, HumanPlayer] = {}


class TournamentStartConfig(BaseModel):
    white_backend: str = "lmstudio"
    white_name: str = "White"
    white_model: str = ""
    white_url: str = "http://localhost:1234/v1"
    white_thinking: bool = False
    black_backend: str = "lmstudio"
    black_name: str = "Black"
    black_model: str = ""
    black_url: str = "http://localhost:1235/v1"
    black_thinking: bool = False
    tutor_backend: str = "lmstudio"
    tutor_model: str = ""
    tutor_url: str = "http://localhost:1234/v1"
    # Reasoning coherence judge (defaults to same as tutor when model is "")
    judge_backend: str = "lmstudio"
    judge_model: str = ""
    judge_url: str = "http://localhost:1234/v1"
    games: int = 10
    # Time control: seconds per move, 0 = no limit
    move_timeout: int = 0
    # Human-play settings
    human_assisted: bool = True    # True = show Stockfish candidates; False = blind
    # Multi-player tournament fields (len >= 2 activates bracket mode)
    players: list[PlayerSpec] = []
    format: str = "round_robin"   # "round_robin" | "gauntlet"
    games_per_pair: int = 2       # games per head-to-head matchup


# ── Tournament title pool ─────────────────────────────────────────────────

_WINNER_TITLES = [
    "The Relentless",
    "Silicon Kasparov",
    "The Inevitable",
    "Iron Crown",
    "The Grand Inquisitor",
    "Digital Tal",
    "The Patient King",
    "Last Model Standing",
    "The Unbreakable",
    "The Silicon Sultan",
    "The Eternal Engine",
    "Chess Machine Prime",
    "The Cold Logician",
    "The Iron Strategist",
    "Checkmate Incarnate",
]


def pick_title(model_id: str, fmt: str) -> str:
    import hashlib
    seed = hashlib.md5(f"{model_id}:{fmt}".encode()).digest()
    idx = int.from_bytes(seed[:4], "big") % len(_WINNER_TITLES)
    return _WINNER_TITLES[idx]


# ── Multi-player bracket scheduling ──────────────────────────────────────

def generate_pairings(player_specs: list[PlayerSpec], fmt: str, games_per_pair: int) -> list[tuple[PlayerSpec, PlayerSpec]]:
    """
    Returns an ordered list of (white, black) spec pairs for the tournament.

    round_robin: every pair plays `games_per_pair` games, alternating colours.
    gauntlet:    player[0] is the champion; everyone else challenges them,
                 `games_per_pair` games per challenger, alternating colours.
    """
    pairings: list[tuple[PlayerSpec, PlayerSpec]] = []
    if fmt == "gauntlet":
        champion = player_specs[0]
        challengers = player_specs[1:]
        for ch in challengers:
            for g in range(games_per_pair):
                if g % 2 == 0:
                    pairings.append((champion, ch))
                else:
                    pairings.append((ch, champion))
    else:  # round_robin
        n = len(player_specs)
        pairs = [(player_specs[i], player_specs[j]) for i in range(n) for j in range(i + 1, n)]
        for g in range(games_per_pair):
            for (a, b) in pairs:
                if g % 2 == 0:
                    pairings.append((a, b))
                else:
                    pairings.append((b, a))
    return pairings


def compute_standings(player_specs: list[PlayerSpec], results: list[dict]) -> list[dict]:
    """
    Given finished game results, compute per-player standings.
    results items: {white_model_id, black_model_id, result}
    Returns list of dicts sorted by points desc.
    """
    standings: dict[str, dict] = {}
    for ps in player_specs:
        standings[ps.model_id] = {
            "model_id": ps.model_id,
            "name": ps.name,
            "points": 0.0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "games_played": 0,
        }
    for r in results:
        w = r.get("white_model_id")
        b = r.get("black_model_id")
        res = r.get("result", "*")
        if w not in standings or b not in standings:
            continue
        standings[w]["games_played"] += 1
        standings[b]["games_played"] += 1
        if res == "1-0":
            standings[w]["wins"] += 1
            standings[w]["points"] += 1.0
            standings[b]["losses"] += 1
        elif res == "0-1":
            standings[b]["wins"] += 1
            standings[b]["points"] += 1.0
            standings[w]["losses"] += 1
        elif res == "1/2-1/2":
            standings[w]["draws"] += 1
            standings[w]["points"] += 0.5
            standings[b]["draws"] += 1
            standings[b]["points"] += 0.5
    return sorted(standings.values(), key=lambda s: (-s["points"], -s["wins"]))


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
                         ps.model_id, ps.url, ps.thinking, move_timeout=config.move_timeout)
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
    white = build_player(config.white_backend, config.white_name, config.white_model, config.white_url, config.white_thinking, move_timeout=config.move_timeout)
    black = build_player(config.black_backend, config.black_name, config.black_model, config.black_url, config.black_thinking, move_timeout=config.move_timeout)

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
            await run_tournament(white, black, config.games, tutor, judge)
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
            _state["status"] = "idle"
            _state["white_is_human"] = False
            _state["black_is_human"] = False
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


# ── Game loop ─────────────────────────────────────────────────────────────

async def play_game(
    white: ChessPlayer,
    black: ChessPlayer,
    stockfish: StockfishEngine,
    game_number: int,
    tutor: TutorConfig | None = None,
    judge: "JudgeConfig | None" = None,
) -> dict:
    board = chess.Board()
    game  = chess.pgn.Game()
    game.headers["White"] = white.config.name
    game.headers["Black"] = black.config.name
    game.headers["Date"]  = datetime.now().strftime("%Y.%m.%d")
    node  = game

    move_qualities_white: list[tuple[str, str]] = []
    move_qualities_black: list[tuple[str, str]] = []
    move_records: list[dict] = []

    await broadcast({
        "type": "game_start",
        "game_number": game_number,
        "white": white.config.name,
        "black": black.config.name,
        "white_elo": round(white.elo),
        "black_elo": round(black.elo),
        "white_model_id": white.config.model_id,
        "black_model_id": black.config.model_id,
        "white_is_human": isinstance(white, HumanPlayer),
        "black_is_human": isinstance(black, HumanPlayer),
        "fen": board.fen(),
    })

    move_number = 0

    loop = asyncio.get_event_loop()

    while not board.is_game_over():
        # Pause / stop checks
        await _pause_event.wait()
        if _stop_requested:
            raise TournamentAborted()

        current_player = white if board.turn == chess.WHITE else black

        # Run blocking Stockfish call in thread pool so event loop stays free
        try:
            candidates = await loop.run_in_executor(
                None, stockfish.get_candidates, board, current_player.config.candidate_count
            )
        except Exception as exc:
            # Stockfish died (e.g. Ctrl+C sent SIGINT to the subprocess).
            # Treat as a clean stop rather than crashing with a traceback.
            raise TournamentAborted() from None
        if not candidates:
            break

        exporter = chess.pgn.StringExporter(headers=False)
        game.accept(exporter)
        pgn_so_far = str(exporter)

        is_human = isinstance(current_player, HumanPlayer)
        await broadcast({
            "type": "thinking",
            "player": current_player.config.name,
            "color": "white" if board.turn == chess.WHITE else "black",
            "fen": board.fen(),
            "candidates": [
                {"uci": m.uci(), "san": board.san(m), "score_cp": s}
                for m, s in candidates
            ],
            "is_human_turn": is_human,
            "legal_uci": current_player.get_legal_uci_moves() if is_human else [],
        })

        # Run blocking model API call in thread pool — this is the main blocker
        timed_out = False
        timeout_secs = current_player.config.move_timeout or None
        try:
            coro = loop.run_in_executor(
                None, current_player.choose_move, board, candidates, pgn_so_far
            )
            decision = await asyncio.wait_for(coro, timeout=timeout_secs)
        except asyncio.TimeoutError:
            print(f"  ⏱  {current_player.config.name} timed out after {timeout_secs}s — top candidate used")
            from models.base import MoveDecision
            decision = MoveDecision(
                move_uci=candidates[0][0].uci(),
                reasoning=f"(timed out after {timeout_secs}s — fell back to top candidate)",
                candidate_rank=1,
                raw_response="",
            )
            timed_out = True
        except Exception as exc:
            # Model was unloaded, connection dropped, or API error mid-inference.
            # If a stop was requested, honour it cleanly; otherwise fall back to
            # Stockfish's top candidate so the game can continue.
            if _stop_requested:
                raise TournamentAborted()
            print(f"  ⚠  {current_player.config.name} API error ({type(exc).__name__}): {exc} — falling back to top candidate")
            from models.base import MoveDecision
            decision = MoveDecision(
                move_uci=candidates[0][0].uci(),
                reasoning="(API error — fell back to top candidate)",
                candidate_rank=1,
                raw_response="",
            )

        if _stop_requested:
            raise TournamentAborted()

        chosen_move  = chess.Move.from_uci(decision.move_uci)
        if chosen_move not in board.legal_moves:
            chosen_move = candidates[0][0]

        quality  = stockfish.evaluate_move_quality(board, chosen_move, candidates)
        san      = board.san(chosen_move)

        # Score from White's perspective (for centipawn graph).
        # candidates are scored from the current player's POV, so negate for Black.
        was_white    = board.turn == chess.WHITE
        chosen_score = next((s for m, s in candidates if m == chosen_move), candidates[0][1])
        score_cp_white = chosen_score if was_white else (
            -chosen_score if chosen_score is not None else None
        )

        if was_white:
            move_qualities_white.append((san, quality))
        else:
            move_qualities_black.append((san, quality))

        # Reasoning coherence scoring — fire in thread pool so it doesn't
        # block the game loop; skip for human/timed-out/fallback moves.
        fen_before_push = board.fen()
        coherence_score: float | None = None
        if judge and not timed_out and not isinstance(current_player, HumanPlayer):
            try:
                coherence_score = await loop.run_in_executor(
                    None,
                    score_reasoning_coherence,
                    decision.reasoning, san, fen_before_push, candidates, judge,
                )
            except Exception:
                coherence_score = None

        board.push(chosen_move)
        node = node.add_variation(chosen_move)
        move_number += 1

        move_records.append({
            "move_number":    move_number,
            "player_model_id": current_player.config.model_id,
            "player_name":    current_player.config.name,
            "move_uci":       chosen_move.uci(),
            "move_san":       san,
            "candidate_rank": decision.candidate_rank,
            "quality":        quality,
            "score_cp":       score_cp_white,
            "reasoning":      decision.reasoning,
            "thinking_content": decision.thinking_content,
            "fen_after":      board.fen(),
            "coherence_score": coherence_score,
            "timed_out":      timed_out,
        })

        await broadcast({
            "type":           "move",
            "move_number":    move_number,
            "player":         current_player.config.name,
            "color":          "white" if not board.turn else "black",
            "san":            san,
            "uci":            chosen_move.uci(),
            "quality":        quality,
            "candidate_rank": decision.candidate_rank,
            "reasoning":      decision.reasoning,
            "thinking_content": decision.thinking_content,
            "coherence_score": coherence_score,
            "timed_out":      timed_out,
            "score_cp_white": score_cp_white,
            "fen":            board.fen(),
        })

        if not _headless:
            await asyncio.sleep(0.05)   # pacing for live viewer

    # ── Game over ──────────────────────────────────────────────────────
    result      = board.result()
    termination = (
        "checkmate" if board.is_checkmate()
        else "stalemate" if board.is_stalemate()
        else "draw"
    )

    game.headers["Result"] = result
    pgn_string = str(game)

    # Opening detection — keep both forms (with ply depth + classic 2-tuple)
    opening_deep = detect_opening_depth(pgn_string)   # (eco, name, ply) or None
    opening = (opening_deep[0], opening_deep[1]) if opening_deep else None
    opening_ply = opening_deep[2] if opening_deep else None

    # ELO — use game count for dynamic K
    w_count = database.get_player_game_count(white.config.model_id)
    b_count = database.get_player_game_count(black.config.model_id)
    w_elo_before, b_elo_before = white.elo, black.elo
    w_elo_after, b_elo_after   = calculate_elos(
        w_elo_before, b_elo_before, result, w_count, b_count
    )
    white.update_elo(w_elo_after)
    black.update_elo(b_elo_after)

    database.upsert_player(white.config.model_id, white.config.name, white.config.backend, w_elo_after)
    database.upsert_player(black.config.model_id, black.config.name, black.config.backend, b_elo_after)

    game_id = database.record_game(
        white_model_id=white.config.model_id,
        black_model_id=black.config.model_id,
        result=result,
        termination=termination,
        total_moves=move_number,
        pgn=pgn_string,
        white_elo_before=w_elo_before,
        black_elo_before=b_elo_before,
        white_elo_after=w_elo_after,
        black_elo_after=b_elo_after,
    )
    for rec in move_records:
        database.record_move(
            game_id=game_id,
            move_number=rec["move_number"],
            player_model_id=rec["player_model_id"],
            move_uci=rec["move_uci"],
            move_san=rec["move_san"],
            candidate_rank=rec["candidate_rank"],
            quality=rec["quality"],
            score_cp=rec["score_cp"],
            reasoning=rec["reasoning"],
            thinking_content=rec["thinking_content"],
            fen_after=rec["fen_after"],
            coherence_score=rec.get("coherence_score"),
            timed_out=rec.get("timed_out", False),
        )

    # ── Achievements ───────────────────────────────────────────────────
    score_history_white = [rec["score_cp"] for rec in move_records]
    awards: dict[str, list[str]] = {}
    for player, color, qualities, elo_b, opp_elo_b in [
        (white, "white", move_qualities_white, w_elo_before, b_elo_before),
        (black, "black", move_qualities_black, b_elo_before, w_elo_before),
    ]:
        codes = evaluate_achievements(
            color=color,
            result=result,
            total_moves=move_number,
            move_qualities=qualities,
            score_history_white=score_history_white,
            player_elo_before=elo_b,
            opp_elo_before=opp_elo_b,
            opening_ply=opening_ply,
        )
        if codes:
            database.record_achievements(player.config.model_id, game_id, codes)
            awards[player.config.model_id] = codes
            print(f"  🏅 {player.config.name}: {', '.join(codes)}")

    await broadcast({
        "type":            "game_over",
        "game_id":         game_id,
        "result":          result,
        "termination":     termination,
        "total_moves":     move_number,
        "white_elo_after": round(w_elo_after),
        "black_elo_after": round(b_elo_after),
        "pgn":             pgn_string,
        "opening_eco":     opening[0] if opening else None,
        "opening_name":    opening[1] if opening else None,
        "achievements":    {
            "white": [
                {"code": c, **ACHIEVEMENT_CATALOGUE.get(c, {"label": c, "desc": ""})}
                for c in awards.get(white.config.model_id, [])
            ],
            "black": [
                {"code": c, **ACHIEVEMENT_CATALOGUE.get(c, {"label": c, "desc": ""})}
                for c in awards.get(black.config.model_id, [])
            ],
        },
    })

    # ── Lessons for both players ───────────────────────────────────────
    is_draw = result == "1/2-1/2"
    for player, color, qualities in [
        (white, "White", move_qualities_white),
        (black, "Black", move_qualities_black),
    ]:
        if isinstance(player, HumanPlayer):
            continue   # humans don't receive AI-generated lessons
        quality_summary = build_quality_summary(qualities)
        lessons = generate_lessons(
            pgn=pgn_string,
            player_name=player.config.name,
            player_color=color,
            result=result,
            termination=termination,
            quality_summary=quality_summary,
            tutor=tutor,
            opening=opening,
            is_draw=is_draw,
        )

        if lessons["improve"] or lessons["strength"]:
            bmr = bad_move_rate(qualities)
            for lesson in lessons["improve"]:
                tagged = f"[improve] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "improve", bmr)
            for lesson in lessons["strength"]:
                tagged = f"[strength] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "strength", bmr)

            await broadcast({
                "type":     "lessons",
                "player":   player.config.name,
                "color":    color.lower(),
                "improve":  lessons["improve"],
                "strength": lessons["strength"],
            })
            print(f"\n  📚 {player.config.name}:")
            for l in lessons["improve"]:
                print(f"    ↑ improve: {l}")
            for l in lessons["strength"]:
                print(f"    ★ strength: {l}")

        # ── Lesson compression: every 5 games once threshold is reached ──
        # Trigger: game count divisible by 5, and at least 10 lessons stored.
        # Runs in executor to avoid blocking the event loop.
        game_count = database.get_player_game_count(player.config.model_id)
        lesson_count = database.get_lesson_count(player.config.model_id)
        if tutor and tutor.model_id and game_count >= 5 and game_count % 5 == 0 and lesson_count >= 10:
            print(f"  🗜  Compressing {lesson_count} lessons for {player.config.name} (game #{game_count})…")
            all_lessons = database.get_all_raw_lessons(player.config.model_id)
            profile = await loop.run_in_executor(
                None, compress_lessons, all_lessons, player.config.name, game_count, tutor
            )
            if profile:
                database.set_strategic_profile(player.config.model_id, profile)
                player.config.strategic_profile = profile

    return {
        "game_id":     game_id,
        "result":      result,
        "termination": termination,
        "moves":       move_number,
    }


# ── Multi-player bracket runner ───────────────────────────────────────────

def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Canonical (sorted) pair key regardless of colour assignment."""
    return (min(a, b), max(a, b))


async def run_bracket_tournament(
    player_specs: list[PlayerSpec],
    player_map: dict[str, ChessPlayer],
    pairings: list[tuple[PlayerSpec, PlayerSpec]],
    fmt: str,
    tutor: TutorConfig | None = None,
    judge: "JudgeConfig | None" = None,
):
    total = len(pairings)
    game_results: list[dict] = []

    tournament_id = database.create_tournament(
        fmt=fmt,
        player_ids=[ps.model_id for ps in player_specs],
        total_games=total,
    )
    _state["tournament_id"] = tournament_id

    # Best-of-series tracking: per canonical pair, count wins for each side
    # and the total games scheduled between them.
    # Structure: {pair_key: {"wins": {model_id: int}, "scheduled": int}}
    pair_schedule: dict[tuple, dict] = {}
    for ws, bs in pairings:
        key = _pair_key(ws.model_id, bs.model_id)
        if key not in pair_schedule:
            pair_schedule[key] = {"wins": {ws.model_id: 0, bs.model_id: 0}, "scheduled": 0}
        pair_schedule[key]["scheduled"] += 1

    skipped: set[tuple] = set()   # pairs whose series is already decided

    actual_idx = 0   # games actually played (for progress display)
    with StockfishEngine() as stockfish:
        for idx, (white_spec, black_spec) in enumerate(pairings, start=1):
            await _pause_event.wait()
            if _stop_requested:
                break

            # Skip if series already clinched for this pair
            key = _pair_key(white_spec.model_id, black_spec.model_id)
            if key in skipped:
                continue

            actual_idx += 1
            white = player_map[white_spec.model_id]
            black = player_map[black_spec.model_id]

            # Refresh ELOs from DB before each game
            white.elo = database.get_player_elo(white.config.model_id)
            black.elo = database.get_player_elo(black.config.model_id)

            _state.update({
                "game_number": actual_idx,
                "white":       white.config.name,
                "black":       black.config.name,
                "white_elo":   round(white.elo),
                "black_elo":   round(black.elo),
            })
            await broadcast({"type": "tournament_status", **_state})

            print(f"\n♟  Game {actual_idx}/{total}: {white.config.name} (W) vs {black.config.name} (B)")
            try:
                summary = await play_game(white, black, stockfish, actual_idx, tutor, judge)
            except TournamentAborted:
                print("\n  Tournament stopped by user.")
                database.abort_tournament(tournament_id)
                break

            result = summary["result"]
            game_results.append({
                "white_model_id": white.config.model_id,
                "black_model_id": black.config.model_id,
                "result": result,
            })
            database.record_tournament_game(tournament_id, summary["game_id"], actual_idx,
                                            white.config.model_id, black.config.model_id)

            # Update series win counts
            ps = pair_schedule[key]
            if result == "1-0":
                ps["wins"][white_spec.model_id] = ps["wins"].get(white_spec.model_id, 0) + 1
            elif result == "0-1":
                ps["wins"][black_spec.model_id] = ps["wins"].get(black_spec.model_id, 0) + 1

            # Check if series is decided: one player has more wins than the
            # other can reach even winning all remaining games.
            games_played_in_pair = sum(
                1 for gr in game_results
                if _pair_key(gr["white_model_id"], gr["black_model_id"]) == key
            )
            remaining = ps["scheduled"] - games_played_in_pair
            wins_list = list(ps["wins"].values())
            leader = max(wins_list)
            trailer = min(wins_list)
            if remaining > 0 and leader > trailer + remaining:
                winner_id = max(ps["wins"], key=ps["wins"].get)
                winner_name = player_map[winner_id].config.name
                print(f"   Series decided: {winner_name} wins — skipping {remaining} remaining game(s)")
                skipped.add(key)

            standings = compute_standings(player_specs, game_results)
            # Attach series records to each standing row
            for row in standings:
                row["series"] = {
                    opp_id: ps["wins"]
                    for (a, b), ps in pair_schedule.items()
                    for opp_id in ([b] if a == row["model_id"] else ([a] if b == row["model_id"] else []))
                }
            _state["standings"] = standings
            await broadcast({
                "type":       "standings_update",
                "standings":  standings,
                "game_index": actual_idx,
                "total":      total,
            })

            print(
                f"   Result: {result} in {summary['moves']} moves "
                f"({summary['termination']})"
            )
            await asyncio.sleep(2)

    # ── Final standings + title ───────────────────────────────────────
    if game_results:
        final = compute_standings(player_specs, game_results)
        for row in final:
            row["series"] = {
                opp_id: ps["wins"]
                for (a, b), ps in pair_schedule.items()
                for opp_id in ([b] if a == row["model_id"] else ([a] if b == row["model_id"] else []))
            }
        winner_id = final[0]["model_id"] if final else None
        title = pick_title(winner_id, fmt) if winner_id else None
        database.finish_tournament(tournament_id, winner_id, title)
        _state.update({
            "status":    "idle",
            "standings": final,
        })
        await broadcast({
            "type":      "tournament_complete",
            "standings": final,
            "winner":    final[0] if final else None,
            "title":     title,
        })
        if final:
            print(f'\n\U0001f3c6 Tournament complete!  Winner: {final[0]["name"]} — "{title}"')
    else:
        _state["status"] = "idle"

    await broadcast({"type": "tournament_status", **_state})


# ── 2-player match runner ─────────────────────────────────────────────────

async def run_tournament(
    white: ChessPlayer,
    black: ChessPlayer,
    n_games: int,
    tutor: TutorConfig | None = None,
    judge: "JudgeConfig | None" = None,
):
    with StockfishEngine() as stockfish:
        for i in range(1, n_games + 1):
            await _pause_event.wait()
            if _stop_requested:
                break

            _state["game_number"] = i
            _state["white_elo"]   = round(white.elo)
            _state["black_elo"]   = round(black.elo)
            await broadcast({"type": "tournament_status", **_state})

            print(f"\n♟  Game {i}/{n_games}: {white.config.name} (W) vs {black.config.name} (B)")
            try:
                summary = await play_game(white, black, stockfish, i, tutor, judge)
            except TournamentAborted:
                print("\n  Tournament stopped by user.")
                break

            print(
                f"   Result: {summary['result']} in {summary['moves']} moves "
                f"({summary['termination']})"
            )
            print(
                f"   ELO → {white.config.name}: {round(white.elo)} | "
                f"{black.config.name}: {round(black.elo)}"
            )

            white, black = black, white   # alternate colors
            if not _headless:
                await asyncio.sleep(2)   # pause between games for live viewer

    _state["status"] = "idle"
    await broadcast({"type": "tournament_status", **_state})
    print("\n🏆 Tournament complete!")


# ── Player builder ────────────────────────────────────────────────────────

def build_player(
    backend: str,
    name: str,
    model_id: str,
    base_url: str | None = None,
    enable_thinking: bool = False,
    candidate_count: int | None = None,
    move_timeout: int = 0,
) -> ChessPlayer:
    db_exists = Path("nimzo.db").exists()
    config = PlayerConfig(
        name=name,
        model_id=model_id,
        backend=backend,
        base_url=base_url,
        enable_thinking=enable_thinking,
        candidate_count=candidate_count if candidate_count is not None else 5,
        move_timeout=move_timeout,
        lesson_memory=database.get_player_lessons(model_id) if db_exists else [],
        strategic_profile=database.get_strategic_profile(model_id) if db_exists else None,
    )
    if backend == "anthropic":
        player = AnthropicPlayer(config)
    elif backend == "lmstudio":
        player = LMStudioPlayer(config)
    elif backend == "human":
        player = HumanPlayer(config)
    else:
        raise ValueError(f"Unknown backend: {backend!r}")

    if db_exists:
        player.elo = database.get_player_elo(model_id)
        if player.elo != 1200.0:
            print(f"  ↑ {name} ({model_id}): restored ELO {round(player.elo)}")
    return player


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
    parser.add_argument("--white-url",     default=os.environ.get("WHITE_URL", os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")))
    parser.add_argument("--black-backend", default=os.environ.get("BLACK_BACKEND", "lmstudio"))
    parser.add_argument("--black-name",    default="")
    parser.add_argument("--black-model",   default="")   # explicit only — no env fallback
    parser.add_argument("--black-url",     default=os.environ.get("BLACK_URL",     "http://localhost:1234/v1"))
    parser.add_argument("--tutor-backend", default=os.environ.get("TUTOR_BACKEND", "lmstudio"))
    parser.add_argument("--tutor-model",   default=os.environ.get("TUTOR_MODEL",   ""))
    parser.add_argument("--tutor-url",     default=os.environ.get("TUTOR_URL",     "http://localhost:1234/v1"))
    parser.add_argument("--judge-model",   default=os.environ.get("JUDGE_MODEL",   ""),
                        help="Model for reasoning coherence scoring (defaults to tutor model)")
    parser.add_argument("--games",         type=int, default=int(os.environ.get("GAMES", 1)))
    parser.add_argument("--move-timeout",  type=int, default=0,
                        help="Per-move timeout in seconds (0 = no limit)")
    parser.add_argument("--thinking",      action="store_true", default=False,
                        help="Enable extended thinking for both players (LM Studio)")
    parser.add_argument("--headless",      action="store_true", default=False,
                        help="Run without HTTP server or browser — DB only, fast benchmarking")
    parser.add_argument("--port",          type=int, default=int(os.environ.get("PORT", 8765)))
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
        import time; time.sleep(0.4)   # brief pause for OS to release the socket

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

    if _cli_config:
        w = _cli_config.white_name or _cli_config.white_model
        b = _cli_config.black_name or _cli_config.black_model
        g = _cli_config.games
        print(f"🌐  Nimzo  →  http://localhost:{port}")
        print(f"♟   {w} vs {b}  ·  {g} game(s)")
        if _cli_config.tutor_model:
            print(f"🎓  Tutor: {_cli_config.tutor_model}")
        if _cli_config.move_timeout:
            print(f"⏱  Move timeout: {_cli_config.move_timeout}s")
    else:
        print(f"🌐  Nimzo  →  http://localhost:{port}")
        print("    Open the browser to configure and start a tournament.")

    # Auto-open browser unless suppressed or in CLI mode with --no-browser
    if not args.no_browser:
        import threading, webbrowser
        def _open_browser():
            import time; time.sleep(1.2)   # wait for uvicorn to be ready
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
