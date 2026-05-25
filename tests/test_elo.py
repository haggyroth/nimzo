"""
Tests for ELO calculation and dynamic K-factor.
"""
import pytest
from analysis import dynamic_k_factor, expected_score, new_elo, calculate_elos


class TestDynamicKFactor:
    def test_new_player_gets_k32(self):
        assert dynamic_k_factor(0) == 32.0
        assert dynamic_k_factor(1) == 32.0
        assert dynamic_k_factor(19) == 32.0

    def test_experienced_player_gets_k24(self):
        assert dynamic_k_factor(20) == 24.0
        assert dynamic_k_factor(39) == 24.0

    def test_veteran_player_gets_k16(self):
        assert dynamic_k_factor(40) == 16.0
        assert dynamic_k_factor(100) == 16.0


class TestExpectedScore:
    def test_equal_players_expect_half(self):
        assert expected_score(1200, 1200) == pytest.approx(0.5)

    def test_higher_rated_player_favoured(self):
        assert expected_score(1600, 1200) > 0.5

    def test_lower_rated_player_underdog(self):
        assert expected_score(1200, 1600) < 0.5

    def test_symmetry(self):
        e1 = expected_score(1400, 1200)
        e2 = expected_score(1200, 1400)
        assert e1 + e2 == pytest.approx(1.0)

    def test_400_point_gap(self):
        # Classic: 400 cp diff → ~91% expected
        assert expected_score(1600, 1200) == pytest.approx(10/11, rel=1e-3)


class TestNewElo:
    def test_win_increases_elo(self):
        result = new_elo(1200, 1200, 1.0)
        assert result > 1200

    def test_loss_decreases_elo(self):
        result = new_elo(1200, 1200, 0.0)
        assert result < 1200

    def test_draw_between_equals_unchanged(self):
        result = new_elo(1200, 1200, 0.5)
        assert result == pytest.approx(1200.0)

    def test_upset_win_gives_bigger_gain(self):
        # Beating a much stronger opponent gives more ELO than beating an equal
        gain_vs_stronger = new_elo(1200, 1600, 1.0) - 1200
        gain_vs_equal    = new_elo(1200, 1200, 1.0) - 1200
        assert gain_vs_stronger > gain_vs_equal

    def test_expected_loss_costs_less(self):
        # Losing to a much stronger opponent costs less ELO
        cost_vs_stronger = 1200 - new_elo(1200, 1600, 0.0)
        cost_vs_equal    = 1200 - new_elo(1200, 1200, 0.0)
        assert cost_vs_stronger < cost_vs_equal

    def test_k_factor_respected(self):
        # Veteran (k=16) gains less than newcomer (k=32) for same win
        newcomer = new_elo(1200, 1200, 1.0, games_played=0)
        veteran  = new_elo(1200, 1200, 1.0, games_played=50)
        assert newcomer > veteran


class TestCalculateElos:
    def test_white_win(self):
        w_new, b_new = calculate_elos(1200, 1200, "1-0")
        assert w_new > 1200
        assert b_new < 1200

    def test_black_win(self):
        w_new, b_new = calculate_elos(1200, 1200, "0-1")
        assert w_new < 1200
        assert b_new > 1200

    def test_draw_between_equals(self):
        w_new, b_new = calculate_elos(1200, 1200, "1/2-1/2")
        assert w_new == pytest.approx(1200.0)
        assert b_new == pytest.approx(1200.0)

    def test_elo_sum_conserved_on_draw(self):
        # Total ELO is conserved in a draw between equal players
        w_new, b_new = calculate_elos(1200, 1200, "1/2-1/2")
        assert w_new + b_new == pytest.approx(2400.0)

    def test_elo_sum_conserved_on_win(self):
        # Total ELO is conserved on a win (zero-sum)
        w_new, b_new = calculate_elos(1300, 1100, "1-0")
        assert w_new + b_new == pytest.approx(2400.0)

    def test_invalid_result_treated_as_draw(self):
        w_new, b_new = calculate_elos(1200, 1200, "*")
        # Should behave like a draw (0.5/0.5)
        assert w_new == pytest.approx(1200.0)
        assert b_new == pytest.approx(1200.0)
