"""
SQLite persistence for Nimzo.
Players are keyed by model_id so ELO and lessons persist across name changes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


DB_PATH = Path("nimzo.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    backend     TEXT NOT NULL,
    elo         REAL DEFAULT 1200.0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS games (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    white_player_id  INTEGER REFERENCES players(id),
    black_player_id  INTEGER REFERENCES players(id),
    result           TEXT,           -- '1-0' | '0-1' | '1/2-1/2'
    termination      TEXT,           -- 'checkmate' | 'stalemate' | 'draw'
    total_moves      INTEGER,
    pgn              TEXT,
    white_elo_before REAL,
    black_elo_before REAL,
    white_elo_after  REAL,
    black_elo_after  REAL,
    played_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS moves (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id        INTEGER REFERENCES games(id),
    move_number    INTEGER,
    player_id      INTEGER REFERENCES players(id),
    move_uci       TEXT,
    move_san       TEXT,
    candidate_rank INTEGER,
    quality        TEXT,
    score_cp       REAL,
    reasoning      TEXT,
    fen_after      TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER REFERENCES players(id),
    game_id     INTEGER REFERENCES games(id),
    lesson      TEXT,
    lesson_type TEXT DEFAULT 'improve',   -- 'improve' | 'strength'
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
        conn.executescript(_SCHEMA)
        # Non-destructive migrations for existing databases
        _migrate(conn)


def _migrate(conn: sqlite3.Connection):
    # Add lesson_type column if missing (pre-v2 databases)
    try:
        conn.execute("ALTER TABLE lessons ADD COLUMN lesson_type TEXT DEFAULT 'improve'")
    except sqlite3.OperationalError:
        pass  # already exists


# ── Players ──────────────────────────────────────────────────────────────

def upsert_player(model_id: str, name: str, backend: str, elo: float = 1200.0) -> int:
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
    with get_conn() as conn:
        row = conn.execute("SELECT elo FROM players WHERE model_id = ?", (model_id,)).fetchone()
        return row["elo"] if row else 1200.0


def get_player_game_count(model_id: str) -> int:
    """Total games played by a model — used for dynamic K-factor."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM games g
            JOIN players p ON (g.white_player_id = p.id OR g.black_player_id = p.id)
            WHERE p.model_id = ?
            """,
            (model_id,),
        ).fetchone()
        return row["cnt"] if row else 0


# ── Games ────────────────────────────────────────────────────────────────

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
        conn.execute("UPDATE players SET elo = ? WHERE model_id = ?", (white_elo_after, white_model_id))
        conn.execute("UPDATE players SET elo = ? WHERE model_id = ?", (black_elo_after, black_model_id))
        return cur.lastrowid


def get_recent_games(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                g.id, g.result, g.termination, g.total_moves, g.played_at,
                wp.name AS white_name, bp.name AS black_name,
                g.white_elo_before, g.white_elo_after,
                g.black_elo_before,  g.black_elo_after
            FROM games g
            JOIN players wp ON g.white_player_id = wp.id
            JOIN players bp ON g.black_player_id = bp.id
            ORDER BY g.played_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Moves ────────────────────────────────────────────────────────────────

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


def get_game(game_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT g.*, wp.name AS white_name, bp.name AS black_name,
                   wp.model_id AS white_model_id, bp.model_id AS black_model_id
            FROM games g
            JOIN players wp ON g.white_player_id = wp.id
            JOIN players bp ON g.black_player_id = bp.id
            WHERE g.id = ?
            """,
            (game_id,),
        ).fetchone()
        return dict(row) if row else None


def get_game_moves(game_id: int) -> list[dict]:
    """All moves for a game in order, with player name and quality."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.move_number, m.move_san, m.move_uci, m.quality,
                   m.candidate_rank, m.reasoning, m.score_cp
            FROM moves m
            WHERE m.game_id = ?
            ORDER BY m.move_number ASC
            """,
            (game_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Lessons ──────────────────────────────────────────────────────────────

def record_lesson(
    player_model_id: str,
    game_id: int,
    lesson: str,
    lesson_type: str = "improve",   # "improve" | "strength"
):
    with get_conn() as conn:
        player_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO lessons (player_id, game_id, lesson, lesson_type) VALUES (?, ?, ?, ?)",
            (player_id, game_id, lesson, lesson_type),
        )


def get_player_lessons(model_id: str, limit: int = 10) -> list[str]:
    """
    Return recent lessons prefixed by type so the player prompt can bucket them.
    Format: "[improve] text" or "[strength] text"
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT l.lesson, COALESCE(l.lesson_type, 'improve') AS lesson_type
            FROM lessons l
            JOIN players p ON l.player_id = p.id
            WHERE p.model_id = ?
            ORDER BY l.created_at DESC
            LIMIT ?
            """,
            (model_id, limit),
        ).fetchall()
        return [f"[{r['lesson_type']}] {r['lesson']}" for r in rows]


# ── Leaderboard ───────────────────────────────────────────────────────────

