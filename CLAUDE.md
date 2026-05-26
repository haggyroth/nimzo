# Nimzo

AI chess tournament system where locally-hosted LLMs compete in **guided mode**: Stockfish generates ranked candidate moves, and each model chooses from them with reasoning. Supports adaptive learning via post-game lesson generation.

## Architecture

```
arena.py          — FastAPI app, WebSocket/HTTP routes, shared state (_state, broadcast)
game.py           — Core game loop (play_game), tournament runners, build_player
engine.py         — Stockfish wrapper: candidate generation, move quality evaluation
analysis.py       — ELO calculation, post-game lesson generation via LLM
db.py             — SQLite persistence: games, moves, ELO history, lessons
config_loader.py  — TOML config file parser
providers.py      — Cloud provider registry (OpenAI, DeepSeek, Qwen, Gemini, xAI)
viewer.html       — Slim HTML shell (~474 lines); links to:
static/
  viewer.css        — All viewer styles (~1087 lines)
  viewer.js         — All viewer JavaScript (~1694 lines)
  viewer_utils.js   — Shared utility functions (FEN parser, sparklines, etc.)
models/
  base.py               — abstract ChessPlayer, prompt builder, lesson memory
  lmstudio_player.py    — OpenAI-compatible client (LM Studio, Ollama)
  anthropic_player.py   — Anthropic API client
  human_player.py       — Human move input (via browser UI)
  metadata.py           — Model metadata parsing (family, size, quantization)
  model_profiles.py     — Per-model behavioural profiles (thinking budget, token limits)
  portraits.py          — Gemini portrait generation
```

### arena.py ↔ game.py circular import

`arena.py` imports `game.py` at its bottom (after all definitions).
`game.py` imports `import arena as _arena` at its top to access `broadcast`,
`_state`, `_pause_event`, `_stop_requested`, and `TournamentAborted`.
Python resolves this safely because `game.py`'s `import arena` runs against the
already-complete `arena` module object.  **Rule:** never move definitions that
`game.py` depends on below the `from game import ...` line in `arena.py`.

## How Guided Mode Works

Each turn:
1. Stockfish analyses the position at `candidate_depth=10` with `multipv=N`
2. Top N moves are formatted with SAN notation and centipawn scores
3. The model receives the board FEN, game PGN so far, candidate list, accumulated lessons, and any coaching profile
4. Model responds with `CHOICE`, `MOVE` (UCI), and `REASONING`
5. Response is parsed; falls back to candidate #1 if parsing fails
6. Move quality is evaluated by comparing chosen move's score vs top candidate

Move quality labels: `best` `excellent` `good` `inaccuracy` `mistake` `blunder`
(Thresholds: <10 / <25 / <50 / <150 cp loss — see `CP_LOSS_*` constants in `engine.py`)

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

### Headless mode (no HTTP server)

```bash
python arena.py --headless \
  --white-model qwen3-coder-30b --black-model gemma-4b --games 20
```

Runs purely as a CLI process — no uvicorn, no browser. Useful for overnight benchmarking.

### TOML config file

```bash
python arena.py --config tournament.toml
```

See `config_loader.py` for the full schema. Supports multi-player bracket/round-robin/gauntlet formats with per-player style and candidate count overrides.

## Personality Styles

Each player can have a playing style injected into its system prompt:

| Style | Effect |
|---|---|
| `aggressive` | Favours open games, tactics, piece activity, material sacrifice |
| `positional` | Favours closed structures, outposts, patient manoeuvring |
| `defensive` | Consolidates before attacking; trades when ahead in material |

Set via `--white-style aggressive` or in `PlayerSpec.style`.

## Adaptive Difficulty

When `adaptive_difficulty=True`, after each game the rolling 10-game win rate for each player is checked. If it exceeds 65% their `candidate_count` drops by 1 (harder); if it falls below 35% it rises by 1 (easier). Bounds are 3–10. Thresholds are named constants in `arena.py` (`_ADAPT_*`).

## Reasoning Coherence Scoring

