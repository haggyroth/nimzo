"""
game.py — Core game loop, tournament runners, and player builder.

This module is imported by arena.py (which provides the WebSocket broadcast
infrastructure and shared state).  The apparent circular import is intentional
and safe: arena.py adds `from game import ...` at the very bottom of its module
body, so by the time Python executes that line, every name this module reads via
`import arena as _arena` is already defined.

Dependency map:
    arena.py  ──imports──▶  game.py   (via `from game import ...` at bottom)
    game.py   ──imports──▶  arena     (via `import arena as _arena` at top)
                                       safe because arena defs precede the import
"""

from __future__ import annotations  # PEP 563 — all annotations are strings at runtime

import asyncio
import itertools
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import chess
import chess.pgn

import arena as _arena   # circular-safe — see module docstring

import db as database
from engine import StockfishEngine
from models.base import ChessPlayer, MoveDecision, PlayerConfig
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
    detect_opening_depth,
    evaluate_achievements,
    score_reasoning_coherence,
    ACHIEVEMENT_CATALOGUE,
)

if TYPE_CHECKING:
    from arena import PlayerSpec   # type-checker only; not imported at runtime


# ── Adaptive difficulty constants ─────────────────────────────────────────
# Also re-exported so arena.py (and CLAUDE.md) can reference them there.
_ADAPT_CANDIDATE_MIN = 3
_ADAPT_CANDIDATE_MAX = 10
_ADAPT_WIN_RATE_HIGH = 0.65   # reduce candidates (harder) above this win rate
_ADAPT_WIN_RATE_LOW  = 0.35   # increase candidates (easier) below this win rate


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

def generate_pairings(
    player_specs: list[PlayerSpec],
    fmt: str,
    games_per_pair: int,
) -> list[tuple[PlayerSpec, PlayerSpec]]:
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
        pairs = list(itertools.combinations(player_specs, 2))
        for g in range(games_per_pair):
            for (a, b) in pairs:
                if g % 2 == 0:
                    pairings.append((a, b))
                else:
                    pairings.append((b, a))
    return pairings


