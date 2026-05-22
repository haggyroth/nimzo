"""
Nimzo — Orchestrator + HTTP/WebSocket server

Serves the viewer at http://localhost:8765/ and exposes a REST API for
tournament control. WebSocket events stream to the viewer at /ws.

Usage (CLI mode — starts tournament immediately):
    python arena.py \
      --white-name Qwen --white-model qwen3-coder-30b --white-url http://localhost:1234/v1 \
      --black-name Llama --black-model llama-3.1-70b  --black-url http://localhost:1235/v1 \
      --tutor-model qwen3-coder-30b --tutor-url http://localhost:1234/v1 \
      --games 20

Usage (server mode — configure via browser UI):
    python arena.py
    open http://localhost:8765
"""

from __future__ import annotations

import os
import asyncio
import json
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
from pydantic import BaseModel
import uvicorn

from engine import StockfishEngine
from models.base import ChessPlayer, PlayerConfig
from models.anthropic_player import AnthropicPlayer
from models.lmstudio_player import LMStudioPlayer
from analysis import TutorConfig, calculate_elos, generate_lessons, build_quality_summary
import db as database


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
}

# Set from CLI args before server start; triggers auto-start in lifespan
_cli_config: "TournamentStartConfig | None" = None


# ── Tournament abort signal ───────────────────────────────────────────────

class TournamentAborted(Exception):
    pass


# ── FastAPI app ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    if _cli_config is not None:
        asyncio.create_task(_auto_start(_cli_config))
    yield

app = FastAPI(title="Nimzo", lifespan=lifespan)


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
    if not _connected_clients:
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


@app.get("/api/games")
async def api_games(limit: int = 20):
    return database.get_recent_games(limit)


@app.get("/api/models")
async def api_models(url: str = "http://localhost:1234/v1"):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/models")
            return resp.json()
    except Exception as exc:
        return {"data": [], "error": str(exc)}


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
    games: int = 10


@app.post("/api/tournament/start")
async def api_start(config: TournamentStartConfig):
    global _tournament_task, _stop_requested
    if _tournament_task and not _tournament_task.done():
        return {"error": "A tournament is already running"}

    _stop_requested = False
    _pause_event.set()

    white  = build_player(config.white_backend, config.white_name, config.white_model, config.white_url, config.white_thinking)
    black  = build_player(config.black_backend, config.black_name, config.black_model, config.black_url, config.black_thinking)
    tutor  = TutorConfig(backend=config.tutor_backend, model_id=config.tutor_model, base_url=config.tutor_url)

    _state.update({
        "status": "running",
        "game_number": 0,
        "total_games": config.games,
        "white": config.white_name,
        "black": config.black_name,
        "white_elo": round(white.elo),
        "black_elo": round(black.elo),
    })
    await broadcast({"type": "tournament_status", **_state})

    _tournament_task = asyncio.create_task(run_tournament(white, black, config.games, tutor))
    return {"ok": True}


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
        candidates = await loop.run_in_executor(
            None, stockfish.get_candidates, board, current_player.config.candidate_count
        )
        if not candidates:
            break

        exporter = chess.pgn.StringExporter(headers=False)
        game.accept(exporter)
        pgn_so_far = str(exporter)

        await broadcast({
            "type": "thinking",
            "player": current_player.config.name,
            "color": "white" if board.turn == chess.WHITE else "black",
            "fen": board.fen(),
            "candidates": [
                {"uci": m.uci(), "san": board.san(m), "score_cp": s}
                for m, s in candidates
            ],
        })

        # Run blocking model API call in thread pool — this is the main blocker
        try:
            decision = await loop.run_in_executor(
                None, current_player.choose_move, board, candidates, pgn_so_far
            )
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
            "fen_after":      board.fen(),
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
            "score_cp_white": score_cp_white,
            "fen":            board.fen(),
        })

        await asyncio.sleep(0.05)

    # ── Game over ──────────────────────────────────────────────────────
    result      = board.result()
    termination = (
        "checkmate" if board.is_checkmate()
        else "stalemate" if board.is_stalemate()
        else "draw"
    )

    game.headers["Result"] = result
    pgn_string = str(game)

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
            fen_after=rec["fen_after"],
        )

    await broadcast({
        "type":            "game_over",
        "result":          result,
        "termination":     termination,
        "total_moves":     move_number,
        "white_elo_after": round(w_elo_after),
        "black_elo_after": round(b_elo_after),
        "pgn":             pgn_string,
    })

    # ── Lessons for both players ───────────────────────────────────────
    for player, color, qualities in [
        (white, "White", move_qualities_white),
        (black, "Black", move_qualities_black),
    ]:
        quality_summary = build_quality_summary(qualities)
        lessons = generate_lessons(
            pgn=pgn_string,
            player_name=player.config.name,
            player_color=color,
            result=result,
            termination=termination,
            quality_summary=quality_summary,
            tutor=tutor,
        )

        if lessons["improve"] or lessons["strength"]:
            for lesson in lessons["improve"]:
                tagged = f"[improve] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "improve")
            for lesson in lessons["strength"]:
                tagged = f"[strength] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "strength")

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

    return {
        "game_id":     game_id,
        "result":      result,
        "termination": termination,
        "moves":       move_number,
    }


