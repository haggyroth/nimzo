# Nimzo

AI chess tournament system where locally-hosted LLMs compete in **guided mode**: Stockfish generates ranked candidate moves, and each model chooses from them with reasoning. Supports adaptive learning via post-game lesson generation.

## Architecture

```
arena.py          — orchestrator: game loop, WebSocket broadcast, tournament runner
engine.py         — Stockfish wrapper: candidate generation, move quality evaluation
analysis.py       — ELO calculation, post-game lesson generation via LLM
db.py             — SQLite persistence: games, moves, ELO history, lessons
models/
  base.py         — abstract ChessPlayer, prompt builder, lesson memory
  lmstudio_player.py  — OpenAI-compatible client (LM Studio, Ollama)
  anthropic_player.py — Anthropic API client (optional, not used in local setup)
```

## How Guided Mode Works

Each turn:
1. Stockfish analyses the position at `candidate_depth=10` with `multipv=N`
2. Top N moves are formatted with SAN notation and centipawn scores
3. The model receives the board FEN, game PGN so far, candidate list, and accumulated lessons
4. Model responds with `CHOICE`, `MOVE` (UCI), and `REASONING`
5. Response is parsed; falls back to candidate #1 if parsing fails
6. Move quality is evaluated by comparing chosen move's score vs top candidate

Move quality labels: `best` `excellent` `good` `inaccuracy` `mistake` `blunder`

## Running a Tournament

### GUI mode (default)

```bash
pip install -r requirements.txt
export STOCKFISH_PATH=/opt/homebrew/bin/stockfish   # or wherever stockfish is installed

python arena.py
# Browser opens automatically at http://localhost:8765
# Select models from the dropdowns and click Start
```

Both players default to `http://localhost:1234/v1` — LM Studio runs a single
server on port 1234 and can serve any loaded model by ID. No second instance
needed; just load whichever models you want in LM Studio and pick them in the UI.

### CLI mode (auto-starts without browser)

```bash
python arena.py \
  --white-name "Qwen" --white-model qwen3-coder-30b \
  --black-name "Gemma" --black-model google/gemma-4-e4b \
  --games 5
```

Model IDs must be passed explicitly — `WHITE_MODEL`/`BLACK_MODEL` env vars do
**not** trigger CLI mode (prevents `.env` files from auto-starting tournaments).

If you need two separate LM Studio instances (e.g. to load two large models
simultaneously), start a second one on port 1235 and pass `--black-url http://localhost:1235/v1`.

Colors alternate each game automatically.

## WebSocket Events

The arena broadcasts JSON events to `ws://localhost:8765`. The visualizer connects here.

| Event | Key fields |
|---|---|
| `game_start` | `white`, `black`, `white_elo`, `black_elo`, `fen` |
| `thinking` | `player`, `color`, `fen`, `candidates[]` |
| `move` | `san`, `uci`, `quality`, `candidate_rank`, `reasoning`, `fen` |
| `game_over` | `result`, `termination`, `white_elo_after`, `black_elo_after` |

## Adaptive Learning Loop

After each game:
1. Losing player's move history is summarized (quality counts, blunders/mistakes by SAN)
2. A Haiku API call generates 2-3 specific lessons from the PGN + quality summary
3. Lessons are stored in SQLite and appended to the player's `lesson_memory`
4. On the next game, the last 10 lessons are injected into the system prompt

If both models are local and no Anthropic key is set, disable lesson generation by commenting out the `generate_lessons()` call in `arena.py` around the game-over block, or swap in a local model call in `analysis.py`.

## Database Schema

`nimzo.db` — created automatically on first run.

- `players` — name, model_id, backend, current ELO
- `games` — result, termination, PGN, ELO before/after for both players
- `moves` — per-move record with quality, candidate rank, reasoning, FEN after
- `lessons` — per-player lessons linked to the game that generated them

Useful queries:
```sql
-- Leaderboard
SELECT name, elo, COUNT(*) as games FROM players JOIN games ...;

-- Blunder rate by player
SELECT p.name, COUNT(*) as blunders
FROM moves m JOIN players p ON m.player_id = p.id
WHERE m.quality = 'blunder' GROUP BY p.name;

-- How often each player deviates from Stockfish's top pick
SELECT p.name, AVG(m.candidate_rank) as avg_rank
FROM moves m JOIN players p ON m.player_id = p.id GROUP BY p.name;
```

## Key Configuration

In `models/base.py`:
- `candidate_count` — how many Stockfish candidates the model sees (default: 5)
- `temperature` — model temperature (default: 0.3; lower = more consistent)

In `engine.py`:
- `depth` — Stockfish depth for full analysis (default: 15)
- `candidate_depth` — depth for candidate generation (default: 10; increase for stronger candidates, slower per move)

In `analysis.py`:
- `K_FACTOR` — ELO K-factor (default: 32; reduce as game count grows for stability)

## Adding a New Backend

Subclass `ChessPlayer` in `models/base.py`:

```python
class MyPlayer(ChessPlayer):
    def choose_move(self, board, candidates, game_history_pgn) -> MoveDecision:
        prompt = self.build_prompt(board, candidates, game_history_pgn)
        # call your backend, parse response
        return MoveDecision(uci, reasoning, candidate_rank, raw)
```

Then add a branch in `build_player()` in `arena.py`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `STOCKFISH_PATH` | `/usr/games/stockfish` | Path to stockfish binary |
| `ANTHROPIC_API_KEY` | — | Required only if using Anthropic backend or lesson generation |
