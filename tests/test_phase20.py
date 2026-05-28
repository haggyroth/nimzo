"""
tests/test_phase20.py — Phase 20: forced opening prefix (opening_pgn).

Covers:
  P-1  TournamentStartConfig accepts opening_pgn
  P-2  Defaults to empty string when not supplied
  P-3  config_loader reads opening_pgn from TOML [match]
  P-4  config_loader defaults to "" when opening_pgn absent from TOML
  P-5  play_game replays valid prefix and broadcasts is_book_move events
  P-6  play_game silently skips illegal moves and continues from last valid position
  P-7  play_game handles completely invalid PGN without raising
  P-8  play_game with empty opening_pgn starts from the initial position
  P-9  HTTP: POST /api/tournament/start with opening_pgn is accepted
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch, MagicMock

import chess


# ── P-1 / P-2: Pydantic model validation ─────────────────────────────────────


class TestTournamentStartConfigOpeningPgn:
    def test_accepts_opening_pgn(self):
        """P-1: opening_pgn field is accepted."""
        from arena.models import TournamentStartConfig
        cfg = TournamentStartConfig(
            white_model="a", black_model="b",
            opening_pgn="1. e4 e5 2. Nf3 Nc6",
        )
        assert cfg.opening_pgn == "1. e4 e5 2. Nf3 Nc6"

    def test_defaults_to_empty_string(self):
        """P-2: opening_pgn defaults to empty string."""
        from arena.models import TournamentStartConfig
        cfg = TournamentStartConfig(white_model="a", black_model="b")
        assert cfg.opening_pgn == ""


# ── P-3 / P-4: config_loader TOML support ────────────────────────────────────


class TestConfigLoaderOpeningPgn:
    def test_reads_opening_pgn_from_toml(self, tmp_path):
        """P-3: [match] opening_pgn is parsed correctly."""
        toml_content = """\
[match]
games = 1
opening_pgn = "1. e4 e5 2. Nf3 Nc6"

[white]
name = "W"
model = "m1"

[black]
name = "B"
model = "m2"
"""
        toml_path = tmp_path / "test.toml"
        toml_path.write_text(toml_content)
        from config_loader import load_config
        cfg = load_config(str(toml_path))
        assert cfg.opening_pgn == "1. e4 e5 2. Nf3 Nc6"

    def test_opening_pgn_absent_gives_empty(self, tmp_path):
        """P-4: omitting opening_pgn in TOML gives empty string."""
        toml_content = """\
[match]
games = 1

[white]
name = "W"
model = "m1"

