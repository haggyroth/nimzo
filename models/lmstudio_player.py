"""
LM Studio (or any OpenAI-compatible) player.
"""

import os
import re
import chess
from openai import OpenAI

from .base import ChessPlayer, PlayerConfig, MoveDecision


class LMStudioPlayer(ChessPlayer):
    def __init__(self, config: PlayerConfig):
        super().__init__(config)
        self.client = OpenAI(
            base_url=config.base_url or os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            api_key=config.api_key or os.environ.get("LMSTUDIO_API_KEY", "lm-studio"),
        )

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision:
        prompt = self.build_prompt(board, candidates, game_history_pgn)
        thinking = self.config.enable_thinking

        response = self.client.chat.completions.create(
            model=self.config.model_id,
            max_tokens=2048 if thinking else 512,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user",   "content": prompt},
            ],
            extra_body={"enable_thinking": thinking},
        )

        raw = response.choices[0].message.content or ""
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

        # 1. Explicit MOVE field — highest confidence
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

        # 4. Fallback to Stockfish's top candidate
        move, _ = candidates[0]
        return MoveDecision(move.uci(), "(parse failed — defaulted to top candidate)", 1, raw)
