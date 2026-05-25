"""
Per-model configuration profile loader.

Profiles live in model_profiles.json at the project root.  Matching is
case-insensitive substring of model_id — first match wins.

Usage::

    from models.model_profiles import get_profile

    p = get_profile("qwen3-30b-a3b@q4_k_m")
    # p.no_think_prefix      → True
    # p.thinking_budget_tokens → 1024
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ModelProfile:
    match: str                            # Substring matched against model_id (case-insensitive)
    description: str = ""
    # Thinking control
    no_think_prefix: bool = False         # Prepend /no_think to system prompt when thinking disabled
    thinking_budget_tokens: int = 0       # Token budget passed to model when thinking IS enabled (0 = no budget hint)
    # Token limits
    max_tokens_thinking: int = 2048       # max_tokens when thinking enabled
    max_tokens_default: int = 512         # max_tokens when thinking disabled


_PROFILES: list[ModelProfile] | None = None


def _load() -> list[ModelProfile]:
    global _PROFILES
    if _PROFILES is not None:
        return _PROFILES
    path = Path(__file__).parent.parent / "model_profiles.json"
    if not path.exists():
        _PROFILES = []
        return _PROFILES
    data = json.loads(path.read_text())
    _PROFILES = [
        ModelProfile(**{k: v for k, v in p.items() if not k.startswith("_")})
        for p in data.get("profiles", [])
    ]
    return _PROFILES


def get_profile(model_id: str) -> Optional[ModelProfile]:
    """Return the first profile whose match string is found in model_id, or None."""
    model_id_lower = model_id.lower()
    for p in _load():
        if p.match.lower() in model_id_lower:
            return p
    return None


def reload():
    """Force a reload of model_profiles.json (useful in tests)."""
    global _PROFILES
    _PROFILES = None
    _load()
