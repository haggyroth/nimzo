"""
tests/test_wave11.py — Wave 11 coverage for P-2 (leaderboard cache) and P-4 (broadcast dedup).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── P-2: Leaderboard cache ────────────────────────────────────────────────


class TestLeaderboardCache:
    """P-2 — invalidation-based in-memory cache for get_leaderboard()."""

    def _fresh_db(self, tmp_path):
        """Return a db module wired to a throwaway SQLite file."""
        import importlib
        import db as database

        db_path = tmp_path / "test.db"
        database.DB_PATH = db_path
        database._leaderboard_cache = None  # reset cache between tests
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        return database

    def test_cache_is_none_initially(self, tmp_path):
        db = self._fresh_db(tmp_path)
        assert db._leaderboard_cache is None

    def test_get_leaderboard_populates_cache(self, tmp_path):
        db = self._fresh_db(tmp_path)
        result = db.get_leaderboard()
        assert db._leaderboard_cache is not None
        # Cache should be a list (empty if no players)
        assert isinstance(db._leaderboard_cache, list)

    def test_get_leaderboard_returns_cached_object(self, tmp_path):
        db = self._fresh_db(tmp_path)
        first  = db.get_leaderboard()
        second = db.get_leaderboard()
        # Must be the exact same list object — no second DB round-trip
        assert first is second

    def test_invalidate_clears_cache(self, tmp_path):
        db = self._fresh_db(tmp_path)
        db.get_leaderboard()                  # populate
        assert db._leaderboard_cache is not None
        db.invalidate_leaderboard_cache()
        assert db._leaderboard_cache is None

    def test_get_leaderboard_after_invalidate_repopulates(self, tmp_path):
        db = self._fresh_db(tmp_path)
        first = db.get_leaderboard()
        db.invalidate_leaderboard_cache()
        second = db.get_leaderboard()
        # After invalidation a new list object is returned
        assert second is not first
        assert isinstance(second, list)

    def test_record_game_invalidates_cache(self, tmp_path):
        db = self._fresh_db(tmp_path)

        # Register two players so record_game can find them
        db.upsert_player("model-a", "Alpha", "lmstudio")
        db.upsert_player("model-b", "Beta",  "lmstudio")

        # Populate cache
        db.get_leaderboard()
        assert db._leaderboard_cache is not None

        # Recording a game must invalidate the cache
        db.record_game(
            white_model_id="model-a",
            black_model_id="model-b",
            result="1-0",
            termination="checkmate",
            total_moves=20,
            pgn="1. e4 e5 *",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )
        assert db._leaderboard_cache is None

    def test_cache_includes_new_game_after_invalidation(self, tmp_path):
        db = self._fresh_db(tmp_path)

        db.upsert_player("model-a", "Alpha", "lmstudio")
        db.upsert_player("model-b", "Beta",  "lmstudio")

        before = db.get_leaderboard()
        total_before = sum(r["total_games"] for r in before)

        db.record_game(
            white_model_id="model-a",
            black_model_id="model-b",
            result="1-0",
            termination="checkmate",
            total_moves=20,
            pgn="1. e4 e5 *",
            white_elo_before=1200.0,
            black_elo_before=1200.0,
            white_elo_after=1216.0,
            black_elo_after=1184.0,
        )

        after = db.get_leaderboard()
        total_after = sum(r["total_games"] for r in after)
        # The new game should be reflected after cache refresh
        assert total_after == total_before + 2  # each player gains 1 game entry

    def test_invalidate_is_idempotent(self, tmp_path):
        db = self._fresh_db(tmp_path)
        db.invalidate_leaderboard_cache()  # already None
        db.invalidate_leaderboard_cache()  # still fine
        assert db._leaderboard_cache is None


# ── P-4: Broadcast deduplication ─────────────────────────────────────────


class TestBroadcastDedup:
    """P-4 — identical consecutive messages are suppressed in broadcast()."""

    def _reset_state(self):
        from arena import state
        state._last_broadcast_msg = None
        return state

    def test_last_broadcast_msg_starts_none(self):
        st = self._reset_state()
        assert st._last_broadcast_msg is None

    def test_broadcast_sends_first_message(self):
        """First broadcast sets _last_broadcast_msg."""
        st = self._reset_state()

        sends = []

        class FakeWS:
            async def send_text(self, msg):
                sends.append(msg)

        st._connected_clients.add(FakeWS())
        try:
            asyncio.run(st.broadcast({"type": "move", "san": "e4"}))
        finally:
            st._connected_clients.clear()

        assert len(sends) == 1
        assert st._last_broadcast_msg is not None

    def test_broadcast_suppresses_duplicate(self):
        """A second identical broadcast is a no-op."""
        st = self._reset_state()

        sends = []

        class FakeWS:
            async def send_text(self, msg):
                sends.append(msg)

        ws = FakeWS()
        st._connected_clients.add(ws)
        try:
            event = {"type": "move", "san": "e4"}
            asyncio.run(st.broadcast(event))
            asyncio.run(st.broadcast(event))  # identical — should be skipped
        finally:
            st._connected_clients.clear()

        assert len(sends) == 1, "duplicate message must be suppressed"

    def test_broadcast_sends_distinct_consecutive_messages(self):
        """Different events are never suppressed."""
        st = self._reset_state()

        sends = []

        class FakeWS:
            async def send_text(self, msg):
                sends.append(msg)

        st._connected_clients.add(FakeWS())
        try:
            asyncio.run(st.broadcast({"type": "move",      "san": "e4"}))
            asyncio.run(st.broadcast({"type": "game_over", "result": "1-0"}))
        finally:
            st._connected_clients.clear()

        assert len(sends) == 2, "distinct events must both be sent"

    def test_broadcast_allows_same_type_after_different_event(self):
        """A-B-A pattern: second A is different from its immediate predecessor B."""
        st = self._reset_state()

        sends = []

        class FakeWS:
            async def send_text(self, msg):
                sends.append(msg)

        st._connected_clients.add(FakeWS())
        try:
            event_a = {"type": "thinking", "fen": "pos1"}
            event_b = {"type": "move",     "san": "e4"}
            asyncio.run(st.broadcast(event_a))  # A
            asyncio.run(st.broadcast(event_b))  # B
            asyncio.run(st.broadcast(event_a))  # A again — but last was B, so send it
        finally:
            st._connected_clients.clear()

        assert len(sends) == 3, "A-B-A pattern must produce three sends"

    def test_broadcast_skips_when_headless(self):
        """Headless mode short-circuits before dedup logic."""
        st = self._reset_state()
        st._mode["headless"] = True
        sends = []

        class FakeWS:
            async def send_text(self, msg):
                sends.append(msg)

        st._connected_clients.add(FakeWS())
        try:
            asyncio.run(st.broadcast({"type": "move", "san": "e4"}))
        finally:
            st._mode["headless"] = False
            st._connected_clients.clear()

        assert len(sends) == 0
        # Headless short-circuit happens before setting _last_broadcast_msg
        assert st._last_broadcast_msg is None

    def test_broadcast_skips_when_no_clients(self):
        """No-op when client set is empty; _last_broadcast_msg stays None."""
        st = self._reset_state()
        asyncio.run(st.broadcast({"type": "move", "san": "e4"}))
        assert st._last_broadcast_msg is None
