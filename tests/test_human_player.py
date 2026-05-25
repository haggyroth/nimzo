"""
Tests for HumanPlayer — blocking choose_move + submit_move flow.
"""

import threading
import time
import chess
import pytest

from models.base import PlayerConfig
from models.human_player import HumanPlayer


@pytest.fixture
def hp():
    cfg = PlayerConfig(name="Alice", model_id="alice", backend="human")
    return HumanPlayer(cfg)


@pytest.fixture
def board():
    return chess.Board()


def _candidates(board, n=5):
    moves = list(board.legal_moves)[:n]
    return [(m, 30) for m in moves]


# ── submit_move validation ────────────────────────────────────────────────


def test_submit_without_board_returns_false(hp):
    assert hp.submit_move("e2e4") is False


def test_submit_illegal_move_returns_false(hp, board):
    hp._current_board = board.copy()
    hp._current_candidates = _candidates(board)
    hp._move_ready.clear()
    assert hp.submit_move("e1e8") is False   # king can't leap across board


def test_submit_malformed_uci_returns_false(hp, board):
    hp._current_board = board.copy()
    hp._move_ready.clear()
    assert hp.submit_move("notauci!") is False


def test_submit_legal_move_returns_true(hp, board):
    hp._current_board = board.copy()
    hp._current_candidates = _candidates(board)
    hp._move_ready.clear()
    assert hp.submit_move("e2e4") is True


def test_submit_sets_pending_uci(hp, board):
    hp._current_board = board.copy()
    hp._current_candidates = _candidates(board)
    hp._move_ready.clear()
    hp.submit_move("e2e4")
    assert hp._pending_uci == "e2e4"


def test_get_legal_uci_moves_empty_without_board(hp):
    assert hp.get_legal_uci_moves() == []


def test_get_legal_uci_moves_returns_all_legal(hp, board):
    hp._current_board = board.copy()
    legal = hp.get_legal_uci_moves()
    expected = {m.uci() for m in board.legal_moves}
    assert set(legal) == expected


def test_get_candidate_uci_moves(hp, board):
    cands = _candidates(board, 3)
    hp._current_candidates = cands
    result = hp.get_candidate_uci_moves()
    assert len(result) == 3
    assert all(isinstance(u, str) for u in result)


# ── Full choose_move → submit_move flow ───────────────────────────────────


def test_choose_move_returns_human_decision(board):
    cfg = PlayerConfig(name="Alice", model_id="alice", backend="human")
    hp = HumanPlayer(cfg)
    cands = _candidates(board)
    target_uci = cands[0][0].uci()

    def _submit_after_delay():
        time.sleep(0.05)
        hp.submit_move(target_uci)

    t = threading.Thread(target=_submit_after_delay, daemon=True)
    t.start()

    decision = hp.choose_move(board, cands, "")
    t.join()

    assert decision.move_uci == target_uci
    assert decision.reasoning == "(human move)"
    assert decision.candidate_rank == 1   # first candidate


def test_choose_move_candidate_rank_for_non_top(board):
    cfg = PlayerConfig(name="Alice", model_id="alice", backend="human")
    hp = HumanPlayer(cfg)
    cands = _candidates(board, 5)
    # Submit the 3rd candidate
    third_uci = cands[2][0].uci()

    def _submit():
        time.sleep(0.05)
        hp.submit_move(third_uci)

    t = threading.Thread(target=_submit, daemon=True)
    t.start()
    decision = hp.choose_move(board, cands, "")
    t.join()
    assert decision.candidate_rank == 3
