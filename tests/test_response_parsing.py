"""
Tests for move response parsing in both player backends.
Uses mock API clients — no real LLM calls.
"""
import chess
import pytest
from unittest.mock import MagicMock, patch

from models.base import PlayerConfig, MoveDecision
from models.lmstudio_player import LMStudioPlayer, _extract_thinking
from models.anthropic_player import AnthropicPlayer
from tests.fixtures.positions import starting_candidates


# ── Shared helpers ────────────────────────────────────────────────────────

def _make_lmstudio_player() -> LMStudioPlayer:
    config = PlayerConfig(
        name="TestModel",
        model_id="test-model",
        backend="lmstudio",
        base_url="http://localhost:1234/v1",
        api_key="test",
    )
    player = LMStudioPlayer.__new__(LMStudioPlayer)
    player.config = config
    player.elo = 1200.0
    return player


def _make_anthropic_player() -> AnthropicPlayer:
    config = PlayerConfig(
        name="TestClaude",
        model_id="claude-3-haiku-20240307",
        backend="anthropic",
        api_key="test",
    )
    player = AnthropicPlayer.__new__(AnthropicPlayer)
    player.config = config
    player.elo = 1200.0
    return player


def _starting_board_and_candidates():
    board = chess.Board()
    candidates = starting_candidates()
    return board, candidates


# ── _extract_thinking ─────────────────────────────────────────────────────

class TestExtractThinking:
    def test_extracts_think_block(self):
        raw = "<think>I should play e4</think>\nCHOICE: 1\nMOVE: e2e4\nREASONING: Controls the center."
        thinking, clean = _extract_thinking(raw)
        assert "I should play e4" in thinking
        assert "<think>" not in clean

    def test_no_think_block(self):
        raw = "CHOICE: 1\nMOVE: e2e4\nREASONING: Controls the center."
        thinking, clean = _extract_thinking(raw)
        assert thinking == ""
        assert clean == raw

    def test_multiline_think_block(self):
        raw = "<think>\nLine 1\nLine 2\n</think>\nCHOICE: 2"
        thinking, clean = _extract_thinking(raw)
        assert "Line 1" in thinking
        assert "Line 2" in thinking
        assert "CHOICE: 2" in clean

    def test_case_insensitive(self):
        raw = "<THINK>Upper case</THINK>\nCHOICE: 1"
        thinking, clean = _extract_thinking(raw)
        assert "Upper case" in thinking

    def test_multiple_blocks_only_first_captured(self):
        raw = "<think>First</think>\n<think>Second</think>\nCHOICE: 1"
        thinking, clean = _extract_thinking(raw)
        assert "First" in thinking
        assert "<think>" not in clean


# ── LMStudioPlayer._parse_response ───────────────────────────────────────

class TestLMStudioParsing:
    def setup_method(self):
        self.player = _make_lmstudio_player()
        self.board, self.candidates = _starting_board_and_candidates()

    def test_parses_choice_number(self):
        raw = "CHOICE: 1\nMOVE: e2e4\nREASONING: Good center control."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "e2e4"
        assert decision.candidate_rank == 1

    def test_parses_explicit_move_field(self):
        raw = "CHOICE: 2\nMOVE: d2d4\nREASONING: The Queen's Gambit approach."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "d2d4"

    def test_parses_reasoning(self):
        raw = "CHOICE: 1\nMOVE: e2e4\nREASONING: Seizes central space."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert "central space" in decision.reasoning

    def test_fallback_to_uci_scan(self):
        # No CHOICE/MOVE headers, but UCI move appears in free text
        raw = "I think e2e4 is the best move here."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "e2e4"

    def test_fallback_to_top_candidate(self):
        # Completely unparseable response → top candidate
        raw = "I have no idea what to play!"
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == self.candidates[0][0].uci()
        assert "parse failed" in decision.reasoning

    def test_ignores_illegal_uci_in_scan(self):
        # h1h9 looks UCI-shaped but is illegal; should fall back to top candidate
        raw = "MOVE: h1h9"
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == self.candidates[0][0].uci()

    def test_think_block_stripped_before_parsing(self):
        raw = "<think>I am thinking about e2e4</think>\nCHOICE: 2\nMOVE: d2d4\nREASONING: Queen pawn."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        # Should parse CHOICE:2 / MOVE:d2d4, not accidentally pick e2e4 from the think block
        assert decision.move_uci == "d2d4"

    def test_thinking_content_attached(self):
        raw = "<think>Deep thought here</think>\nCHOICE: 1\nMOVE: e2e4\nREASONING: Good."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert "Deep thought here" in decision.thinking_content

    def test_no_reasoning_placeholder(self):
        raw = "CHOICE: 1\nMOVE: e2e4"
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.reasoning == "(no reasoning)"

    def test_choice_out_of_range_falls_back(self):
        raw = "CHOICE: 99\nREASONING: Pick 99."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        # 99 is out of range → fall through to UCI scan → fall back to top
        assert decision.move_uci == self.candidates[0][0].uci()

    def test_case_insensitive_headers(self):
        raw = "choice: 1\nmove: e2e4\nreasoning: Lowercase headers work."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "e2e4"


