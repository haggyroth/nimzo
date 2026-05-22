"""
SQLite persistence for Nimzo.
Stores: games, moves (with quality labels), ELO history, lesson memory.

Players are keyed by model_id so ELO and lessons persist across name changes.
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


DB_PATH = Path("nimzo.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    backend     TEXT NOT NULL,
    elo         REAL DEFAULT 1200.0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    white_player_id INTEGER REFERENCES players(id),
    black_player_id INTEGER REFERENCES players(id),
    result          TEXT,           -- '1-0' | '0-1' | '1/2-1/2'
    termination     TEXT,           -- 'checkmate' | 'stalemate' | 'draw'
    total_moves     INTEGER,
    pgn             TEXT,
    white_elo_before REAL,
    black_elo_before REAL,
    white_elo_after  REAL,
    black_elo_after  REAL,
    played_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         INTEGER REFERENCES games(id),
    move_number     INTEGER,
    player_id       INTEGER REFERENCES players(id),
    move_uci        TEXT,
    move_san        TEXT,
    candidate_rank  INTEGER,
    quality         TEXT,
    score_cp        REAL,
    reasoning       TEXT,
    fen_after       TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER REFERENCES players(id),
    game_id     INTEGER REFERENCES games(id),
    lesson      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_conn(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH):
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


# ── Players ─────────────────────────────────────────────────────────────────

def upsert_player(model_id: str, name: str, backend: str, elo: float = 1200.0) -> int:
    """Insert or update a player record, keyed by model_id."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO players (model_id, name, backend, elo)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
                name    = excluded.name,
                backend = excluded.backend,
                elo     = excluded.elo
            """,
            (model_id, name, backend, elo),
        )
        row = conn.execute("SELECT id FROM players WHERE model_id = ?", (model_id,)).fetchone()
        return row["id"]


def get_player_elo(model_id: str) -> float:
    """Return the stored ELO for a model, or 1200 if unseen."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT elo FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        return row["elo"] if row else 1200.0


# ── Games ────────────────────────────────────────────────────────────────────

def record_game(
    white_model_id: str,
    black_model_id: str,
    result: str,
    termination: str,
    total_moves: int,
    pgn: str,
    white_elo_before: float,
    black_elo_before: float,
    white_elo_after: float,
    black_elo_after: float,
) -> int:
    with get_conn() as conn:
        white_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (white_model_id,)
        ).fetchone()["id"]
        black_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (black_model_id,)
        ).fetchone()["id"]

        cur = conn.execute(
            """
            INSERT INTO games
              (white_player_id, black_player_id, result, termination,
               total_moves, pgn,
               white_elo_before, black_elo_before,
               white_elo_after,  black_elo_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                white_id, black_id, result, termination,
                total_moves, pgn,
                white_elo_before, black_elo_before,
                white_elo_after,  black_elo_after,
            ),
        )
        conn.execute(
            "UPDATE players SET elo = ? WHERE model_id = ?", (white_elo_after, white_model_id)
        )
        conn.execute(
            "UPDATE players SET elo = ? WHERE model_id = ?", (black_elo_after, black_model_id)
        )
        return cur.lastrowid


# ── Moves ────────────────────────────────────────────────────────────────────

def record_move(
    game_id: int,
    move_number: int,
    player_model_id: str,
    move_uci: str,
    move_san: str,
    candidate_rank: int,
    quality: str,
    score_cp: Optional[float],
    reasoning: str,
    fen_after: str,
):
    with get_conn() as conn:
        player_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO moves
              (game_id, move_number, player_id, move_uci, move_san,
               candidate_rank, quality, score_cp, reasoning, fen_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id, move_number, player_id, move_uci, move_san,
                candidate_rank, quality, score_cp, reasoning, fen_after,
            ),
        )


# ── Lessons ──────────────────────────────────────────────────────────────────

def record_lesson(player_model_id: str, game_id: int, lesson: str):
    with get_conn() as conn:
        player_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO lessons (player_id, game_id, lesson) VALUES (?, ?, ?)",
            (player_id, game_id, lesson),
        )


def get_player_lessons(model_id: str, limit: int = 10) -> list[str]:
    """Return the most recent lessons for a model."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT l.lesson FROM lessons l
            JOIN players p ON l.player_id = p.id
            WHERE p.model_id = ?
            ORDER BY l.created_at DESC
            LIMIT ?
            """,
            (model_id, limit),
        ).fetchall()
        return [r["lesson"] for r in rows]


# ── Leaderboard ──────────────────────────────────────────────────────────────

def get_leaderboard() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.name, p.model_id, p.backend, p.elo,
                COUNT(CASE WHEN g.white_player_id = p.id AND g.result = '1-0' THEN 1
                           WHEN g.black_player_id = p.id AND g.result = '0-1' THEN 1
                      END) AS wins,
                COUNT(CASE WHEN g.result = '1/2-1/2' THEN 1 END) AS draws,
                COUNT(g.id) AS total_games
            FROM players p
            LEFT JOIN games g
              ON g.white_player_id = p.id OR g.black_player_id = p.id
            GROUP BY p.id
            ORDER BY p.elo DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
