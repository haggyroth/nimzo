"""
Anthropic Claude player — uses the Messages API.

When extended thinking is enabled the API returns a separate thinking block
in message.content; we surface that as thinking_content in MoveDecision so
the viewer can show it in the move card.
"""

import os
import random
import re
import chess
import anthropic

from .base import ChessPlayer, DEFAULT_REQUEST_TIMEOUT_S, PlayerConfig, MoveDecision
from .model_profiles import get_profile


class AnthropicPlayer(ChessPlayer):
    """Chess player backed by the Anthropic Messages API."""

    def __init__(self, config: PlayerConfig):
        super().__init__(config)
        self.client = anthropic.Anthropic(
            api_key=config.api_key or os.environ["ANTHROPIC_API_KEY"],
            timeout=DEFAULT_REQUEST_TIMEOUT_S,
        )

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision:
        """Call the Anthropic API and parse the response into a MoveDecision."""
        prompt  = self.build_prompt(board, candidates, game_history_pgn)
        thinking = self.config.enable_thinking
        profile  = get_profile(self.config.model_id)

        # Thinking budget: prefer profile setting, fall back to 800
        budget = (
            profile.thinking_budget_tokens
            if (profile and profile.thinking_budget_tokens)
            else 800
        )

        kwargs: dict = dict(
            model=self.config.model_id,
            max_tokens=1024,
            system=self.build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
        if not thinking:
            kwargs["temperature"] = self.config.temperature
        else:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["max_tokens"] = max(budget + 1024, 2048)

        message = self.client.messages.create(**kwargs)

        # Separate thinking blocks from text blocks
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        for block in message.content:
            if hasattr(block, "thinking"):
                thinking_parts.append(block.thinking)
            elif hasattr(block, "text"):
                text_parts.append(block.text)

        raw              = "\n".join(text_parts)
        thinking_content = "\n\n".join(thinking_parts)

        return self._parse_response(raw, candidates, board, thinking_content)

    def _parse_response(
        self,
        raw: str,
        candidates: list[tuple[chess.Move, float]],
        board: chess.Board,
        thinking_content: str = "",
    ) -> MoveDecision:
        """
        Extract CHOICE/MOVE/REASONING from raw model output.

        Falls back through three strategies: explicit MOVE UCI field →
        CHOICE number → any UCI token in the response.  If all fail,
        returns candidate #1 with a parse-failed note.
        """
        choice_match    = re.search(r"CHOICE:\s*(\d+)", raw, re.IGNORECASE)
        move_match      = re.search(r"MOVE:\s*([a-h][1-8][a-h][1-8][qrbn]?)", raw, re.IGNORECASE)
        reasoning_match = re.search(r"REASONING:\s*(.+?)(?:\n\n|\Z)", raw, re.IGNORECASE | re.DOTALL)

        reasoning = reasoning_match.group(1).strip() if reasoning_match else "(no reasoning)"

        # 1. Explicit MOVE field
        if move_match:
            uci  = move_match.group(1).lower()
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                rank = next((i + 1 for i, (c, _) in enumerate(candidates) if c == move), 0)
                return MoveDecision(uci, reasoning, rank, raw, thinking_content)

        # 2. CHOICE number
        if choice_match:
            idx = int(choice_match.group(1)) - 1
            if 0 <= idx < len(candidates):
                move, _ = candidates[idx]
                return MoveDecision(move.uci(), reasoning, idx + 1, raw, thinking_content)

        # 3. Any UCI string in the response that's a candidate
        for token in re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?", raw, re.IGNORECASE):
            try:
                move = chess.Move.from_uci(token.lower())
                if move in board.legal_moves:
                    rank = next((i + 1 for i, (c, _) in enumerate(candidates) if c == move), 0)
                    return MoveDecision(move.uci(), reasoning, rank, raw, thinking_content)
            except ValueError:
                continue

        # 4. Fallback: random legal move in blind mode; Stockfish's top otherwise
        if not candidates:
            move = random.choice(list(board.legal_moves))
            return MoveDecision(
                move.uci(), "(parse failed — random legal move, blind mode)", 0, raw, thinking_content
            )
        move, _ = candidates[0]
        return MoveDecision(
            move.uci(), "(parse failed — defaulted to top candidate)", 1, raw, thinking_content
        )
