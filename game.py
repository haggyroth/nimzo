"""
game.py — Core game loop, tournament runners, and player builder.

This module is part of the arena package. arena/__init__.py imports the public
symbols (play_game, run_two_player_tournament, etc.) after all state symbols are
already registered on the package object, making the circular import safe:

Dependency map:
    arena/__init__.py  ──imports──▶  game.py  (via routes/tournament.py)
    game.py            ──imports──▶  arena    (via `import arena as _arena` at top)
                                              safe — arena state is populated first
                                              (see arena/__init__.py import order)
"""

from __future__ import annotations  # PEP 563 — all annotations are strings at runtime

import asyncio
import hashlib
import itertools
import logging
import time
import os
import random
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

import chess
import chess.pgn

import arena as _arena   # circular-safe — see module docstring

import db as database
from engine import StockfishEngine
from models.base import ChessPlayer, MoveDecision, PlayerConfig
from models.anthropic_player import AnthropicPlayer
from models.lmstudio_player import LMStudioPlayer
from models.human_player import HumanPlayer
from providers import CLOUD_PROVIDERS
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
    is_duplicate_lesson,
    family_elo_prior,
    ACHIEVEMENT_CATALOGUE,
)

if TYPE_CHECKING:
    from arena import PlayerSpec   # type-checker only; not imported at runtime


# ── Per-model serialization lock (MN-10) ─────────────────────────────────
# LM Studio / Ollama serves one request at a time per model.  When multiple
# tournament games run concurrently (e.g. two WebSocket clients) they share the
# same local endpoint.  Sending simultaneous requests causes timeouts and
# duplicate replies.  We serialize by (base_url, model_id) pair so calls to
# *different* models are still pipelined freely.
_model_locks: dict[str, asyncio.Lock] = {}


