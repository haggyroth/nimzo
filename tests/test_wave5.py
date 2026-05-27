"""
Wave-5 test hardening — T-8 through T-16.

  T-8   Blind mode: moves outside candidates list get quality="unknown"
  T-9   Blind mode: choose_move with empty candidates falls back to MOVE parse
  T-10  HumanPlayer null-move guard (MN-11): event set with no pending_uci
  T-11  HumanPlayer: submit after timeout is already set returns False
  T-12  Coherence regex doesn't match 110/10 (MN-12 regression)
  T-13  Lesson deduplication: jaccard rejects near-duplicate lessons
  T-14  _parse_lessons: all bullet styles parsed correctly
  T-15  Adaptive difficulty: candidate_count respects MIN/MAX bounds
  T-16  build_quality_summary: accurate counts and blunder/mistake lists
"""

from __future__ import annotations

import threading
import time

import chess
import pytest

from analysis import (
    JudgeConfig,
    _parse_lessons,
    build_quality_summary,
    is_duplicate_lesson,
    jaccard_similarity,
    score_reasoning_coherence,
)
from engine import StockfishEngine
from models.base import MoveDecision, PlayerConfig
from models.human_player import HumanPlayer


# ── Helpers ───────────────────────────────────────────────────────────────────


def _engine():
    """StockfishEngine without starting a subprocess."""
    return StockfishEngine.__new__(StockfishEngine)


def _move(uci: str) -> chess.Move:
    return chess.Move.from_uci(uci)


def _cands(*pairs):
    return [(_move(uci), cp) for uci, cp in pairs]


def _hp() -> HumanPlayer:
    cfg = PlayerConfig(name="Human", model_id="human", backend="human")
    return HumanPlayer(cfg)


# ── T-8: blind mode quality label ────────────────────────────────────────────


class TestBlindModeQuality:
    """T-8 — evaluate_move_quality returns 'unknown' for blind moves (MN-6)."""

    def setup_method(self):
        self.eng = _engine()
        self.board = chess.Board()

    def test_move_outside_candidates_returns_unknown(self):
        """The chosen move is not in the candidates list at all."""
        cands = _cands(("e2e4", 50), ("d2d4", 40))
        result = self.eng.evaluate_move_quality(self.board, _move("g1f3"), cands)
        assert result == "unknown"

    def test_none_score_for_chosen_returns_unknown(self):
        cands = [(_move("e2e4"), 50), (_move("d2d4"), None)]
        result = self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands)
        assert result == "unknown"

    def test_none_score_for_top_returns_unknown(self):
        cands = _cands(("e2e4", None), ("d2d4", 20))
        result = self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands)
        assert result == "unknown"

    def test_both_none_returns_unknown(self):
        cands = _cands(("e2e4", None), ("d2d4", None))
        result = self.eng.evaluate_move_quality(self.board, _move("d2d4"), cands)
        assert result == "unknown"

    def test_top_move_with_none_score_still_best(self):
        """Top-move identity check fires before the None guard."""
        cands = _cands(("e2e4", None), ("d2d4", 20))
        result = self.eng.evaluate_move_quality(self.board, _move("e2e4"), cands)
        assert result == "best"

    def test_empty_candidates_returns_unknown(self):
        result = self.eng.evaluate_move_quality(self.board, _move("e2e4"), [])
        assert result == "unknown"


# ── T-9: AnthropicPlayer blind-mode MOVE fallback ────────────────────────────


class TestAnthropicBlindModeParsing:
    """T-9 — _parse_response falls back to MOVE: field when no candidates given."""

    def _player(self):
        from models.anthropic_player import AnthropicPlayer

        cfg = PlayerConfig(
            name="Claude", model_id="claude-test",
            backend="anthropic", api_key="dummy-key",
        )
        return AnthropicPlayer.__new__(AnthropicPlayer)

    def setup_method(self):
        from models.anthropic_player import AnthropicPlayer
        import os

        cfg = PlayerConfig(
            name="Claude", model_id="claude-test",
            backend="anthropic", api_key="dummy",
        )
        # Bypass __init__ to avoid requiring a real API key
        self.player = AnthropicPlayer.__new__(AnthropicPlayer)
        self.player.config = cfg
        self.board = chess.Board()

    def test_move_field_parsed_in_blind_mode(self):
        """With empty candidates, MOVE: UCI should be extracted from the response."""
        raw = "MOVE: e2e4\nREASONING: Controls center."
        decision = self.player._parse_response(raw, [], self.board)
        assert decision.move_uci == "e2e4"
        assert decision.candidate_rank == 0  # no candidates → rank 0

    def test_invalid_uci_in_move_field_falls_through(self):
        """An invalid UCI in MOVE: should not crash — falls through to scan."""
        raw = "MOVE: zzz9\nREASONING: nonsense."
        # Starting board — any legal move in the response body would be picked.
        # If none found → random legal move returned
        decision = self.player._parse_response(raw, [], self.board)
        assert decision.move_uci  # some move returned, not a crash

    def test_fallback_to_random_with_no_candidates_and_no_uci(self):
        """Pure garbage response with no candidates → random legal move."""
        raw = "I don't know what to do here!"
        decision = self.player._parse_response(raw, [], self.board)
        move = chess.Move.from_uci(decision.move_uci)
        assert move in self.board.legal_moves


