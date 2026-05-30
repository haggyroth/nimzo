# Nimzo Roadmap

Items are organized into four phases by dependency and complexity. Each phase is designed to ship as one or two focused PRs.

---

## Phase 1 — Polish & Visibility

Small, high-ROI changes that improve the experience on every session.

- [x] **Reasoning expand/collapse** — move cards show first 3 lines; `▾ more` toggle reveals full reasoning
- [x] **localStorage form persistence** — match setup (models, names, game count, tutor/judge) survives page reloads
- [x] **Eval bar visibility** — stronger SVG fill opacities, 2px line, taller canvas; `analysis-section` gets `flex-shrink:0`
- [x] **Full reasoning in replay modal** — the per-move detail panel in the replay modal should include the full reasoning string
- [x] **Auto-collapse Configure on match start** — after clicking ▶ START MATCH, collapse Configure and expand Results so progress is visible without scrolling
- [x] **Keyboard shortcuts** — Space = pause/resume, `F` = flip board, `←/→` = replay modal step navigation

---

## Phase 2 — Gameplay & Feedback

Features that directly improve the live game experience.

- [x] **Candidate arrow rank-coding** — color board arrows by rank during thinking: gold = #1, silver = #2, dimmer for #3–5
- [x] **Live elapsed timer** — running `⌚ Xs` counter in the player chyron while a model is thinking (not just after the move)
- [x] **Timeout prominence** — ⏱ banner + distinct card border when a model times out, instead of just a chip
- [x] **Human player click-to-move** — use the existing `cm-chessboard` input event system to accept moves by clicking board squares instead of requiring UCI notation
- [x] **Coherence trend sparkline** — coherence score sparkline in the player chyron alongside the existing quality sparkline (uses `renderSparkline` in `viewer_utils.js`)

---

## Phase 3 — Analysis & History

Deeper post-game insight without requiring external tools.

- [ ] **Per-game Stockfish annotation** — after a game ends, re-run the PGN at depth 20 and store blunder/mistake/inaccuracy annotations as a second quality layer; surface in the replay modal
- [ ] **Opening explorer** — "Opening Explorer" section in Results: ECO codes each model plays, win rate by opening, from stored game PGNs
- [ ] **PGN export from live view** — one-click download of the current game PGN from the header (not just from the history table)
- [ ] **Replay modal eval bar** — show stored per-move centipawn scores as a mini eval bar in the replay modal's move strip
- [ ] **Puzzle gauntlet results page** — full results for puzzle gauntlet mode: solve rate by difficulty, time-to-solve distribution, model comparison

---

## Phase 4 — Platform & Scale

Bigger features for power users and long-running deployments.

- [ ] **ELO ladder / auto-scheduler** — round-robin scheduler that auto-queues matchups between all registered players and continuously updates ratings without manual setup
- [ ] **Model parameter sliders** — live temperature and candidate count controls, effective from the next game without restarting
- [ ] **Concurrent games** — run 2–4 games in parallel (separate boards, separate WebSocket channels) for faster overnight ranking
- [ ] **Cost/token tracking** — for cloud backends, track token counts per move and display estimated cost-per-game in the model card modal
- [ ] **Reasoning dataset export** — `/api/export/reasoning-dataset` emitting JSONL with `(fen, candidates, chosen_move, quality, reasoning)` for fine-tuning or research
- [ ] **Spectator URL** — `?spectate=true` strips the control panel for a clean read-only board + history, embeddable or shareable
- [ ] **Lichess integration** — fetch human game PGNs as opening lines, or let a model play rated games on Lichess via the board API

---

## Completed

- [x] CSS polish — section headers legible (10px, `--text-mid`), Start button gold at rest
- [x] Progressive disclosure in setup forms — advanced options behind `<details>`
- [x] Configure/Results tab split + lessons auto-surfacing
- [x] Configure/Results as independent collapsible groups + font/size consistency audit
- [x] Markdown rendering in reasoning text (`**bold**` → `<strong>`)
- [x] Styled abort confirmation modal
- [x] Empty model dropdown warning
- [x] Init-time backend hook for correct initial UI state
- [x] Eval bar SVG viewBox corrected to match 56px CSS height
- [x] Reasoning expand/collapse DOM-timing fix — prepend card before measuring scrollHeight
