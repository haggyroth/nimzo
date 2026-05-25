# Nimzo Roadmap

AI chess tournament system where locally-hosted LLMs compete in guided mode against Stockfish-ranked candidates.

---

## Phase 1 — Foundation ✅
*Initial experiment → working system*

- [x] Guided mode: Stockfish generates candidates, models choose with reasoning
- [x] LM Studio (OpenAI-compatible) and Anthropic backends
- [x] SQLite persistence: players, games, moves, lessons
- [x] ELO rating system with per-game history
- [x] Post-game lesson generation via Haiku
- [x] WebSocket broadcast to live viewer
- [x] Dark-themed chess viewer (viewer.html)

---

## Phase 2 — Robustness & Learning ✅
*v2 release*

- [x] Both players receive lessons after every game (not just the loser)
- [x] Structured lessons: separate improve/strength sections, labelled coach notes in system prompt
- [x] Configurable tutor model: any LM Studio/Ollama endpoint or Anthropic cloud
- [x] Dynamic K-factor: ELO volatility decays with experience (K=32→24→16)
- [x] Fix thinking mode: Qwen3 now correctly sends `enable_thinking: true/false`
- [x] Robust 4-tier response parsing fallback in both player backends
- [x] FastAPI server: viewer at `http://localhost:8765`, REST control API
- [x] Tournament control UI: configure models, start/pause/resume/stop from browser
- [x] Live leaderboard, lessons panel, recent games panel
- [x] Model discovery: fetch available models from any LM Studio instance
- [x] Qwen models auto-uncheck thinking; name auto-fills from model ID
- [x] Move history newest-first
- [x] Tutor parser: strips `<think>` blocks, handles markdown/numbered bullets

---

## Phase 3 — Analytics & Polish ✅
*v3 release*

- [x] Centipawn evaluation graph: live SVG sparkline, fills White/Black advantage areas
- [x] Collapsible panels: all center and right-panel sections toggle independently
- [x] Default games 1 (was 10); black URL defaults to `localhost:1234`
- [x] `score_cp` correctly written to moves table (was always null)

---

## Phase 4 — Viewer Polish & Quick Wins
*Next*

- [x] **Live eval readout** in player strip during game (+1.2 / -0.8 centipawn number alongside ELO)
- [x] **Annotated PGN export**: one-click download from the game-over overlay; reasoning as `{ }` comments, quality as `?/??/!/!!` glyphs — immediately openable in Lichess or any chess GUI
- [x] **Game replay**: click any game in Recent Games to step through it move-by-move on the board; prev/next controls; reuses existing board renderer with FEN sequence from DB
- [x] **ELO trajectory sparkline** per player row in the leaderboard panel (`get_elo_history()` already in db.py)
- [x] **"Best game" stat** per player: highest average move quality across all games, surfaced as a score in the leaderboard
- [x] **Captured pieces graveyard**: display each side's captured material beside the board, sorted by piece value; show material imbalance score (+2♗ etc.) alongside the graveyard — gives a quick read on who's up in material without parsing the board
- [x] **Opening detection in lessons**: pass ECO code (python-chess can derive from PGN) to the lesson prompt so the coach can reference the specific opening structure — "in the Sicilian Najdorf, your knight retreat on move 14 ignored the standard d5 break"
- [x] **Model personality profile**: per-model summary derived from move data — castling timing, material trade preferences, closed vs open position tendencies; displayed on model card and stats page
- [x] **Stats page** (`/stats`): head-to-head records, win rate by color, average move quality per model, ELO chart over time, blunder rate, candidate deviation rate

---

## Phase 5 — Model Cards & Achievements
*Future*

- [x] **Model cards**: modal/panel that appears when a model is selected in the UI — displays name, ELO, W/D/L, games played, average move quality, personality summary, and metadata
- [x] **Model metadata strategy**: LM Studio's `/models` returns IDs but not specs; options are (a) parse from filename conventions (`qwen3-30b-a3b@q4_k_m` → 30B params, Q4_K_M quant), (b) HuggingFace API lookup by model ID, (c) manual entry in a `model_profiles.json` sidecar — likely a combination
- [x] **Metadata fields**: parameter count, architecture family, quantization, file size, context length, backend
- [x] **Achievement / badge system**: new `achievements` DB table; conditions computed post-game (e.g. "Flawless Game" — zero blunders, "Comeback King" — won from -5cp deficit, "Theorist" — 10+ book moves before first deviation)
- [x] **Trophy display**: badges shown on model cards, player strips during games, and leaderboard rows
- [x] **Model comparison view**: side-by-side stat comparison of any two models
- [ ] **Model profile pictures**: generate a chess grandmaster portrait per model via Google AI Studio (Gemini Flash/Nano — free tier); prompt seeded deterministically from the model ID so the same model always gets the same image; stored as file + path in DB; displayed on model cards, leaderboard rows, and player strips during games — e.g. "Qwen3-30B is playing in the style of Mikhail Tal"

