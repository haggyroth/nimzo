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

## Phase 4 — Viewer Polish & Quick Wins ✅

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

## Phase 5 — Model Cards & Achievements ✅

- [x] **Model cards**: modal/panel that appears when a model is selected in the UI — displays name, ELO, W/D/L, games played, average move quality, personality summary, and metadata
- [x] **Model metadata strategy**: LM Studio's `/models` returns IDs but not specs; parse from filename conventions (`qwen3-30b-a3b@q4_k_m` → 30B params, Q4_K_M quant)
- [x] **Metadata fields**: parameter count, architecture family, quantization, file size, context length, backend
- [x] **Achievement / badge system**: new `achievements` DB table; conditions computed post-game (e.g. "Flawless Game" — zero blunders, "Comeback King" — won from -5cp deficit, "Theorist" — 10+ book moves before first deviation)
- [x] **Trophy display**: badges shown on model cards, player strips during games, and leaderboard rows
- [x] **Model comparison view**: side-by-side stat comparison of any two models
- [x] **Model profile pictures**: generate a chess grandmaster portrait per model via Google AI Studio (Imagen 3); prompt seeded deterministically from the model ID so the same model always gets the same character; stored in `portraits/` + path in DB; displayed on model cards, comparison view, and player strip avatars during games

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

## Phase 6 — Tournament Brackets ✅
*v6 release*

- [x] **Multi-player arena**: register N models; round-robin and gauntlet formats; PlayerSpec model; dynamic player list in UI
- [x] **Bracket formats**: round-robin (all vs all) and gauntlet (champion vs all challengers); configurable games per pair
- [x] **Bracket visualization**: live standings table in viewer sidebar; updates after every game
- [x] **Sequential scheduling**: `generate_pairings()` produces ordered list; games play one at a time
- [x] **Bracket state persistence**: `tournaments` + `tournament_games` DB tables; survives restart
- [x] **Tournament titles**: 15 deterministic titles assigned from `hash(model_id + format)`; stored in DB
- [x] **Tournament history**: `/api/tournament/history`; shown in viewer sidebar + stats page
- [x] **Seeding**: bracket seeded by current ELO at tournament start; highest-rated model is gauntlet champion
- [x] **Best-of series**: track per-pair wins; series ends early when mathematically decided; series scores shown in standings tooltip

---

## Phase 7 — Smarter Lessons ✅

- [x] **Lesson compression / strategic profile**: every 5 games once 10+ lessons are stored, tutor distils all raw lessons into a strategic profile (2–4 persistent weaknesses, 1–3 consistent strengths); profile replaces the raw list in the system prompt (+ 3 most recent lessons for recency); displayed in model card under "Strategic profile"
- [x] **Opening awareness**: ECO code + opening name passed to lesson prompt — "In the Sicilian Najdorf, your knight retreat on move 14 ignored the standard d5 break"
- [x] **Lesson effectiveness tracking**: `bad_move_rate_before` stored per lesson batch; `get_lesson_effectiveness()` computes avg bad-move rate delta vs next 3 games; ↑↓→ chips shown per lesson in model card; `/api/models/{id}/lesson-effectiveness` endpoint
- [x] **Draw lesson handling**: draws with clean play (no blunders/mistakes) skip lesson generation entirely; draws with errors use a lighter single-bullet prompt

---

## Phase 8 — Customization & Themes ✅
*v8 release*

- [x] **Board themes**: 6 preset color schemes (Wood, Green, Blue, Walnut, Contrast, Midnight) using `--sq-light`/`--sq-dark` CSS custom properties; one-click swatch selection
- [x] **Custom colors**: color picker for light squares, dark squares, and accent color; live preview
- [x] **Piece sets**: Unicode (♔♕♖…) and Letters (K Q R…) variants; body-class-switched CSS for consistent cross-OS rendering
- [x] **Board orientation toggle**: flip board; persists per session; also exposed in Appearance panel
- [x] **Font & typography controls**: Mono (JetBrains Mono) / System (system-ui sans-serif) selector; `--ui-font` CSS variable propagates to all panel inputs and controls
- [x] **Settings persistence**: all appearance prefs stored in `localStorage` under `nimzo_settings`; restored on load
- [x] **Animated piece moves**: 180ms CSS keyframe `pieceArrive` slides the piece in from its source square on each `move` event; offset computed from UCI move coordinates

