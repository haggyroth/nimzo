"""
puzzle_loader.py — Load puzzle positions from a TOML file.

Kept as a standalone module (no game.py / arena imports) so tests can
import it directly without triggering the arena ↔ game.py circular import.
"""

from __future__ import annotations

import sys
from pathlib import Path


def load_puzzles(puzzles_file: str) -> list[dict]:
    """
    Load puzzles from a TOML file.

    Resolves relative paths against the directory containing this file
    (the project root).  Returns a list of dicts with keys:
      fen, solution_uci, description

    Raises:
      FileNotFoundError — file does not exist
      ValueError        — no [[puzzle]] entries, or missing required fields
      RuntimeError      — TOML library not available (Python < 3.11 without tomli)
    """
    p = Path(puzzles_file)
    if not p.is_absolute():
        # Resolve relative to the project root (directory of this file)
        p = Path(__file__).parent / puzzles_file
    if not p.exists():
        raise FileNotFoundError(f"Puzzle file not found: {p}")

    if sys.version_info >= (3, 11):
        import tomllib
        with open(p, "rb") as f:
            raw = tomllib.load(f)
    else:
        try:
            import tomli  # type: ignore[import]
            with open(p, "rb") as f:
                raw = tomli.load(f)
        except ImportError:
            raise RuntimeError(
                "TOML support requires Python 3.11+ or `pip install tomli`"
            )

    puzzles = raw.get("puzzle", [])
    if not puzzles:
        raise ValueError(f"No [[puzzle]] entries found in {p}")
    for i, pz in enumerate(puzzles):
        if "fen" not in pz or "solution_uci" not in pz:
            raise ValueError(
                f"Puzzle #{i} in {p} is missing required 'fen' or 'solution_uci' fields"
            )
    return [
        {
            "fen":          pz["fen"],
            "solution_uci": pz["solution_uci"],
            "description":  pz.get("description", f"Puzzle {i + 1}"),
        }
        for i, pz in enumerate(puzzles)
    ]
