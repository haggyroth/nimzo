"""
Tests for db.get_conn() connection configuration — D-1 through D-4.

D-1  PRAGMA journal_mode=WAL is applied to every new connection.
D-2  PRAGMA busy_timeout=5000 is applied so concurrent writers queue rather
     than fail immediately with SQLITE_BUSY.
D-3  conn.row_factory is set to sqlite3.Row so columns are accessible by name.
D-4  WAL mode persists at the database level after the connection closes.
"""
from __future__ import annotations

import sqlite3


class TestGetConnPragmas:
    """D-1 / D-2 — get_conn sets WAL journal mode and busy_timeout."""

    def test_journal_mode_is_wal(self, tmp_path):
        """D-1 — PRAGMA journal_mode=WAL is applied to the connection."""
        import db
        db_path = tmp_path / "pragma_wal.db"
        with db.get_conn(db_path) as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_busy_timeout_is_5000ms(self, tmp_path):
        """D-2 — PRAGMA busy_timeout=5000 is applied (milliseconds)."""
        import db
        db_path = tmp_path / "pragma_timeout.db"
        with db.get_conn(db_path) as conn:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
        assert row[0] == 5000

    def test_row_factory_is_sqlite_row(self, tmp_path):
        """D-3 — row_factory is sqlite3.Row so results support column-name access."""
        import db
        db_path = tmp_path / "pragma_row.db"
        with db.get_conn(db_path) as conn:
            assert conn.row_factory is sqlite3.Row

    def test_wal_persists_across_connections(self, tmp_path):
        """D-4 — WAL is a database-level setting; it remains active after close."""
        import db
        db_path = tmp_path / "pragma_persist.db"
        # Establish WAL via get_conn
        with db.get_conn(db_path) as _conn:
            pass
        # Open a raw connection (no get_conn) and confirm WAL is still set
        raw = sqlite3.connect(str(db_path))
        try:
            mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            raw.close()
        assert mode == "wal"

    def test_column_accessible_by_name_after_init(self, tmp_path):
        """Row factory works end-to-end: column value accessible by name after insert."""
        import db
        db_path = tmp_path / "pragma_col.db"
        db.init_db(db_path)
        db.upsert_player.__wrapped__ = None  # reset any cached state if present
        with db.get_conn(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO players (model_id, name, backend, elo) VALUES (?,?,?,?)",
                ("test-model", "Test", "lmstudio", 1200.0),
            )
            row = conn.execute(
                "SELECT name, elo FROM players WHERE model_id = ?", ("test-model",)
            ).fetchone()
        assert row["name"] == "Test"
        assert row["elo"] == 1200.0