---

## Phase 9 — Testing & Infrastructure ✅
*v9 release*

- [x] **Unit test suite** (`pytest`): 142 tests across ELO, dynamic K-factor, `_parse_lessons`, response parsing in both player backends, `build_quality_summary`, achievements, model profiles, metadata parsing, and DB operations
- [x] **JS unit tests**: `extractModelName`, `parseFen`, `uciToSquares`, `buildSparkline`, `computeCaptures`, `escHtml` — 45 tests using Node's built-in `node:test` runner (zero npm dependencies); pure functions extracted to `static/viewer_utils.js`; JS test job added to CI
- [x] **Mock clients**: `unittest.mock` + `pytest-mock` for LM Studio and Anthropic player tests; zero real API calls in CI
- [x] **Test fixture library**: `tests/fixtures/pgns.py` (Scholar's mate, Fool's mate, stalemate, midgame resign, opening starts) and `tests/fixtures/positions.py` (FEN strings, candidate builders)
- [x] **GitHub Actions CI**: `.github/workflows/ci.yml` — runs pytest + coverage on every push/PR to main; blocks merge on failure
- [x] **Coverage reporting**: `pytest-cov` + `.coveragerc`; `--cov-report=term-missing` in CI; coverage XML artifact uploaded per run

---

## Phase 10 — Qwen & Model-Specific Handling ✅
*v10 release*

- [x] **Deep Qwen thinking audit**: instrument API calls with elapsed time + token counts; warn to console when `<think>` blocks appear or timing/token heuristics suggest thinking is active despite `enable_thinking=false`
- [x] **`/no_think` token injection**: belt-and-suspenders approach — prepend `/no_think\n` to the system prompt when `no_think_prefix: true` in the model profile and thinking is disabled
- [x] **Per-model configuration profiles**: `model_profiles.json` at project root with match-based profiles (Qwen, DeepSeek, Llama); loaded via `models/model_profiles.py`; controls `no_think_prefix`, `thinking_budget_tokens`, `max_tokens_thinking`, `max_tokens_default`
- [x] **Thinking budget control**: when thinking IS enabled and profile specifies `thinking_budget_tokens`, passed as `thinking_budget` in `extra_body` (LM Studio) or `budget_tokens` in the `thinking` dict (Anthropic)
- [x] **Reasoning extraction**: `<think>…</think>` blocks extracted from raw output, stored in `moves.thinking_content` DB column, broadcast in `move` WS event, and surfaced in viewer as a collapsible "🧠 thinking" section per move card

---

## Phase 11 — Human Play & Advanced Metrics ✅
*v11 release*

- [x] **Human vs LLM**: click-on-board move input for human turns; `human` backend in `build_player()`; ELO stored by username; legal move highlighting on square click
- [x] **Assisted vs blind mode**: toggle whether the human sees Stockfish candidates or plays without hints
- [x] **Reasoning coherence scoring**: post-move micro-eval — did the model's stated reasoning justify the chosen move? Produces a "reasoning integrity" stat per model; genuinely novel for LLM comparison; requires a small judge model call per move
- [x] **Stockfish difficulty scaling**: reduce candidate count or depth for human play / weaker models so they're not getting top-10 guidance and still blundering

---

## Phase 12 — Scale & Export ✅
*v12 release*

- [x] **Batch / headless mode**: run games without real-time broadcast for fast benchmarking; results written to DB only
- [x] **Tournament config file** (`tournament.toml`): define players, backends, format, and tutor in one file; coexists with `.env` defaults; makes named matchups replayable
- [x] **Time control simulation**: per-move timeout; models exceeding budget fall back to top Stockfish candidate and are flagged "timeout" in stats
- [x] **PGN collection export**: bulk export all games as a single annotated PGN file for external analysis

---

## Phase 14 — Board Rendering Upgrade ✅
*v14 release*

