"""
SQLite persistence for Nimzo.
Players are keyed by model_id so ELO and lessons persist across name changes.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent / "nimzo.db"


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
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          INTEGER REFERENCES games(id),
    move_number      INTEGER,
    player_id        INTEGER REFERENCES players(id),
    move_uci         TEXT,
    move_san         TEXT,
    candidate_rank   INTEGER,
    quality          TEXT,
    score_cp         REAL,
    reasoning        TEXT,
    fen_after        TEXT,
    thinking_content TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER REFERENCES players(id),
    game_id     INTEGER REFERENCES games(id),
    lesson      TEXT,
    lesson_type TEXT DEFAULT 'improve',   -- 'improve' | 'strength'
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS achievements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER REFERENCES players(id),
    game_id     INTEGER REFERENCES games(id),
    code        TEXT NOT NULL,
    awarded_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(player_id, game_id, code)
);

CREATE TABLE IF NOT EXISTS tournaments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    format          TEXT NOT NULL,   -- 'round_robin' | 'gauntlet' | 'match'
    status          TEXT DEFAULT 'running',  -- 'running' | 'finished' | 'aborted'
    player_ids      TEXT,            -- JSON list of model_ids in seeding order
    total_games     INTEGER DEFAULT 0,
    winner_model_id TEXT,
    title           TEXT,            -- fun winner title
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS tournament_games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id   INTEGER REFERENCES tournaments(id),
    game_id         INTEGER REFERENCES games(id),
    game_index      INTEGER,         -- 1-based position in schedule
    white_model_id  TEXT,
    black_model_id  TEXT
);

CREATE TABLE IF NOT EXISTS puzzle_gauntlets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    status          TEXT DEFAULT 'running',   -- 'running' | 'finished' | 'aborted'
    player_model_ids TEXT,                    -- JSON list of model_ids
    puzzle_count    INTEGER DEFAULT 0,
    puzzles_file    TEXT DEFAULT 'positions.toml',
    candidate_count INTEGER DEFAULT 5,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS puzzle_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gauntlet_id     INTEGER REFERENCES puzzle_gauntlets(id),
    player_id       INTEGER REFERENCES players(id),
    puzzle_index    INTEGER,    -- 0-based
    puzzle_fen      TEXT,
    solution_uci    TEXT,
    chosen_uci      TEXT,
    solved          INTEGER,    -- 1 = correct, 0 = wrong
    candidate_rank  INTEGER,    -- rank of chosen move in candidate list (0 = not in list)
    elapsed_ms      INTEGER,
    reasoning       TEXT,
    played_at       TEXT DEFAULT (datetime('now'))
);

-- Indexes on frequently-queried foreign keys and sort columns (MN-3).
-- IF NOT EXISTS makes these safe to add to an existing database.
CREATE INDEX IF NOT EXISTS idx_moves_game      ON moves(game_id);
CREATE INDEX IF NOT EXISTS idx_moves_player    ON moves(player_id);
CREATE INDEX IF NOT EXISTS idx_games_white     ON games(white_player_id);
CREATE INDEX IF NOT EXISTS idx_games_black     ON games(black_player_id);
CREATE INDEX IF NOT EXISTS idx_games_played    ON games(played_at);
CREATE INDEX IF NOT EXISTS idx_lessons_player  ON lessons(player_id);
CREATE INDEX IF NOT EXISTS idx_tgames_tour     ON tournament_games(tournament_id);
CREATE INDEX IF NOT EXISTS idx_presults_gauntlet ON puzzle_results(gauntlet_id);
CREATE INDEX IF NOT EXISTS idx_presults_player   ON puzzle_results(player_id);
"""


@contextmanager
def get_conn(db_path: Optional[Path] = None):
    """
    Yield a configured SQLite connection.

    ``db_path`` defaults to the module-level ``DB_PATH`` so that
    monkeypatching ``db.DB_PATH`` in tests takes effect without needing to
    pass an explicit path.  (Using ``DB_PATH`` as a default argument would
    capture it at import time and ignore later patches.)
    """
    path = db_path if db_path is not None else DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None):
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA)
        # Non-destructive migrations for existing databases
        _migrate(conn)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for *table* (empty set if table missing)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


# Module-level migration cache — cleared at the start of each _migrate() call
# so consecutive init_db() calls in the same process (e.g. during testing)
# always re-introspect the schema.  Using a module-level dict is cleaner than
# the mutable-default-argument pattern (MN-5 in REVIEW.md).
_migrate_column_cache: dict[str, set[str]] = {}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """ALTER TABLE … ADD COLUMN only when the column does not already exist.

    Uses PRAGMA table_info rather than try/except so that genuine SQL errors
    (wrong type, constraint violation, etc.) are not silently swallowed.
    Results are cached in ``_migrate_column_cache`` for the duration of a
    single migration run (the caller resets it before the first call).
    """
    if table not in _migrate_column_cache:
        _migrate_column_cache[table] = _table_columns(conn, table)
    if column not in _migrate_column_cache[table]:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        _migrate_column_cache[table].add(column)


