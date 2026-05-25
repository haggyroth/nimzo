"""
Tests for Phase 15 — Competitive Depth:
  - Personality styles: directive injection in build_system_prompt
  - Move-quality analytics: get_player_quality_stats
  - Adaptive difficulty: get_recent_win_rate, candidate_count adjustment
"""
import pytest

from models.base import PlayerConfig, ChessPlayer


# ── helpers ──────────────────────────────────────────────────────────────────

def _cfg(style: str = "") -> PlayerConfig:
    return PlayerConfig(name="Bot", model_id="m", backend="lmstudio", style=style)


def _make_game(db, white_mid, black_mid, result="1-0"):
    db.upsert_player(model_id=white_mid, name=white_mid, backend="lmstudio")
    db.upsert_player(model_id=black_mid, name=black_mid, backend="lmstudio")
    return db.record_game(
        white_model_id=white_mid, black_model_id=black_mid,
        result=result, termination="checkmate", total_moves=10,
        pgn="1. e4 e5 *", white_elo_before=1200, black_elo_before=1200,
        white_elo_after=1216, black_elo_after=1184,
    )


# ── Personality styles ────────────────────────────────────────────────────────

class TestPersonalityStyles:
    """build_system_prompt injects the right directive per style."""

    def _prompt(self, style: str) -> str:
        # Minimal concrete subclass — only need build_system_prompt
        class _P(ChessPlayer):
            def choose_move(self, board, candidates, pgn):
                raise NotImplementedError

        return _P(_cfg(style)).build_system_prompt()

    def test_no_style_no_directive(self):
        prompt = self._prompt("")
        assert "playing style" not in prompt.lower()

    def test_balanced_alias_none(self):
        # empty string and "balanced" both produce no directive
        p1 = self._prompt("")
        p2 = self._prompt("balanced")  # unknown key → no directive
        assert "playing style" not in p1.lower()
        assert "playing style" not in p2.lower()

    def test_aggressive_directive_injected(self):
        prompt = self._prompt("aggressive")
        assert "aggressive" in prompt.lower()
        assert "open games" in prompt.lower()

    def test_positional_directive_injected(self):
        prompt = self._prompt("positional")
        assert "positional" in prompt.lower()
        assert "outpost" in prompt.lower()

    def test_defensive_directive_injected(self):
        prompt = self._prompt("defensive")
        assert "defensive" in prompt.lower()
        assert "consolidate" in prompt.lower()

    def test_directive_comes_before_lessons(self):
        """Style directive should appear before lesson memory in the prompt."""
        cfg = _cfg("aggressive")
        cfg.lesson_memory = ["[improve] Watch your queen."]

        class _P(ChessPlayer):
            def choose_move(self, board, candidates, pgn):
                raise NotImplementedError

        prompt = _P(cfg).build_system_prompt()
        assert prompt.index("aggressive") < prompt.index("Watch your queen")

    def test_system_prompt_override_appended_after_style(self):
        cfg = _cfg("positional")
        cfg.system_prompt = "Extra instruction."

        class _P(ChessPlayer):
            def choose_move(self, board, candidates, pgn):
                raise NotImplementedError

        prompt = _P(cfg).build_system_prompt()
        assert prompt.index("positional") < prompt.index("Extra instruction")

    def test_unknown_style_produces_no_extra_text(self):
        prompt = self._prompt("chaotic_evil")
        # Should just be the base prompt — no directive, no crash
        assert "chaotic_evil" not in prompt


# ── Move-quality analytics ────────────────────────────────────────────────────