- [x] **Migrate to cm-chessboard**: replace the hand-rolled SVG board with [cm-chessboard](https://github.com/shaack/cm-chessboard) — loaded from jsDelivr CDN via dynamic ES module imports
- [x] **Drag-and-drop move input**: replaced click-click human input with native drag-and-drop via cm-chessboard's `enableMoveInput()` handler
- [x] **Legal move markers**: cm-chessboard `autoMarkers: MARKER_TYPE.frame` highlights legal drag sources automatically; last-move squares marked via `MARKER_TYPE.square`
- [x] **Promotion picker**: cm-chessboard handles promotion UI natively; auto-queen fallback preserved
- [x] **Smooth animations**: cm-chessboard handles piece slide animations natively (180ms); removed custom animation code
- [x] **Arrow overlays**: Stockfish candidate arrows drawn on `thinking` events using cm-chessboard's Arrows extension
- [x] **Mobile touch support**: cm-chessboard handles touch events natively; human play works on phones/tablets

---

## Phase 15 — Competitive Depth ✅
*v15 release*

- [x] **Player personality styles**: `style` field in `PlayerConfig` injected into system prompt — `"aggressive"` → prefers open games, sacrifices material for initiative; `"positional"` → favours closed structures, outpost control; `"defensive"` → consolidates before attacking, trades pieces when ahead
- [x] **Move-quality analytics endpoint**: `GET /api/models/{model_id}/quality` returning blunder rate, avg centipawn loss, avg candidate rank, and inaccuracy rate
- [x] **Adaptive difficulty**: dynamically adjusts `candidate_count` based on a model's rolling performance — weaker models get more candidates; stronger models get fewer; configurable `_ADAPT_WIN_RATE_HIGH/LOW` thresholds (0.65/0.35)

---

## Phase 16 — Cloud Backends & Code Health ✅

- [x] **Cloud provider registry** (`providers.py`): OpenAI, DeepSeek, Qwen (Dashscope), Google Gemini, xAI — each usable as player, tutor, or judge; API keys drawn from env vars
- [x] **`/api/providers` endpoint**: returns registry with `configured: bool` per provider; viewer populates backend dropdowns dynamically
- [x] **Portrait rate limiting**: 60s per-model cooldown; HTTP 429 on rapid re-requests; quota-exhausted detection skips retries for the session when free tier is drained
- [x] **JS constant extraction**: `DEFAULT_LMSTUDIO_URL` extracted from 4+ hardcoded occurrences in viewer.js
- [x] **Docstring sweep**: PEP 257 docstrings added to all previously undocumented public functions and classes across 11 files
- [x] **Frontend asset consolidation**: `js/viewer_utils.js` → `static/viewer_utils.js`; `/js` StaticFiles mount removed

---

## Phase 17 — Theme Expansion & App Identity ✅

### Goals
Extend the appearance system beyond board colors to full UI color schemes, add a light mode, and give the app a proper visual identity.

- [x] **Terminal color scheme presets**: Solarized Dark, Solarized Light, Catppuccin Mocha, Catppuccin Latte, Nord, Dracula — palette swatches in the Appearance panel; each drives the full set of UI CSS variables.
- [x] **Light/dark mode toggle**: ☀️/🌙 button in the header; each theme tagged `dark: bool`; `_UI_THEME_PAIRS` maps each theme to its closest light/dark partner.
- [x] **Theme import**: `terminalcolors.com` JSON import — maps 16-color ANSI palette to Nimzo's CSS variables; saved as a custom "Imported" swatch.
- [x] **Favicon**: SVG chess-knight favicon (`static/favicon.svg`) linked in `viewer.html`; social card images already present in `.github/`.

---

## Phase 18 — Layout & Visual Customization ✅

### Goals
Give users meaningful control over the page layout and let them bring in their own visual assets.

- [x] **Collapsible main panels**: ⊢/⊣ toggle buttons in the header fold the center (analysis) and right (controls) columns to 24 px; board area reflows via CSS grid-template-columns; state persisted to `localStorage`.
- [x] **Graveyard expansion**: captured-piece display moved from inline player-strip into dedicated `.player-graveyard` rows above/below the board; 14 px glyphs with letter-spacing for compact display; material imbalance score preserved.
- [x] **Background image upload**: file input in Appearance panel; base64 stored in separate `nimzo_board_bg` localStorage key; opacity slider (0–100%); "Clear image" button; applied via `::before` pseudo-element on `.board-col`.
- [ ] **Custom piece PNG import**: deferred — cm-chessboard SVG sprite architecture makes clean per-piece PNG overlays complex; moved to [Future Considerations](#future-considerations).

---

## Phase 19 — Model Identity & Cards ✅

### Goals
Rich per-model stat cards surfaced inline during games and in the leaderboard; smarter metadata from HuggingFace; user-controlled portrait images.

- [x] **Toggleable model stat cards**: collapsible panel above each player strip (toggle with a ▲/▼ chevron or click on the player name). Card shows: ELO + sparkline, W/D/L record, blunder rate, avg move quality, avg candidate deviation, personality style badge, current series score vs opponent, all-time head-to-head vs this specific opponent. "Sports chyron" aesthetic — dense horizontal stat row, no scrolling.
- [x] **Current-tournament stats injection**: while a bracket tournament is running, the card also shows the model's position in the standings, points, and games remaining — updated via `game_over` WS events.
- [x] **HuggingFace metadata integration**: `GET https://huggingface.co/api/models/{model_id}` for models that look like HF paths (contain `/`); parse `safetensors.total` for size, `cardData.language` / `tags` for family confirmation; cache results in the existing `hf_metadata_cache.json` with a 24h TTL. Falls back to filename-parse for non-HF IDs.
- [x] **User photo upload for model portraits**: file input (accepts PNG/JPEG/WebP, max 2 MB) in the model card or portrait area; uploaded to `POST /api/models/{id}/portrait/upload` (multipart); server saves to `portraits/` with the same `portrait_filename()` hash path; marks record as `user_provided=True` in DB so it isn't overwritten by Gemini auto-generation. UI shows a "📷 Upload photo" button and a "↺ Regenerate AI portrait" button.
- [x] **Portrait quota-exhaustion handling**: once all Gemini models return 429 with free-tier limit exhausted, set a session-level flag and display a "Portrait generation unavailable (API quota)" notice in the UI rather than silent repeated failures in the console.

### Implementation notes
- HuggingFace API calls run in `asyncio.to_thread()` and are cached locally; no key required for public models.
- Portrait upload endpoint: `POST /api/models/{id}/portrait/upload` with `multipart/form-data`; validates MIME type + file size; stores alongside Gemini-generated portraits in the same directory.
- Stat cards are pure frontend (all data already available via existing `/api/models/{id}` endpoint); no new backend needed beyond the upload endpoint.
- `user_provided` flag in `players` table requires a schema migration (additive `ALTER TABLE`).

---

## Phase 20 — Gameplay Rules & Blind Mode
*Next*

### Goals
Give more control over game rules and let models play their opening moves from their own chess knowledge rather than always following Stockfish's guidance.

- [x] **Opening blind mode**: new `blind_opening_moves: int` setting per player (default: 0; UI toggle in player config). For the first N full moves (each player), Stockfish candidates are withheld — the model receives only the board FEN and game PGN and must supply a `MOVE:` UCI response from its own knowledge. Parse via the same 4-tier fallback; default to a random legal move if parsing fails in blind mode (not Stockfish's top pick, since that defeats the purpose). Each model's opening repertoire becomes a genuine expression of its training.
- [x] **Turn cap / move limit draw**: new `max_moves: int` setting (default: 500 half-moves = 250 per side; configurable in UI and TOML). When `board.ply() >= max_moves`, the game is declared a draw with termination `"move limit reached"`. Displayed in the game-over overlay and stored in the `termination` column.
- [x] **Blind mode toggle in UI**: checkbox in each player's config card; also supported in `tournament.toml` via `blind_opening_moves = 3`; shown as a badge on the player strip during the opening phase.
- [x] **Forced opening prefix**: supply a PGN move sequence in the TOML config (`opening_pgn = "1. e4 e5 2. Nf3 Nc6"`); both models are stepped through those moves automatically before guided play begins. Lets you study how models handle specific structures they were trained on (Sicilian, King's Indian, etc.) without relying on blind-mode chance to reach those positions.

### Implementation notes
- `blind_opening_moves` is added to `PlayerConfig` (default 0 = always use Stockfish candidates); `game.py`'s `play_game()` checks `board.fullmove_number <= player.config.blind_opening_moves` to decide whether to pass candidates.
- The prompt `build_prompt()` in `base.py` gets a `has_candidates: bool` argument; when False, the candidates section is replaced with "Play your best opening move from your chess knowledge."
- Turn cap is a single `if board.ply() >= game_config.max_moves: break` in the main game loop; the result is set to `"1/2-1/2"` with the special termination string.
- Forced opening prefix: `chess.Board` replays the supplied PGN moves before the main loop; the viewer shows those moves as greyed-out "book" moves in the move history.
- Both settings are surfaced in the TOML schema via `config_loader.py`.

---

## Phase 21 — Tutor UX & Learning Improvements ✅

### Goals
Make lesson generation visible to the viewer, improve compression quality, and fix ELO seeding for new players.

- [x] **Lesson generation splash screen**: when `generate_lessons()` begins, broadcast a `lesson_generating` WS event (`{tutor_model}`); the viewer shows a centered overlay with a chess-piece spinner, the tutor model name, and "Generating lessons…" When `lessons_saved` is broadcast, the overlay dismisses and the lessons panel updates.
- [x] **Jaccard similarity lesson deduplication**: before saving a new lesson, check it against all existing lessons via word-overlap Jaccard similarity (threshold 0.75). Near-duplicates are skipped with a console notice. Full compression still triggers at 10+ lessons.
- [x] **ELO seeding improvements**: `K_PROVISIONAL = 40` for the first 5 games (new tier added to `dynamic_k_factor()`), then drops to the existing K=32/24/16 schedule. A small size-based starting offset (`family_elo_prior()`) is applied to brand-new players — e.g. 70B models start at +12, 2B models at −10 — and washes out within ~8 games.

---

## Open Questions

*Resolved questions are struck through and answered below.*

~~**Browser vs standalone**~~: keep browser as the primary interface; Tauri packaging moves to [Future Considerations](#future-considerations).

~~**Model metadata source**~~: HuggingFace API for models with a `/` in their ID (e.g. `mistralai/ministral-3-3b`); filename parsing for local LM Studio IDs. Implemented in Phase 19.

~~**Lesson compression trigger**~~: semantic similarity check (Jaccard ≥ 0.75 for deduplication) + 10-lesson threshold for full compression. Implemented in Phase 21.

~~**ELO floor/seeding**~~: start at 1200 with `K_PROVISIONAL = 40` for first 5 games; model-family prior ±15 ELO that decays within ~8 games. Implemented in Phase 21.

~~**Tutor async**~~: keep blocking between games for now; non-blocking tutor is a [Future Consideration](#future-considerations).

~~**Parallel games in brackets**~~: keep sequential for simplicity; parallel scheduling is a [Future Consideration](#future-considerations).

~~**Qwen `/no_think`**~~: addressed in Phase 10. Belt-and-suspenders approach: `no_think_prefix` in profile prepends `/no_think\n` and also sets `enable_thinking=false` in `extra_body`.

---

### Open Questions — New

- **Custom piece PNGs**: cm-chessboard's SVG sprite architecture makes clean per-piece PNG overlays complex; deferred to Future Considerations.
- **Turn cap**: introduce a draw rule at 250 moves per player (500 half-moves)? Addressed in Phase 20.

---

## Phase 22 — Async Database (aiosqlite) ✅

### Goals
All `database.*` calls currently run synchronous SQLite queries on the asyncio event loop, blocking it briefly on every game write, leaderboard poll, and stats request. At tournament scale (many games, large stats tables) this creates latency spikes visible to connected WebSocket clients. Migrating to `aiosqlite` or wrapping every call in `asyncio.to_thread()` eliminates the blocking.

### Approach options

| Approach | Effort | Notes |
|---|---|---|
| `asyncio.to_thread()` wrappers | Low — one decorator per call-site | No schema changes; no new dep; connection pool unchanged; easiest to review |
| `aiosqlite` migration | Medium — rewrites all `db.py` functions to `async def` | Cleaner long-term; requires updating every call site in game.py / routes; adds `aiosqlite` to requirements.txt |
| SQLAlchemy async | High | Overkill for SQLite-only project; not recommended |

**Recommended**: `asyncio.to_thread()` wrappers on the call sites in `arena/routes/*` and `game.py` — preserves the existing synchronous `db.py` API (no churn on tests) while unblocking the event loop. Can be followed by a full `aiosqlite` rewrite in a later phase if profiling shows it's worthwhile.

### Scope

- Wrap all `database.*` calls in `game.py` and `arena/routes/` with `await asyncio.to_thread(database.fn, ...args)`
- No changes to `db.py` function signatures
- Update tests where relevant (calls that were sync become async)
- Benchmark: measure average game-loop wall time before/after with `time.perf_counter()` around the write block

---

## Phase 23 — Analytics Depth

### Goals
Surface the data that already exists in the DB but isn't yet visualised, and add the one missing dimension (move latency) that requires a small instrumentation change.

- [x] **Move latency tracking**: record wall-clock time per move — `time.perf_counter()` around each `choose_move()` call; store in a new `moves.elapsed_ms` column. Surfaces inference speed vs quality tradeoffs per model; shown in move cards and as an aggregate stat ("avg ms/move") in the model card and leaderboard. A genuinely novel LLM comparison axis.
- [x] **Opening repertoire stats**: store the ECO code and opening name per game (python-chess can derive from PGN; already passed to the lesson prompt). Add a `games.eco_code` + `games.opening_name` column. New `/api/models/{id}/openings` endpoint returns win/draw/loss breakdown per opening family. Shown in the model card as a "Favourite openings" table.
- [x] **Reasoning coherence trend**: coherence scores are stored per move but there's no longitudinal view. Add a per-game average coherence score and plot it as a sparkline in the model card alongside the ELO sparkline. Shows whether a model's reasoning integrity improves after lessons or degrades under context pressure.
- [x] **Lichess analysis link**: "Open in Lichess ↗" button in the game-over overlay and game history panel. Constructs `https://lichess.org/paste?pgn=<encoded-pgn>` — one URL parameter, zero backend work. Lets players instantly deep-dive any game in Lichess's analysis board.
- [x] **Shareable game URL**: `/watch/<game_id>` route that serves the viewer pre-seeded to a specific completed game in replay mode. Makes it easy to link a notable game without the recipient needing to find it in the history panel.

### Implementation notes
- `elapsed_ms`: nullable INTEGER column added via `_add_column_if_missing`; timer wraps the `await player.choose_move(...)` call in `game.py`; broadcast in the `move` WS event.
- ECO lookup: `chess.pgn.Game` exposes `headers["ECO"]` and `headers["Opening"]` after calling `chess.polyglot` or the eco lookup in python-chess; store on `record_game()`.
- Coherence trend: compute `AVG(coherence_score)` per game in a new DB query; no new columns needed.
- `/watch/<game_id>`: serve `viewer.html` with a `?game=<id>` query param; JS detects it and immediately enters replay mode for that game on load.

---

## Phase 24 — Tournament Formats & Scheduling

### Goals
Add the elimination bracket format that rounds out the tournament system, a puzzle gauntlet for direct capability benchmarking, handicap matches for cross-tier comparisons, and scheduled/queued tournament runs.

- [ ] **Elimination bracket**: single-elimination (and optionally double-elimination) format alongside round-robin and gauntlet. `generate_pairings()` produces a bracket tree; `compute_standings()` tracks advancement. Winner overlay shows the bracket path. Seeded by ELO at tournament start.
- [ ] **Puzzle gauntlet mode**: feed models a curated set of standard positions (mate-in-2s, endgame studies, tactical puzzles) from a `positions.toml` file instead of full games. Each model gets the same position and the same candidate list; score is fraction of puzzles solved (correct move chosen) and average candidate rank on near-misses. Bypasses ELO noise — a direct capability benchmark. Very fast to run (no full games).
- [x] **Handicap matches**: `candidate_count` can be set asymmetrically per player for a single match — e.g. weaker model sees 8 candidates, stronger model sees 3. Configurable in the UI per-player or via TOML `candidate_count` under `[white]`/`[black]`. Makes cross-tier matchups competitive and lets you find the "fair" candidate split between two models.
- [ ] **Scheduled / queued tournaments**: `run_at` field in the TOML config (ISO datetime or `+Nh` offset). The arena accepts the config, parks it in a queue, and starts it at the specified time. Enables "start this overnight benchmark at 2am" workflows without leaving a terminal session open. Queued tournaments shown in the UI with a countdown.

### Implementation notes
- Elimination bracket: add `"elimination"` to the `format` enum in `TournamentStartConfig`; `generate_pairings()` returns first-round pairs; after each game `advance_bracket()` updates a `bracket_tree` stored in `tournaments.bracket_json` (JSON column).
- Puzzle gauntlet: `positions.toml` schema — `[[puzzle]] fen = "..." solution_uci = "e2e4" description = "..."`. Game loop variant: one move per position, no board advancement, score logged to a new `puzzle_results` table.
- Scheduled tournaments: `apscheduler` (already in FastAPI ecosystem) or a simple `asyncio.sleep(delta)` task registered on config upload; stored in a `scheduled_tournaments` DB table so it survives restart.

---

## Future Considerations

Items that are well-defined but deferred due to complexity, scope, or dependencies on earlier phases.

### Standalone App & Distribution
*(originally Phase 13)*

- **Tauri wrapper**: package the FastAPI + HTML SPA as a native desktop app (Mac/Windows/Linux); Tauri is significantly lighter than Electron — no bundled Chromium; the existing web frontend needs no changes
- **Python runtime bundling**: bundle the Python backend using PyInstaller or `uv` standalone builds so users don't need a Python install; Stockfish binary included as a sidecar asset
- **OS-native file dialogs**: replace browser download links with native save-file dialogs for PGN export and DB backup — Tauri's `dialog` plugin handles this
- **Auto-update**: ship an update manifest; Tauri's updater plugin can pull new releases from GitHub releases on startup
- **Installer / release packaging**: GitHub Actions workflow to build platform-specific installers (`.dmg`, `.exe`, `.AppImage`) on tag push
- **App icon & branding**: design a Nimzo app icon; register as a protocol handler so `nimzo://` links can deep-link into specific tournaments or model cards

### Other Deferred Items

- **Engine-free mode**: remove Stockfish from the loop entirely — models generate their own UCI move from the FEN + PGN with no candidate list. Evaluated afterward by Stockfish for quality scoring. Tests raw chess ability rather than candidate-selection ability; a genuinely different capability dimension from guided mode. Requires a new prompt variant, a fallback for illegal-move responses (re-prompt up to 3×, then random legal move), and careful framing so models don't treat it as a trick question. Deferred because guided mode is Nimzo's core differentiator — engine-free is a separate product mode.
- **Custom piece PNG import**: file upload (12 files: K Q R B N P × 2 colors); cm-chessboard re-renders via SVG sprites — a `MutationObserver` + CSS `background-image` overlay approach is workable but fiddly; deferred from Phase 18
- **Non-blocking tutor**: move lesson generation to a background task so the next game starts immediately; broadcast `lesson_generating` / `lessons_saved` WS events while the game runs (partial overlap with Phase 21's splash screen)
- **Parallel bracket games**: run simultaneous games in a bracket round for speed; requires scoped `_state` per game, multiple Stockfish engine instances, and careful WebSocket multiplexing
- **arena.py code split**: at 1600+ lines, splitting into `arena/api.py` (HTTP/WS endpoints), `arena/runners.py` (game loop, tournament runners), and `arena/cli.py` (argparse + entry point) would significantly improve navigability
- **Structured logging**: replace `print(...)` throughout with Python's `logging` module (levels: DEBUG/INFO/WARNING/ERROR); enables log-level filtering and log file output without changing any call sites
- **aiosqlite / thread isolation**: promoted to Phase 22 above.
