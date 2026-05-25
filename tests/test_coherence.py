"""
Tests for score_reasoning_coherence() and get_coherence_stats().

All LLM/API calls are mocked — no real network or model needed.
"""
from __future__ import annotations

import chess
import pytest

from analysis import JudgeConfig, score_reasoning_coherence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_judge(model_id: str = "test-judge") -> JudgeConfig:
    return JudgeConfig(
        backend="lmstudio",
        model_id=model_id,
        base_url="http://localhost:1234/v1",
    )


def _candidates(board: chess.Board, n: int = 3):
    """Return first n legal moves as (move, score_cp) tuples."""
    moves = list(board.legal_moves)[:n]
    return [(m, (i + 1) * 50) for i, m in enumerate(moves)]


STARTING_FEN = chess.STARTING_FEN
STARTING_BOARD = chess.Board()
E4_SAN = "e4"
VALID_REASONING = "I play e4 to control the center and open lines for my bishop."


# ---------------------------------------------------------------------------
# Skip conditions — no API calls should be made
# ---------------------------------------------------------------------------

class TestSkipConditions:
    def test_empty_reasoning_returns_none(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like")
        result = score_reasoning_coherence(
            reasoning="",
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result is None
        mock_call.assert_not_called()

    def test_paren_reasoning_skipped(self, mocker):
        """Reasoning starting with '(' signals human/fallback move — skip."""
        mock_call = mocker.patch("analysis._call_tutor_like")
        result = score_reasoning_coherence(
            reasoning="(human move)",
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result is None
        mock_call.assert_not_called()

    def test_timeout_reasoning_skipped(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like")
        result = score_reasoning_coherence(
            reasoning="(timed out after 60s — fell back to top Stockfish candidate)",
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result is None
        mock_call.assert_not_called()

    def test_no_judge_returns_none(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=None,
        )
        assert result is None
        mock_call.assert_not_called()

    def test_blank_model_id_returns_none(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like")
        judge = JudgeConfig(model_id="")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=judge,
        )
        assert result is None
        mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# Successful scoring
# ---------------------------------------------------------------------------

class TestSuccessfulScoring:
    def test_returns_float_from_judge(self, mocker):
        mocker.patch("analysis._call_tutor_like", return_value="8")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result == 8.0

    def test_score_10_accepted(self, mocker):
        mocker.patch("analysis._call_tutor_like", return_value="10")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result == 10.0

    def test_score_0_accepted(self, mocker):
        mocker.patch("analysis._call_tutor_like", return_value="0")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result == 0.0

    def test_extracts_integer_from_prose(self, mocker):
        """Judge returned prose; we should still extract the first integer."""
        mocker.patch("analysis._call_tutor_like", return_value="Score: 7\nBecause...")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result == 7.0

    def test_strips_think_block_before_parsing(self, mocker):
        raw = "<think>Hmm, let me think...</think>\n9"
        mocker.patch("analysis._call_tutor_like", return_value=raw)
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result == 9.0

    def test_non_integer_response_returns_none(self, mocker):
        mocker.patch("analysis._call_tutor_like", return_value="great move!")
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result is None

    def test_api_error_returns_none(self, mocker):
        mocker.patch("analysis._call_tutor_like", side_effect=ConnectionError("refused"))
        result = score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert result is None

    def test_judge_called_once(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like", return_value="6")
        score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        assert mock_call.call_count == 1

    def test_fen_and_reasoning_in_prompt(self, mocker):
        mock_call = mocker.patch("analysis._call_tutor_like", return_value="5")
        score_reasoning_coherence(
            reasoning=VALID_REASONING,
            move_san=E4_SAN,
            board_fen=STARTING_FEN,
            candidates=_candidates(STARTING_BOARD),
            judge=_dummy_judge(),
        )
        _, kwargs = mock_call.call_args
        prompt = mock_call.call_args[0][1]  # positional: (cfg, prompt, system, max_tokens)
        assert STARTING_FEN in prompt
        assert VALID_REASONING in prompt
        assert E4_SAN in prompt


# ---------------------------------------------------------------------------
# DB: get_coherence_stats
# ---------------------------------------------------------------------------

class TestGetCoherenceStats:
    def test_empty_model_returns_none_avg(self, tmp_db):
        tmp_db.upsert_player(model_id="model-x", name="ModelX", backend="lmstudio")
        stats = tmp_db.get_coherence_stats("model-x")
        assert stats["avg_coherence"] is None
        assert stats["scored_moves"] == 0
        assert stats["total_moves"] == 0
        assert stats["timeout_count"] == 0

    def test_unknown_model_returns_zeros(self, tmp_db):
        stats = tmp_db.get_coherence_stats("nonexistent-model")
        assert stats["avg_coherence"] is None
        assert stats["total_moves"] == 0

    def _setup_game_with_moves(self, db, model_id, coherence_scores, timed_outs=None):
        """Helper: create a player, game, and moves with coherence scores."""
        if timed_outs is None:
            timed_outs = [False] * len(coherence_scores)
        db.upsert_player(model_id=model_id, name="Player", backend="lmstudio")
        db.upsert_player(model_id="opponent-model", name="Opponent", backend="lmstudio")
        game_id = db.record_game(
            white_model_id=model_id,
            black_model_id="opponent-model",
            result="1-0",
            termination="checkmate",
            total_moves=len(coherence_scores),
            pgn="1. e4 *",
            white_elo_before=1200,
            black_elo_before=1200,
            white_elo_after=1216,
            black_elo_after=1184,
        )
        for i, (score, timed_out) in enumerate(zip(coherence_scores, timed_outs)):
            db.record_move(
                game_id=game_id,
                move_number=i + 1,
                player_model_id=model_id,
                move_uci="e2e4",
                move_san="e4",
                candidate_rank=1,
                quality="best",
                score_cp=0.0,
                reasoning="Good center control." if score is not None else "(human move)",
                fen_after=chess.STARTING_FEN,
                coherence_score=score,
                timed_out=timed_out,
            )
        return game_id

    def test_avg_coherence_computed(self, tmp_db):
        self._setup_game_with_moves(tmp_db, "model-avg", [6.0, 8.0, 10.0])
        stats = tmp_db.get_coherence_stats("model-avg")
        assert stats["avg_coherence"] == pytest.approx(8.0, abs=0.01)
        assert stats["scored_moves"] == 3

    def test_null_scores_excluded_from_avg(self, tmp_db):
        # None scores should not count toward avg_coherence or scored_moves
        self._setup_game_with_moves(tmp_db, "model-null", [5.0, None, None])
        stats = tmp_db.get_coherence_stats("model-null")
        assert stats["scored_moves"] == 1
        assert stats["avg_coherence"] == pytest.approx(5.0, abs=0.01)

    def test_timeout_count(self, tmp_db):
        self._setup_game_with_moves(
            tmp_db, "model-timeout",
            coherence_scores=[None, None, None],
            timed_outs=[True, False, True],
        )
        stats = tmp_db.get_coherence_stats("model-timeout")
        assert stats["timeout_count"] == 2

    def test_total_moves_includes_unscored(self, tmp_db):
        self._setup_game_with_moves(tmp_db, "model-total", [7.0, None, 3.0])
        stats = tmp_db.get_coherence_stats("model-total")
        assert stats["total_moves"] == 3
        assert stats["scored_moves"] == 2