def get_leaderboard() -> list[dict]:
    """
    Leaderboard rows include each player's 'best game' score —
    the highest per-game average move quality (mapped to 0..100)
    across all games with ≥5 quality-scored moves.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            WITH player_game_scores AS (
                SELECT
                    m.player_id,
                    m.game_id,
                    AVG(CASE m.quality
                          WHEN 'best'       THEN 100.0
                          WHEN 'excellent'  THEN 85.0
                          WHEN 'good'       THEN 70.0
                          WHEN 'inaccuracy' THEN 50.0
                          WHEN 'mistake'    THEN 25.0
                          WHEN 'blunder'    THEN 0.0
                          ELSE NULL
                        END) AS avg_q
                FROM moves m
                WHERE m.quality IS NOT NULL
                GROUP BY m.player_id, m.game_id
                HAVING COUNT(m.id) >= 5
            ),
            best_game AS (
                SELECT
                    pgs.player_id,
                    ROUND(MAX(pgs.avg_q), 1) AS best_score,
                    (SELECT pgs2.game_id
                       FROM player_game_scores pgs2
                       WHERE pgs2.player_id = pgs.player_id
                       ORDER BY pgs2.avg_q DESC, pgs2.game_id DESC
                       LIMIT 1) AS best_game_id
                FROM player_game_scores pgs
                GROUP BY pgs.player_id
            )
            SELECT
                p.name, p.model_id, p.backend, ROUND(p.elo) AS elo,
                COUNT(CASE WHEN g.white_player_id = p.id AND g.result = '1-0' THEN 1
                           WHEN g.black_player_id = p.id AND g.result = '0-1' THEN 1
                      END) AS wins,
                COUNT(CASE WHEN g.result = '1/2-1/2' THEN 1 END) AS draws,
                COUNT(CASE WHEN g.white_player_id = p.id AND g.result = '0-1' THEN 1
                           WHEN g.black_player_id = p.id AND g.result = '1-0' THEN 1
                      END) AS losses,
                COUNT(g.id)     AS total_games,
                bg.best_score   AS best_game_score,
                bg.best_game_id AS best_game_id
            FROM players p
            LEFT JOIN games g
              ON g.white_player_id = p.id OR g.black_player_id = p.id
            LEFT JOIN best_game bg ON bg.player_id = p.id
            GROUP BY p.id
            ORDER BY p.elo DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]


def get_elo_history(model_id: str) -> list[dict]:
    """ELO trajectory over time — useful for charts."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                g.played_at,
                CASE WHEN g.white_player_id = p.id THEN g.white_elo_after
                     ELSE g.black_elo_after END AS elo_after
            FROM games g
            JOIN players p ON (g.white_player_id = p.id OR g.black_player_id = p.id)
            WHERE p.model_id = ?
            ORDER BY g.played_at ASC
            """,
            (model_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Stats page queries ────────────────────────────────────────────────────

def get_player_move_stats() -> list[dict]:
    """Per-player move quality counts, avg candidate rank, blunder/mistake rates."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.name,
                p.model_id,
                COUNT(m.id)                                         AS total_moves,
                SUM(CASE WHEN m.quality='best'       THEN 1 ELSE 0 END) AS best,
                SUM(CASE WHEN m.quality='excellent'  THEN 1 ELSE 0 END) AS excellent,
                SUM(CASE WHEN m.quality='good'       THEN 1 ELSE 0 END) AS good,
                SUM(CASE WHEN m.quality='inaccuracy' THEN 1 ELSE 0 END) AS inaccuracy,
                SUM(CASE WHEN m.quality='mistake'    THEN 1 ELSE 0 END) AS mistake,
                SUM(CASE WHEN m.quality='blunder'    THEN 1 ELSE 0 END) AS blunder,
                ROUND(AVG(m.candidate_rank), 2)                     AS avg_candidate_rank
            FROM moves m
            JOIN players p ON m.player_id = p.id
            GROUP BY p.id
            ORDER BY p.elo DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]


def get_color_stats() -> list[dict]:
    """Per-player win/draw/loss split broken out by colour played."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.name,
                p.model_id,
                SUM(CASE WHEN g.white_player_id = p.id AND g.result='1-0'     THEN 1 ELSE 0 END) AS white_wins,
                SUM(CASE WHEN g.white_player_id = p.id AND g.result='1/2-1/2' THEN 1 ELSE 0 END) AS white_draws,
                SUM(CASE WHEN g.white_player_id = p.id AND g.result='0-1'     THEN 1 ELSE 0 END) AS white_losses,
                SUM(CASE WHEN g.black_player_id = p.id AND g.result='0-1'     THEN 1 ELSE 0 END) AS black_wins,
                SUM(CASE WHEN g.black_player_id = p.id AND g.result='1/2-1/2' THEN 1 ELSE 0 END) AS black_draws,
                SUM(CASE WHEN g.black_player_id = p.id AND g.result='1-0'     THEN 1 ELSE 0 END) AS black_losses
            FROM players p
            LEFT JOIN games g ON (g.white_player_id = p.id OR g.black_player_id = p.id)
            GROUP BY p.id
            ORDER BY p.elo DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]


def get_head_to_head() -> list[dict]:
    """All unique pairings with W/D/L from each player's perspective."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                wp.name  AS white_name,
                bp.name  AS black_name,
                wp.model_id AS white_model_id,
                bp.model_id AS black_model_id,
                SUM(CASE WHEN g.result='1-0'     THEN 1 ELSE 0 END) AS white_wins,
                SUM(CASE WHEN g.result='1/2-1/2' THEN 1 ELSE 0 END) AS draws,
                SUM(CASE WHEN g.result='0-1'     THEN 1 ELSE 0 END) AS black_wins,
                COUNT(*)                                              AS total
            FROM games g
            JOIN players wp ON g.white_player_id = wp.id
            JOIN players bp ON g.black_player_id = bp.id
            GROUP BY g.white_player_id, g.black_player_id
            ORDER BY total DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]
