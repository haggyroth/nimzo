"""
SQLite persistence for Nimzo.
Players are keyed by model_id so ELO and lessons persist across name changes.
"""

from __future__ import annotations

import sqlite3
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
    # Add portrait_path column if missing
    try:
        conn.execute("ALTER TABLE players ADD COLUMN portrait_path TEXT")
    except sqlite3.OperationalError:
        pass  # already exists
    # Add strategic_profile column if missing (lesson compression)
    try:
        conn.execute("ALTER TABLE players ADD COLUMN strategic_profile TEXT")
    except sqlite3.OperationalError:
        pass  # already exists
    # Add thinking_content column if missing (pre-Phase-10 databases)
    try:
        conn.execute("ALTER TABLE moves ADD COLUMN thinking_content TEXT")
    except sqlite3.OperationalError:
        pass  # already exists
    # Add bad_move_rate_before for lesson effectiveness tracking (Phase 7 loose end)
    try:
        conn.execute("ALTER TABLE lessons ADD COLUMN bad_move_rate_before REAL")
    except sqlite3.OperationalError:
        pass  # already exists
    # Phase 12: reasoning coherence score (judge model per move)
    try:
        conn.execute("ALTER TABLE moves ADD COLUMN coherence_score REAL")
    except sqlite3.OperationalError:
        pass
    # Phase 12: time-control timeout flag
    try:
        conn.execute("ALTER TABLE moves ADD COLUMN timed_out INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
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


def set_portrait_path(model_id: str, path: str) -> None:
    """Persist a generated portrait path for a player."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE players SET portrait_path = ? WHERE model_id = ?",
            (path, model_id),
        )


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
    thinking_content: str = "",
    coherence_score: Optional[float] = None,
    timed_out: bool = False,
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
               thinking_content, coherence_score, timed_out)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id, move_number, player_id, move_uci, move_san,
                candidate_rank, quality, score_cp, reasoning, fen_after,
                thinking_content or "", coherence_score,
                1 if timed_out else 0,
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
                   m.coherence_score, m.timed_out
            FROM moves m
            WHERE m.game_id = ?
            ORDER BY m.move_number ASC
            """,
            (game_id,),
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
                SUM(CASE WHEN m.timed_out = 1 THEN 1 ELSE 0 END) AS timeouts,
                COUNT(m.id)             AS total_moves
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
                g.started_at,
                CAST(
                    SUM(CASE WHEN m.quality IN ('blunder','mistake') THEN 1 ELSE 0 END)
                    AS REAL
                ) / NULLIF(COUNT(*), 0) AS bad_rate
            FROM moves m
            JOIN games g ON m.game_id = g.id
            WHERE m.player_model_id = ?
            GROUP BY m.game_id
            ORDER BY g.started_at ASC
            """,
            (model_id,),
        ).fetchall()

        if not game_rates:
            return []

        # Build ordered list of (game_id, started_at, bad_rate)
        ordered = [(r["game_id"], r["started_at"], r["bad_rate"]) for r in game_rates]

        lessons = conn.execute(
            """
            SELECT l.id, l.lesson, l.lesson_type, l.game_id, l.bad_move_rate_before,
                   g.started_at AS lesson_at
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
            lesson_at = les["lesson_at"]
            # Subsequent game rates (games played AFTER this lesson's game)
            subsequent = [
                rate for (_, at, rate) in ordered
                if at > lesson_at and rate is not None
            ][:lookback_games]
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
                "game_id":              les["game_id"],
            })
        return results


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


# ── Model profile (personality + headline stats) ──────────────────────────

def get_model_profile(model_id: str) -> dict | None:
    """
    Aggregate personality-relevant stats for a single model.
    Pulled entirely from existing tables — no schema change.
    """
    with get_conn() as conn:
        player = conn.execute(
            """
            SELECT id, name, model_id, backend, ROUND(elo) AS elo
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
            "name":             player["name"],
            "model_id":         player["model_id"],
            "backend":          player["backend"],
            "elo":              player["elo"],
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
                   wp.name AS winner_name
            FROM tournaments t
            LEFT JOIN players wp ON t.winner_model_id = wp.model_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result = []
        for r in rows:
            rec = dict(r)
            # Resolve player names from model_id list
            ids = json.loads(rec.get("player_ids") or "[]")
            names = []
            for mid in ids:
                p = conn.execute(
                    "SELECT name FROM players WHERE model_id = ?", (mid,)
                ).fetchone()
                names.append(p["name"] if p else mid)
            rec["player_names"] = names
            rec["game_count"] = conn.execute(
                "SELECT COUNT(*) AS n FROM tournament_games WHERE tournament_id = ?",
                (r["id"],),
            ).fetchone()["n"]
            result.append(rec)
        return result