An optional judge model scores each move's reasoning 0–10 via `score_reasoning_coherence()` in `analysis.py`. Configure with `--judge-model <id>`. Scores are stored per move and shown in the viewer.

## WebSocket Events

The arena broadcasts JSON events to `ws://localhost:8765`. The visualizer connects here.

| Event | Key fields |
|---|---|
| `game_start` | `white`, `black`, `white_elo`, `black_elo`, `fen` |
| `thinking` | `player`, `color`, `fen`, `candidates[]`, `is_human_turn` |
| `move` | `san`, `uci`, `quality`, `candidate_rank`, `reasoning`, `coherence_score`, `fen` |
| `game_over` | `result`, `termination`, `white_elo_after`, `black_elo_after` |

## Adaptive Learning Loop

After each game:
1. Losing player's move history is summarized (quality counts, blunders/mistakes by SAN)
2. A tutor LLM call generates 2-3 specific lessons from the PGN + quality summary
3. Lessons are stored in SQLite and appended to the player's `lesson_memory`
4. On the next game, the last 10 lessons (or a compressed strategic profile) are injected into the system prompt

If both models are local and no Anthropic key is set, disable lesson generation by commenting out the `generate_lessons()` call in `arena.py` around the game-over block, or configure a local `--tutor-model`.

## Database Schema

`nimzo.db` — created automatically on first run, anchored to the directory containing `arena.py` regardless of working directory.

- `players` — name, model_id, backend, current ELO, portrait_path
- `games` — result, termination, PGN, ELO before/after for both players
- `moves` — per-move record with quality, candidate rank, reasoning, coherence score, FEN after
- `lessons` — per-player lessons linked to the game that generated them
- `tournaments` — bracket/round-robin tournament records

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
- `DEFAULT_REQUEST_TIMEOUT_S` — HTTP timeout for all player backends (default: 120s)

In `engine.py`:
- `depth` — Stockfish depth for full analysis (default: 15)
- `candidate_depth` — depth for candidate generation (default: 10; increase for stronger candidates, slower per move)
- `CP_LOSS_*` — named thresholds for move quality labels (excellent/good/inaccuracy/mistake/blunder)

In `analysis.py`:
- `K_INITIAL / K_MID / K_STABLE` — ELO K-factor schedule (32 → 24 → 16 as games accumulate)
- `K_THRESH_PROVISIONAL / K_THRESH_ESTABLISHED` — game-count breakpoints for K-factor decay

In `arena.py`:
- `_DEFAULT_PORT` — server port (default: 8765; override with `--port` or `PORT` env var)
- `_DEFAULT_LMSTUDIO_URL` — default LM Studio endpoint (http://localhost:1234/v1)

In `game.py`:
- `_ADAPT_CANDIDATE_MIN/MAX` — candidate count bounds for adaptive difficulty (3–10)
- `_ADAPT_WIN_RATE_HIGH/LOW` — win-rate thresholds that trigger difficulty adjustment (0.65/0.35)

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
| `ANTHROPIC_API_KEY` | — | Required for Anthropic backend or lesson generation |
| `GOOGLE_API_KEY` | — | Required for portrait generation (Gemini Imagen) |
| `PORT` | `8765` | Server port |
| `NIMZO_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` to expose on LAN) |
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | Default LM Studio endpoint |
| `OPENAI_API_KEY` | — | OpenAI cloud backend |
| `DEEPSEEK_API_KEY` | — | DeepSeek cloud backend |
| `DASHSCOPE_API_KEY` | — | Qwen / Alibaba Dashscope cloud backend |
| `GEMINI_API_KEY` | — | Google Gemini cloud backend |
| `XAI_API_KEY` | — | xAI Grok cloud backend |

## Git Workflow

**Always branch from `main`.** Each phase gets its own short-lived branch cut directly from the current `origin/main`:

```bash
git fetch origin
git worktree add .claude/worktrees/<phase-slug> -b <phase-slug> origin/main
```

Never branch from another feature branch — that's what causes cascading merge conflicts when earlier PRs land on main.

**Keep branches small.** One phase = one branch = one PR = one merge commit on main. Merge (or squash-merge) promptly so the next phase starts clean.