def _migrate(conn: sqlite3.Connection):
    """Non-destructive schema migrations for databases created before the
    current schema was finalised.  Each call is idempotent."""
    # Reset the per-call column cache so each migration run gets fresh data.
    _migrate_column_cache.clear()

    _add_column_if_missing(conn, "lessons", "lesson_type",        "TEXT DEFAULT 'improve'")
    _add_column_if_missing(conn, "players", "portrait_path",       "TEXT")
    _add_column_if_missing(conn, "players", "strategic_profile",   "TEXT")
    _add_column_if_missing(conn, "moves",   "thinking_content",    "TEXT")
    _add_column_if_missing(conn, "lessons", "bad_move_rate_before","REAL")
    _add_column_if_missing(conn, "moves",   "coherence_score",     "REAL")
    _add_column_if_missing(conn, "moves",   "timed_out",           "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "players", "user_provided_portrait", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "tournaments", "bracket_json",    "TEXT")
    _add_column_if_missing(conn, "moves",   "elapsed_ms",          "INTEGER")
    _add_column_if_missing(conn, "moves",   "tokens_input",        "INTEGER")
    _add_column_if_missing(conn, "moves",   "tokens_output",       "INTEGER")
    _add_column_if_missing(conn, "games",  "eco_code",            "TEXT")
    _add_column_if_missing(conn, "games",  "opening_name",        "TEXT")
    # Create tournament tables for existing DBs (CREATE TABLE IF NOT EXISTS is idempotent
    # in the schema, but the schema only runs once so we ensure them here too)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tournaments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            format          TEXT NOT NULL,
            status          TEXT DEFAULT 'running',
            player_ids      TEXT,
            total_games     INTEGER DEFAULT 0,
            winner_model_id TEXT,
            title           TEXT,
            started_at      TEXT DEFAULT (datetime('now')),
            finished_at     TEXT
        );
        CREATE TABLE IF NOT EXISTS tournament_games (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER REFERENCES tournaments(id),
            game_id         INTEGER REFERENCES games(id),
            game_index      INTEGER,
            white_model_id  TEXT,
            black_model_id  TEXT
        );
        CREATE TABLE IF NOT EXISTS puzzle_gauntlets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            status          TEXT DEFAULT 'running',
            player_model_ids TEXT,
            puzzle_count    INTEGER DEFAULT 0,
            puzzles_file    TEXT DEFAULT 'positions.toml',
            candidate_count INTEGER DEFAULT 5,
            started_at      TEXT DEFAULT (datetime('now')),
            finished_at     TEXT
        );
        CREATE TABLE IF NOT EXISTS puzzle_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            gauntlet_id     INTEGER REFERENCES puzzle_gauntlets(id),
            player_id       INTEGER REFERENCES players(id),
            puzzle_index    INTEGER,
            puzzle_fen      TEXT,
            solution_uci    TEXT,
            chosen_uci      TEXT,
            solved          INTEGER,
            candidate_rank  INTEGER,
            elapsed_ms      INTEGER,
            reasoning       TEXT,
            played_at       TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_presults_gauntlet ON puzzle_results(gauntlet_id);
        CREATE INDEX IF NOT EXISTS idx_presults_player   ON puzzle_results(player_id);
    """)


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
        player_id = row["id"]
    invalidate_leaderboard_cache()
    return player_id


def player_exists(model_id: str) -> bool:
    """Return True if the model_id has a row in the players table."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        return row is not None


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


def get_all_players() -> list[dict]:
    """Return all players with their model_id and portrait_path."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT model_id, name, portrait_path FROM players ORDER BY elo DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_portrait_path(model_id: str) -> Optional[str]:
    """Return the stored portrait_path for a player, or None if not yet generated."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT portrait_path FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        return row["portrait_path"] if row else None


def set_portrait_path(model_id: str, path: str, user_provided: bool = False) -> None:
    """Persist a portrait path for a player.

    When ``user_provided`` is True the record is marked so that automatic
    AI re-generation doesn't silently overwrite the user's own photo.
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE players SET portrait_path = ?, user_provided_portrait = ? WHERE model_id = ?",
            (path, 1 if user_provided else 0, model_id),
        )


def is_user_provided_portrait(model_id: str) -> bool:
    """Return True if the model's portrait was uploaded by the user."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_provided_portrait FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        return bool(row["user_provided_portrait"]) if row else False


def get_strategic_profile(model_id: str) -> Optional[str]:
    """Return the compressed strategic profile for a player, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT strategic_profile FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        return row["strategic_profile"] if row else None


def set_strategic_profile(model_id: str, profile: str) -> None:
    """Persist a tutor-compressed strategic profile for a player."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE players SET strategic_profile = ? WHERE model_id = ?",
            (profile, model_id),
        )