# ── AnthropicPlayer._parse_response ──────────────────────────────────────

class TestAnthropicParsing:
    def setup_method(self):
        self.player = _make_anthropic_player()
        self.board, self.candidates = _starting_board_and_candidates()

    def test_parses_choice(self):
        raw = "CHOICE: 1\nMOVE: e2e4\nREASONING: Controls center."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "e2e4"

    def test_thinking_content_passed_through(self):
        raw = "CHOICE: 1\nMOVE: e2e4\nREASONING: Center."
        decision = self.player._parse_response(raw, self.candidates, self.board, thinking_content="Claude thought here")
        assert "Claude thought here" in decision.thinking_content

    def test_fallback_to_top_candidate(self):
        raw = "Hmm, I'm not sure."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == self.candidates[0][0].uci()

    def test_move_field_takes_priority(self):
        # If MOVE: and CHOICE: disagree, MOVE: wins (it's more specific)
        raw = "CHOICE: 2\nMOVE: e2e4\nREASONING: e4 is best."
        decision = self.player._parse_response(raw, self.candidates, self.board)
        assert decision.move_uci == "e2e4"


# ── choose_move integration with mock client ─────────────────────────────

class TestLMStudioChooseMoveMocked:
    def test_choose_move_calls_api_and_parses(self, mocker):
        player = _make_lmstudio_player()
        board, candidates = _starting_board_and_candidates()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "CHOICE: 1\nMOVE: e2e4\nREASONING: Classic."
        mock_response.usage.total_tokens = 50

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        player.client = mock_client

        decision = player.choose_move(board, candidates, "")
        assert decision.move_uci == "e2e4"
        mock_client.chat.completions.create.assert_called_once()

    def test_no_think_prefix_injected_for_qwen(self, mocker):
        """With no_think_prefix=True in profile, system prompt should start with /no_think."""
        config = PlayerConfig(
            name="Qwen", model_id="qwen3-30b", backend="lmstudio",
            base_url="http://localhost:1234/v1", api_key="test",
            enable_thinking=False,
        )
        player = LMStudioPlayer.__new__(LMStudioPlayer)
        player.config = config
        player.elo = 1200.0

        board, candidates = _starting_board_and_candidates()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "CHOICE: 1\nMOVE: e2e4\nREASONING: Good."
        mock_response.usage.total_tokens = 40

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        player.client = mock_client

        player.choose_move(board, candidates, "")

        call_kwargs = mock_client.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        assert system_msg["content"].startswith("/no_think")

    def test_thinking_budget_passed_when_enabled(self, mocker):
        """When thinking=True and profile has budget, it's in extra_body."""
        config = PlayerConfig(
            name="Qwen", model_id="qwen3-30b", backend="lmstudio",
            base_url="http://localhost:1234/v1", api_key="test",
            enable_thinking=True,
        )
        player = LMStudioPlayer.__new__(LMStudioPlayer)
        player.config = config
        player.elo = 1200.0

        board, candidates = _starting_board_and_candidates()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "CHOICE: 1\nMOVE: e2e4\nREASONING: Good."
        mock_response.usage.total_tokens = 200

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        player.client = mock_client

        player.choose_move(board, candidates, "")

        call_kwargs = mock_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs.get("extra_body", {})
        assert extra_body.get("enable_thinking") is True
        assert "thinking_budget" in extra_body
