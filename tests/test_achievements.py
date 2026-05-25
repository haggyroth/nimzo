"""
Tests for evaluate_achievements.
"""
from analysis import evaluate_achievements


def _ach(
    *,
    color="white",
    result="1-0",
    total_moves=30,
    move_qualities=None,
    score_history_white=None,
    player_elo=1200,
    opp_elo=1200,
    opening_ply=None,
):
    """Helper: call evaluate_achievements with sensible defaults."""
    return evaluate_achievements(
        color=color,
        result=result,
        total_moves=total_moves,
        move_qualities=move_qualities or [],
        score_history_white=score_history_white or [],
        player_elo_before=player_elo,
        opp_elo_before=opp_elo,
        opening_ply=opening_ply,
    )


class TestFlawless:
    def test_earned_with_no_blunders_or_mistakes(self):
        qualities = [("e4", "best"), ("Nf3", "good"), ("Bc4", "excellent")]
        assert "flawless" in _ach(move_qualities=qualities)

    def test_not_earned_with_blunder(self):
        qualities = [("e4", "best"), ("Qh5??", "blunder")]
        assert "flawless" not in _ach(move_qualities=qualities)

    def test_not_earned_with_mistake(self):
        qualities = [("e4", "best"), ("d4?", "mistake")]
        assert "flawless" not in _ach(move_qualities=qualities)

    def test_not_earned_with_empty_qualities(self):
        # No moves → no flawless (nothing to be flawless about)
        assert "flawless" not in _ach(move_qualities=[])


class TestTactician:
    def test_earned_with_five_best_in_a_row(self):
        qualities = [("m1", "best")] * 5
        assert "tactician" in _ach(move_qualities=qualities)

    def test_earned_with_more_than_five(self):
        qualities = [("m1", "best")] * 8
        assert "tactician" in _ach(move_qualities=qualities)

    def test_not_earned_with_four_in_a_row(self):
        qualities = [("m1", "best")] * 4
        assert "tactician" not in _ach(move_qualities=qualities)

    def test_not_earned_with_streak_broken(self):
        qualities = [("m1", "best")] * 3 + [("m4", "good")] + [("m5", "best")] * 3
        assert "tactician" not in _ach(move_qualities=qualities)

    def test_earned_with_streak_at_end(self):
        qualities = [("m1", "good")] * 2 + [("m3", "best")] * 5
        assert "tactician" in _ach(move_qualities=qualities)


class TestCrusherGrinder:
    def test_crusher_earned_on_quick_white_win(self):
        assert "crusher" in _ach(color="white", result="1-0", total_moves=20)

    def test_crusher_earned_on_quick_black_win(self):
        assert "crusher" in _ach(color="black", result="0-1", total_moves=18)

    def test_crusher_not_earned_on_loss(self):
        assert "crusher" not in _ach(color="white", result="0-1", total_moves=20)

    def test_crusher_boundary_25_moves(self):
        assert "crusher" in _ach(color="white", result="1-0", total_moves=25)
        assert "crusher" not in _ach(color="white", result="1-0", total_moves=26)

    def test_grinder_earned_on_long_win(self):
        assert "grinder" in _ach(color="white", result="1-0", total_moves=70)

    def test_grinder_boundary(self):
        assert "grinder" not in _ach(color="white", result="1-0", total_moves=69)
        assert "grinder" in _ach(color="white", result="1-0", total_moves=71)

    def test_grinder_not_earned_on_loss(self):
        assert "grinder" not in _ach(color="white", result="0-1", total_moves=80)


class TestComeback:
    def test_earned_when_deficit_then_win(self):
        # White was -400cp at some point but won
        scores = [-400.0, -200.0, 100.0, 300.0]
        assert "comeback" in _ach(
            color="white", result="1-0", score_history_white=scores
        )

    def test_earned_for_black_comeback(self):
        # From Black's POV: White was +400 (Black was -400), but Black won
        scores = [400.0, 200.0, -100.0, -300.0]
        assert "comeback" in _ach(
            color="black", result="0-1", score_history_white=scores
        )

    def test_not_earned_when_never_down_300(self):
        scores = [-200.0, 0.0, 200.0]
        assert "comeback" not in _ach(
            color="white", result="1-0", score_history_white=scores
        )

    def test_not_earned_on_loss(self):
        scores = [-400.0, -500.0, -600.0]
        assert "comeback" not in _ach(
            color="white", result="0-1", score_history_white=scores
        )

    def test_handles_none_scores(self):
        scores = [None, -400.0, None, 200.0]
        assert "comeback" in _ach(
            color="white", result="1-0", score_history_white=scores
        )


class TestUpsetAchievements:
    def test_giant_killer_on_win_vs_stronger(self):
        assert "giant_killer" in _ach(
            color="white", result="1-0", player_elo=1100, opp_elo=1300
        )

    def test_iron_wall_on_draw_vs_stronger(self):
        assert "iron_wall" in _ach(
            color="white", result="1/2-1/2", player_elo=1100, opp_elo=1300
        )

    def test_no_upset_vs_equal(self):
        result = _ach(color="white", result="1-0", player_elo=1200, opp_elo=1200)
        assert "giant_killer" not in result
        assert "iron_wall" not in result

    def test_no_upset_vs_weaker(self):
        result = _ach(color="white", result="1-0", player_elo=1400, opp_elo=1100)
        assert "giant_killer" not in result

    def test_boundary_exactly_100_diff(self):
        assert "giant_killer" in _ach(
            color="white", result="1-0", player_elo=1200, opp_elo=1300
        )

    def test_boundary_99_diff_no_upset(self):
        assert "giant_killer" not in _ach(
            color="white", result="1-0", player_elo=1200, opp_elo=1299
        )


class TestTheorist:
    def test_earned_at_12_ply(self):
        assert "theorist" in _ach(opening_ply=12)

    def test_earned_above_12_ply(self):
        assert "theorist" in _ach(opening_ply=20)

    def test_not_earned_at_11_ply(self):
        assert "theorist" not in _ach(opening_ply=11)

    def test_not_earned_with_no_opening(self):
        assert "theorist" not in _ach(opening_ply=None)


class TestMultipleAchievements:
    def test_can_earn_multiple(self):
        # Quick win + flawless + tactician
        qualities = [("m1", "best")] * 6
        result = _ach(
            color="white",
            result="1-0",
            total_moves=20,
            move_qualities=qualities,
        )
        assert "crusher" in result
        assert "flawless" in result
        assert "tactician" in result
