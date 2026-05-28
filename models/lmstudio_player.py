"""
LM Studio (or any OpenAI-compatible) player.

Model-specific behaviour is controlled by model_profiles.json:
  - no_think_prefix:        prepend /no_think to the system prompt when thinking is
                            disabled, as a belt-and-suspenders alternative to
                            extra_body={"enable_thinking": false}
  - thinking_budget_tokens: pass a budget hint in extra_body when thinking IS enabled
  - max_tokens_thinking / max_tokens_default: override per-state token limits
"""

import logging
import os
import random
import re
import time

logger = logging.getLogger(__name__)
import chess
from openai import OpenAI

from .base import ChessPlayer, DEFAULT_REQUEST_TIMEOUT_S, PlayerConfig, MoveDecision
from .model_profiles import get_profile


# Regex that matches a <think>…</think> block (greedy-minimal, non-nested)
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def _extract_thinking(raw: str) -> tuple[str, str]:
    """
    Split raw model output into (thinking_content, clean_text).

    thinking_content — everything inside the FIRST <think>…</think> block
                       only.  If the model emits multiple think blocks,
                       subsequent ones are silently stripped (they appear
                       in clean_text as gaps, not as separate captures).
                       This is intentional: we surface one consolidated
                       think trace to the viewer rather than a list.
    clean_text       — raw with ALL <think>…</think> blocks stripped and
                       leading/trailing whitespace removed.
    """
    match = _THINK_RE.search(raw)
    thinking = match.group(1).strip() if match else ""
    clean = _THINK_RE.sub("", raw).strip()
    return thinking, clean


class LMStudioPlayer(ChessPlayer):
    """Chess player backed by any OpenAI-compatible endpoint (LM Studio, Ollama, etc.)."""

    def __init__(self, config: PlayerConfig):
        super().__init__(config)
        self.client = OpenAI(
            base_url=config.base_url or os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            api_key=config.api_key or os.environ.get("LMSTUDIO_API_KEY", "lm-studio"),
            timeout=DEFAULT_REQUEST_TIMEOUT_S,
        )

    def choose_move(
        self,
        board: chess.Board,
        candidates: list[tuple[chess.Move, float]],
        game_history_pgn: str,
    ) -> MoveDecision:
        """Call the LM Studio API and parse the response into a MoveDecision."""
        prompt  = self.build_prompt(board, candidates, game_history_pgn)
        thinking = self.config.enable_thinking
        profile  = get_profile(self.config.model_id)

        # ── max_tokens ───────────────────────────────────────────────
        if profile:
            max_tokens = profile.max_tokens_thinking if thinking else profile.max_tokens_default
        else:
            max_tokens = 2048 if thinking else 512

        # ── System prompt — optionally inject /no_think ──────────────
        system_prompt = self.build_system_prompt()
        if profile and profile.no_think_prefix and not thinking:
            # Qwen3's documented method: first token of the system prompt
            # tells the model to skip its chain-of-thought entirely.
            system_prompt = "/no_think\n" + system_prompt

        # ── extra_body ───────────────────────────────────────────────
        # Only send thinking-control fields when the profile indicates the model
        # supports them (Qwen3, DeepSeek-R1, etc.).  Sending unknown extra_body
        # keys to plain models is harmless via LM Studio but adds noise to logs.
        extra_body: dict = {}
        if profile and profile.no_think_prefix is not None:
            # Profile explicitly opts in — send the flag for both on and off
            extra_body["enable_thinking"] = thinking
        elif thinking:
            # Thinking explicitly enabled by the user but no profile: send the flag
            extra_body["enable_thinking"] = True
        if thinking and profile and profile.thinking_budget_tokens:
            extra_body["thinking_budget"] = profile.thinking_budget_tokens

        # ── API call with timing for audit purposes ───────────────────
        t0 = time.monotonic()
        response = self.client.chat.completions.create(
            model=self.config.model_id,
            max_tokens=max_tokens,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt},
            ],
            extra_body=extra_body,
        )
        elapsed = time.monotonic() - t0

        raw = response.choices[0].message.content or ""

        # ── Thinking audit: warn if model appears to be thinking
        # despite being told not to ───────────────────────────────────
        if not thinking:
            thinking_found = bool(_THINK_RE.search(raw))
            usage = getattr(response, "usage", None)
            total_tokens = getattr(usage, "total_tokens", None)
            if thinking_found or (elapsed > 15 and total_tokens and total_tokens > 800):
                logger.warning(
                    "[%s] thinking appears active despite enable_thinking=false "
                    "(elapsed=%.1fs, tokens=%s, <think>=%s)",
                    self.config.model_id, elapsed, total_tokens,
                    "yes" if thinking_found else "no",
                )

        return self._parse_response(raw, candidates, board)

    def _parse_response(
        self,
        raw: str,
        candidates: list[tuple[chess.Move, float]],
        board: chess.Board,
    ) -> MoveDecision:
        """
        Extract CHOICE/MOVE/REASONING from raw model output.

        Strips ``<think>…</think>`` blocks first, then falls back through:
        explicit MOVE UCI → CHOICE number → any UCI token in the response.
        Returns candidate #1 with a parse-failed note if all strategies fail.
        """
        # Always extract <think> blocks — some models (DeepSeek R1, Qwen3 in
        # thinking mode) include them regardless of the enable_thinking flag.
        thinking_content, clean = _extract_thinking(raw)

        choice_match    = re.search(r"CHOICE:\s*(\d+)", clean, re.IGNORECASE)
        move_match      = re.search(r"MOVE:\s*([a-h][1-8][a-h][1-8][qrbn]?)", clean, re.IGNORECASE)
        reasoning_match = re.search(r"REASONING:\s*(.+?)(?:\n\n|\Z)", clean, re.IGNORECASE | re.DOTALL)

        if reasoning_match:
            reasoning = reasoning_match.group(1).strip()
        elif not candidates:
            # Blind mode: model may write free-form prose instead of a tagged
            # REASONING: line.  Strip the MOVE line and use whatever's left.
            leftover = re.sub(r"MOVE:\s*[a-h][1-8][a-h][1-8][qrbn]?\s*",
                              "", clean, flags=re.IGNORECASE).strip()
            reasoning = leftover[:300] if len(leftover) > 10 else ""
        else:
            reasoning = "(no reasoning)"

        # 1. Explicit MOVE field — highest confidence
        if move_match:
            uci = move_match.group(1).lower()
            try:
                move = chess.Move.from_uci(uci)
                if move in board.legal_moves:
                    rank = next((i + 1 for i, (c, _) in enumerate(candidates) if c == move), 0)
                    return MoveDecision(uci, reasoning, rank, raw, thinking_content)
            except ValueError:
                pass  # fall through to CHOICE / scan strategies

        # 2. CHOICE number
        if choice_match:
            idx = int(choice_match.group(1)) - 1
            if 0 <= idx < len(candidates):
                move, _ = candidates[idx]
                return MoveDecision(move.uci(), reasoning, idx + 1, raw, thinking_content)

        # 3. Any UCI string in the response that's a candidate
        for token in re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?", clean, re.IGNORECASE):
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