def get_all_raw_lessons(model_id: str) -> list[dict]:
    """Return every recorded lesson for a player, oldest-first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT l.lesson, COALESCE(l.lesson_type, 'improve') AS lesson_type
            FROM lessons l
            JOIN players p ON l.player_id = p.id
            WHERE p.model_id = ?
            ORDER BY l.id ASC
            """,
            (model_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_lesson_count(model_id: str) -> int:
    """Total lessons ever recorded for a player."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM lessons l
            JOIN players p ON l.player_id = p.id
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
    eco_code: Optional[str] = None,
    opening_name: Optional[str] = None,
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
               white_elo_after,  black_elo_after,
               eco_code, opening_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                white_id, black_id, result, termination,
                total_moves, pgn,
                white_elo_before, black_elo_before,
                white_elo_after,  black_elo_after,
                eco_code, opening_name,
            ),
        )
        conn.execute("UPDATE players SET elo = ? WHERE model_id = ?", (white_elo_after, white_model_id))
        conn.execute("UPDATE players SET elo = ? WHERE model_id = ?", (black_elo_after, black_model_id))
    invalidate_leaderboard_cache()
    return cur.lastrowid


def get_all_games(
    model_id: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    """
    Return game rows for bulk export, oldest-first.

    model_id — when set, restrict to games where that model played as
               either colour.  Matches on players.model_id.
    limit    — safety cap; defaults to 5 000.
    """
    with get_conn() as conn:
        if model_id:
            rows = conn.execute(
                """
                SELECT
                    g.id, g.result, g.termination, g.total_moves, g.played_at,
                    wp.name AS white_name, bp.name AS black_name,
                    wp.model_id AS white_model_id, bp.model_id AS black_model_id,
                    g.white_elo_before, g.white_elo_after,
                    g.black_elo_before, g.black_elo_after
                FROM games g
                JOIN players wp ON g.white_player_id = wp.id
                JOIN players bp ON g.black_player_id = bp.id
                WHERE wp.model_id = ? OR bp.model_id = ?
                ORDER BY g.played_at ASC
                LIMIT ?
                """,
                (model_id, model_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    g.id, g.result, g.termination, g.total_moves, g.played_at,
                    wp.name AS white_name, bp.name AS black_name,
                    wp.model_id AS white_model_id, bp.model_id AS black_model_id,
                    g.white_elo_before, g.white_elo_after,
                    g.black_elo_before, g.black_elo_after
                FROM games g
                JOIN players wp ON g.white_player_id = wp.id
                JOIN players bp ON g.black_player_id = bp.id
                ORDER BY g.played_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_recent_games(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                g.id, g.result, g.termination, g.total_moves, g.played_at,
                wp.name AS white_name, bp.name AS black_name,
                wp.model_id AS white_model_id, bp.model_id AS black_model_id,
                g.white_elo_before, g.white_elo_after,
                g.black_elo_before,  g.black_elo_after,
                g.eco_code, g.opening_name
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
    thinking_content: str = "",
    coherence_score: Optional[float] = None,
    timed_out: bool = False,
    elapsed_ms: Optional[int] = None,
    tokens_input: Optional[int] = None,
    tokens_output: Optional[int] = None,
):
    with get_conn() as conn:
        player_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO moves
              (game_id, move_number, player_id, move_uci, move_san,
               candidate_rank, quality, score_cp, reasoning, fen_after,
               thinking_content, coherence_score, timed_out, elapsed_ms,
               tokens_input, tokens_output)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id, move_number, player_id, move_uci, move_san,
                candidate_rank, quality, score_cp, reasoning, fen_after,
                thinking_content or "", coherence_score,
                1 if timed_out else 0, elapsed_ms,
                tokens_input, tokens_output,
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
                   m.candidate_rank, m.reasoning, m.score_cp, m.thinking_content,
                   m.coherence_score, m.timed_out, m.elapsed_ms, m.fen_after,
                   m.tokens_input, m.tokens_output
            FROM moves m
            WHERE m.game_id = ?
            ORDER BY m.move_number ASC
            """,
            (game_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_reasoning_dataset(
    limit: int = 10000,
    quality: Optional[str] = None,
    model_id: Optional[str] = None,
) -> list[dict]:
    """
    Return move records suitable for fine-tuning / research export.

    Fields: game_id, move_number, san, uci, fen_after, quality,
    candidate_rank, score_cp, reasoning, thinking_content,
    model_id, model_name.
    """
    params: list = []
    filters: list[str] = ["m.reasoning IS NOT NULL", "m.reasoning != ''"]
    if quality:
        filters.append("m.quality = ?")
        params.append(quality)
    if model_id:
        filters.append("p.model_id = ?")
        params.append(model_id)
    where = "WHERE " + " AND ".join(filters)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT m.game_id,
                   m.move_number,
                   m.move_san        AS san,
                   m.move_uci        AS uci,
                   m.fen_after,
                   m.quality,
                   m.candidate_rank,
                   m.score_cp,
                   m.reasoning,
                   m.thinking_content,
                   p.model_id,
                   p.name            AS model_name
            FROM moves m
            JOIN players p ON m.player_id = p.id
            {where}
            ORDER BY m.game_id DESC, m.move_number ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_coherence_stats(model_id: str) -> dict:
    """
    Return average coherence score and timeout rate for a model.
    Only counts moves where coherence_score IS NOT NULL.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                AVG(m.coherence_score)  AS avg_coherence,
                COUNT(m.id)             AS scored_moves,
                SUM(CASE WHEN m.timed_out = 1 THEN 1 ELSE 0 END) AS timeouts
            FROM moves m
            JOIN players p ON m.player_id = p.id
            WHERE p.model_id = ?
              AND m.coherence_score IS NOT NULL
            """,
            (model_id,),
        ).fetchone()
        total_row = conn.execute(
            """
            SELECT COUNT(m.id) AS total,
                   SUM(CASE WHEN m.timed_out = 1 THEN 1 ELSE 0 END) AS timeouts
            FROM moves m
            JOIN players p ON m.player_id = p.id
            WHERE p.model_id = ?
            """,
            (model_id,),
        ).fetchone()
        return {
            "avg_coherence":  round(row["avg_coherence"], 2) if row["avg_coherence"] is not None else None,
            "scored_moves":   row["scored_moves"] or 0,
            "total_moves":    total_row["total"] or 0,
            "timeout_count":  total_row["timeouts"] or 0,
        }


def get_token_stats(model_id: str) -> dict:
    """
    Return aggregate token usage for a model.

    Returns ``{total_input, total_output, avg_input_per_move, avg_output_per_move,
    moves_with_tokens}`` — only moves where token data is available are counted.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(m.tokens_input)                AS total_input,
                SUM(m.tokens_output)               AS total_output,
                AVG(m.tokens_input)                AS avg_input,
                AVG(m.tokens_output)               AS avg_output,
                COUNT(CASE WHEN m.tokens_input IS NOT NULL THEN 1 END) AS moves_with_tokens
            FROM moves m
            JOIN players p ON m.player_id = p.id
            WHERE p.model_id = ?
            """,
            (model_id,),
        ).fetchone()
    return {
        "total_input":        int(row["total_input"])  if row["total_input"]  is not None else None,
        "total_output":       int(row["total_output"]) if row["total_output"] is not None else None,
        "avg_input_per_move": round(row["avg_input"],  1) if row["avg_input"]  is not None else None,
        "avg_output_per_move":round(row["avg_output"], 1) if row["avg_output"] is not None else None,
        "moves_with_tokens":  row["moves_with_tokens"] or 0,
    }


