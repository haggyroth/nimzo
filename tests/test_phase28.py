"""
tests/test_phase28.py — Phase 28: Wave C replay enrichment.

Covers:
  C-1  viewer.html has rpEvalChart container element
  C-2  viewer.html has rp-pgn-dl download button in replay header
  C-3  viewer.js defines rpRenderEvalChart function
  C-4  viewer.js rpRenderEvalChart builds SVG with eval data
  C-5  viewer.js rpRender calls rpRenderEvalChart
  C-6  viewer.js openReplay renders rp-eval-badge on move items
  C-7  viewer.js openReplay renders rp-summary game summary bar
  C-8  rp-summary shows blunder/mistake/inaccuracy chips
  C-9  viewer.css has rp-eval-chart styles
  C-10 viewer.css has rp-eval-badge styles
  C-11 viewer.css has rp-summary and rp-sum-chip styles
  C-12 viewer.css has rp-pgn-dl styles
  C-13 HTTP: GET /api/games/<id>/moves returns score_cp for each move
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import arena  # noqa: F401 — pre-init to avoid circular import


_VIEWER_JS   = Path(__file__).parents[1] / "static" / "viewer.js"
_VIEWER_HTML = Path(__file__).parents[1] / "viewer.html"
_VIEWER_CSS  = Path(__file__).parents[1] / "static" / "viewer.css"


# ── C-1 / C-2: viewer.html checks ────────────────────────────────────────────

class TestViewerHtmlWaveC:
    def _html(self):
        return _VIEWER_HTML.read_text()

    def test_eval_chart_container_present(self):
        """C-1: viewer.html has rpEvalChart container element."""
        assert "rpEvalChart" in self._html()

    def test_pgn_dl_button_present(self):
        """C-2: viewer.html has rp-pgn-dl download button wired to downloadGamePgn."""
        html = self._html()
        assert "rp-pgn-dl" in html
        assert "downloadGamePgn" in html


# ── C-3 through C-8: viewer.js source checks ─────────────────────────────────

class TestViewerJsWaveC:
    def _src(self):
        return _VIEWER_JS.read_text()

    def test_rp_render_eval_chart_defined(self):
        """C-3: rpRenderEvalChart is defined in viewer.js."""
        assert "function rpRenderEvalChart" in self._src()

    def test_rp_render_eval_chart_builds_svg(self):
        """C-4: rpRenderEvalChart generates an SVG element."""
        src = self._src()
        fn_start = src.index("function rpRenderEvalChart")
        # Find the matching closing brace by scanning forward
        fn_body = src[fn_start:fn_start + 3000]
        assert "<svg" in fn_body
        assert "polyline" in fn_body  # the eval line
        assert "rpGo" in fn_body       # clickable cursor jumps

    def test_rp_render_calls_eval_chart(self):
        """C-5: rpRender calls rpRenderEvalChart() to update the cursor."""
        src = self._src()
        rp_render_start = src.index("function rpRender()")
        # Find end of rpRender — next function definition
        next_fn = src.index("function rpDrawBoard", rp_render_start)
        rp_render_body = src[rp_render_start:next_fn]
        assert "rpRenderEvalChart" in rp_render_body

    def test_open_replay_renders_eval_badge(self):
        """C-6: openReplay renders rp-eval-badge on move items."""
        src = self._src()
        open_replay_start = src.index("async function openReplay")
        close_replay_start = src.index("function closeReplay", open_replay_start)
        open_replay_body = src[open_replay_start:close_replay_start]
        assert "rp-eval-badge" in open_replay_body
        assert "score_cp" in open_replay_body

    def test_open_replay_renders_summary(self):
        """C-7: openReplay renders rp-summary game summary bar."""
        src = self._src()
        open_replay_start = src.index("async function openReplay")
        close_replay_start = src.index("function closeReplay", open_replay_start)
        open_replay_body = src[open_replay_start:close_replay_start]
        assert "rp-summary" in open_replay_body

    def test_summary_counts_blunders_mistakes(self):
        """C-8: game summary tracks blunder/mistake/inaccuracy per player."""
        src = self._src()
        open_replay_start = src.index("async function openReplay")
        close_replay_start = src.index("function closeReplay", open_replay_start)
        open_replay_body = src[open_replay_start:close_replay_start]
        # Should accumulate per-player quality counts
        assert "blunder" in open_replay_body
        assert "mistake" in open_replay_body
        assert "inaccuracy" in open_replay_body
        assert "rp-sum-chip" in open_replay_body


# ── C-9 through C-12: viewer.css checks ──────────────────────────────────────

class TestViewerCssWaveC:
    def _css(self):
        return _VIEWER_CSS.read_text()

    def test_eval_chart_styles_present(self):
        """C-9: viewer.css has .rp-eval-chart styles."""
        assert ".rp-eval-chart" in self._css()

    def test_eval_badge_styles_present(self):
        """C-10: viewer.css has .rp-eval-badge styles."""
        assert ".rp-eval-badge" in self._css()

    def test_summary_styles_present(self):
        """C-11: viewer.css has .rp-summary and .rp-sum-chip styles."""
        css = self._css()
        assert ".rp-summary" in css
        assert ".rp-sum-chip" in css

    def test_pgn_dl_styles_present(self):
        """C-12: viewer.css has .rp-pgn-dl styles."""
        assert ".rp-pgn-dl" in self._css()


# ── C-13: HTTP route test ─────────────────────────────────────────────────────

@contextmanager
def _make_http_client(tmp_path: Path):
    from fastapi.testclient import TestClient
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
        database.upsert_player("model-a", "Alice", "lmstudio")
        database.upsert_player("model-b", "Bob",   "lmstudio")
        gid = database.record_game(
            "model-a", "model-b", "1-0", "Checkmate", 4,
            "1. e4 e5 2. Nf3 Nc6",
            1200.0, 1200.0, 1220.0, 1180.0,
        )
        database.record_move(
            game_id=gid, move_number=1, player_model_id="model-a",
            move_uci="e2e4", move_san="e4",
            candidate_rank=1, quality="best", score_cp=30,
            reasoning="Central control",
            fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            thinking_content="", coherence_score=None, timed_out=False, elapsed_ms=500,
        )
        database.record_move(
            game_id=gid, move_number=2, player_model_id="model-b",
            move_uci="e7e5", move_san="e5",
            candidate_rank=1, quality="good", score_cp=-10,
            reasoning="Symmetric response",
            fen_after="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
            thinking_content="", coherence_score=None, timed_out=False, elapsed_ms=700,
        )

        from arena import app as _app
        with TestClient(_app, raise_server_exceptions=True) as client:
            yield client, gid


class TestHttpWaveC:
    def test_moves_endpoint_returns_score_cp(self, tmp_path):
        """C-13: GET /api/games/<id>/moves returns score_cp for each move."""
        with _make_http_client(tmp_path) as (client, gid):
            resp = client.get(f"/api/games/{gid}/moves")
        assert resp.status_code == 200
        moves = resp.json()
        assert len(moves) == 2
        # Both moves should have score_cp
        assert moves[0]["score_cp"] == 30
        assert moves[1]["score_cp"] == -10
