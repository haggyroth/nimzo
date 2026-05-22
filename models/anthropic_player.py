"""
Anthropic Claude player — uses the Messages API.
"""

import os
import re
import chess
import anthropic

from .base import ChessPlayer, PlayerConfig, MoveDecision


class AnthropicPlayer(ChessPlayer):
    def __init__(self, config: PlayerConfig):
        super().__init__(config)
        self.client = anthropic.Anthropic(
            api_key=config.api_key or os.environ["ANTHROPIC_API_KEY"]
        )

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision:
        prompt = self.build_prompt(board, candidates, game_history_pgn)

        kwargs: dict = dict(
            model=self.config.model_id,
            max_tokens=1024,
            system=self.build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
        if not self.config.enable_thinking:
            kwargs["temperature"] = self.config.temperature
        else:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 800}
            kwargs["max_tokens"] = 2048

        message = self.client.messages.create(**kwargs)

        # Extract text content (skip thinking blocks)
        raw = next(
            (block.text for block in message.content if hasattr(block, "text")),
            "",
        )
        return self._parse_response(raw, candidates, board)

    def _parse_response(
        self,
        raw: str,
        candidates: list[tuple[chess.Move, float]],
        board: chess.Board,
    ) -> MoveDecision:
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
                return MoveDecision(uci, reasoning, rank, raw)

        # 2. CHOICE number
        if choice_match:
            idx = int(choice_match.group(1)) - 1
            if 0 <= idx < len(candidates):
                move, _ = candidates[idx]
                return MoveDecision(move.uci(), reasoning, idx + 1, raw)

        # 3. Any UCI string in the response that's a candidate
        for token in re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?", raw, re.IGNORECASE):
            try:
                move = chess.Move.from_uci(token.lower())
                if move in board.legal_moves:
                    rank = next((i + 1 for i, (c, _) in enumerate(candidates) if c == move), 0)
                    return MoveDecision(move.uci(), reasoning, rank, raw)
            except ValueError:
                continue

        # 4. Fallback
        move, _ = candidates[0]
        return MoveDecision(move.uci(), "(parse failed — defaulted to top candidate)", 1, raw)