### Achievement ideas
| Badge | Condition |
|---|---|
| Flawless | Game with zero blunders or mistakes |
| Comeback | Won from a position ≤ -300cp |
| Theorist | Followed opening theory 10+ moves |
| Tactician | 3+ "best" moves in a row |
| Grinder | Won a 70+ move endgame |
| Crusher | Won in ≤ 25 moves |
| Iron Wall | Drew against a higher-rated opponent |
| Top Scholar | Most improved ELO over 10 games |

---

## Phase 6 — Tournament Brackets
*Future*

- [ ] **Multi-player arena**: register N models; currently hardcoded 2-player — needs a player pool and scheduling logic
- [ ] **Bracket formats**: single-elimination, round-robin (all vs all), Swiss (pair by standing each round), gauntlet (one champion vs all challengers)
- [ ] **Bracket visualization**: bracket tree or standings table in the viewer; updates live as games complete
- [ ] **Sequential scheduling**: games play one at a time (simpler, no parallel inference required); next pairing auto-queued
- [ ] **Bracket state persistence**: tournament survives server restart; state saved to DB
- [ ] **Seeding**: initial bracket seeding by current ELO; manual seed override option
- [ ] **Tournament titles**: fun made-up titles awarded to bracket winners ("Grand Inquisitor", "Silicon Kasparov", "The Relentless") — stored in DB and displayed as trophies on model cards
- [ ] **Tournament history**: past tournaments with winner, format, date, and final standings
- [ ] **Best-of series**: track set scores within a matchup for a more dramatic narrative

---

## Phase 7 — Smarter Lessons
*Future*

- [ ] **Lesson compression / strategic profile**: every N games, tutor consolidates the raw lesson list into 5–8 distilled principles per model — prevents context bloat, stops the same lesson from appearing 6 different ways; profile evolves rather than accumulates
- [ ] **Opening awareness**: ECO code + opening name passed to lesson prompt (prerequisite for Phase 4 opening detection item)
- [ ] **Lesson effectiveness tracking**: correlate lesson topics with subsequent quality improvements — did the coaching actually work?
- [ ] **Draw lesson handling**: draws produce weaker coaching signal; lighter lesson prompt or skip entirely (open question)

---

## Phase 8 — Customization & Themes
*Future*

- [ ] **Board themes**: preset color schemes (classic, green felt, blue ocean, high contrast) using CSS custom properties; `--sq-light` and `--sq-dark` already in use
- [ ] **Custom colors**: color picker for board squares, highlights, and UI accent color
- [ ] **Piece sets**: current Unicode pieces render inconsistently across OS/fonts; add SVG piece set options (e.g. Merida, Alpha, Neo)
- [x] **Board orientation toggle**: flip board to show from Black's perspective; persists per session
- [ ] **Font & typography controls**: font family selector (monospace vs sans-serif), font size slider; CSS custom properties make this straightforward; persisted in `localStorage`
- [ ] **UI framework consideration**: current hand-crafted CSS is lean and custom; Tailwind or Bootstrap are options if maintenance becomes painful — worth evaluating when the component count grows rather than rewriting speculatively
- [ ] **Settings persistence**: store theme/orientation/font preferences in `localStorage`
- [ ] **Animated piece moves**: smooth CSS transitions when pieces move rather than instant re-render

---

## Phase 9 — Testing & Infrastructure
*Future*

- [ ] **Unit test suite** (`pytest`): cover ELO calculation, dynamic K-factor, lesson parser (`_parse_lessons`), response parsing in both player backends, `build_quality_summary`, DB operations (upsert, record, query)
- [ ] **JS unit tests**: `extractModelName`, `parseFen`, `uciToSquares`, `renderEvalGraph` — candidate for Vitest or a simple node test script
- [ ] **Mock clients**: fake LM Studio / Anthropic responses for player backend tests; avoid real API calls in CI
- [ ] **Test fixture library**: sample PGNs (short games, draws, resignations), board positions (tactical puzzles, endgames), candidate lists
- [ ] **GitHub Actions CI**: run pytest on every PR; block merge on failure
- [ ] **Coverage reporting**: track which paths are exercised; target critical parsing and ELO logic first

