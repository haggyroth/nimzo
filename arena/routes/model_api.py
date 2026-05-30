"""
arena/routes/model_api.py — /api/models/* routes, portrait endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, UploadFile

import db as database
import models.portraits as _portraits_module
from analysis import ACHIEVEMENT_CATALOGUE, derive_personality_traits
from models.metadata import get_model_metadata
from models.portraits import generate_portrait, portrait_filename
from providers import CLOUD_PROVIDERS
from arena.state import (
    _PORTRAIT_COOLDOWN_S,
    _PORTRAITS_DIR,
    _DEFAULT_LMSTUDIO_URL,
    _portrait_last_generated,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-model locks for portrait generation (MN-10): prevents two concurrent
# requests for the same model from both passing the cooldown check and both
# calling the paid Gemini API.
_portrait_locks: dict[str, asyncio.Lock] = {}


@router.get("/api/models/{model_id:path}/profile")
async def api_model_profile(model_id: str):
    """Return enriched profile for a model: stats, personality traits, and achievements."""
    profile = await asyncio.to_thread(database.get_model_profile, model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Model not found")
    profile["traits"] = derive_personality_traits(profile)
    profile["achievements"] = [
        {
            "code":  a["code"],
            "times": a["times"],
            **ACHIEVEMENT_CATALOGUE.get(a["code"], {"label": a["code"], "desc": ""}),
        }
        for a in await asyncio.to_thread(database.get_player_achievements, model_id)
    ]
    # Run HF fetch off the event loop so a slow HF response can't stall the UI.
    profile["metadata"] = await asyncio.to_thread(get_model_metadata, model_id)
    # Include portrait URL if already generated
    portrait_path = await asyncio.to_thread(database.get_portrait_path, model_id)
    profile["portrait_url"] = f"/{portrait_path}" if portrait_path else None
    return profile


@router.get("/api/models/{model_id:path}/lesson-effectiveness")
async def api_lesson_effectiveness(model_id: str):
    return await asyncio.to_thread(database.get_lesson_effectiveness, model_id)


@router.get("/api/models/{model_id:path}/coherence")
async def api_coherence_stats(model_id: str):
    """Average reasoning coherence score and timeout rate for a model."""
    return await asyncio.to_thread(database.get_coherence_stats, model_id)


@router.get("/api/models/{model_id:path}/coherence-history")
async def api_coherence_history(model_id: str):
    """Per-game average coherence score for a model, ordered chronologically."""
    return await asyncio.to_thread(database.get_coherence_history, model_id)


@router.get("/api/models/{model_id:path}/openings")
async def api_model_openings(model_id: str):
    """W/D/L breakdown per opening for a model, ordered by games played."""
    return await asyncio.to_thread(database.get_openings_for_model, model_id)


@router.get("/api/models/{model_id:path}/tokens")
async def api_model_tokens(model_id: str):
    """Aggregate token usage for a model (total and per-move averages)."""
    return await asyncio.to_thread(database.get_token_stats, model_id)


@router.get("/api/models/{model_id:path}/quality")
async def api_model_quality(model_id: str):
    """
    Move-quality breakdown for a single model.

    Returns quality counts and rates (0-1), avg candidate rank, avg centipawn
    score, and bad-move rate (mistakes + blunders).  404 if model unknown or
    has no recorded moves.
    """
    stats = await asyncio.to_thread(database.get_player_quality_stats, model_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Model not found or no moves recorded")
    return stats


@router.post("/api/models/{model_id:path}/portrait")
async def api_generate_portrait(model_id: str):
    """
    Generate (or retrieve cached) portrait for a model.

    Returns ``{portrait_url: "/portraits/abc.png"}`` on success,
    ``{portrait_url: null}`` if no API key or generation fails.
    Runs the blocking Imagen call in a thread-pool executor.

    Rate-limited to one generation per model per ``_PORTRAIT_COOLDOWN_S``
    seconds to prevent runaway paid API calls.
    """
    # Reject unknown model IDs — prevents paid API calls for arbitrary ghost IDs
    if not await asyncio.to_thread(database.player_exists, model_id):
        raise HTTPException(status_code=404, detail="Model not found")

    # Return cached path without regenerating
    existing = await asyncio.to_thread(database.get_portrait_path, model_id)
    if existing and Path(existing).exists():
        return {"portrait_url": f"/{existing}"}

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return {"portrait_url": None, "quota_exhausted": False}

    # Quota exhausted — return immediately without hammering the API
    if _portraits_module._quota_exhausted:
        return {"portrait_url": None, "quota_exhausted": True}

    # Per-model lock: serialises concurrent portrait requests so the cooldown
    # check is atomic — two simultaneous callers can't both slip through (MN-10).
    if model_id not in _portrait_locks:
        _portrait_locks[model_id] = asyncio.Lock()
    async with _portrait_locks[model_id]:
        now = time.monotonic()
        last = _portrait_last_generated.get(model_id, 0.0)
        if now - last < _PORTRAIT_COOLDOWN_S:
            remaining = int(_PORTRAIT_COOLDOWN_S - (now - last))
            raise HTTPException(
                status_code=429,
                detail=f"Portrait recently generated; retry in {remaining}s",
            )
        _portrait_last_generated[model_id] = now

    path = await asyncio.to_thread(generate_portrait, model_id, api_key, _PORTRAITS_DIR)

    if path:
        await asyncio.to_thread(database.set_portrait_path, model_id, path)

    quota_exhausted = _portraits_module._quota_exhausted
    return {"portrait_url": f"/{path}" if path else None, "quota_exhausted": quota_exhausted}


@router.post("/api/models/{model_id:path}/portrait/upload")
async def api_upload_portrait(model_id: str, file: UploadFile = File(...)):
    """
    Accept a user-uploaded portrait (PNG / JPEG / WebP, max 2 MB).

    Saves to ``portraits/`` using the same deterministic filename as
    AI-generated portraits, marks the record as ``user_provided=True``
    so automatic Gemini re-generation never overwrites it, and returns
    the public URL.
    """
    _ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
    _MAX_BYTES = 2 * 1024 * 1024   # 2 MB

    if not await asyncio.to_thread(database.player_exists, model_id):
        raise HTTPException(status_code=404, detail="Model not found")

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {content_type!r}. Use PNG, JPEG, or WebP.",
        )

    # Reject oversized uploads early using the Content-Length header before
    # reading the body — avoids buffering a multi-MB payload just to discard
    # it (S-2 in REVIEW.md).  Fall through to the post-read check as a
    # defence-in-depth safety net for clients that omit Content-Length.
    cl = file.size  # FastAPI / Starlette expose this from the Content-Length header
    if cl is not None and cl > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({cl // 1024} KB declared). Maximum is 2 MB.",
        )

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)//1024} KB). Maximum is 2 MB.",
        )

    filename = portrait_filename(model_id)
    dest = _PORTRAITS_DIR / filename
    _PORTRAITS_DIR.mkdir(exist_ok=True)
    dest.write_bytes(data)

    await asyncio.to_thread(database.set_portrait_path, model_id, f"portraits/{filename}", user_provided=True)
    return {"portrait_url": f"/portraits/{filename}", "user_provided": True}


@router.get("/api/models/{model_id_a:path}/h2h/{model_id_b:path}")
async def api_h2h(model_id_a: str, model_id_b: str):
    """Head-to-head record for model_a vs model_b from model_a's perspective."""
    return await asyncio.to_thread(database.get_h2h_record, model_id_a, model_id_b)