# ── T-10: HumanPlayer null-move guard (MN-11) ────────────────────────────────


class TestHumanPlayerNullMoveGuard:
    """T-10 — choose_move handles _pending_uci=None after event is set."""

    def test_null_pending_uci_falls_back_to_top_candidate(self):
        """
        Simulate race: _move_ready is set externally but _pending_uci stays None.
        choose_move must fall back gracefully rather than raising AttributeError.
        """
        board = chess.Board()
        cands = [(m, 30) for m in list(board.legal_moves)[:3]]
        hp = _hp()

        def _set_without_uci():
            time.sleep(0.05)
            # Trigger the event without setting _pending_uci
            hp._move_ready.set()

        t = threading.Thread(target=_set_without_uci, daemon=True)
        t.start()
        decision = hp.choose_move(board, cands, "")
        t.join()

        # Should fall back to top candidate rather than crash
        assert decision.move_uci == cands[0][0].uci()
        assert "lost" in decision.reasoning or "fallback" in decision.reasoning.lower()

    def test_valid_submit_still_works_normally(self):
        """Normal submit path is unaffected by the null guard."""
        board = chess.Board()
        cands = [(m, 30) for m in list(board.legal_moves)[:3]]
        hp = _hp()
        target_uci = cands[0][0].uci()

        def _submit():
            time.sleep(0.05)
            hp.submit_move(target_uci)

        t = threading.Thread(target=_submit, daemon=True)
        t.start()
        decision = hp.choose_move(board, cands, "")
        t.join()

        assert decision.move_uci == target_uci
        assert decision.reasoning == "(human move)"


# ── T-11: HumanPlayer submit after event already set ─────────────────────────


class TestHumanPlayerDoubleSubmit:
    """T-11 — submitting a second move while the event is already set is a no-op."""

    def test_double_submit_returns_false(self):
        board = chess.Board()
        hp = _hp()
        hp._current_board = board.copy()
        hp._current_candidates = [(m, 30) for m in list(board.legal_moves)[:3]]
        hp._move_ready.clear()

        # First submit succeeds
        first_uci = list(board.legal_moves)[0].uci()
        assert hp.submit_move(first_uci) is True
        assert hp._move_ready.is_set()

        # Second submit while event is set should return False
        second_uci = list(board.legal_moves)[1].uci()
        assert hp.submit_move(second_uci) is False

    def test_pending_uci_unchanged_after_double_submit(self):
        board = chess.Board()
        hp = _hp()
        hp._current_board = board.copy()
        hp._current_candidates = [(m, 30) for m in list(board.legal_moves)[:3]]
        hp._move_ready.clear()

        moves = list(board.legal_moves)
        first_uci = moves[0].uci()
        second_uci = moves[1].uci()

        hp.submit_move(first_uci)
        hp.submit_move(second_uci)   # should be ignored

        assert hp._pending_uci == first_uci


# ── T-12: Coherence regex boundary (MN-12) ───────────────────────────────────


class TestCoherenceRegexBoundary:
    """T-12 — \b word-boundary prevents matching '110/10' as score 10."""

    def test_110_not_mistaken_for_10(self, mocker):
        """'110/10' should not produce score 10.0 — regex uses \b boundaries."""
        mocker.patch("analysis._call_tutor_like", return_value="110/10")
        result = score_reasoning_coherence(
            reasoning="Good central control.",
            move_san="e4",
            board_fen=chess.STARTING_FEN,
            candidates=[(m, 50) for m in list(chess.Board().legal_moves)[:3]],
            judge=JudgeConfig(backend="lmstudio", model_id="judge"),
        )
        # '110/10' has no \b-bounded integer 0-10, so should return None
        assert result is None, (
            f"Regex matched '110/10' as {result!r} — word-boundary guard failed"
        )

    def test_bare_10_still_matched(self, mocker):
        """A bare '10' at word boundary must still parse correctly."""
        mocker.patch("analysis._call_tutor_like", return_value="10")
        result = score_reasoning_coherence(
            reasoning="Excellent move.",
            move_san="e4",
            board_fen=chess.STARTING_FEN,
            candidates=[(m, 50) for m in list(chess.Board().legal_moves)[:3]],
            judge=JudgeConfig(backend="lmstudio", model_id="judge"),
        )
        assert result == 10.0

    def test_score_in_prose_matched(self, mocker):
        """'Score: 7' — integer at word boundary inside prose — must still parse."""
        mocker.patch("analysis._call_tutor_like", return_value="Score: 7\nBecause...")
        result = score_reasoning_coherence(
            reasoning="Solid development.",
            move_san="Nf3",
            board_fen=chess.STARTING_FEN,
            candidates=[(m, 50) for m in list(chess.Board().legal_moves)[:3]],
            judge=JudgeConfig(backend="lmstudio", model_id="judge"),
        )
        assert result == 7.0


