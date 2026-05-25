"""
Tests for analysis functions that previously had zero coverage:
  - bad_move_rate
  - derive_personality_traits
  - compress_lessons
"""
import pytest
from analysis import bad_move_rate, derive_personality_traits, compress_lessons, TutorConfig


# ── bad_move_rate ────────────────────────────────────────────────────────────

class TestBadMoveRate:
    def test_empty_returns_none(self):
        assert bad_move_rate([]) is None

    def test_all_best_returns_zero(self):
        moves = [("e4", "best"), ("Nf3", "best"), ("Bc4", "best")]
        assert bad_move_rate(moves) == 0.0

    def test_all_blunders(self):
        moves = [("Qh5", "blunder"), ("Bxf7", "blunder")]
        assert bad_move_rate(moves) == 1.0

    def test_mixed_counts_only_blunder_and_mistake(self):
        moves = [
            ("e4", "best"),
            ("Nf3", "good"),
            ("Bc4", "excellent"),
            ("Ng5", "mistake"),
            ("Qxf7", "blunder"),
        ]
        # 2 bad out of 5 = 0.4
        assert bad_move_rate(moves) == pytest.approx(0.4, abs=0.0001)

    def test_inaccuracy_not_counted(self):
        moves = [("e4", "inaccuracy"), ("Nf3", "inaccuracy"), ("Bc4", "best")]
        assert bad_move_rate(moves) == 0.0

    def test_single_mistake(self):
        moves = [("e4", "mistake")]
        assert bad_move_rate(moves) == 1.0

    def test_result_is_rounded(self):
        # 1 bad of 3 = 0.3333... should be rounded to 4 decimal places
        moves = [("e4", "blunder"), ("Nf3", "best"), ("Bc4", "best")]
        result = bad_move_rate(moves)
        assert result == round(1 / 3, 4)


# ── derive_personality_traits ────────────────────────────────────────────────

def _profile(
    total_moves=100,
    picked_top=50,
    avg_rank=2.0,
    captures=15,
    checks=5,
    castles_k=8,
    castles_q=2,
    total_games=10,
    games_castled=8,
    avg_castle_move=8.0,
    white_wins=3, white_draws=1, white_losses=1,
    black_wins=3, black_draws=1, black_losses=1,
    q_blunder=2, q_mistake=3, q_best=40,
    **kwargs,
):
    """Build a minimal profile dict matching the shape db.get_model_profile returns."""
    return {
        "moves": {
            "total_moves": total_moves,
            "picked_top": picked_top,
            "avg_rank": avg_rank,
            "captures": captures,
            "checks": checks,
            "q_blunder": q_blunder,
            "q_mistake": q_mistake,
            "q_best": q_best,
        },
        "castling": {
            "games_castled": games_castled,
            "kingside": castles_k,
            "queenside": castles_q,
            "avg_castle_move": avg_castle_move,
        },
        "color": {
            "white_wins": white_wins, "white_draws": white_draws, "white_losses": white_losses,
            "black_wins": black_wins, "black_draws": black_draws, "black_losses": black_losses,
        },
        "games": {"total_games": total_games},
    }


class TestDerivePersonalityTraits:
    def test_empty_profile_returns_empty(self):
        assert derive_personality_traits({}) == []

    def test_none_profile_returns_empty(self):
        assert derive_personality_traits(None) == []

    def test_too_few_moves_returns_new_face(self):
        p = _profile(total_moves=5)
        traits = derive_personality_traits(p)
        assert len(traits) == 1
        assert traits[0]["label"] == "New face"

    def test_stockfish_loyalist_threshold(self):
        # ≥80% of moves pick top candidate
        p = _profile(total_moves=100, picked_top=82)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Stockfish loyalist" in labels

    def test_free_spirit_threshold(self):
        # ≤45% pick top candidate
        p = _profile(total_moves=100, picked_top=44)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Free spirit" in labels

    def test_neither_loyalist_nor_free_spirit(self):
        # 60% — neither threshold triggered
        p = _profile(total_moves=100, picked_top=60)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Stockfish loyalist" not in labels
        assert "Free spirit" not in labels

    def test_trade_happy_threshold(self):
        # ≥22% capture rate
        p = _profile(total_moves=100, captures=23)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Trade-happy" in labels

    def test_positional_threshold(self):
        # ≤10% captures AND ≥50 moves
        p = _profile(total_moves=60, captures=6)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Positional" in labels

    def test_attacker_threshold(self):
        # ≥12% check rate
        p = _profile(total_moves=100, checks=13)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Attacker" in labels

    def test_king_in_open_threshold(self):
        # castled in < 40% of games
        p = _profile(total_moves=100, total_games=10, games_castled=3)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "King in the open" in labels

    def test_queenside_castler(self):
        p = _profile(total_moves=100, total_games=10, games_castled=5,
                     castles_k=1, castles_q=4)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Queenside" in labels

    def test_streaky_blunder_threshold(self):
        # ≥5% blunder rate
        p = _profile(total_moves=100, q_blunder=6)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Streaky" in labels

    def test_blunder_free_threshold(self):
        # 0 blunders over ≥50 moves
        p = _profile(total_moves=60, q_blunder=0)
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Blunder-free" in labels

    def test_white_favoured_bias(self):
        # White win rate - Black win rate ≥ 0.2, min 3 games each side
        p = _profile(
            total_moves=100,
            white_wins=4, white_draws=0, white_losses=1,   # 80%
            black_wins=1, black_draws=0, black_losses=4,   # 20%
        )
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "White-favoured" in labels

    def test_black_favoured_bias(self):
        p = _profile(
            total_moves=100,
            white_wins=1, white_draws=0, white_losses=4,   # 20%
            black_wins=4, black_draws=0, black_losses=1,   # 80%
        )
        labels = [t["label"] for t in derive_personality_traits(p)]
        assert "Black-favoured" in labels

    def test_capped_at_five_traits(self):
        # Force many traits simultaneously
        p = _profile(
            total_moves=100,
            picked_top=82,      # loyalist
            captures=25,        # trade-happy
            checks=15,          # attacker
            q_blunder=6,        # streaky
            total_games=10, games_castled=3,  # king in open
        )
        traits = derive_personality_traits(p)
        assert len(traits) <= 5

    def test_detail_contains_percentage(self):
        p = _profile(total_moves=100, picked_top=85)
        traits = derive_personality_traits(p)
        loyalist = next((t for t in traits if t["label"] == "Stockfish loyalist"), None)
        assert loyalist is not None
        assert "%" in loyalist["detail"]