[black]
name = "B"
model = "m2"
"""
        toml_path = tmp_path / "test.toml"
        toml_path.write_text(toml_content)
        from config_loader import load_config
        cfg = load_config(str(toml_path))
        assert cfg.opening_pgn == ""


# ── P-5 through P-8: play_game prefix logic ───────────────────────────────────


def _fake_stockfish():
    """Return a mock StockfishEngine that always gives one candidate."""
    sf = MagicMock()
    # get_candidates returns list of (chess.Move, score_cp) tuples
    sf.get_candidates.side_effect = lambda board, n: [
        (next(iter(board.legal_moves)), 0)
    ]
    sf.evaluate_move_quality.return_value = "good"
    return sf


def _fake_player(color: str, stop_after: int = 0):
    """
    Return a mock ChessPlayer.

    If stop_after > 0, the player raises TournamentAborted after that many
    calls so tests don't run a full game.
    """
    from models.base import PlayerConfig, MoveDecision
    import arena as _arena

    cfg = PlayerConfig(
        name=color, model_id=f"test-{color}", backend="lmstudio",
        base_url="http://localhost:1234/v1", candidate_count=5,
    )
    player = MagicMock()
    player.config = cfg
    player.elo = 1200.0
    call_count = [0]

    def _choose(board, candidates, pgn):
        call_count[0] += 1
        if stop_after and call_count[0] > stop_after:
            raise _arena.TournamentAborted()
        move = candidates[0][0] if candidates else next(iter(board.legal_moves))
        return MoveDecision(move_uci=move.uci(), reasoning="test", candidate_rank=1, raw_response="")

    player.choose_move.side_effect = _choose
    return player


class TestPlayGameOpeningPrefix:
    """Tests that play_game correctly handles opening_pgn."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_broadcasts_book_moves(self):
        """P-5: valid prefix broadcasts is_book_move=True events."""
        import arena as _arena
        from game import play_game

        broadcast_events = []

        async def fake_broadcast(msg):
            broadcast_events.append(msg)

        white = _fake_player("white", stop_after=1)
        black = _fake_player("black", stop_after=1)
        sf = _fake_stockfish()

        with patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": False}), \
             patch.dict(_arena._mode, {"headless": True}):
            try:
                self._run(play_game(white, black, sf, 1, opening_pgn="1. e4 e5"))
            except Exception:
                pass  # TournamentAborted or game over — we only care about events

        book_events = [e for e in broadcast_events if e.get("is_book_move")]
        # "1. e4 e5" = 2 moves → 2 book events
        assert len(book_events) == 2
        assert book_events[0]["quality"] == "book"
        assert book_events[0]["san"] == "e4"
        assert book_events[1]["san"] == "e5"

    def test_prefix_advances_board_position(self):
        """P-5b: after prefix, board is at the expected position."""
        import arena as _arena
        from game import play_game

        board_fens_at_book = []

        async def fake_broadcast(msg):
            if msg.get("is_book_move"):
                board_fens_at_book.append(msg["fen"])

        white = _fake_player("white", stop_after=0)
        black = _fake_player("black", stop_after=0)
        sf = _fake_stockfish()

        with patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": True}), \
             patch.dict(_arena._mode, {"headless": True}):
            try:
                self._run(play_game(white, black, sf, 1, opening_pgn="1. d4"))
            except Exception:
                pass

        # After 1. d4, it's Black's turn
        assert len(board_fens_at_book) == 1
        board = chess.Board(board_fens_at_book[0])
        assert board.turn == chess.BLACK
        assert board.fullmove_number == 1

    def test_illegal_move_stops_prefix_early(self):
        """P-6: illegal move in PGN stops the prefix; game continues from that point."""
        import arena as _arena
        from game import play_game

        book_sans = []

        async def fake_broadcast(msg):
            if msg.get("is_book_move"):
                book_sans.append(msg["san"])

        white = _fake_player("white", stop_after=1)
        black = _fake_player("black", stop_after=1)
        sf = _fake_stockfish()

        # "1. e4 Qxh8" — Qxh8 is illegal from the starting position after 1.e4
        # We build a raw PGN with an illegal second move by constructing it ourselves.
        # chess.pgn.read_game will still parse it; board.push will reject it.
        # Craft raw UCI PGN that chess will parse but the second move is invalid:
        bad_pgn = "1. e4 e5 2. Ke2 Ke7 3. Kxe5"  # Kxe5 captures own piece — illegal
        # Only e4, e5, Ke2, Ke7 should be pushed; Kxe5 is illegal
        with patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": False}), \
             patch.dict(_arena._mode, {"headless": True}):
            try:
                self._run(play_game(white, black, sf, 1, opening_pgn=bad_pgn))
            except Exception:
                pass

        # Kxe5 is not a legal move, so prefix stops at 4 moves (e4, e5, Ke2, Ke7)
        assert len(book_sans) == 4
        assert "Kxe5" not in book_sans

    def test_invalid_pgn_does_not_raise(self):
        """P-7: completely garbled PGN is silently ignored."""
        import arena as _arena
        from game import play_game

        book_events = []

        async def fake_broadcast(msg):
            if msg.get("is_book_move"):
                book_events.append(msg)

        white = _fake_player("white", stop_after=1)
        black = _fake_player("black", stop_after=1)
        sf = _fake_stockfish()

        with patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": False}), \
             patch.dict(_arena._mode, {"headless": True}):
            try:
                self._run(play_game(white, black, sf, 1, opening_pgn="NOT VALID PGN !!!"))
            except Exception:
                pass

        # No book moves should be broadcast for garbled input
        assert len(book_events) == 0

    def test_empty_opening_pgn_no_book_events(self):
        """P-8: empty opening_pgn produces no book move events."""
        import arena as _arena
        from game import play_game

        book_events = []

        async def fake_broadcast(msg):
            if msg.get("is_book_move"):
                book_events.append(msg)

        white = _fake_player("white", stop_after=1)
        black = _fake_player("black", stop_after=1)
        sf = _fake_stockfish()

        with patch.object(_arena, "broadcast", side_effect=fake_broadcast), \
             patch.object(_arena._pause_event, "wait", new=AsyncMock(return_value=None)), \
             patch.dict(_arena._stop, {"requested": False}), \
             patch.dict(_arena._mode, {"headless": True}):
            try:
                self._run(play_game(white, black, sf, 1, opening_pgn=""))
            except Exception:
                pass

        assert len(book_events) == 0


# ── P-9: HTTP route ───────────────────────────────────────────────────────────


class TestOpeningPgnHTTPRoute:
    def _client(self, tmp_path):
        import db as database
        db_path = tmp_path / "test.db"

        @contextmanager
        def _conn(path_arg=None):
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

        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            from fastapi.testclient import TestClient
            from arena import app
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c

    def test_post_start_accepts_opening_pgn(self, tmp_path):
        """P-9: POST /api/tournament/start with opening_pgn is accepted."""
        for client in self._client(tmp_path):
            resp = client.post("/api/tournament/start", json={
                "white_model": "model-a",
                "black_model": "model-b",
                "white_backend": "lmstudio",
                "black_backend": "lmstudio",
                "opening_pgn": "1. e4 e5 2. Nf3 Nc6",
                "games": 1,
            })
            assert resp.status_code == 200
