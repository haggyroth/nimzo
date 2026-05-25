"""
Shared pytest fixtures.
"""
import sqlite3
import pytest
from unittest.mock import patch
from contextlib import contextmanager


@pytest.fixture
def tmp_db(tmp_path):
    """
    Provide a db module wired to a fresh temp SQLite file.
    Patches db.get_conn so every call (regardless of default args) uses tmp_path.
    """
    import db as _db

    db_path = tmp_path / "test_nimzo.db"

    # Build a get_conn that always uses our temp path
    @contextmanager
    def _patched_get_conn(db_path_arg=None):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with patch.object(_db, "get_conn", _patched_get_conn):
        _db.init_db(db_path)
        yield _db
