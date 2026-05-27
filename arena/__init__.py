"""
arena — Nimzo FastAPI server package.

Import order is critical for the arena ↔ game.py circular import:

  1. State symbols FIRST — game.py reads these via `import arena as _arena`
  2. App object (no game.py dep)
  3. Routers — routes/tournament.py imports game.py which does `import arena`
     By this point arena.broadcast etc. are already on the package object.
  4. Re-export symbols that tests import directly from `arena`
"""

from __future__ import annotations

# ── 1. State symbols — must come before anything that imports game.py ─────
# `name as name` syntax marks these as intentional re-exports (suppresses F401)
from arena.state import (          # noqa: E402
    broadcast as broadcast,
    _state as _state,
    _pause_event as _pause_event,
    _stop as _stop,                          # mutable dict {"requested": bool}
    _mode as _mode,                          # mutable dict {"headless": bool}
    TournamentAborted as TournamentAborted,
    _active_human_players as _active_human_players,
    _connected_clients as _connected_clients,
    _tournament_task as _tournament_task,
    _cli_config as _cli_config,
    _DEFAULT_PORT as _DEFAULT_PORT,
    _DEFAULT_LMSTUDIO_URL as _DEFAULT_LMSTUDIO_URL,
    _DEFAULT_LMSTUDIO_URL_2 as _DEFAULT_LMSTUDIO_URL_2,
    _PORTRAIT_COOLDOWN_S as _PORTRAIT_COOLDOWN_S,
    _PORTRAITS_DIR as _PORTRAITS_DIR,
    _portrait_last_generated as _portrait_last_generated,
)

# ── 2. App object (no game.py dep) ────────────────────────────────────────
from arena.app import app          # noqa: E402

# ── 3. Routers — tournament.py transitively imports game.py ──────────────
from arena.routes import games, model_api, stats   # noqa: E402
from arena.routes import tournament as _tr         # noqa: E402
app.include_router(games.router)
app.include_router(model_api.router)
app.include_router(stats.router)
app.include_router(_tr.router)

# ── 4. Re-exports that tests use ──────────────────────────────────────────
from game import play_game                           # noqa: E402, F401
from arena.routes.games import _build_game_pgn       # noqa: E402, F401
from arena.models import (                           # noqa: E402, F401
    PlayerSpec,
    TournamentStartConfig,
    HumanMoveRequest,
)