def get_coherence_history(model_id: str) -> list[dict]:
    """Per-game average coherence score for a model, ordered chronologically.

    Returns a list of ``{game_id, game_number, avg_coherence}`` dicts.
    Games with no scored moves are excluded.
    """
    with get_conn() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        if not player:
            return []
        rows = conn.execute(
            """
            SELECT g.id AS game_id,
                   ROW_NUMBER() OVER (ORDER BY g.id) AS game_number,
                   ROUND(AVG(m.coherence_score), 2)  AS avg_coherence
            FROM games g
            JOIN moves m ON m.game_id = g.id AND m.player_id = ?
            WHERE m.coherence_score IS NOT NULL
            GROUP BY g.id
            HAVING COUNT(m.coherence_score) > 0
            ORDER BY g.id
            """,
            (player["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


def get_openings_for_model(model_id: str, limit: int = 8) -> list[dict]:
    """W/D/L breakdown per opening for a model, ordered by games played.

    Returns a list of ``{eco_code, opening_name, games, wins, draws, losses}``
    dicts, capped at *limit* entries.  Only games with a recognised opening
    (non-NULL ``eco_code``) are included.
    """
    with get_conn() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        if not player:
            return []
        pid = player["id"]
        rows = conn.execute(
            """
            SELECT
                g.eco_code,
                g.opening_name,
                COUNT(*)  AS games,
                SUM(CASE
                    WHEN (g.white_player_id = ? AND g.result = '1-0')
                      OR (g.black_player_id = ? AND g.result = '0-1')
                    THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN g.result = '1/2-1/2' THEN 1 ELSE 0 END) AS draws,
                SUM(CASE
                    WHEN (g.white_player_id = ? AND g.result = '0-1')
                      OR (g.black_player_id = ? AND g.result = '1-0')
                    THEN 1 ELSE 0 END) AS losses
            FROM games g
            WHERE (g.white_player_id = ? OR g.black_player_id = ?)
              AND g.eco_code IS NOT NULL
            GROUP BY g.eco_code, g.opening_name
            ORDER BY games DESC
            LIMIT ?
            """,
            (pid, pid, pid, pid, pid, pid, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_top_openings(limit: int = 15) -> list[dict]:
    """Top openings by games played across all games, with W/D/L breakdown.

    Returns ``{eco_code, opening_name, games, white_wins, black_wins, draws}``
    dicts ordered by game count descending.  Only games with a recognised
    opening (non-NULL, non-empty ``eco_code``) are included.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                eco_code,
                opening_name,
                COUNT(*)  AS games,
                SUM(CASE WHEN result = '1-0'     THEN 1 ELSE 0 END) AS white_wins,
                SUM(CASE WHEN result = '0-1'     THEN 1 ELSE 0 END) AS black_wins,
                SUM(CASE WHEN result = '1/2-1/2' THEN 1 ELSE 0 END) AS draws
            FROM games
            WHERE eco_code IS NOT NULL AND eco_code != ''
            GROUP BY eco_code, opening_name
            ORDER BY games DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Lessons ──────────────────────────────────────────────────────────────

def record_lesson(
    player_model_id: str,
    game_id: int,
    lesson: str,
    lesson_type: str = "improve",   # "improve" | "strength"
    bad_move_rate_before: float | None = None,
):
    with get_conn() as conn:
        player_id = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO lessons (player_id, game_id, lesson, lesson_type, bad_move_rate_before) VALUES (?, ?, ?, ?, ?)",
            (player_id, game_id, lesson, lesson_type, bad_move_rate_before),
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


def get_lesson_effectiveness(model_id: str, lookback_games: int = 3) -> list[dict]:
    """
    For each lesson this player has received that has a bad_move_rate_before,
    compute the average bad_move_rate in the next `lookback_games` games played
    AFTER that lesson was given and return a delta.

    Returns a list of dicts:
      lesson, lesson_type, bad_move_rate_before, bad_move_rate_after,
      delta (after - before; negative = improved), game_id
    Only rows where both before and after rates are available are returned.
    """
    with get_conn() as conn:
        player = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        if not player:
            return []
        pid = player["id"]

        # Per-game bad_move_rate for this player (blunders + mistakes / total moves)
        game_rates = conn.execute(
            """
            SELECT
                m.game_id,
                g.played_at,
                CAST(
                    SUM(CASE WHEN m.quality IN ('blunder','mistake') THEN 1 ELSE 0 END)
                    AS REAL
                ) / NULLIF(COUNT(*), 0) AS bad_rate
            FROM moves m
            JOIN games g ON m.game_id = g.id
            WHERE m.player_id = ?
            GROUP BY m.game_id
            ORDER BY g.played_at ASC
            """,
            (pid,),
        ).fetchall()

        if not game_rates:
            return []

        # Map game_id → bad_rate for fast lookup
        rate_by_game: dict[int, float] = {
            r["game_id"]: r["bad_rate"] for r in game_rates if r["bad_rate"] is not None
        }
        # Ordered game IDs (ascending by played_at) for slicing subsequent games
        ordered_game_ids: list[int] = [r["game_id"] for r in game_rates]

        lessons = conn.execute(
            """
            SELECT l.id, l.lesson, l.lesson_type, l.game_id, l.bad_move_rate_before,
                   g.played_at AS lesson_at
            FROM lessons l
            JOIN games g ON l.game_id = g.id
            WHERE l.player_id = ?
              AND l.bad_move_rate_before IS NOT NULL
            ORDER BY l.created_at DESC
            LIMIT 20
            """,
            (pid,),
        ).fetchall()

        results = []
        for les in lessons:
            lesson_game_id = les["game_id"]
            # Subsequent game rates (games played AFTER this lesson's game)
            # Use positional ordering (already sorted by played_at ASC in the SQL
            # above) to avoid brittle Python string-date comparison.
            try:
                idx = ordered_game_ids.index(lesson_game_id)
            except ValueError:
                continue
            subsequent_ids = ordered_game_ids[idx + 1 : idx + 1 + lookback_games]
            subsequent = [rate_by_game[gid] for gid in subsequent_ids if gid in rate_by_game]
            if not subsequent:
                continue
            after = sum(subsequent) / len(subsequent)
            before = les["bad_move_rate_before"]
            results.append({
                "lesson":               les["lesson"],
                "lesson_type":          les["lesson_type"],
                "bad_move_rate_before": before,
                "bad_move_rate_after":  round(after, 4),
                "delta":                round(after - before, 4),
                "games_measured":       len(subsequent),
                "game_id":              lesson_game_id,
            })
        return results


# ── Leaderboard ───────────────────────────────────────────────────────────

# Invalidation-based in-memory cache for the leaderboard query.
# Set to None whenever any game is recorded; repopulated on next read.
# This prevents re-running the heavy 3-CTE query on every /api/leaderboard poll.
_leaderboard_cache: list[dict] | None = None


def invalidate_leaderboard_cache() -> None:
    """Mark the leaderboard cache as stale. Called after any write that changes standings."""
    global _leaderboard_cache
    _leaderboard_cache = None


def get_leaderboard() -> list[dict]:
    """
    Leaderboard rows include each player's 'best game' score —
    the highest per-game average move quality (mapped to 0..100)
    across all games with ≥5 quality-scored moves.

    Results are cached in-process and invalidated automatically when
    ``record_game()`` commits new data.
    """
    global _leaderboard_cache
    if _leaderboard_cache is not None:
        return _leaderboard_cache
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
                bg.best_game_id AS best_game_id,
                COALESCE(
                  (SELECT COUNT(*) FROM achievements a WHERE a.player_id = p.id),
                  0
                ) AS achievement_count
            FROM players p
            LEFT JOIN games g
              ON g.white_player_id = p.id OR g.black_player_id = p.id
            LEFT JOIN best_game bg ON bg.player_id = p.id
            GROUP BY p.id
            ORDER BY p.elo DESC
            """,
        ).fetchall()
        result = [dict(r) for r in rows]

        # Append recent form (last 5 results, oldest→newest) for each player.
        # Uses a window-function query so we only hit the DB once for all players.
        form_rows = conn.execute(
            """
            SELECT
                p.model_id,
                CASE WHEN g.white_player_id = p.id AND g.result = '1-0'  THEN 'W'
                     WHEN g.black_player_id = p.id AND g.result = '0-1'  THEN 'W'
                     WHEN g.result = '1/2-1/2'                           THEN 'D'
                     ELSE                                                      'L'
                END AS outcome,
                ROW_NUMBER() OVER (
                    PARTITION BY p.id ORDER BY g.played_at DESC
                ) AS rn
            FROM players p
            JOIN games g ON (g.white_player_id = p.id OR g.black_player_id = p.id)
            """,
        ).fetchall()
        # Collect per-player: keep only the 5 most recent (rn ≤ 5)
        from collections import defaultdict
        _form_map: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for fr in form_rows:
            if fr["rn"] <= 5:
                _form_map[fr["model_id"]].append((fr["rn"], fr["outcome"]))
        # Sort by rn descending → oldest-first chronological display
        for row_dict in result:
            items = sorted(_form_map.get(row_dict["model_id"], []), key=lambda x: -x[0])
            row_dict["recent_form"] = [o for _, o in items]

        _leaderboard_cache = result
        return _leaderboard_cache


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


def get_elo_history_batch(model_ids: list[str]) -> dict[str, list[dict]]:
    """ELO trajectory for multiple models in a single query.

    Returns a dict keyed by model_id; missing models map to an empty list.
    """
    if not model_ids:
        return {}
    placeholders = ",".join("?" * len(model_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.model_id,
                g.played_at,
                CASE WHEN g.white_player_id = p.id THEN g.white_elo_after
                     ELSE g.black_elo_after END AS elo_after
            FROM games g
            JOIN players p ON (g.white_player_id = p.id OR g.black_player_id = p.id)
            WHERE p.model_id IN ({placeholders})
            ORDER BY p.model_id, g.played_at ASC
            """,
            model_ids,
        ).fetchall()
    result: dict[str, list[dict]] = {mid: [] for mid in model_ids}
    for r in rows:
        result[r["model_id"]].append(
            {"played_at": r["played_at"], "elo_after": r["elo_after"]}
        )
    return result


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


def get_player_quality_stats(model_id: str) -> Optional[dict]:
    """
    Move-quality breakdown for a single model.
    Returns rates (0-1), counts, avg candidate rank, and avg position score
    (centipawns from White's POV after the chosen move — NOT centipawn loss),
    or None if the player is unknown or has no moves.
    """
    with get_conn() as conn:
        pid_row = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        if not pid_row:
            return None
        pid = pid_row["id"]
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                                        AS total_moves,
                SUM(CASE WHEN quality='best'       THEN 1 ELSE 0 END)          AS best,
                SUM(CASE WHEN quality='excellent'  THEN 1 ELSE 0 END)          AS excellent,
                SUM(CASE WHEN quality='good'       THEN 1 ELSE 0 END)          AS good,
                SUM(CASE WHEN quality='inaccuracy' THEN 1 ELSE 0 END)          AS inaccuracy,
                SUM(CASE WHEN quality='mistake'    THEN 1 ELSE 0 END)          AS mistake,
                SUM(CASE WHEN quality='blunder'    THEN 1 ELSE 0 END)          AS blunder,
                ROUND(AVG(candidate_rank), 2)                                  AS avg_candidate_rank,
                ROUND(AVG(CASE WHEN score_cp IS NOT NULL THEN score_cp END), 1) AS avg_position_score_cp
            FROM moves
            WHERE player_id = ?
            """,
            (pid,),
        ).fetchone()
        if not row or not row["total_moves"]:
            return None
        d = dict(row)
        n = d["total_moves"]
        for q in ("best", "excellent", "good", "inaccuracy", "mistake", "blunder"):
            d[f"{q}_rate"] = round((d[q] or 0) / n, 4)
        d["bad_move_rate"] = round(((d["mistake"] or 0) + (d["blunder"] or 0)) / n, 4)
        d["model_id"] = model_id
        return d


def get_recent_win_rate(model_id: str, n: int = 10) -> Optional[float]:
    """
    Win rate (0-1) for a model over its last *n* games.
    Draws count as 0.5.  Returns None if fewer than *n* games exist.
    """
    with get_conn() as conn:
        pid_row = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (model_id,)
        ).fetchone()
        if not pid_row:
            return None
        pid = pid_row["id"]
        rows = conn.execute(
            """
            SELECT result, white_player_id
            FROM games
            WHERE white_player_id = ? OR black_player_id = ?
            ORDER BY played_at DESC, id DESC
            LIMIT ?
            """,
            (pid, pid, n),
        ).fetchall()
        if len(rows) < n:
            return None
        score = 0.0
        for r in rows:
            is_white = r["white_player_id"] == pid
            if r["result"] == "1/2-1/2":
                score += 0.5
            elif (r["result"] == "1-0" and is_white) or (r["result"] == "0-1" and not is_white):
                score += 1.0
        return round(score / n, 4)


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


def get_h2h_record(model_id_a: str, model_id_b: str) -> dict:
    """W/D/L for model_a vs model_b from model_a's perspective, across all colors."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN
                    (wp.model_id=:a AND g.result='1-0') OR
                    (bp.model_id=:a AND g.result='0-1')
                    THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN g.result='1/2-1/2' THEN 1 ELSE 0 END) AS draws,
                SUM(CASE WHEN
                    (wp.model_id=:a AND g.result='0-1') OR
                    (bp.model_id=:a AND g.result='1-0')
                    THEN 1 ELSE 0 END) AS losses,
                COUNT(*) AS total
            FROM games g
            JOIN players wp ON g.white_player_id = wp.id
            JOIN players bp ON g.black_player_id = bp.id
            WHERE (wp.model_id=:a AND bp.model_id=:b)
               OR (wp.model_id=:b AND bp.model_id=:a)
            """,
            {"a": model_id_a, "b": model_id_b},
        ).fetchone()
        if not row or not row["total"]:
            return {"wins": 0, "draws": 0, "losses": 0, "total": 0}
        return dict(row)


# ── Model profile (personality + headline stats) ──────────────────────────

def get_model_profile(model_id: str) -> dict | None:
    """
    Aggregate personality-relevant stats for a single model.
    Pulled entirely from existing tables — no schema change.
    """
    with get_conn() as conn:
        player = conn.execute(
            """
            SELECT id, name, model_id, backend, ROUND(elo) AS elo, user_provided_portrait
            FROM players WHERE model_id = ?
            """,
            (model_id,),
        ).fetchone()
        if not player:
            return None
        pid = player["id"]

        # Aggregate move-level signals
        moves = conn.execute(
            """
            SELECT
              COUNT(*)                                                   AS total_moves,
              SUM(CASE WHEN move_san LIKE '%x%' THEN 1 ELSE 0 END)       AS captures,
              SUM(CASE WHEN move_san LIKE '%+%'
                       OR  move_san LIKE '%#%' THEN 1 ELSE 0 END)        AS checks,
              SUM(CASE WHEN move_san = 'O-O'   THEN 1 ELSE 0 END)        AS castles_k,
              SUM(CASE WHEN move_san = 'O-O-O' THEN 1 ELSE 0 END)        AS castles_q,
              ROUND(AVG(candidate_rank), 2)                              AS avg_rank,
              SUM(CASE WHEN candidate_rank = 1 THEN 1 ELSE 0 END)        AS picked_top,
              SUM(CASE WHEN quality = 'best'       THEN 1 ELSE 0 END)    AS q_best,
              SUM(CASE WHEN quality = 'excellent'  THEN 1 ELSE 0 END)    AS q_excellent,
              SUM(CASE WHEN quality = 'good'       THEN 1 ELSE 0 END)    AS q_good,
              SUM(CASE WHEN quality = 'inaccuracy' THEN 1 ELSE 0 END)    AS q_inaccuracy,
              SUM(CASE WHEN quality = 'mistake'    THEN 1 ELSE 0 END)    AS q_mistake,
              SUM(CASE WHEN quality = 'blunder'    THEN 1 ELSE 0 END)    AS q_blunder
            FROM moves
            WHERE player_id = ?
            """,
            (pid,),
        ).fetchone()

        # Castling: how soon and which side, per game
        castle_rows = conn.execute(
            """
            SELECT game_id, move_san, MIN(move_number) AS first_move
            FROM moves
            WHERE player_id = ? AND (move_san = 'O-O' OR move_san = 'O-O-O')
            GROUP BY game_id
            """,
            (pid,),
        ).fetchall()
        castle_moves = [r["first_move"] for r in castle_rows]
        avg_castle_move = (
            round(sum(castle_moves) / len(castle_moves), 1) if castle_moves else None
        )

        # Per-colour record
        color = conn.execute(
            """
            SELECT
              SUM(CASE WHEN g.white_player_id = ? AND g.result='1-0'     THEN 1 ELSE 0 END) AS white_wins,
              SUM(CASE WHEN g.white_player_id = ? AND g.result='1/2-1/2' THEN 1 ELSE 0 END) AS white_draws,
              SUM(CASE WHEN g.white_player_id = ? AND g.result='0-1'     THEN 1 ELSE 0 END) AS white_losses,
              SUM(CASE WHEN g.black_player_id = ? AND g.result='0-1'     THEN 1 ELSE 0 END) AS black_wins,
              SUM(CASE WHEN g.black_player_id = ? AND g.result='1/2-1/2' THEN 1 ELSE 0 END) AS black_draws,
              SUM(CASE WHEN g.black_player_id = ? AND g.result='1-0'     THEN 1 ELSE 0 END) AS black_losses
            FROM games g
            WHERE g.white_player_id = ? OR g.black_player_id = ?
            """,
            (pid, pid, pid, pid, pid, pid, pid, pid),
        ).fetchone()

        # Game-length summary
        game_summary = conn.execute(
            """
            SELECT
              COUNT(*)                AS total_games,
              ROUND(AVG(total_moves)) AS avg_game_moves,
              MIN(total_moves)        AS shortest_game,
              MAX(total_moves)        AS longest_game,
              SUM(CASE WHEN termination = 'checkmate' THEN 1 ELSE 0 END) AS checkmate_games
            FROM games
            WHERE white_player_id = ? OR black_player_id = ?
            """,
            (pid, pid),
        ).fetchone()

        recent_lessons = conn.execute(
            """
            SELECT lesson, COALESCE(lesson_type, 'improve') AS lesson_type, created_at
            FROM lessons
            WHERE player_id = ?
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (pid,),
        ).fetchall()

        return {
            "name":                  player["name"],
            "model_id":              player["model_id"],
            "backend":               player["backend"],
            "elo":                   player["elo"],
            "user_provided_portrait": bool(player["user_provided_portrait"]),
            "moves":            dict(moves) if moves else {},
            "castling": {
                "games_castled":   len(castle_moves),
                "avg_castle_move": avg_castle_move,
                "kingside":  sum(1 for r in castle_rows if r["move_san"] == "O-O"),
                "queenside": sum(1 for r in castle_rows if r["move_san"] == "O-O-O"),
            },
            "color":            dict(color)        if color        else {},
            "games":            dict(game_summary) if game_summary else {},
            "recent_lessons":   [dict(r) for r in recent_lessons],
            "strategic_profile": conn.execute(
                "SELECT strategic_profile FROM players WHERE id = ?", (pid,)
            ).fetchone()["strategic_profile"],
        }


# ── Achievements ──────────────────────────────────────────────────────────

def record_achievements(player_model_id: str, game_id: int, codes: list[str]):
    if not codes:
        return
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM players WHERE model_id = ?", (player_model_id,)
        ).fetchone()
        if not row:
            return
        pid = row["id"]
        for code in codes:
            try:
                conn.execute(
                    "INSERT INTO achievements (player_id, game_id, code) VALUES (?, ?, ?)",
                    (pid, game_id, code),
                )
            except sqlite3.IntegrityError:
                pass  # already awarded this code on this game
    invalidate_leaderboard_cache()


def get_player_achievements(model_id: str) -> list[dict]:
    """All achievements earned by a model, with counts per code."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.code, COUNT(*) AS times, MAX(a.awarded_at) AS latest
            FROM achievements a
            JOIN players p ON a.player_id = p.id
            WHERE p.model_id = ?
            GROUP BY a.code
            ORDER BY times DESC, latest DESC
            """,
            (model_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_achievements_for_game(game_id: int) -> dict[str, list[str]]:
    """Returns {model_id: [codes...]} earned by each player in this game."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.model_id, a.code
            FROM achievements a
            JOIN players p ON a.player_id = p.id
            WHERE a.game_id = ?
            """,
            (game_id,),
        ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["model_id"], []).append(r["code"])
    return out


def get_leaderboard_achievement_counts() -> dict[str, int]:
    """Map model_id → total achievements (for compact display on leaderboard)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.model_id, COUNT(*) AS n
            FROM achievements a
            JOIN players p ON a.player_id = p.id
            GROUP BY p.id
            """,
        ).fetchall()
    return {r["model_id"]: r["n"] for r in rows}


def games_for_backfill() -> list[dict]:
    """Every game with all data needed to evaluate achievements (PGN + ELO + result)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.result, g.termination, g.total_moves, g.pgn,
                   g.white_elo_before, g.black_elo_before,
                   wp.model_id AS white_model_id, bp.model_id AS black_model_id
            FROM games g
            JOIN players wp ON g.white_player_id = wp.id
            JOIN players bp ON g.black_player_id = bp.id
            ORDER BY g.id ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def has_any_achievements() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM achievements LIMIT 1").fetchone()
    return row is not None


# ── Tournaments ───────────────────────────────────────────────────────────

def create_tournament(
    format: str,
    player_ids: list[str],
    total_games: int,
) -> int:
    """Create a new tournament record; returns the new tournament id."""
    import json
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tournaments (format, player_ids, total_games, status)
            VALUES (?, ?, ?, 'running')
            """,
            (format, json.dumps(player_ids), total_games),
        )
        row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        return row["id"]


def finish_tournament(
    tournament_id: int,
    winner_model_id: Optional[str],
    title: Optional[str],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE tournaments
            SET status = 'finished', winner_model_id = ?, title = ?,
                finished_at = datetime('now')
            WHERE id = ?
            """,
            (winner_model_id, title, tournament_id),
        )


def abort_tournament(tournament_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE tournaments SET status = 'aborted', finished_at = datetime('now') WHERE id = ?",
            (tournament_id,),
        )


def update_tournament_bracket(tournament_id: int, bracket: dict) -> None:
    """Persist the current bracket JSON for a running elimination tournament."""
    import json
    with get_conn() as conn:
        conn.execute(
            "UPDATE tournaments SET bracket_json = ? WHERE id = ?",
            (json.dumps(bracket), tournament_id),
        )


def record_tournament_game(
    tournament_id: int,
    game_id: int,
    game_index: int,
    white_model_id: str,
    black_model_id: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tournament_games
                (tournament_id, game_id, game_index, white_model_id, black_model_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tournament_id, game_id, game_index, white_model_id, black_model_id),
        )


def get_tournament_history(limit: int = 20) -> list[dict]:
    """Return recent finished/aborted tournaments with player names and results."""
    import json
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.format, t.status, t.player_ids, t.total_games,
                   t.winner_model_id, t.title, t.started_at, t.finished_at,
                   t.bracket_json,
                   wp.name AS winner_name
            FROM tournaments t
            LEFT JOIN players wp ON t.winner_model_id = wp.model_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not rows:
            return []

        # Pre-load all player names in a single query (avoids N+1 per-player
        # lookups — previously: 20 tournaments × 6 players = 120 extra queries).
        player_name_map: dict[str, str] = {
            r["model_id"]: r["name"]
            for r in conn.execute("SELECT model_id, name FROM players").fetchall()
        }

        # Pre-load game counts for all returned tournament IDs in one GROUP BY.
        tour_ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(tour_ids))
        game_counts: dict[int, int] = {
            r["tournament_id"]: r["n"]
            for r in conn.execute(
                f"SELECT tournament_id, COUNT(*) AS n FROM tournament_games "
                f"WHERE tournament_id IN ({placeholders}) GROUP BY tournament_id",
                tour_ids,
            ).fetchall()
        }

        result = []
        for r in rows:
            rec = dict(r)
            ids = json.loads(rec.get("player_ids") or "[]")
            rec["player_names"] = [player_name_map.get(mid, mid) for mid in ids]
            rec["game_count"] = game_counts.get(r["id"], 0)
            # Parse bracket JSON for elimination tournaments
            bj = rec.get("bracket_json")
            rec["bracket"] = json.loads(bj) if bj else None
            result.append(rec)
        return result


# ── Puzzle Gauntlets ──────────────────────────────────────────────────────

def create_puzzle_gauntlet(
    player_model_ids: list[str],
    puzzle_count: int,
    puzzles_file: str = "positions.toml",
    candidate_count: int = 5,
) -> int:
    """Create a new puzzle gauntlet record; returns the new gauntlet id."""
    import json
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO puzzle_gauntlets
                (player_model_ids, puzzle_count, puzzles_file, candidate_count, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            (json.dumps(player_model_ids), puzzle_count, puzzles_file, candidate_count),
        )
        row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        return row["id"]


def finish_puzzle_gauntlet(gauntlet_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE puzzle_gauntlets
            SET status = 'finished', finished_at = datetime('now')
            WHERE id = ?
            """,
            (gauntlet_id,),
        )


def abort_puzzle_gauntlet(gauntlet_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE puzzle_gauntlets SET status = 'aborted', finished_at = datetime('now') WHERE id = ?",
            (gauntlet_id,),
        )


def record_puzzle_result(
    gauntlet_id: int,
    player_id: int,
    puzzle_index: int,
    puzzle_fen: str,
    solution_uci: str,
    chosen_uci: str,
    solved: bool,
    candidate_rank: int,
    elapsed_ms: int,
    reasoning: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO puzzle_results
                (gauntlet_id, player_id, puzzle_index, puzzle_fen, solution_uci,
                 chosen_uci, solved, candidate_rank, elapsed_ms, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (gauntlet_id, player_id, puzzle_index, puzzle_fen, solution_uci,
             chosen_uci, int(solved), candidate_rank, elapsed_ms, reasoning),
        )


def get_puzzle_gauntlets(limit: int = 20) -> list[dict]:
    """Return recent puzzle gauntlets with per-player aggregate scores."""
    import json
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, status, player_model_ids, puzzle_count, puzzles_file,
                   candidate_count, started_at, finished_at
            FROM puzzle_gauntlets
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not rows:
            return []

        gauntlet_ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(gauntlet_ids))

        # Per-player aggregate scores across all gauntlets in one query
        score_rows = conn.execute(
            f"""
            SELECT pr.gauntlet_id, p.model_id, p.name,
                   COUNT(*) AS total,
                   SUM(pr.solved) AS solved,
                   AVG(CASE WHEN pr.candidate_rank > 0 THEN pr.candidate_rank END) AS avg_rank
            FROM puzzle_results pr
            JOIN players p ON pr.player_id = p.id
            WHERE pr.gauntlet_id IN ({placeholders})
            GROUP BY pr.gauntlet_id, p.model_id
            """,
            gauntlet_ids,
        ).fetchall()

        scores_by_gauntlet: dict[int, list[dict]] = {}
        for sr in score_rows:
            gid = sr["gauntlet_id"]
            if gid not in scores_by_gauntlet:
                scores_by_gauntlet[gid] = []
            scores_by_gauntlet[gid].append({
                "model_id":  sr["model_id"],
                "name":      sr["name"],
                "solved":    sr["solved"] or 0,
                "total":     sr["total"],
                "fraction":  round((sr["solved"] or 0) / sr["total"], 3) if sr["total"] else 0.0,
                "avg_rank":  round(sr["avg_rank"], 2) if sr["avg_rank"] is not None else None,
            })

        result = []
        for r in rows:
            rec = dict(r)
            rec["player_model_ids"] = json.loads(rec.get("player_model_ids") or "[]")
            rec["scores"] = scores_by_gauntlet.get(r["id"], [])
            result.append(rec)
        return result


def get_puzzle_gauntlet_results(gauntlet_id: int) -> list[dict]:
    """Return per-puzzle per-player results for a single gauntlet."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT pr.puzzle_index, pr.puzzle_fen, pr.solution_uci,
                   p.model_id, p.name,
                   pr.chosen_uci, pr.solved, pr.candidate_rank,
                   pr.elapsed_ms, pr.reasoning
            FROM puzzle_results pr
            JOIN players p ON pr.player_id = p.id
            WHERE pr.gauntlet_id = ?
            ORDER BY pr.puzzle_index ASC, p.name ASC
            """,
            (gauntlet_id,),
        ).fetchall()
    return [dict(r) for r in rows]
