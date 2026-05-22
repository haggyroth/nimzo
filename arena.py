"""
Nimzo — Main Orchestrator

Runs games between two players in guided mode.
Broadcasts real-time state over WebSocket so the visualizer can watch live.

Usage:
    python arena.py --white anthropic --black lmstudio --games 10
"""

import os
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import argparse
import chess
import chess.pgn
import chess.engine
from datetime import datetime
from pathlib import Path
import websockets
import websockets.server

from engine import StockfishEngine
from models.base import ChessPlayer, PlayerConfig
from models.anthropic_player import AnthropicPlayer
from models.lmstudio_player import LMStudioPlayer
from analysis import calculate_elos, generate_lessons, build_quality_summary
import db as database


# ── WebSocket broadcast ─────────────────────────────────────────────────

connected_clients: set = set()


async def broadcast(event: dict):
    """Send JSON event to all connected visualizer clients."""
    if not connected_clients:
        return
    msg = json.dumps(event)
    await asyncio.gather(
        *[client.send(msg) for client in connected_clients],
        return_exceptions=True,
    )


async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)


# ── Game loop ───────────────────────────────────────────────────────────

async def play_game(
    white: ChessPlayer,
    black: ChessPlayer,
    stockfish: StockfishEngine,
    game_number: int,
) -> dict:
    board = chess.Board()
    game = chess.pgn.Game()
    game.headers["White"] = white.config.name
    game.headers["Black"] = black.config.name
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    node = game

    move_qualities_white: list[tuple[str, str]] = []
    move_qualities_black: list[tuple[str, str]] = []
    move_records = []

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

    while not board.is_game_over():
        current_player = white if board.turn == chess.WHITE else black

        # Get Stockfish candidates
        candidates = stockfish.get_candidates(board, n=current_player.config.candidate_count)
        if not candidates:
            break

        # Build PGN string for context
        exporter = chess.pgn.StringExporter(headers=False)
        game.accept(exporter)
        pgn_so_far = str(exporter)

        # Broadcast thinking state
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

        # Model chooses a move
        decision = current_player.choose_move(board, candidates, pgn_so_far)

        # Validate
        chosen_move = chess.Move.from_uci(decision.move_uci)
        if chosen_move not in board.legal_moves:
            chosen_move = candidates[0][0]  # Fallback

        # Evaluate quality
        quality = stockfish.evaluate_move_quality(board, chosen_move, candidates)
        san = board.san(chosen_move)

        if board.turn == chess.WHITE:
            move_qualities_white.append((san, quality))
        else:
            move_qualities_black.append((san, quality))

        # Apply move
        board.push(chosen_move)
        node = node.add_variation(chosen_move)
        move_number += 1

        # Score after move (negate because board.turn flipped)
        score_after = None
        if candidates:
            _, top_score = candidates[0]
            if top_score is not None:
                score_after = -top_score if chosen_move == candidates[0][0] else None

        move_records.append({
            "move_number": move_number,
            "player_model_id": current_player.config.model_id,
            "player_name": current_player.config.name,
            "move_uci": chosen_move.uci(),
            "move_san": san,
            "candidate_rank": decision.candidate_rank,
            "quality": quality,
            "score_cp": score_after,
            "reasoning": decision.reasoning,
            "fen_after": board.fen(),
        })

        await broadcast({
            "type": "move",
            "move_number": move_number,
            "player": current_player.config.name,
            "color": "white" if not board.turn else "black",  # flipped after push
            "san": san,
            "uci": chosen_move.uci(),
            "quality": quality,
            "candidate_rank": decision.candidate_rank,
            "reasoning": decision.reasoning,
            "fen": board.fen(),
        })

        await asyncio.sleep(0.1)  # Small delay so visualizer can keep up

    # ── Game over ──────────────────────────────────────────────────────
    result = board.result()
    termination = (
        "checkmate" if board.is_checkmate()
        else "stalemate" if board.is_stalemate()
        else "draw"
    )

    game.headers["Result"] = result
    pgn_string = str(game)

    # ELO
    w_elo_before = white.elo
    b_elo_before = black.elo
    w_elo_after, b_elo_after = calculate_elos(w_elo_before, b_elo_before, result)
    white.update_elo(w_elo_after)
    black.update_elo(b_elo_after)

    # Persist
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

    # Adaptive lessons for the loser (or both if draw)
    if result == "1-0":
        loser, loser_color = black, "Black"
        loser_qualities = move_qualities_black
    elif result == "0-1":
        loser, loser_color = white, "White"
        loser_qualities = move_qualities_white
    else:
        loser = loser_color = loser_qualities = None

    if loser is not None:
        quality_summary = build_quality_summary(loser_qualities)
        lessons = generate_lessons(
            pgn=pgn_string,
            loser_name=loser.config.name,
            loser_color=loser_color,
            result=result,
            termination=termination,
            quality_summary=quality_summary,
        )
        for lesson in lessons:
            loser.add_lesson(lesson)
            database.record_lesson(loser.config.model_id, game_id, lesson)

        print(f"\n📚 Lessons for {loser.config.name}:")
        for l in lessons:
            print(f"  - {l}")

    await broadcast({
        "type": "game_over",
        "result": result,
        "termination": termination,
        "total_moves": move_number,
        "white_elo_after": round(w_elo_after),
        "black_elo_after": round(b_elo_after),
        "pgn": pgn_string,
    })

    return {
        "game_id": game_id,
        "result": result,
        "termination": termination,
        "moves": move_number,
    }


