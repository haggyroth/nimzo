"""
Base class for all chess players in the arena.
Guided mode: each model is given the top N Stockfish candidate moves
and must CHOOSE one with reasoning — tests strategy, not move generation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import chess

# Default HTTP timeout for all player backends (seconds).
# Override per-player via PlayerConfig.move_timeout.
DEFAULT_REQUEST_TIMEOUT_S = 120.0


@dataclass
class PlayerConfig:
    name: str                          # Display name, e.g. "Claude Sonnet 4"
    model_id: str                      # API model string
    backend: str                       # "anthropic" | "lmstudio"
    base_url: Optional[str] = None     # For LM Studio / Ollama endpoints
    api_key: Optional[str] = None      # Override; else reads from env
    candidate_count: int = 5           # How many Stockfish candidates to offer
    temperature: float = 0.3
    enable_thinking: bool = False      # Extended thinking (Qwen3, etc.)
    system_prompt: str = ""            # Optional override (rarely needed)
    move_timeout: int = 0              # Seconds per move, 0 = no limit
    style: str = ""                    # Play style: "aggressive" | "positional" | "defensive" | ""
    lesson_memory: list[str] = field(default_factory=list)
    strategic_profile: Optional[str] = None   # Compressed multi-game coaching profile


@dataclass
class MoveDecision:
    move_uci: str                  # Chosen move in UCI format (e.g. "e2e4")
    reasoning: str                 # Model's explanation
    candidate_rank: int            # Which candidate was chosen (1 = Stockfish's top pick)
    raw_response: str              # Full model output for logging
    thinking_content: str = ""     # Extracted <think>…</think> block, if any


class ChessPlayer(ABC):
    def __init__(self, config: PlayerConfig):
        self.config = config
        self.elo = 1200.0

    @abstractmethod
    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision: ...

    def build_prompt(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> str:
        color = "White" if board.turn == chess.WHITE else "Black"
        is_white = board.turn == chess.WHITE
        fen = board.fen()

        candidate_lines = []
        for i, (move, score_cp) in enumerate(candidates, 1):
            san = board.san(move)
            if score_cp is not None:
                # Always show eval from White's perspective — standard chess convention
                # (candidates arrive from current-player POV, so negate for Black)
                white_cp = score_cp if is_white else -score_cp
                score_str = f"{white_cp / 100:+.2f}"
            else:
                score_str = "?"
            label = "  ← Stockfish's top pick" if i == 1 else ""
            candidate_lines.append(
                f"  {i}. {san} (UCI: {move.uci()}) — eval: {score_str}{label}"
            )

        candidates_block = "\n".join(candidate_lines)

        if is_white:
            score_note = "higher eval = better for you"
        else:
            score_note = "lower eval = better for you; you want to minimise White's advantage"

        return f"""You are playing chess as {color}.

Current position (FEN): {fen}

Game so far (PGN):
{game_history_pgn or '(game just started)'}

Stockfish's top {len(candidates)} candidates, ranked best to worst for {color} ({score_note}):
{candidates_block}

Choose ONE of the numbered candidates. Respond in this exact format:
CHOICE: <number>
MOVE: <UCI notation, e.g. e2e4>
REASONING: <2-4 sentences on why this move fits your strategic plan>

Do not suggest any move not in the list above."""

    # Directives injected when a personality style is set
    _STYLE_DIRECTIVES: dict = {
        "aggressive": (
            "Your playing style is aggressive. Favour open games, tactical complications, "
            "and piece activity. Sacrifice material for initiative when the position allows. "
            "Keep queens on the board and create imbalances; avoid dry, symmetrical positions."
        ),
        "positional": (
            "Your playing style is positional. Favour closed structures, outpost control, "
            "and long-term pawn majorities. Trade pieces when it improves your structure. "
            "Avoid premature attacks and prefer patient manoeuvring."
        ),
        "defensive": (
            "Your playing style is defensive. Consolidate your position before attacking. "
            "Trade pieces when ahead in material and keep the position solid. "
            "Only launch a counterattack once your own king is safe and your structure is sound."
        ),
    }

    def build_system_prompt(self) -> str:
        base = (
            "You are a chess player competing in an AI tournament. "
            "You think strategically, consider your opponent's plans, "
            "and play to win. Be concise but show your reasoning."
        )

        # Personality style directive
        style_dir = self._STYLE_DIRECTIVES.get(self.config.style or "", "")
        if style_dir:
            base = f"{base}\n\n{style_dir}"

        if self.config.system_prompt:
            base = f"{base}\n\n{self.config.system_prompt}"

        # ── Strategic profile (compressed) ───────────────────────────────
        # When a tutor-compressed profile exists, use it as the primary
        # coaching context.  Append the 3 most-recent raw lessons alongside
        # for recency so very-recent feedback isn't buried.
        if self.config.strategic_profile:
            profile_block = (
                "Your strategic profile (distilled from all your games):\n"
                + self.config.strategic_profile
            )

            # Grab the 3 most recent individual lessons for recency context
            recent: list[str] = []
            for entry in reversed(self.config.lesson_memory[-6:]):
                if entry.startswith("[improve]"):
                    recent.append("↑ " + entry[len("[improve]"):].strip())
                elif entry.startswith("[strength]"):
                    recent.append("★ " + entry[len("[strength]"):].strip())
                if len(recent) >= 3:
                    break

            if recent:
                recent_block = (
                    "Recent game notes:\n"
                    + "\n".join(f"- {l}" for l in reversed(recent))
                )
                return f"{base}\n\n{profile_block}\n\n{recent_block}"
            return f"{base}\n\n{profile_block}"

        # ── Raw lesson list (no profile yet) ─────────────────────────────
        if not self.config.lesson_memory:
            return base

        improve = []
        strength = []
        for entry in self.config.lesson_memory[-10:]:
            if entry.startswith("[improve]"):
                improve.append(entry[len("[improve]"):].strip())
            elif entry.startswith("[strength]"):
                strength.append(entry[len("[strength]"):].strip())
            else:
                improve.append(entry)  # legacy unprefixed lessons

        sections = []
        if improve:
            sections.append(
                "Areas to work on:\n" + "\n".join(f"- {l}" for l in improve[-5:])
            )
        if strength:
            sections.append(
                "What you've been doing well:\n" + "\n".join(f"- {l}" for l in strength[-5:])
            )

        if sections:
            notes = "\n\n".join(sections)
            return f"{base}\n\nCoach's notes from your recent games:\n{notes}"
        return base

    def get_legal_uci_moves(self) -> list[str]:
        """
        Return all legal UCI moves on the current board.
        Only meaningful for HumanPlayer; LLM players return an empty list.
        """
        return []

    def add_lesson(self, lesson: str):
        """lesson should already include [improve] or [strength] prefix."""
        self.config.lesson_memory.append(lesson)

    def update_elo(self, new_elo: float):
        self.elo = new_elo
