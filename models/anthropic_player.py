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

        message = self.client.messages.create(
            model=self.config.model_id,
            max_tokens=512,
            temperature=self.config.temperature,
            system=self.build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        return self._parse_response(raw, candidates, board)

    def _parse_response(
        self,
        raw: str,
        candidates: list[tuple[chess.Move, float]],
        board: chess.Board,
    ) -> MoveDecision:
        choice_match = re.search(r"CHOICE:\s*(\d+)", raw, re.IGNORECASE)
        move_match = re.search(r"MOVE:\s*([a-h][1-8][a-h][1-8][qrbn]?)", raw, re.IGNORECASE)
        reasoning_match = re.search(r"REASONING:\s*(.+?)(?:\n|$)", raw, re.IGNORECASE | re.DOTALL)

        reasoning = reasoning_match.group(1).strip() if reasoning_match else "(no reasoning)"

        if move_match:
            uci = move_match.group(1).lower()
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                rank = next(
                    (i + 1 for i, (c, _) in enumerate(candidates) if c == move), 0
                )
                return MoveDecision(uci, reasoning, rank, raw)

        if choice_match:
            idx = int(choice_match.group(1)) - 1
            if 0 <= idx < len(candidates):
                move, _ = candidates[idx]
                return MoveDecision(move.uci(), reasoning, idx + 1, raw)

        move, _ = candidates[0]
        return MoveDecision(move.uci(), "(parse failed — defaulted to top candidate)", 1, raw)