@router.get("/api/compare")
async def api_compare(a: str, b: str):
    """
    Full comparison bundle for two models.

    Returns profiles, ELO histories, coherence stats, top openings, and the
    head-to-head record for models *a* and *b* in a single round-trip.
    """
    if not a or not b:
        raise HTTPException(status_code=400, detail="Both 'a' and 'b' query params are required")

    def _gather():
        profile_a  = database.get_model_profile(a)
        profile_b  = database.get_model_profile(b)
        if not profile_a or not profile_b:
            return None
        elo_a      = database.get_elo_history(a)
        elo_b      = database.get_elo_history(b)
        coh_a      = database.get_coherence_stats(a)
        coh_b      = database.get_coherence_stats(b)
        openings_a = database.get_openings_for_model(a)[:5]
        openings_b = database.get_openings_for_model(b)[:5]
        h2h        = database.get_h2h_record(a, b)
        return {
            "a":           {**profile_a, "elo_history": elo_a, "coherence": coh_a, "openings": openings_a},
            "b":           {**profile_b, "elo_history": elo_b, "coherence": coh_b, "openings": openings_b},
            "h2h":         h2h,
        }

    result = await asyncio.to_thread(_gather)
    if result is None:
        raise HTTPException(status_code=404, detail="One or both models not found")
    return result


