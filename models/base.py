"""
Base class for all chess players in the arena.
Guided mode: each model is given the top N Stockfish candidate moves
and must CHOOSE one with reasoning — tests strategy, not move generation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import chess


@dataclass
class PlayerConfig:
    name: str                          # Display name, e.g. "Claude Sonnet 4"
    model_id: str                      # API model string
    backend: str                       # "anthropic" | "lmstudio" | "ollama"
    base_url: Optional[str] = None     # For LM Studio / Ollama endpoints
    api_key: Optional[str] = None      # Override; else reads from env
    candidate_count: int = 5           # How many Stockfish candidates to offer
    temperature: float = 0.3
    enable_thinking: bool = False      # Set True to allow extended thinking (slower)
    system_prompt: str = ""            # Seeded with accumulated lessons
    lesson_memory: list[str] = field(default_factory=list)


@dataclass
class MoveDecision:
    move_uci: str           # Chosen move in UCI format (e.g. "e2e4")
    reasoning: str          # Model's explanation
    candidate_rank: int     # Which candidate was chosen (1 = Stockfish's top pick)
    raw_response: str       # Full model output for logging


class ChessPlayer(ABC):
    def __init__(self, config: PlayerConfig):
        self.config = config
        self.elo = 1200.0

    @abstractmethod
    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],  # (move, stockfish_score_cp)
        game_history_pgn: str,
    ) -> MoveDecision:
        """
        Given the board and a ranked list of Stockfish candidate moves,
        return the model's chosen move with reasoning.
        """
        ...

    def build_prompt(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> str:
        color = "White" if board.turn == chess.WHITE else "Black"
        fen = board.fen()

        candidate_lines = []
        for i, (move, score_cp) in enumerate(candidates, 1):
            san = board.san(move)
            score_str = f"{score_cp/100:+.2f}" if score_cp is not None else "?"
            candidate_lines.append(f"  {i}. {san} (UCI: {move.uci()}) — eval: {score_str} pawns")

        candidates_block = "\n".join(candidate_lines)

        lessons_block = ""
        if self.config.lesson_memory:
            lessons = "\n".join(f"- {l}" for l in self.config.lesson_memory[-10:])
            lessons_block = f"\n\nLessons from your previous games:\n{lessons}"

        return f"""You are playing chess as {color}.{lessons_block}

Current position (FEN): {fen}

Game so far (PGN):
{game_history_pgn or '(game just started)'}

Stockfish's top {len(candidates)} candidate moves for this position:
{candidates_block}

Choose ONE of the numbered candidates. Respond in this exact format:
CHOICE: <number>
MOVE: <UCI notation, e.g. e2e4>
REASONING: <2-4 sentences on why this move fits your strategic plan>

Do not suggest any move not in the list above."""

    def build_system_prompt(self) -> str:
        base = (
            "You are a chess player competing in an AI tournament. "
            "You think strategically, consider your opponent's plans, "
            "and play to win. Be concise but show your reasoning."
        )
        if self.config.system_prompt:
            return f"{base}\n\n{self.config.system_prompt}"
        return base

    def add_lesson(self, lesson: str):
        self.config.lesson_memory.append(lesson)

    def update_elo(self, new_elo: float):
        self.elo = new_elo