---

## Phase 10 — Qwen & Model-Specific Handling
*Research needed*

- [ ] **Deep Qwen thinking audit**: determine whether LM Studio actually honours `enable_thinking: false` in `extra_body`, or whether the model still thinks regardless; instrument with response timing and token counts
- [ ] **`/no_think` token injection**: Qwen3's documented method to disable thinking is prepending `/no_think` as the first token of the system prompt — implement as a fallback if `enable_thinking: false` is insufficient
- [ ] **Per-model configuration profiles**: a `model_profiles.json` or DB table storing model-specific flags (e.g. `force_no_think: true`, `thinking_budget_tokens: 800`, `max_tokens_override: 2048`) — applied automatically when a matching model ID is detected
- [ ] **Thinking budget control**: when thinking IS enabled, expose a `budget_tokens` setting rather than just a boolean toggle; avoids models spending 10k tokens reasoning about a straightforward recapture
- [ ] **Reasoning extraction**: for models that output `<think>…</think>` blocks, surface the thinking content in the viewer as an expandable section per move rather than discarding it

---

## Phase 11 — Human Play & Advanced Metrics
*Future*

- [ ] **Human vs LLM**: click-on-board move input for human turns; `human` backend in `build_player()`; ELO stored by username; legal move highlighting on square click
- [ ] **Assisted vs blind mode**: toggle whether the human sees Stockfish candidates or plays without hints
- [ ] **Reasoning coherence scoring**: post-move micro-eval — did the model's stated reasoning justify the chosen move? Produces a "reasoning integrity" stat per model; genuinely novel for LLM comparison; requires a small judge model call per move
- [ ] **Stockfish difficulty scaling**: reduce candidate count or depth for human play / weaker models so they're not getting top-10 guidance and still blundering

---

## Phase 12 — Scale & Export
*Future*

- [ ] **Batch / headless mode**: run games without real-time broadcast for fast benchmarking; results written to DB only
- [ ] **Tournament config file** (`tournament.toml`): define players, backends, format, and tutor in one file; coexists with `.env` defaults; makes named matchups replayable
- [ ] **Time control simulation**: per-move timeout; models exceeding budget fall back to top Stockfish candidate and are flagged "timeout" in stats
- [ ] **PGN collection export**: bulk export all games as a single annotated PGN file for external analysis

---

## Phase 13 — Standalone App & Distribution
*Future*

- [ ] **Tauri wrapper**: package the FastAPI + HTML SPA as a native desktop app (Mac/Windows/Linux); Tauri is significantly lighter than Electron — no bundled Chromium; the existing web frontend needs no changes
- [ ] **Python runtime bundling**: bundle the Python backend using PyInstaller or `uv` standalone builds so users don't need a Python install; Stockfish binary included as a sidecar asset
- [ ] **OS-native file dialogs**: replace browser download links with native save-file dialogs for PGN export and DB backup — Tauri's `dialog` plugin handles this
- [ ] **Auto-update**: ship an update manifest; Tauri's updater plugin can pull new releases from GitHub releases on startup
- [ ] **Installer / release packaging**: GitHub Actions workflow to build platform-specific installers (`.dmg`, `.exe`, `.AppImage`) on tag push
- [ ] **App icon & branding**: design a Nimzo app icon; register as a protocol handler so `nimzo://` links can deep-link into specific tournaments or model cards

---

## Open Questions

- **Browser vs standalone**: stay browser-based (zero install friction, easy updates) vs Tauri desktop app (native dialogs, no Python required for end users, distributable to non-technical users) — not mutually exclusive; browser mode can remain the dev/power-user path
- **Model metadata source**: parse filename vs HuggingFace API vs manual sidecar — what's the right default?
- **Lesson compression trigger**: fixed game count, lesson list length threshold, or semantic similarity check?
- **ELO floor/seeding**: start new players at 1200 or seed by model family/size?
- **Tutor async**: lesson generation currently blocks between games; worth making non-blocking?
- **Parallel games in brackets**: run multiple games simultaneously for speed, or keep sequential for simplicity?
- **Qwen `/no_think`**: does it need to be the literal first token, or anywhere in the system prompt?