# Hosts allowed for the /api/models proxy.  Prevents SSRF when the server is
# exposed on a LAN (NIMZO_HOST=0.0.0.0).  Extend via the env var if you run
# LM Studio on a remote host inside your trusted network.
_PROXY_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "localhost", "127.0.0.1", "::1",
    *filter(None, os.environ.get("NIMZO_ALLOWED_MODEL_HOSTS", "").split(",")),
})

# Ports allowed for the /api/models proxy.  None means no explicit port in the
# URL (i.e. the protocol default).  Covers LM Studio (1234/1235) and Ollama
# (11434).  Extend via NIMZO_ALLOWED_MODEL_PORTS (comma-separated integers).
_PROXY_ALLOWED_PORTS: frozenset[int | None] = frozenset({
    None,   # no explicit port — uses protocol default (80 / 443)
    1234, 1235,   # LM Studio primary and secondary instance
    11434,         # Ollama
    *[
        int(p)
        for p in filter(None, os.environ.get("NIMZO_ALLOWED_MODEL_PORTS", "").split(","))
        if p.strip().isdigit()
    ],
})


def _check_proxy_url(url: str) -> None:
    """Raise HTTPException(403) if *url* points outside the host/port allowlists."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().strip("[]")  # strip IPv6 brackets
    port = parsed.port  # None if not explicitly specified
    if host not in _PROXY_ALLOWED_HOSTS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Host {host!r} is not in the proxy allowlist. "
                "Add it to the NIMZO_ALLOWED_MODEL_HOSTS env var (comma-separated) "
                "to permit requests to that host."
            ),
        )
    if port not in _PROXY_ALLOWED_PORTS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Port {port} is not in the proxy allowlist. "
                "Add it to the NIMZO_ALLOWED_MODEL_PORTS env var (comma-separated) "
                "to permit requests to that port."
            ),
        )


@router.get("/api/models")
async def api_models(url: str = _DEFAULT_LMSTUDIO_URL):
    """Proxy GET /models to a local OpenAI-compatible server and return the result."""
    _check_proxy_url(url)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:
            resp = await client.get(f"{url.rstrip('/')}/models")
            return resp.json()
    except Exception as exc:
        return {"data": [], "error": str(exc)}


@router.get("/api/providers")
async def api_providers():
    """
    Return the cloud provider registry with a ``configured`` flag per entry.

    ``configured`` is True when the provider's API key env var is set (non-empty),
    letting the viewer show which providers are ready to use without exposing
    the actual key values.
    """
    return {
        name: {
            "label":      info["label"],
            "base_url":   info["base_url"],
            "models":     info["models"],
            "configured": bool(os.environ.get(info["key_env"])),
        }
        for name, info in CLOUD_PROVIDERS.items()
    }
