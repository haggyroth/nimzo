# Nimzo

AI chess tournament system where locally-hosted LLMs compete against each other. Uses **guided mode**: Stockfish generates ranked candidate moves and each model picks one with reasoning — so matches test strategic judgment, not move generation.

Supports adaptive learning: after each game the losing model receives lessons generated from its mistakes, injected into its system prompt for the next game.

## How it works

Each turn:
1. Stockfish analyses the position and produces the top N candidate moves with centipawn scores
2. The model receives the board (FEN), game history (PGN), candidate list, and any lessons from previous games
3. Model responds with a choice, the UCI move, and reasoning
4. Move quality is evaluated (`best` → `blunder`) by comparing the chosen move's score to Stockfish's top pick

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install Stockfish (macOS)
brew install stockfish

# Configure
cp .env.example .env
# Edit .env — set STOCKFISH_PATH, model IDs, and optionally ANTHROPIC_API_KEY
```

## Running a tournament

```bash
python3 arena.py --games 10
```

Models are configured in `.env`:

```env
WHITE_NAME=Qwen-v1
WHITE_MODEL=qwen3.5-4b:v1

BLACK_NAME=Gemma-4B
BLACK_MODEL=google/gemma-4-e4b
```

Both players default to `LMSTUDIO_BASE_URL` — point it at any OpenAI-compatible endpoint (LM Studio, Ollama, etc.). Colors alternate each game automatically.

### Options

| Flag | Default | Description |
|---|---|---|
| `--games N` | 10 | Number of games to play |
| `--thinking` | off | Enable extended thinking for Qwen3-style models |
| `--white-url / --black-url` | `LMSTUDIO_BASE_URL` | Override endpoint per player |

## Live viewer

Open `viewer.html` in a browser while a tournament is running. It connects to the WebSocket at `ws://localhost:8765` and shows the board, candidate moves, move quality, and each model's reasoning in real time.

## ELO & learning

ELO is stored in `nimzo.db` (SQLite) and tied to the model ID — renaming a player in `.env` won't reset its score. Lessons accumulate across games and are injected into the system prompt (last 10).

Lesson generation requires `ANTHROPIC_API_KEY`. Without it, games still run and ELO is tracked — lessons are silently skipped.

## Architecture

```
arena.py          — game loop, WebSocket broadcast, tournament runner
engine.py         — Stockfish wrapper: candidate generation, move quality
analysis.py       — ELO calculation, post-game lesson generation
db.py             — SQLite persistence: games, moves, ELO, lessons
models/
  base.py         — abstract ChessPlayer, prompt builder, lesson memory
  lmstudio_player.py  — OpenAI-compatible client (LM Studio, Ollama)
  anthropic_player.py — Anthropic API client
viewer.html       — WebSocket live visualizer
```

## Adding a backend

Subclass `ChessPlayer` in `models/base.py`:

```python
class MyPlayer(ChessPlayer):
    def choose_move(self, board, candidates, game_history_pgn) -> MoveDecision:
        prompt = self.build_prompt(board, candidates, game_history_pgn)
        # call your backend, parse response
        return MoveDecision(uci, reasoning, candidate_rank, raw)
```

Then add a branch in `build_player()` in `arena.py`.