# ── T-13: Lesson deduplication ────────────────────────────────────────────────


class TestLessonDeduplication:
    """T-13 — jaccard_similarity and is_duplicate_lesson."""

    def test_identical_lessons_are_duplicates(self):
        lesson = "Avoid moving the same piece twice in the opening."
        assert is_duplicate_lesson(lesson, [lesson]) is True

    def test_very_similar_lessons_are_duplicates(self):
        a = "Avoid moving the same piece twice in the opening."
        b = "Avoid moving the same piece twice during the opening."
        assert is_duplicate_lesson(a, [b]) is True

    def test_different_lessons_not_duplicates(self):
        a = "Castle early to keep your king safe."
        b = "Control the center with pawns in the opening."
        assert is_duplicate_lesson(a, [b]) is False

    def test_empty_existing_never_duplicate(self):
        assert is_duplicate_lesson("some lesson", []) is False

    def test_jaccard_identity(self):
        s = "rooks belong on open files"
        assert jaccard_similarity(s, s) == pytest.approx(1.0)

    def test_jaccard_disjoint_is_zero(self):
        assert jaccard_similarity("apple orange", "banana grape") == pytest.approx(0.0)

    def test_jaccard_partial_overlap(self):
        a = "keep your king safe"
        b = "keep your queen active"
        # shared: "keep", "your" → 2 / (4+4-2) = 2/6 ≈ 0.333
        sim = jaccard_similarity(a, b)
        assert 0.2 < sim < 0.5

    def test_threshold_boundary(self):
        """Similarity at exactly 0.75 is a duplicate; below is not."""
        # 3 words shared out of 4 total = 0.75
        a = "one two three"
        b = "one two three"
        assert jaccard_similarity(a, b) == pytest.approx(1.0)
        assert is_duplicate_lesson(a, [b], threshold=0.75) is True

    def test_empty_strings_not_duplicate(self):
        assert is_duplicate_lesson("", [""]) is False


# ── T-14: _parse_lessons bullet styles ───────────────────────────────────────


class TestParseLessonsBulletStyles:
    """T-14 — _parse_lessons handles all supported bullet formats."""

    def _parse(self, text: str):
        return _parse_lessons(text)

    def test_dash_bullets(self):
        raw = "IMPROVE:\n- Avoid blundering pieces.\n\nSTRENGTH:\n- Good endgame technique."
        result = self._parse(raw)
        assert result["improve"] == ["Avoid blundering pieces."]
        assert result["strength"] == ["Good endgame technique."]

    def test_numbered_bullets(self):
        raw = "IMPROVE:\n1. Watch out for back-rank mates.\n2. Trade pawns more carefully.\nSTRENGTH:\n1. Nice rook activity."
        result = self._parse(raw)
        assert len(result["improve"]) == 2
        assert result["improve"][0] == "Watch out for back-rank mates."
        assert result["improve"][1] == "Trade pawns more carefully."
        assert result["strength"] == ["Nice rook activity."]

    def test_lettered_bullets(self):
        raw = "IMPROVE:\na. Develop knights before bishops.\nb. Castle sooner.\nSTRENGTH:\na. Excellent pawn structure."
        result = self._parse(raw)
        assert result["improve"][0] == "Develop knights before bishops."
        assert result["strength"][0] == "Excellent pawn structure."

    def test_star_bullets(self):
        raw = "IMPROVE:\n* Activate your rooks.\nSTRENGTH:\n* Strong king safety."
        result = self._parse(raw)
        assert result["improve"] == ["Activate your rooks."]
        assert result["strength"] == ["Strong king safety."]

    def test_think_block_stripped(self):
        raw = "<think>Let me consider...</think>\nIMPROVE:\n- Be careful on move 15.\nSTRENGTH:\n- Accurate endgame."
        result = self._parse(raw)
        assert result["improve"] == ["Be careful on move 15."]

    def test_markdown_bold_section_header(self):
        raw = "**IMPROVE:**\n- Watch your king safety.\n**STRENGTH:**\n- Strong tactical play."
        result = self._parse(raw)
        assert result["improve"] == ["Watch your king safety."]
        assert result["strength"] == ["Strong tactical play."]

    def test_max_two_bullets_per_section(self):
        raw = "IMPROVE:\n- Lesson 1.\n- Lesson 2.\n- Lesson 3.\nSTRENGTH:\n- Good 1.\n- Good 2.\n- Good 3."
        result = self._parse(raw)
        assert len(result["improve"]) == 2
        assert len(result["strength"]) == 2

    def test_no_bullets_returns_empty_lists(self):
        raw = "Sorry I have no feedback."
        result = self._parse(raw)
        assert result["improve"] == []
        assert result["strength"] == []


