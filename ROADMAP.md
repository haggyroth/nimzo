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
*Current release*

- [x] **Both players receive lessons** after every game (not just the loser)
- [x] **Structured lessons**: separate "areas to improve" + "strengths" sections, injected into system prompt with context labels
- [x] **Configurable tutor model**: any LM Studio / Ollama endpoint or Anthropic cloud; disabled gracefully if no model set
- [x] **Dynamic K-factor**: ELO volatility decays as games accumulate (K=32 → 24 → 16)
- [x] **Thinking mode fixed**: Qwen3 and other reasoning models now correctly enable extended thinking via `enable_thinking: true`
- [x] **Robust response parsing**: 4-tier fallback chain (MOVE field → CHOICE field → any UCI in text → Stockfish top pick)
- [x] **FastAPI server**: viewer served at `http://localhost:8765`, REST API for tournament control
- [x] **Tournament control UI**: configure models, start/pause/resume/stop from the browser
- [x] **Leaderboard panel**: live W/D/L standings, auto-refreshes
- [x] **Lessons panel**: per-player improve/strength cards shown after each game
- [x] **Model discovery**: fetch available models from any LM Studio instance via the UI
- [x] **ELO history query**: `get_elo_history()` available for future charting

---

## Phase 3 — Analytics & Polish
*Next*

- [ ] **ELO trajectory chart**: sparkline per player in the leaderboard panel
- [ ] **Game replay**: click a game in history to step through moves on the board
- [ ] **Move distribution heatmap**: per-player quality breakdown across all games
- [ ] **Candidate selection analysis**: how often each model deviates from Stockfish's top pick, by quality tier
- [ ] **Lesson effectiveness tracking**: correlate lesson topics with subsequent game improvement
- [ ] **Export**: download PGN or CSV of all games
- [ ] **Rematch button**: one-click rematch from the game-over overlay with colors swapped

---

## Phase 4 — Tournament Formats
*Future*

- [ ] **Round-robin tournaments**: register N players, auto-schedule all pairings
- [ ] **Swiss pairings**: pair players by current standing each round
- [ ] **Time controls**: per-move timeout with auto-fallback to Stockfish top pick
- [ ] **Handicap mode**: stronger model plays without seeing the top-ranked candidate
- [ ] **Spectator bracket view**: tournament tree visualization

---

## Phase 5 — Backends & Integrations
*Future*

- [ ] **Ollama backend**: native support (currently works via the LM Studio OpenAI-compat path)
- [ ] **vLLM / LocalAI**: additional OpenAI-compatible server support
- [ ] **Batch evaluation**: run games faster without real-time broadcast for benchmarking
- [ ] **Opening book injection**: seed games from specific ECO codes to test model knowledge
- [ ] **Stockfish skill levels**: use SF skill 0–20 as a calibration opponent

---

## Open Questions

- **Lesson deduplication**: avoid re-teaching the same lesson many games in a row; needs semantic similarity check or recency decay
- **ELO floor**: should new players start at 1200 or be seeded based on model size/family?
- **Tutor quality**: larger tutor model → better lessons, but slower after-game processing; worth making async / non-blocking?
- **Draw handling**: many games end in draws; lesson generation for draws is less informative — should draws use a lighter lesson prompt?
