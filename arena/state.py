"""
arena/state.py — Shared mutable state, constants, broadcast(), TournamentAborted.

All other arena sub-modules import from here.  game.py also accesses these
via `import arena as _arena` (the package), which re-exports them from
arena/__init__.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────
_DEFAULT_PORT           = 8765
_DEFAULT_LMSTUDIO_URL   = "http://localhost:1234/v1"
_DEFAULT_LMSTUDIO_URL_2 = "http://localhost:1235/v1"  # second LM Studio instance

# Per-model portrait generation cooldown (seconds)
_PORTRAIT_COOLDOWN_S = 60.0

# Portraits dir anchored to repo root regardless of CWD
_PORTRAITS_DIR = Path(__file__).parent.parent / "portraits"
_PORTRAITS_DIR.mkdir(exist_ok=True)

# ── Global tournament state ───────────────────────────────────────────────

_connected_clients: set[WebSocket] = set()
_tournament_task: asyncio.Task | None = None
_pause_event: asyncio.Event = asyncio.Event()
_pause_event.set()   # set = running (not paused)
_stop_requested: bool = False

_state: dict = {
    "status": "idle",       # idle | running | paused | stopping | stopped
    "game_number": 0,
    "total_games": 0,
    "white": None,
    "black": None,
    "white_elo": None,
    "black_elo": None,
    # Human-play flags
    "white_is_human": False,
    "black_is_human": False,
    "human_assisted": True,
    # Tournament-mode fields (None in 2-player match mode)
    "format": None,           # "round_robin" | "gauntlet" | "match"
    "standings": None,        # list[dict] or None
    "tournament_id": None,
}

# Set from CLI args before server start; triggers auto-start in lifespan
_cli_config: "TournamentStartConfig | None" = None  # noqa: F821 — forward ref

# Headless mode: skip WebSocket server, remove per-move delays
_headless: bool = False

# Active human player registry — keyed by "white" or "black"
_active_human_players: dict = {}

# Per-model portrait generation cooldown tracker: model_id → epoch time
_portrait_last_generated: dict[str, float] = {}


# ── Tournament abort signal ───────────────────────────────────────────────

class TournamentAborted(Exception):
    pass


# ── Broadcast ────────────────────────────────────────────────────────────

async def broadcast(event: dict):
    """Serialise ``event`` to JSON and send it to every connected WebSocket client."""
    if _headless or not _connected_clients:
        return
    msg = json.dumps(event)
    dead = set()
    for ws in list(_connected_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connected_clients.discard(ws)
