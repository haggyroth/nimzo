"""
ECO opening detection for Nimzo.

Loads the Lichess chess-openings dataset (files a–e) on first import,
builds a FEN-prefix → (eco, name) lookup, and caches the result to
openings_cache.json so subsequent starts are instant.

Public API
----------
detect_opening(game: chess.pgn.Game) -> tuple[str, str] | None
    Returns (eco_code, opening_name) for the deepest known position
    in the game, or None if no match.
"""

from __future__ import annotations

import io
import json
import os
import chess
import chess.pgn

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "openings_cache.json")
_TSV_BASE   = "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{}.tsv"
_FILES      = list("abcde")

# Populated lazily: fen_key → {"eco": str, "name": str}
_table: dict[str, dict] = {}
_loaded = False


def _fen_key(board: chess.Board) -> str:
    """Compact position key: piece placement + side-to-move only."""
    parts = board.fen().split()
    return parts[0] + " " + parts[1]


def _load_tsv(text: str) -> list[tuple[str, str, str]]:
    """Parse a single TSV file into (eco, name, pgn_moves) tuples."""
    rows = []
    for line in text.splitlines()[1:]:   # skip header
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        eco, name, pgn_moves = parts[0], parts[1], parts[2]
        rows.append((eco, name, pgn_moves))
    return rows


def _build_table(rows: list[tuple[str, str, str]]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for eco, name, pgn_moves in rows:
        try:
            game = chess.pgn.read_game(io.StringIO(pgn_moves))
            if game is None:
                continue
            board = game.board()
            for move in game.mainline_moves():
                board.push(move)
            key = _fen_key(board)
            # Longer name wins if there's a collision (more specific line)
            if key not in table or len(name) > len(table[key]["name"]):
                table[key] = {"eco": eco, "name": name}
        except Exception:
            continue
    return table


def _ensure_loaded() -> None:
    global _table, _loaded
    if _loaded:
        return

    # Try loading from cache first
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, "r") as f:
                _table = json.load(f)
            _loaded = True
            return
        except Exception:
            pass

    # Download from Lichess
    import urllib.request
    rows: list[tuple[str, str, str]] = []
    for letter in _FILES:
        try:
            url = _TSV_BASE.format(letter)
            with urllib.request.urlopen(url, timeout=10) as resp:
                text = resp.read().decode("utf-8")
            rows.extend(_load_tsv(text))
        except Exception as e:
            print(f"  ⚠  openings: could not fetch {letter}.tsv — {e}")

    if rows:
        _table = _build_table(rows)
        try:
            with open(_CACHE_FILE, "w") as f:
                json.dump(_table, f, separators=(",", ":"))
        except Exception:
            pass

    _loaded = True


def detect_opening(game: chess.pgn.Game) -> tuple[str, str] | None:
    """
    Walk the game's mainline moves and return the deepest ECO match.
    Returns (eco_code, opening_name) or None.
    """
    _ensure_loaded()
    if not _table:
        return None

    board = game.board()
    best: tuple[str, str] | None = None

    for move in game.mainline_moves():
        board.push(move)
        key = _fen_key(board)
        if key in _table:
            entry = _table[key]
            best = (entry["eco"], entry["name"])

    return best
