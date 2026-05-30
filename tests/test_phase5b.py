"""
tests/test_phase5b.py — Phase 5b: Stockfish depth-20 post-game annotation.

Covers:
  A-1  engine.StockfishEngine has an annotate_game method
  A-2  annotate_game returns expected keys per move
  A-3  annotate_game handles empty / invalid PGN gracefully
  A-4  db.record_move_annotations + db.get_game_annotations round-trip
  A-5  db.get_game_annotations returns empty list for unannotated game
  A-6  db.record_move_annotations is idempotent (re-annotation replaces rows)
  A-7  db.get_annotation_status returns 'done'/'none' correctly
  A-8  HTTP: GET /api/games/<id>/annotations returns 200 + list
  A-9  HTTP: GET /api/games/<id>/annotations returns [] for unannotated game
  A-10 viewer.js defines onAnnotationsReady function
  A-11 viewer.js openReplay fetches /annotations alongside /moves
  A-12 viewer.js references rp-ann-dot in move list rendering
  A-13 viewer.css defines .rp-ann-dot styles
  A-14 viewer.css defines .rp-annotation block styles
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import arena  # noqa: F401 — pre-init the package


# ── Paths ──────────────────────────────────────────────────────────────────

_VIEWER_JS  = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_CSS = Path(__file__).parents[1] / "static" / "viewer.css"


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_conn_factory(db_path: Path):
    """Return a get_conn-compatible context-manager factory."""
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
    return _conn


# ── A-1 / A-2 / A-3: engine.annotate_game ─────────────────────────────────

class TestAnnotateGame:
    """Tests for StockfishEngine.annotate_game (engine mocked — no Stockfish in CI)."""

    _SAMPLE_PGN = (
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 "
        "6. Re1 b5 7. Bb3 d6 8. c3 O-O *"
    )

    def _make_engine(self, top_cp=50, actual_cp=30):
        """Build a mock chess.engine.SimpleEngine whose analyse returns fixed scores."""
        mock_score_top    = MagicMock()
        mock_score_actual = MagicMock()
        mock_score_top.pov.return_value    = MagicMock(is_mate=MagicMock(return_value=False), score=MagicMock(return_value=top_cp))
        mock_score_actual.pov.return_value = MagicMock(is_mate=MagicMock(return_value=False), score=MagicMock(return_value=actual_cp))

        def _analyse(board, limit, multipv=None, root_moves=None):
            legal = list(board.legal_moves)
            if not legal:
                return {"pv": [], "score": mock_score_top}
            top_move = legal[0]
            if root_moves:
                return {"pv": [root_moves[0]], "score": mock_score_actual}
            return {"pv": [top_move], "score": mock_score_top}

        mock_engine = MagicMock()
        mock_engine.analyse.side_effect = _analyse
        return mock_engine

    def test_annotate_game_method_exists(self):
        """A-1: StockfishEngine has annotate_game."""
        from engine import StockfishEngine
        assert hasattr(StockfishEngine, "annotate_game")
        assert callable(StockfishEngine.annotate_game)

    def test_annotate_game_returns_correct_keys(self):
        """A-2: annotate_game returns dicts with required keys per move."""
        from engine import StockfishEngine
        sf = StockfishEngine.__new__(StockfishEngine)
        sf._engine = self._make_engine(top_cp=50, actual_cp=30)

        results = sf.annotate_game(self._SAMPLE_PGN)
        assert len(results) > 0
        required = {"move_number", "move_san", "annotation", "cp_loss", "best_move_san"}
        for item in results:
            assert required.issubset(item.keys()), f"Missing keys in {item}"

    def test_annotate_game_move_numbers_sequential(self):
        """A-2b: move_number is 1-based and sequential."""
        from engine import StockfishEngine
        sf = StockfishEngine.__new__(StockfishEngine)
        sf._engine = self._make_engine()

        results = sf.annotate_game(self._SAMPLE_PGN)
        for i, item in enumerate(results, 1):
            assert item["move_number"] == i

    def test_annotate_game_empty_pgn(self):
        """A-3a: annotate_game returns [] for empty PGN."""
        from engine import StockfishEngine
        sf = StockfishEngine.__new__(StockfishEngine)
        sf._engine = self._make_engine()
        assert sf.annotate_game("") == []

    def test_annotate_game_invalid_pgn(self):
        """A-3b: annotate_game returns [] for garbage PGN."""
        from engine import StockfishEngine
        sf = StockfishEngine.__new__(StockfishEngine)
        sf._engine = self._make_engine()
        assert sf.annotate_game("not a pgn at all ????") == []

    def test_annotate_game_quality_labels(self):
        """A-2c: cp_loss=20 → 'good' (CP_LOSS_EXCELLENT=10 ≤ 20 < CP_LOSS_GOOD=25)."""
        from engine import StockfishEngine
        sf = StockfishEngine.__new__(StockfishEngine)
        # top=50, actual=30 → cp_loss=20 → 'good'
        sf._engine = self._make_engine(top_cp=50, actual_cp=30)
        results = sf.annotate_game(self._SAMPLE_PGN)
        # Some moves will be "best" (played move == top_move),
        # others "good" (cp_loss=20). None should be "blunder".
        labels = {r["annotation"] for r in results}
        assert not (labels - {"best", "good", "unknown"})


# ── A-4 / A-5 / A-6 / A-7: db functions ──────────────────────────────────

class TestAnnotationDb:
    def _seed(self, db, db_path):
        db._leaderboard_cache = None
        db._migrate_column_cache.clear()
        db.init_db(db_path)
        db.upsert_player("m-a", "Alice", "lmstudio")
        db.upsert_player("m-b", "Bob",   "lmstudio")
        return db.record_game(
            "m-a", "m-b", "1-0", "Checkmate", 4,
            "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#",
            1200.0, 1200.0, 1220.0, 1180.0,
        )

    def test_record_and_get_annotations(self, tmp_path):
        """A-4: record_move_annotations + get_game_annotations round-trip."""
        import db as database
        db_path = tmp_path / "ann.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed(database, db_path)
            anns = [
                {"move_number": 1, "annotation": "best",     "cp_loss": 0,   "best_move_san": "e4"},
                {"move_number": 2, "annotation": "inaccuracy","cp_loss": 35,  "best_move_san": "d5"},
                {"move_number": 3, "annotation": "blunder",   "cp_loss": 200, "best_move_san": "Nf3"},
                {"move_number": 4, "annotation": "best",     "cp_loss": 0,   "best_move_san": "Qxf7#"},
            ]
            database.record_move_annotations(game_id, anns)
            rows = database.get_game_annotations(game_id)
        assert len(rows) == 4
        assert rows[0]["annotation"] == "best"
        assert rows[1]["annotation"] == "inaccuracy"
        assert rows[2]["cp_loss"]    == 200
        assert rows[2]["best_move_san"] == "Nf3"

    def test_get_annotations_empty_for_new_game(self, tmp_path):
        """A-5: get_game_annotations returns [] before annotation runs."""
        import db as database
        db_path = tmp_path / "ann2.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed(database, db_path)
            rows = database.get_game_annotations(game_id)
        assert rows == []

    def test_record_annotations_idempotent(self, tmp_path):
        """A-6: re-annotating same game replaces previous rows."""
        import db as database
        db_path = tmp_path / "ann3.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed(database, db_path)
            database.record_move_annotations(game_id, [
                {"move_number": 1, "annotation": "blunder", "cp_loss": 300, "best_move_san": "d4"},
            ])
            # Re-annotate with different data
            database.record_move_annotations(game_id, [
                {"move_number": 1, "annotation": "best", "cp_loss": 0, "best_move_san": "e4"},
                {"move_number": 2, "annotation": "good", "cp_loss": 15, "best_move_san": None},
            ])
            rows = database.get_game_annotations(game_id)
        assert len(rows) == 2
        assert rows[0]["annotation"] == "best"

    def test_annotation_status(self, tmp_path):
        """A-7: get_annotation_status returns 'none' then 'done'."""
        import db as database
        db_path = tmp_path / "ann4.db"
        _conn = _make_conn_factory(db_path)
        with patch.object(database, "get_conn", _conn):
            game_id = self._seed(database, db_path)
            assert database.get_annotation_status(game_id) == "none"
            database.record_move_annotations(game_id, [
                {"move_number": 1, "annotation": "best", "cp_loss": 0, "best_move_san": "e4"},
            ])
            assert database.get_annotation_status(game_id) == "done"


# ── A-8 / A-9: HTTP routes ─────────────────────────────────────────────────

@contextmanager
def _make_client(tmp_path: Path):
    import db as database
    from fastapi.testclient import TestClient

    db_path = tmp_path / "http.db"
    _conn = _make_conn_factory(db_path)

    with patch.object(database, "get_conn", _conn):
        database._leaderboard_cache = None
        database._migrate_column_cache.clear()
        database.init_db(db_path)
        database.upsert_player("m-a", "Alice", "lmstudio")
        database.upsert_player("m-b", "Bob",   "lmstudio")
        gid = database.record_game(
            "m-a", "m-b", "1-0", "Checkmate", 4,
            "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#",
            1200.0, 1200.0, 1220.0, 1180.0,
        )
        database.record_move_annotations(gid, [
            {"move_number": 1, "annotation": "best",    "cp_loss": 0,  "best_move_san": "e4"},
            {"move_number": 2, "annotation": "mistake", "cp_loss": 80, "best_move_san": "d5"},
        ])

        from arena import app as _app
        with TestClient(_app, raise_server_exceptions=True) as client:
            yield client, gid


class TestAnnotationsEndpoint:
    def test_annotations_returns_200(self, tmp_path):
        """A-8: GET /api/games/<id>/annotations returns 200."""
        with _make_client(tmp_path) as (client, gid):
            resp = client.get(f"/api/games/{gid}/annotations")
        assert resp.status_code == 200

    def test_annotations_returns_list(self, tmp_path):
        """A-8b: response body is a list with expected fields."""
        with _make_client(tmp_path) as (client, gid):
            resp = client.get(f"/api/games/{gid}/annotations")
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["annotation"] == "best"
        assert data[1]["annotation"] == "mistake"
        assert data[1]["cp_loss"] == 80
        assert "best_move_san" in data[0]

    def test_annotations_empty_for_unannotated(self, tmp_path):
        """A-9: returns [] for a game with no annotations yet."""
        import db as database
        db_path = tmp_path / "empty.db"
        _conn = _make_conn_factory(db_path)

        with patch.object(database, "get_conn", _conn):
            database._leaderboard_cache = None
            database._migrate_column_cache.clear()
            database.init_db(db_path)
            database.upsert_player("m-a", "Alice", "lmstudio")
            database.upsert_player("m-b", "Bob",   "lmstudio")
            gid = database.record_game(
                "m-a", "m-b", "1-0", "Checkmate", 4, "1. e4 e5 *",
                1200.0, 1200.0, 1220.0, 1180.0,
            )
            from arena import app as _app
            from fastapi.testclient import TestClient
            with TestClient(_app, raise_server_exceptions=True) as client:
                resp = client.get(f"/api/games/{gid}/annotations")
        assert resp.status_code == 200
        assert resp.json() == []


# ── A-10 / A-11 / A-12: viewer.js ─────────────────────────────────────────

class TestViewerJsPhase5b:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_on_annotations_ready_defined(self):
        """A-10: onAnnotationsReady is defined in viewer.js."""
        assert "async function onAnnotationsReady" in self._src()

    def test_open_replay_fetches_annotations(self):
        """A-11: openReplay fetches /annotations alongside /moves."""
        src = self._src()
        # Find openReplay function body
        start = src.index("async function openReplay")
        end   = src.index("function closeReplay")
        fn_body = src[start:end]
        assert "/annotations" in fn_body

    def test_move_list_has_ann_dot(self):
        """A-12: move list rendering emits rp-ann-dot elements."""
        src = self._src()
        assert "rp-ann-dot" in src

    def test_annotation_block_in_rprender(self):
        """A-12b: rpRender emits rp-annotation block."""
        src = self._src()
        assert "rp-annotation" in src
        assert "rp-ann-" in src

    def test_annotations_ready_in_dispatch(self):
        """A-10b: annotations_ready is dispatched in the WS switch."""
        src = self._src()
        assert "annotations_ready" in src


# ── A-13 / A-14: viewer.css ───────────────────────────────────────────────

class TestViewerCssPhase5b:
    def _css(self):
        return _VIEWER_CSS.read_text()

    def test_rp_ann_dot_defined(self):
        """A-13: .rp-ann-dot class is defined in viewer.css."""
        assert ".rp-ann-dot" in self._css()

    def test_rp_annotation_defined(self):
        """A-14: .rp-annotation class is defined in viewer.css."""
        assert ".rp-annotation" in self._css()

    def test_blunder_mistake_inaccuracy_dot_colors(self):
        """A-13b: annotation dot variants for blunder/mistake/inaccuracy exist."""
        css = self._css()
        assert "rp-ann-blunder"    in css
        assert "rp-ann-mistake"    in css
        assert "rp-ann-inaccuracy" in css