# ── Tournament runner ─────────────────────────────────────────────────────

async def run_tournament(
    white: ChessPlayer,
    black: ChessPlayer,
    n_games: int,
    tutor: TutorConfig | None = None,
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
                summary = await play_game(white, black, stockfish, i, tutor)
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
            await asyncio.sleep(2)

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
) -> ChessPlayer:
    db_exists = Path("nimzo.db").exists()
    config = PlayerConfig(
        name=name,
        model_id=model_id,
        backend=backend,
        base_url=base_url,
        enable_thinking=enable_thinking,
        lesson_memory=database.get_player_lessons(model_id) if db_exists else [],
    )
    if backend == "anthropic":
        player = AnthropicPlayer(config)
    elif backend == "lmstudio":
        player = LMStudioPlayer(config)
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nimzo chess tournament server")
    parser.add_argument("--white-backend", default=os.environ.get("WHITE_BACKEND", "lmstudio"))
    parser.add_argument("--white-name",    default=os.environ.get("WHITE_NAME",    "White"))
    parser.add_argument("--white-model",   default=os.environ.get("WHITE_MODEL",   ""))
    parser.add_argument("--white-url",     default=os.environ.get("WHITE_URL",     "http://localhost:1234/v1"))
    parser.add_argument("--black-backend", default=os.environ.get("BLACK_BACKEND", "lmstudio"))
    parser.add_argument("--black-name",    default=os.environ.get("BLACK_NAME",    "Black"))
    parser.add_argument("--black-model",   default=os.environ.get("BLACK_MODEL",   ""))
    parser.add_argument("--black-url",     default=os.environ.get("BLACK_URL",     "http://localhost:1235/v1"))
    parser.add_argument("--tutor-backend", default=os.environ.get("TUTOR_BACKEND", "lmstudio"))
    parser.add_argument("--tutor-model",   default=os.environ.get("TUTOR_MODEL",   ""))
    parser.add_argument("--tutor-url",     default=os.environ.get("TUTOR_URL",     "http://localhost:1234/v1"))
    parser.add_argument("--games",         type=int, default=int(os.environ.get("GAMES", 10)))
    parser.add_argument("--thinking",      action="store_true", default=False,
                        help="Enable extended thinking for both players (LM Studio)")
    parser.add_argument("--port",          type=int, default=int(os.environ.get("PORT", 8765)))
    args = parser.parse_args()

    port = args.port
    print(f"🌐  Nimzo server → http://localhost:{port}")

    if args.white_model and args.black_model:
        _cli_config = TournamentStartConfig(
            white_backend=args.white_backend,
            white_name=args.white_name,
            white_model=args.white_model,
            white_url=args.white_url,
            white_thinking=args.thinking,
            black_backend=args.black_backend,
            black_name=args.black_name,
            black_model=args.black_model,
            black_url=args.black_url,
            black_thinking=args.thinking,
            tutor_backend=args.tutor_backend,
            tutor_model=args.tutor_model,
            tutor_url=args.tutor_url,
            games=args.games,
        )
        print(f"    {args.white_name} vs {args.black_name}  ({args.games} games)")
        if args.tutor_model:
            print(f"    Tutor: {args.tutor_model} @ {args.tutor_url}")
    else:
        print("    No players configured — open the viewer to set up a tournament.")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