def compute_standings(
    player_specs: list[PlayerSpec],
    results: list[dict],
) -> list[dict]:
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


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Canonical (sorted) pair key regardless of colour assignment."""
    return (min(a, b), max(a, b))


# ── Core game loop ────────────────────────────────────────────────────────

async def play_game(
    white: ChessPlayer,
    black: ChessPlayer,
    stockfish: StockfishEngine,
    game_number: int,
    tutor: TutorConfig | None = None,
    judge: JudgeConfig | None = None,
    adaptive_difficulty: bool = False,
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

    await _arena.broadcast({
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

    loop = asyncio.get_running_loop()

    while not board.is_game_over():
        # Pause / stop checks
        await _arena._pause_event.wait()
        if _arena._stop_requested:
            raise _arena.TournamentAborted()

        current_player = white if board.turn == chess.WHITE else black

        # Run blocking Stockfish call in thread pool so event loop stays free
        try:
            candidates = await loop.run_in_executor(
                None, stockfish.get_candidates, board, current_player.config.candidate_count
            )
        except Exception:
            # Stockfish died (e.g. Ctrl+C sent SIGINT to the subprocess).
            # Treat as a clean stop rather than crashing with a traceback.
            raise _arena.TournamentAborted() from None
        if not candidates:
            break

        exporter = chess.pgn.StringExporter(headers=False)
        game.accept(exporter)
        pgn_so_far = str(exporter)

        is_human = isinstance(current_player, HumanPlayer)
        await _arena.broadcast({
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
            if _arena._stop_requested:
                raise _arena.TournamentAborted()
            print(f"  ⚠  {current_player.config.name} API error ({type(exc).__name__}): {exc} — falling back to top candidate")
            decision = MoveDecision(
                move_uci=candidates[0][0].uci(),
                reasoning="(API error — fell back to top candidate)",
                candidate_rank=1,
                raw_response="",
            )

        if _arena._stop_requested:
            raise _arena.TournamentAborted()

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

        await _arena.broadcast({
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

        if not _arena._headless:
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

    await _arena.broadcast({
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

            await _arena.broadcast({
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

    # ── Adaptive difficulty ───────────────────────────────────────────────
    if adaptive_difficulty:
        for player in (white, black):
            rate = database.get_recent_win_rate(player.config.model_id, n=10)
            if rate is None:
                continue
            old_count = player.config.candidate_count
            if rate > _ADAPT_WIN_RATE_HIGH and old_count > _ADAPT_CANDIDATE_MIN:
                player.config.candidate_count = old_count - 1
                print(f"  📉 {player.config.name}: win rate {rate:.0%} → candidates {old_count}→{player.config.candidate_count}")
            elif rate < _ADAPT_WIN_RATE_LOW and old_count < _ADAPT_CANDIDATE_MAX:
                player.config.candidate_count = old_count + 1
                print(f"  📈 {player.config.name}: win rate {rate:.0%} → candidates {old_count}→{player.config.candidate_count}")

    return {
        "game_id":     game_id,
        "result":      result,
        "termination": termination,
        "moves":       move_number,
    }


# ── Multi-player bracket runner ───────────────────────────────────────────

async def run_bracket_tournament(
    player_specs: list[PlayerSpec],
    player_map: dict[str, ChessPlayer],
    pairings: list[tuple[PlayerSpec, PlayerSpec]],
    fmt: str,
    tutor: TutorConfig | None = None,
    judge: JudgeConfig | None = None,
    adaptive_difficulty: bool = False,
):
    total = len(pairings)
    game_results: list[dict] = []

    tournament_id = database.create_tournament(
        format=fmt,
        player_ids=[ps.model_id for ps in player_specs],
        total_games=total,
    )
    _arena._state["tournament_id"] = tournament_id

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
            await _arena._pause_event.wait()
            if _arena._stop_requested:
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

            _arena._state.update({
                "game_number": actual_idx,
                "white":       white.config.name,
                "black":       black.config.name,
                "white_elo":   round(white.elo),
                "black_elo":   round(black.elo),
            })
            await _arena.broadcast({"type": "tournament_status", **_arena._state})

            print(f"\n♟  Game {actual_idx}/{total}: {white.config.name} (W) vs {black.config.name} (B)")
            try:
                summary = await play_game(white, black, stockfish, actual_idx, tutor, judge, adaptive_difficulty=adaptive_difficulty)
            except _arena.TournamentAborted:
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

            # Check if series is decided
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
            _arena._state["standings"] = standings
            await _arena.broadcast({
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
        _arena._state.update({"status": "idle", "standings": final})
        await _arena.broadcast({
            "type":      "tournament_complete",
            "standings": final,
            "winner":    final[0] if final else None,
            "title":     title,
        })
        if final:
            print(f'\n\U0001f3c6 Tournament complete!  Winner: {final[0]["name"]} — "{title}"')
    else:
        _arena._state["status"] = "idle"

    await _arena.broadcast({"type": "tournament_status", **_arena._state})


# ── 2-player match runner ─────────────────────────────────────────────────

async def run_tournament(
    white: ChessPlayer,
    black: ChessPlayer,
    n_games: int,
    tutor: TutorConfig | None = None,
    judge: JudgeConfig | None = None,
    adaptive_difficulty: bool = False,
):
    with StockfishEngine() as stockfish:
        for i in range(1, n_games + 1):
            await _arena._pause_event.wait()
            if _arena._stop_requested:
                break

            _arena._state.update({"game_number": i, "white_elo": round(white.elo), "black_elo": round(black.elo)})
            await _arena.broadcast({"type": "tournament_status", **_arena._state})

            print(f"\n♟  Game {i}/{n_games}: {white.config.name} (W) vs {black.config.name} (B)")
            try:
                summary = await play_game(white, black, stockfish, i, tutor, judge, adaptive_difficulty=adaptive_difficulty)
            except _arena.TournamentAborted:
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
            if not _arena._headless:
                await asyncio.sleep(2)   # pause between games for live viewer

    _arena._state["status"] = "idle"
    await _arena.broadcast({"type": "tournament_status", **_arena._state})
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
    style: str = "",
) -> ChessPlayer:
    db_exists = (Path(__file__).parent / "nimzo.db").exists()
    config = PlayerConfig(
        name=name,
        model_id=model_id,
        backend=backend,
        base_url=base_url,
        enable_thinking=enable_thinking,
        candidate_count=candidate_count if candidate_count is not None else 5,
        move_timeout=move_timeout,
        style=style,
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