# ── Tournament runner ───────────────────────────────────────────────────

async def run_tournament(white: ChessPlayer, black: ChessPlayer, n_games: int):
    database.init_db()

    ws_port = int(os.environ.get("WS_PORT", 8765))
    ws_server = await websockets.serve(ws_handler, "localhost", ws_port)
    print(f"🔌 WebSocket server on ws://localhost:{ws_port} — open the visualizer now")

    with StockfishEngine() as stockfish:
        for i in range(1, n_games + 1):
            print(f"\n♟️  Game {i}/{n_games}: {white.config.name} (W) vs {black.config.name} (B)")
            summary = await play_game(white, black, stockfish, i)
            print(
                f"   Result: {summary['result']} in {summary['moves']} moves "
                f"({summary['termination']})"
            )
            print(
                f"   ELO → {white.config.name}: {round(white.elo)} | "
                f"{black.config.name}: {round(black.elo)}"
            )

            # Alternate colors each game
            white, black = black, white

            await asyncio.sleep(2)  # Pause between games

    ws_server.close()
    await ws_server.wait_closed()
    print("\n🏆 Tournament complete!")


# ── Entry point ─────────────────────────────────────────────────────────

def build_player(
    backend: str,
    name: str,
    model_id: str,
    base_url: str = None,
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
        raise ValueError(f"Unknown backend: {backend}")

    # Restore ELO from previous games
    if db_exists:
        player.elo = database.get_player_elo(model_id)
        if player.elo != 1200.0:
            print(f"  ↑ {name} ({model_id}): restored ELO {round(player.elo)}")

    return player


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nimzo")
    parser.add_argument("--white-backend", default=os.environ.get("WHITE_BACKEND", "lmstudio"))
    parser.add_argument("--white-name",    default=os.environ.get("WHITE_NAME",    "White"))
    parser.add_argument("--white-model",   default=os.environ.get("WHITE_MODEL",   ""))
    parser.add_argument("--white-url",     default=os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--black-backend", default=os.environ.get("BLACK_BACKEND", "lmstudio"))
    parser.add_argument("--black-name",    default=os.environ.get("BLACK_NAME",    "Black"))
    parser.add_argument("--black-model",   default=os.environ.get("BLACK_MODEL",   ""))
    parser.add_argument("--black-url",     default=os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"))
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--thinking", action="store_true", default=False,
                        help="Enable extended thinking for LM Studio models (slower but more deliberate)")
    args = parser.parse_args()

    white_player = build_player(args.white_backend, args.white_name, args.white_model, args.white_url, args.thinking)
    black_player = build_player(args.black_backend, args.black_name, args.black_model, args.black_url, args.thinking)

    asyncio.run(run_tournament(white_player, black_player, args.games))
