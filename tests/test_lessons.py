"""
Tests for _parse_lessons, build_quality_summary, and generate_lessons logic
(the parts that don't require an LLM call).
"""
from analysis import _parse_lessons, build_quality_summary, generate_lessons, TutorConfig


class TestParseLessons:
    def test_basic_improve_and_strength(self):
        raw = """
IMPROVE:
- Move your knights before bishops
- Control the center early

STRENGTH:
- Good endgame technique
"""
        result = _parse_lessons(raw)
        assert "Move your knights before bishops" in result["improve"]
        assert "Control the center early" in result["improve"]
        assert "Good endgame technique" in result["strength"]

    def test_strips_think_blocks(self):
        raw = """<think>Internal reasoning here</think>
IMPROVE:
- Focus on king safety
STRENGTH:
- Strong opening play
"""
        result = _parse_lessons(raw)
        assert any("king safety" in l for l in result["improve"])
        assert not any("Internal reasoning" in l for l in result["improve"])

    def test_markdown_bold_headers(self):
        raw = """**IMPROVE:**
- Avoid hanging pieces
**STRENGTH:**
- Accurate endgame conversion
"""
        result = _parse_lessons(raw)
        assert any("hanging pieces" in l for l in result["improve"])
        assert any("endgame conversion" in l for l in result["strength"])

    def test_numbered_bullets(self):
        raw = """IMPROVE:
1. Develop pieces faster
2. Castle earlier
STRENGTH:
1. Consistent pawn structure
"""
        result = _parse_lessons(raw)
        assert any("Develop pieces faster" in l for l in result["improve"])
        assert any("Castle earlier" in l for l in result["improve"])
        assert any("pawn structure" in l for l in result["strength"])

    def test_caps_insensitive_headers(self):
        raw = """improve:
- Watch out for forks
strength:
- Great tactical vision
"""
        result = _parse_lessons(raw)
        assert result["improve"]
        assert result["strength"]

    def test_capped_at_two_each(self):
        raw = """IMPROVE:
- Lesson 1
- Lesson 2
- Lesson 3
- Lesson 4
STRENGTH:
- Strength 1
- Strength 2
- Strength 3
"""
        result = _parse_lessons(raw)
        assert len(result["improve"]) <= 2
        assert len(result["strength"]) <= 2

    def test_empty_input_returns_empty_lists(self):
        result = _parse_lessons("")
        assert result == {"improve": [], "strength": []}

    def test_no_sections_returns_empty(self):
        raw = "Great game! Keep it up."
        result = _parse_lessons(raw)
        assert result["improve"] == []
        assert result["strength"] == []

    def test_only_improve_section(self):
        raw = """IMPROVE:
- Watch for back rank mates
"""
        result = _parse_lessons(raw)
        assert result["improve"]
        assert result["strength"] == []

    def test_bullet_variants(self):
        raw = """IMPROVE:
* Star bullet lesson
• Dot bullet lesson
STRENGTH:
a) Letter bullet lesson
"""
        result = _parse_lessons(raw)
        assert len(result["improve"]) == 2
        assert result["strength"]

    def test_think_block_in_middle(self):
        """Think block between sections should not disrupt parsing."""
        raw = """IMPROVE:
- Improve your rook activity
<think>thinking...</think>
STRENGTH:
- Nice queen maneuver
"""
        result = _parse_lessons(raw)
        assert result["improve"]
        assert result["strength"]


class TestBuildQualitySummary:
    def test_counts_all_qualities(self):
        qualities = [
            ("e2e4", "best"), ("d7d5", "good"), ("g1f3", "best"),
            ("c7c5", "inaccuracy"), ("f1b5", "blunder"),
        ]
        summary = build_quality_summary(qualities)
        assert "best: 2" in summary
        assert "good: 1" in summary
        assert "inaccuracy: 1" in summary
        assert "blunder: 1" in summary

    def test_blunders_listed_by_move(self):
        qualities = [("Nf3", "best"), ("Qh5?", "blunder"), ("Qxf7#", "best")]
        summary = build_quality_summary(qualities)
        assert "Qh5?" in summary

    def test_mistakes_listed_by_move(self):
        qualities = [("e4", "best"), ("d5?", "mistake")]
        summary = build_quality_summary(qualities)
        assert "d5?" in summary

    def test_best_moves_listed(self):
        qualities = [("e4", "best"), ("Nf3", "best"), ("Bc4", "best")]
        summary = build_quality_summary(qualities)
        assert "Best moves" in summary

    def test_empty_input(self):
        summary = build_quality_summary([])
        assert "Move quality:" in summary

    def test_best_moves_capped_at_six(self):
        qualities = [(f"move{i}", "best") for i in range(10)]
        summary = build_quality_summary(qualities)
        # Should list at most 6 best moves (commas = items - 1)
        best_line = [l for l in summary.splitlines() if "Best moves" in l]
        if best_line:
            items = len(best_line[0].split(":")[1].split(","))
            assert items <= 6


class TestGenerateLessonsSkipLogic:
    """Tests for the skip logic that doesn't require an LLM call."""

    def test_no_tutor_returns_empty(self):
        result = generate_lessons(
            pgn="1. e4 e5 *",
            player_name="ModelA",
            player_color="White",
            result="1/2-1/2",
            termination="draw",
            quality_summary="Move quality: good: 5",
        )
        assert result == {"improve": [], "strength": []}

    def test_clean_draw_skipped_by_default(self):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        result = generate_lessons(
            pgn="1. e4 e5 *",
            player_name="ModelA",
            player_color="White",
            result="1/2-1/2",
            termination="draw",
            quality_summary="Move quality: best: 3, good: 5",
            tutor=tutor,
            is_draw=True,
            skip_if_clean_draw=True,
        )
        assert result == {"improve": [], "strength": []}

    def test_messy_draw_not_skipped(self, mocker):
        """A draw with blunders/mistakes should still go to the LLM."""
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mock_call = mocker.patch("analysis._call_tutor_like", return_value="IMPROVE:\n- Watch for blunders\nSTRENGTH:\n- Good opening\n")
        generate_lessons(
            pgn="1. e4 e5 *",
            player_name="ModelA",
            player_color="White",
            result="1/2-1/2",
            termination="draw",
            quality_summary="Move quality: blunder: 1, good: 5",
            tutor=tutor,
            is_draw=True,
            skip_if_clean_draw=True,
        )
        mock_call.assert_called_once()

    def test_skip_clean_draw_false_passes_through(self, mocker):
        tutor = TutorConfig(model_id="test-model", base_url="http://localhost:1234/v1")
        mock_call = mocker.patch("analysis._call_tutor_like", return_value="IMPROVE:\n- Lesson\nSTRENGTH:\n- Strength\n")
        generate_lessons(
            pgn="1. e4 e5 *",
            player_name="ModelA",
            player_color="White",
            result="1/2-1/2",
            termination="draw",
            quality_summary="Move quality: good: 5",
            tutor=tutor,
            is_draw=True,
            skip_if_clean_draw=False,
        )
        mock_call.assert_called_once()
