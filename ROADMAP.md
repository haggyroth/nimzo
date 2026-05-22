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

- [x] Centipawn evaluation graph: live SVG sparkline in center panel, updates each move
- [x] Collapsible right-panel sections (Tournament / Leaderboard / Lessons / Recent Games)
- [x] Default games 10 → 1 for quick test runs
- [x] Black player URL defaults to `localhost:1234` (same instance, avoids confusion)
- [x] `score_cp` now correctly written to moves table (was always `null`)
- [ ] **ELO trajectory sparkline** per player in the leaderboard panel
- [ ] **Game replay**: click a past game in the history panel to step through moves
- [ ] **Annotated PGN export**: reasoning as `{ }` comments, quality as `?/??/!/!!` glyphs — reviewable in Lichess/any GUI
- [ ] **Stats page** (`/stats`): head-to-head records, win rate by color, avg move quality per model, ELO chart over time
- [ ] **Move quality heatmap**: per-player quality breakdown across all games

---

## Phase 4 — Smarter Lessons
*Next*

- [ ] **Lesson compression/condensation**: every N games, ask the tutor to merge the raw lesson list into a distilled "strategic profile" of 5–8 principles per model — prevents context bloat and keeps lessons from repeating
- [ ] **Opening book awareness**: pass the ECO code (python-chess can derive it from PGN) to the lesson prompt so the coach can contextualize mistakes within the specific opening structure played
- [ ] **Lesson effectiveness tracking**: correlate lesson topics with subsequent quality improvements to measure whether coaching is working

---

## Phase 5 — Tournament Formats
*Future*

- [ ] **Round-robin**: register N players, auto-schedule all pairings
- [ ] **Gauntlet**: one champion plays all challengers in sequence
- [ ] **Best-of series**: track set scores, not just ELO, for a more dramatic narrative
- [ ] **Tournament format flag**: `--format round_robin|gauntlet|series`

---

## Phase 6 — Human Play & Advanced Metrics
*Future*

- [ ] **Human vs LLM**: click-on-board UI for human moves; `human` backend type in `build_player()`; ELO stored by username; optional assisted (see candidates) vs blind mode
- [ ] **Reasoning coherence scoring**: post-move micro-eval "did the stated reasoning justify the chosen move?" — produces a "reasoning integrity" stat per model, genuinely novel for LLM comparison
- [ ] **Per-move reasoning quality** via a small judge model (Haiku): flags cases where a model says one thing and does another
- [ ] **Stockfish difficulty scaling**: reduce candidate count (top 3 vs 5) or candidate depth for weaker models / human play

---

## Phase 7 — Infrastructure
*Future*

- [ ] **Time control simulation**: per-move timeout; models that exceed budget fall back to top Stockfish candidate, flagged as "timeout" in stats
- [ ] **Tournament config file** (`tournament.toml`): define players, backends, format in one file; coexists with `.env` defaults
- [ ] **Batch/headless mode**: run games without real-time broadcast for fast benchmarking

---

## Open Questions

- **Lesson deduplication**: when should compression trigger — fixed game count, lesson list length, or semantic similarity threshold?
- **ELO floor/seeding**: should new players start at 1200 or be seeded by model size/family?
- **Tutor async**: lesson generation currently blocks between games; worth making non-blocking so the next game starts sooner?
- **Human guided vs blind**: do humans see Stockfish candidates? Both modes are interesting for different reasons.
- **Draw lessons**: games that end in draws produce less clear coaching signal — should they use a lighter lesson prompt or be skipped?