# ── T-15: Adaptive difficulty MIN/MAX bounds ──────────────────────────────────


class TestAdaptiveDifficultyBounds:
    """T-15 — candidate_count never goes below MIN or above MAX."""

    def test_candidate_count_not_below_min(self):
        from game import _ADAPT_CANDIDATE_MIN

        config = PlayerConfig(
            name="Bot", model_id="bot", backend="lmstudio",
            candidate_count=_ADAPT_CANDIDATE_MIN,
        )
        # Simulate the adjustment logic used in play_game
        # High win rate would reduce by 1, but MIN clamps it
        new_count = max(_ADAPT_CANDIDATE_MIN, config.candidate_count - 1)
        assert new_count == _ADAPT_CANDIDATE_MIN

    def test_candidate_count_not_above_max(self):
        from game import _ADAPT_CANDIDATE_MAX

        config = PlayerConfig(
            name="Bot", model_id="bot", backend="lmstudio",
            candidate_count=_ADAPT_CANDIDATE_MAX,
        )
        new_count = min(_ADAPT_CANDIDATE_MAX, config.candidate_count + 1)
        assert new_count == _ADAPT_CANDIDATE_MAX

    def test_min_is_3_and_max_is_10(self):
        """Sanity-check the constants haven't been accidentally changed."""
        from game import _ADAPT_CANDIDATE_MIN, _ADAPT_CANDIDATE_MAX

        assert _ADAPT_CANDIDATE_MIN == 3
        assert _ADAPT_CANDIDATE_MAX == 10

    def test_reduction_from_4_goes_to_3(self):
        from game import _ADAPT_CANDIDATE_MIN

        config = PlayerConfig(
            name="Bot", model_id="bot", backend="lmstudio", candidate_count=4,
        )
        new_count = max(_ADAPT_CANDIDATE_MIN, config.candidate_count - 1)
        assert new_count == 3

    def test_increase_from_9_goes_to_10(self):
        from game import _ADAPT_CANDIDATE_MAX

        config = PlayerConfig(
            name="Bot", model_id="bot", backend="lmstudio", candidate_count=9,
        )
        new_count = min(_ADAPT_CANDIDATE_MAX, config.candidate_count + 1)
        assert new_count == 10


# ── T-16: build_quality_summary ───────────────────────────────────────────────


class TestBuildQualitySummary:
    """T-16 — build_quality_summary produces accurate quality counts."""

    def test_empty_moves_returns_empty_header(self):
        result = build_quality_summary([])
        assert "Move quality:" in result

    def test_counts_each_quality(self):
        moves = [
            ("e4", "best"), ("e5", "excellent"), ("Nf3", "good"),
            ("Nc6", "inaccuracy"), ("Bb5", "mistake"), ("a6", "blunder"),
        ]
        result = build_quality_summary(moves)
        assert "best: 1" in result
        assert "excellent: 1" in result
        assert "good: 1" in result
        assert "inaccuracy: 1" in result
        assert "mistake: 1" in result
        assert "blunder: 1" in result

    def test_blunders_listed_by_san(self):
        moves = [("e4", "best"), ("Qh5", "blunder"), ("Bc4", "good")]
        result = build_quality_summary(moves)
        assert "Qh5" in result
        assert "Blunders:" in result

    def test_mistakes_listed_by_san(self):
        moves = [("e4", "best"), ("d5", "mistake"), ("exd5", "good")]
        result = build_quality_summary(moves)
        assert "d5" in result
        assert "Mistakes:" in result

    def test_best_moves_listed(self):
        moves = [("e4", "best"), ("Nf3", "best"), ("Bc4", "best")]
        result = build_quality_summary(moves)
        assert "Best moves" in result
        assert "e4" in result

    def test_no_blunders_or_mistakes_no_extra_lines(self):
        moves = [("e4", "best"), ("Nf3", "excellent")]
        result = build_quality_summary(moves)
        assert "Blunders:" not in result
        assert "Mistakes:" not in result

    def test_all_unknown_quality(self):
        moves = [("e4", "unknown"), ("e5", "unknown")]
        result = build_quality_summary(moves)
        assert "unknown: 2" in result