class TestGetPlayerQualityStats:
    def test_unknown_model_returns_none(self, tmp_db):
        assert tmp_db.get_player_quality_stats("ghost") is None

    def test_no_moves_returns_none(self, tmp_db):
        tmp_db.upsert_player(model_id="empty", name="Empty", backend="lmstudio")
        assert tmp_db.get_player_quality_stats("empty") is None

    def _seed(self, db, model_id, moves: list[tuple[str, int]]):
        """Insert a player and record moves with given (quality, candidate_rank)."""
        opp = "opp"
        db.upsert_player(model_id=model_id, name=model_id, backend="lmstudio")
        db.upsert_player(model_id=opp, name=opp, backend="lmstudio")
        gid = db.record_game(
            white_model_id=model_id, black_model_id=opp,
            result="1-0", termination="checkmate", total_moves=len(moves),
            pgn="*", white_elo_before=1200, black_elo_before=1200,
            white_elo_after=1216, black_elo_after=1184,
        )
        for i, (quality, rank) in enumerate(moves, 1):
            db.record_move(
                game_id=gid, player_model_id=model_id,
                move_number=i * 2 - 1, move_san="e4", move_uci="e2e4",
                candidate_rank=rank, quality=quality, score_cp=10,
                reasoning="ok", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b",
            )

    def test_total_moves_count(self, tmp_db):
        self._seed(tmp_db, "bot", [("good", 1), ("blunder", 3), ("best", 1)])
        stats = tmp_db.get_player_quality_stats("bot")
        assert stats["total_moves"] == 3

    def test_quality_counts(self, tmp_db):
        self._seed(tmp_db, "bot", [("blunder", 3), ("blunder", 4), ("good", 1)])
        stats = tmp_db.get_player_quality_stats("bot")
        assert stats["blunder"] == 2
        assert stats["good"] == 1
        assert stats["mistake"] == 0

    def test_blunder_rate(self, tmp_db):
        self._seed(tmp_db, "bot", [("blunder", 3), ("good", 1), ("good", 1)])
        stats = tmp_db.get_player_quality_stats("bot")
        assert stats["blunder_rate"] == pytest.approx(1 / 3, abs=0.001)

    def test_bad_move_rate_includes_mistakes(self, tmp_db):
        self._seed(tmp_db, "bot", [("blunder", 3), ("mistake", 2), ("good", 1)])
        stats = tmp_db.get_player_quality_stats("bot")
        assert stats["bad_move_rate"] == pytest.approx(2 / 3, abs=0.001)

    def test_avg_candidate_rank(self, tmp_db):
        self._seed(tmp_db, "bot", [("good", 1), ("good", 3)])
        stats = tmp_db.get_player_quality_stats("bot")
        assert stats["avg_candidate_rank"] == pytest.approx(2.0, abs=0.01)

    def test_model_id_in_result(self, tmp_db):
        self._seed(tmp_db, "mybot", [("good", 1)])
        stats = tmp_db.get_player_quality_stats("mybot")
        assert stats["model_id"] == "mybot"

    def test_all_rate_keys_present(self, tmp_db):
        self._seed(tmp_db, "bot", [("good", 1)])
        stats = tmp_db.get_player_quality_stats("bot")
        for q in ("best", "excellent", "good", "inaccuracy", "mistake", "blunder"):
            assert f"{q}_rate" in stats
        assert "bad_move_rate" in stats


# ── Adaptive difficulty ───────────────────────────────────────────────────────

class TestGetRecentWinRate:
    def test_unknown_model_returns_none(self, tmp_db):
        assert tmp_db.get_recent_win_rate("ghost") is None

    def test_fewer_than_n_games_returns_none(self, tmp_db):
        _make_game(tmp_db, "a", "b")  # only 1 game, n=10 default
        assert tmp_db.get_recent_win_rate("a") is None

    def test_exact_n_games_returns_rate(self, tmp_db):
        for _ in range(10):
            _make_game(tmp_db, "a", "b", result="1-0")
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == 1.0

    def test_all_losses_returns_zero(self, tmp_db):
        for _ in range(10):
            _make_game(tmp_db, "a", "b", result="0-1")
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == 0.0

    def test_all_draws_returns_half(self, tmp_db):
        for _ in range(10):
            _make_game(tmp_db, "a", "b", result="1/2-1/2")
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == pytest.approx(0.5)

    def test_mixed_results(self, tmp_db):
        # 6 wins, 2 draws, 2 losses → 6 + 1 + 1 / 10 = 0.8 ← wait
        # 6 wins = 6pts, 2 draws = 1pt, 2 losses = 0 → 7/10 = 0.7
        for _ in range(6):
            _make_game(tmp_db, "a", "b", result="1-0")
        for _ in range(2):
            _make_game(tmp_db, "a", "b", result="1/2-1/2")
        for _ in range(2):
            _make_game(tmp_db, "a", "b", result="0-1")
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == pytest.approx(0.7, abs=0.001)

    def test_plays_as_black(self, tmp_db):
        """Win rate accounts for colour — model as black wins when result=0-1."""
        for _ in range(10):
            _make_game(tmp_db, "b", "a", result="0-1")  # "a" is black, wins
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == 1.0

    def test_only_last_n_games_counted(self, tmp_db):
        """Older games beyond the window don't affect the rate."""
        # 5 old losses
        for _ in range(5):
            _make_game(tmp_db, "a", "b", result="0-1")
        # 10 recent wins (these should be the window)
        for _ in range(10):
            _make_game(tmp_db, "a", "b", result="1-0")
        rate = tmp_db.get_recent_win_rate("a", n=10)
        assert rate == 1.0

    def test_custom_n(self, tmp_db):
        for _ in range(5):
            _make_game(tmp_db, "a", "b", result="1-0")
        # n=5 should succeed; n=6 should return None
        assert tmp_db.get_recent_win_rate("a", n=5) == 1.0
        assert tmp_db.get_recent_win_rate("a", n=6) is None
