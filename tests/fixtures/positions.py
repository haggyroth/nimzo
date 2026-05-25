"""
Chess position fixtures (FEN strings) and candidate move lists for tests.
"""
import chess

# Starting position
STARTING_FEN = chess.STARTING_FEN

# Open e4/e5 middlegame — White to move
OPEN_MIDDLEGAME_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"

# Endgame — King and pawn vs King
KPK_FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"

# Tactical position — White can play Qxf7#
TACTICAL_FEN = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"


def make_candidates(board: chess.Board, moves: list[str]) -> list[tuple[chess.Move, float]]:
    """Build a candidate list from UCI strings with dummy scores."""
    result = []
    for i, uci in enumerate(moves):
        move = chess.Move.from_uci(uci)
        score = 100.0 - i * 20.0   # decreasing scores: 100, 80, 60, ...
        result.append((move, score))
    return result


def starting_candidates() -> list[tuple[chess.Move, float]]:
    """Five common opening candidates from the starting position."""
    board = chess.Board()
    return make_candidates(board, ["e2e4", "d2d4", "g1f3", "c2c4", "b1c3"])