def _get_model_lock(base_url: str, model_id: str) -> asyncio.Lock:
    """Return (creating if needed) the serialization lock for a model endpoint."""
    key = f"{base_url}|{model_id}"
    if key not in _model_locks:
        _model_locks[key] = asyncio.Lock()
    return _model_locks[key]


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
    """Return a deterministic victory title for a model/format pair."""
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
    max_moves: int = 500,
) -> dict:
    """
    Run a single game between two players and return a result dict.

    Broadcasts ``thinking``, ``move``, and ``game_over`` WebSocket events
    during play.  After the game, optionally generates tutor lessons for the
    loser and coherence scores for each move via the judge model.

    ``max_moves`` caps the game at that many half-moves (plies); the game is
    declared a draw with termination ``"move limit reached"`` if exceeded.

    Players with ``config.blind_opening_moves > 0`` have Stockfish candidates
    withheld for the first N full moves; the model must choose freely from its
    chess knowledge and the fallback on parse failure is a random legal move.

    Returns a dict with keys: result, termination, pgn, white_elo_before/after,
    black_elo_before/after, and per-move quality/coherence data.
    """
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

    # Sentinel so the post-loop code knows *why* we exited
    move_limit_hit = False

    while not board.is_game_over():
        # ── Turn cap ──────────────────────────────────────────────────────
        if board.ply() >= max_moves:
            move_limit_hit = True
            break

        # Pause / stop checks
        await _arena._pause_event.wait()
        if _arena._stop["requested"]:
            raise _arena.TournamentAborted()

        current_player = white if board.turn == chess.WHITE else black

        # ── Blind mode detection ─────────────────────────────────────────
        # Full-game blind: config.blind = True (never show candidates).
        # Opening blind: candidates withheld for first N full moves only.
        # board.fullmove_number counts full moves (1 after 1.e4, 2 after 1.e4 e5, etc.)
        is_blind = current_player.config.blind or (
            current_player.config.blind_opening_moves > 0
            and board.fullmove_number <= current_player.config.blind_opening_moves
        )

        # Run blocking Stockfish call in thread pool so event loop stays free.
        # We always fetch candidates so move-quality evaluation still works even in
        # blind mode; the list is simply withheld from the model prompt.
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
            # In blind mode the viewer gets an empty candidate list so arrows/
            # ranked moves are not shown — matching the model's information.
            "candidates": [] if is_blind else [
                {"uci": m.uci(), "san": board.san(m), "score_cp": s}
                for m, s in candidates
            ],
            "is_human_turn": is_human,
            "is_blind_move": is_blind,
            "legal_uci": current_player.get_legal_uci_moves() if is_human else [],
        })

        # Model receives empty candidate list in blind mode
        model_candidates = [] if is_blind else candidates

        # Run blocking model API call in thread pool — this is the main blocker.
        # Acquire a per-model lock first so concurrent tournament games don't
        # hammer the same LM Studio endpoint simultaneously (MN-10).
        timed_out = False
        timeout_secs = current_player.config.move_timeout or None
        _lock = _get_model_lock(
            current_player.config.base_url or "",
            current_player.config.model_id,
        )
        _t0 = time.perf_counter()
        try:
            async with _lock:
                coro = loop.run_in_executor(
                    None, current_player.choose_move, board, model_candidates, pgn_so_far
                )
                decision = await asyncio.wait_for(coro, timeout=timeout_secs)
        except asyncio.TimeoutError:
            logger.warning("%s timed out after %ss — %s", current_player.config.name, timeout_secs, "random (blind)" if is_blind else "top candidate used")
            fallback_move = random.choice(list(board.legal_moves)) if is_blind else candidates[0][0]
            decision = MoveDecision(
                move_uci=fallback_move.uci(),
                reasoning=f"(timed out after {timeout_secs}s — fell back to {'random move' if is_blind else 'top candidate'})",
                candidate_rank=0 if is_blind else 1,
                raw_response="",
            )
            timed_out = True
        except Exception as exc:
            # Model was unloaded, connection dropped, or API error mid-inference.
            # If a stop was requested, honour it cleanly; otherwise fall back so
            # the game can continue.
            if _arena._stop["requested"]:
                raise _arena.TournamentAborted()
            fallback_move = random.choice(list(board.legal_moves)) if is_blind else candidates[0][0]
            logger.warning("%s API error (%s): %s — falling back to %s", current_player.config.name, type(exc).__name__, exc, "random move" if is_blind else "top candidate")
            decision = MoveDecision(
                move_uci=fallback_move.uci(),
                reasoning=f"(API error — fell back to {'random move' if is_blind else 'top candidate'})",
                candidate_rank=0 if is_blind else 1,
                raw_response="",
            )

        elapsed_ms = round((time.perf_counter() - _t0) * 1000)

        if _arena._stop["requested"]:
            raise _arena.TournamentAborted()

        chosen_move  = chess.Move.from_uci(decision.move_uci)
        if chosen_move not in board.legal_moves:
            # Fallback of last resort — should be rare; mirrors the blind/guided logic
            chosen_move = random.choice(list(board.legal_moves)) if is_blind else candidates[0][0]

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
            "is_blind_move":  is_blind,
            "elapsed_ms":     elapsed_ms,
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
            "is_blind_move":  is_blind,
            "score_cp_white": score_cp_white,
            "elapsed_ms":     elapsed_ms,
            "fen":            board.fen(),
        })

        if not _arena._mode["headless"]:
            await asyncio.sleep(0.05)   # pacing for live viewer

    # ── Game over ──────────────────────────────────────────────────────
    if move_limit_hit:
        result      = "1/2-1/2"
        termination = "move limit reached"
    else:
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
            elapsed_ms=rec.get("elapsed_ms"),
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
            logger.info("Achievements for %s: %s", player.config.name, ", ".join(codes))

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
    _has_tutor = bool(tutor and tutor.model_id)
    _lesson_players = [
        (p, c, q) for p, c, q in [
            (white, "White", move_qualities_white),
            (black, "Black", move_qualities_black),
        ]
        if not isinstance(p, HumanPlayer)
    ]

    if _has_tutor and _lesson_players:
        await _arena.broadcast({
            "type":        "lesson_generating",
            "tutor_model": tutor.model_id,
        })

    for player, color, qualities in _lesson_players:
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
            existing = [l["lesson"] for l in database.get_all_raw_lessons(player.config.model_id)]

            saved_improve: list[str] = []
            saved_strength: list[str] = []

            for lesson in lessons["improve"]:
                if is_duplicate_lesson(lesson, existing):
                    logger.warning("Skipping duplicate lesson for %s: %s", player.config.name, lesson[:60])
                    continue
                tagged = f"[improve] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "improve", bmr)
                existing.append(lesson)
                saved_improve.append(lesson)

            for lesson in lessons["strength"]:
                if is_duplicate_lesson(lesson, existing):
                    logger.warning("Skipping duplicate lesson for %s: %s", player.config.name, lesson[:60])
                    continue
                tagged = f"[strength] {lesson}"
                player.add_lesson(tagged)
                database.record_lesson(player.config.model_id, game_id, lesson, "strength", bmr)
                existing.append(lesson)
                saved_strength.append(lesson)

            if saved_improve or saved_strength:
                await _arena.broadcast({
                    "type":     "lessons",
                    "player":   player.config.name,
                    "color":    color.lower(),
                    "improve":  saved_improve,
                    "strength": saved_strength,
                })
                logger.info("Lessons for %s:", player.config.name)
                for l in saved_improve:
                    logger.info("  improve: %s", l)
                for l in saved_strength:
                    logger.info("  strength: %s", l)

        # ── Lesson compression: every 5 games once threshold is reached ──
        game_count = database.get_player_game_count(player.config.model_id)
        lesson_count = database.get_lesson_count(player.config.model_id)
        if _has_tutor and game_count >= 5 and game_count % 5 == 0 and lesson_count >= 10:
            logger.info("Compressing %d lessons for %s (game #%d)…", lesson_count, player.config.name, game_count)
            all_lessons = database.get_all_raw_lessons(player.config.model_id)
            profile = await loop.run_in_executor(
                None, compress_lessons, all_lessons, player.config.name, game_count, tutor
            )
            if profile:
                database.set_strategic_profile(player.config.model_id, profile)
                player.config.strategic_profile = profile

    if _has_tutor and _lesson_players:
        await _arena.broadcast({"type": "lessons_saved"})

    # ── Adaptive difficulty ───────────────────────────────────────────────
    if adaptive_difficulty:
        for player in (white, black):
            rate = database.get_recent_win_rate(player.config.model_id, n=10)
            if rate is None:
                continue
            old_count = player.config.candidate_count
            if rate > _ADAPT_WIN_RATE_HIGH and old_count > _ADAPT_CANDIDATE_MIN:
                player.config.candidate_count = old_count - 1
                logger.info("%s: win rate %.0f%% -> candidates %d->%d (harder)", player.config.name, rate * 100, old_count, player.config.candidate_count)
            elif rate < _ADAPT_WIN_RATE_LOW and old_count < _ADAPT_CANDIDATE_MAX:
                player.config.candidate_count = old_count + 1
                logger.info("%s: win rate %.0f%% -> candidates %d->%d (easier)", player.config.name, rate * 100, old_count, player.config.candidate_count)

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
    max_moves: int = 0,
):
    """
    Drive a multi-player round-robin or gauntlet tournament.

    Iterates through ``pairings``, playing ``games_per_pair`` games for each
    head-to-head matchup (alternating colours).  Broadcasts live standings
    updates after each game and a final ``tournament_over`` event when done.
    """
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
            if _arena._stop["requested"]:
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

            logger.info("Game %d/%d: %s (W) vs %s (B)", actual_idx, total, white.config.name, black.config.name)
            try:
                summary = await play_game(white, black, stockfish, actual_idx, tutor, judge, adaptive_difficulty=adaptive_difficulty, max_moves=max_moves or 500)
            except _arena.TournamentAborted:
                logger.info("Tournament stopped by user.")
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
                logger.info("Series decided: %s wins — skipping %d remaining game(s)", winner_name, remaining)
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

            logger.info("Result: %s in %d moves (%s)", result, summary["moves"], summary["termination"])
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
            logger.info('Tournament complete! Winner: %s — "%s"', final[0]["name"], title)
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
    max_moves: int = 0,
):
    """
    Drive a 2-player match of ``n_games`` games, alternating colours each game.

    Broadcasts ``tournament_over`` when all games are complete or a stop is
    requested.  Handles adaptive difficulty by adjusting each player's
    ``candidate_count`` after each game based on their rolling win rate.
    """
    with StockfishEngine() as stockfish:
        for i in range(1, n_games + 1):
            await _arena._pause_event.wait()
            if _arena._stop["requested"]:
                break

            _arena._state.update({"game_number": i, "white_elo": round(white.elo), "black_elo": round(black.elo)})
            await _arena.broadcast({"type": "tournament_status", **_arena._state})

            logger.info("Game %d/%d: %s (W) vs %s (B)", i, n_games, white.config.name, black.config.name)
            try:
                summary = await play_game(white, black, stockfish, i, tutor, judge, adaptive_difficulty=adaptive_difficulty, max_moves=max_moves or 500)
            except _arena.TournamentAborted:
                logger.info("Tournament stopped by user.")
                break

            logger.info("Result: %s in %d moves (%s)", summary["result"], summary["moves"], summary["termination"])
            logger.info("ELO -> %s: %d | %s: %d", white.config.name, round(white.elo), black.config.name, round(black.elo))

            white, black = black, white   # alternate colors
            if not _arena._mode["headless"]:
                await asyncio.sleep(2)   # pause between games for live viewer

    _arena._state["status"] = "idle"
    await _arena.broadcast({"type": "tournament_status", **_arena._state})
    logger.info("Tournament complete!")


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
    blind_opening_moves: int = 0,
    blind: bool = False,
) -> ChessPlayer:
    """
    Construct the correct ``ChessPlayer`` subclass for the given backend.

    Loads any existing lesson memory and strategic profile from the DB if
    a player record already exists.  Supports backends: ``"lmstudio"``,
    ``"anthropic"``, ``"human"``, and any key in ``CLOUD_PROVIDERS``
    (``"openai"``, ``"deepseek"``, ``"qwen"``, ``"gemini"``, ``"xai"``).
    """
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
        blind_opening_moves=blind_opening_moves,
        blind=blind,
        lesson_memory=database.get_player_lessons(model_id) if db_exists else [],
        strategic_profile=database.get_strategic_profile(model_id) if db_exists else None,
    )
    if backend == "anthropic":
        player = AnthropicPlayer(config)
    elif backend == "lmstudio":
        player = LMStudioPlayer(config)
    elif backend == "human":
        player = HumanPlayer(config)
    elif backend in CLOUD_PROVIDERS:
        info = CLOUD_PROVIDERS[backend]
        config.base_url = base_url or info["base_url"]
        config.api_key  = os.environ.get(info["key_env"], "")
        player = LMStudioPlayer(config)
    else:
        raise ValueError(f"Unknown backend: {backend!r}")

    if db_exists:
        player.elo = database.get_player_elo(model_id)
        if player.elo != 1200.0:
            logger.info("%s (%s): restored ELO %d", name, model_id, round(player.elo))
    else:
        prior = family_elo_prior(model_id)
        if prior != 0.0:
            player.elo = 1200.0 + prior
            logger.info("%s: new player, family prior %+.0f -> starting ELO %d", name, prior, round(player.elo))
    return player