# ── compress_lessons ─────────────────────────────────────────────────────────

class TestCompressLessons:
    def test_no_tutor_returns_none(self):
        lessons = [{"lesson": "Watch for forks", "lesson_type": "improve"}]
        assert compress_lessons(lessons, "ModelA", game_count=5, tutor=None) is None

    def test_blank_model_id_returns_none(self):
        tutor = TutorConfig(model_id="")
        lessons = [{"lesson": "Watch for forks", "lesson_type": "improve"}]
        assert compress_lessons(lessons, "ModelA", game_count=5, tutor=tutor) is None

    def test_empty_lesson_list_returns_none(self):
        tutor = TutorConfig(model_id="test-model")
        assert compress_lessons([], "ModelA", game_count=5, tutor=tutor) is None

    def test_only_unknown_type_lessons_returns_none(self):
        """Lessons with unknown type produce no improve/strength lists → skip."""
        tutor = TutorConfig(model_id="test-model")
        lessons = [{"lesson": "Something", "lesson_type": "other"}]
        assert compress_lessons(lessons, "ModelA", game_count=5, tutor=tutor) is None

    def test_calls_backend_and_returns_profile(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mock_call = mocker.patch(
            "analysis._call_lmstudio",
            return_value="WEAKNESSES:\n- Drops pieces\nSTRENGTHS:\n- Good endgames\n",
        )
        lessons = [
            {"lesson": "Watch for forks", "lesson_type": "improve"},
            {"lesson": "Good pawn structure", "lesson_type": "strength"},
        ]
        result = compress_lessons(lessons, "ModelA", game_count=10, tutor=tutor)
        mock_call.assert_called_once()
        assert result is not None
        assert "WEAKNESSES" in result

    def test_empty_llm_response_returns_none(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mocker.patch("analysis._call_lmstudio", return_value="   ")
        lessons = [{"lesson": "Watch for forks", "lesson_type": "improve"}]
        result = compress_lessons(lessons, "ModelA", game_count=10, tutor=tutor)
        assert result is None

    def test_api_error_returns_none(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mocker.patch("analysis._call_lmstudio", side_effect=ConnectionError("refused"))
        lessons = [{"lesson": "Watch for forks", "lesson_type": "improve"}]
        result = compress_lessons(lessons, "ModelA", game_count=10, tutor=tutor)
        assert result is None

    def test_prompt_includes_player_name_and_lessons(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mock_call = mocker.patch("analysis._call_lmstudio", return_value="WEAKNESSES:\n- Test\n")
        lessons = [
            {"lesson": "Avoid hanging pieces", "lesson_type": "improve"},
            {"lesson": "Strong endgames", "lesson_type": "strength"},
        ]
        compress_lessons(lessons, "Gandalf", game_count=7, tutor=tutor)
        prompt = mock_call.call_args[0][1]
        assert "Gandalf" in prompt
        assert "7" in prompt
        assert "Avoid hanging pieces" in prompt
        assert "Strong endgames" in prompt

    def test_improve_and_strength_lessons_formatted_separately(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mock_call = mocker.patch("analysis._call_lmstudio", return_value="WEAKNESSES:\n- x\n")
        lessons = [
            {"lesson": "Lesson A", "lesson_type": "improve"},
            {"lesson": "Lesson B", "lesson_type": "improve"},
            {"lesson": "Strength C", "lesson_type": "strength"},
        ]
        compress_lessons(lessons, "P", game_count=5, tutor=tutor)
        prompt = mock_call.call_args[0][1]
        # Both sections should be present
        assert "Lesson A" in prompt
        assert "Strength C" in prompt
