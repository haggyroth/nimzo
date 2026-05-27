"""
Model metadata extraction.

Two sources combined into a single dict:

  1. Filename conventions — parse `qwen3-coder-30b-a3b@q4_k_m` style IDs
     for family, parameter count, and quantization. Always works offline.

  2. HuggingFace API — for `owner/repo` style IDs we hit the public API
     (cached on disk for 24 hours) to pull license, architecture, context
     length, and total file size. Best-effort; failures are silent.

Backends like LM Studio expose the model ID as-is, so this lives close
to the lmstudio_player. The parser is deliberately conservative — it
returns Nones rather than guessing wildly.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


# Anchor cache to repo root regardless of CWD (see REVIEW.md MN-1)
_CACHE_PATH = Path(__file__).parent.parent / "hf_metadata_cache.json"
_CACHE_TTL_SECONDS = 24 * 3600   # 24 hours (1 day)
_HF_API = "https://huggingface.co/api/models/{repo}"
_REQUEST_TIMEOUT = 4.0    # seconds — strict, this is a UI call


# ── Filename parsing ──────────────────────────────────────────────────────

# Known LLM families. Order matters: longer/more-specific first so that
# "qwen3" matches before "qwen", "deepseek-r1" before "deepseek", etc.
_FAMILY_PATTERNS = [
    ("Qwen3-Coder",   r"qwen-?3.*coder"),
    ("Qwen3",         r"qwen-?3"),
    ("Qwen2.5",       r"qwen-?2\.?5"),
    ("Qwen2",         r"qwen-?2"),
    ("Qwen",          r"qwen"),
    ("DeepSeek-R1",   r"deepseek.?r1"),
    ("DeepSeek",      r"deepseek"),
    ("Llama 3.3",     r"llama-?3\.?3"),
    ("Llama 3.2",     r"llama-?3\.?2"),
    ("Llama 3.1",     r"llama-?3\.?1"),
    ("Llama 3",       r"llama-?3"),
    ("Llama 2",       r"llama-?2"),
    ("Llama",         r"llama"),
    ("Gemma 3",       r"gemma-?3"),
    ("Gemma 2",       r"gemma-?2"),
    ("Gemma",         r"gemma"),
    ("Phi-4",         r"phi-?4"),
    ("Phi-3",         r"phi-?3"),
    ("Phi",           r"phi"),
    ("Mistral",       r"mistral"),
    ("Ministral",     r"ministral"),
    ("Mixtral",       r"mixtral"),
    ("Nemotron",      r"nemotron"),
    ("Yi",            r"\byi-"),
    ("Command R",     r"command-?r"),
    ("Granite",       r"granite"),
]

# Param size: "30b", "1.5b", "3b", "405b", or sometimes "30B-A3B" (active params)
_PARAM_PATTERN = re.compile(r"(?<![a-z])(\d+(?:\.\d+)?)[bB](?![a-z])")

# Active-experts hint, e.g. "30b-a3b" → 3B active. Captured separately so we
# can show "30B (3B active)".
_ACTIVE_PATTERN = re.compile(r"a(\d+(?:\.\d+)?)b\b", re.IGNORECASE)

# Quantization tags. Order: prefer specific (q4_k_m, iq3_xs) over generic.
_QUANT_PATTERNS = [
    r"iq[0-9]+(?:_[a-z]+)?",
    r"q[0-9]+_k_[ms]",
    r"q[0-9]+_[01k]",
    r"q[0-9]+",
    r"fp16", r"bf16", r"fp8", r"int8", r"int4",
]
_QUANT_RE = re.compile(r"\b(" + "|".join(_QUANT_PATTERNS) + r")\b", re.IGNORECASE)


def parse_model_id(model_id: str) -> dict:
    """
    Extract what we can from the bare model identifier.
    All fields can be None / missing.
    """
    if not model_id:
        return {}

    norm = model_id.lower().replace("@", "-")
    # owner/repo → repo (leave the owner around so HF still works separately)
    bare = norm.split("/")[-1]

    out: dict = {"raw_id": model_id}

    # Family
    for label, pat in _FAMILY_PATTERNS:
        if re.search(pat, bare):
            out["family"] = label
            break

    # Param count (largest match wins — handles "qwen3-30b-a3b" correctly:
    # the 30b dominates the 3b).
    nums = [float(m.group(1)) for m in _PARAM_PATTERN.finditer(bare)]
    if nums:
        # Convention: largest number = total params, smaller = active experts
        total = max(nums)
        out["param_count"] = _format_b(total)
        active_match = _ACTIVE_PATTERN.search(bare)
        if active_match and float(active_match.group(1)) < total:
            out["active_params"] = _format_b(float(active_match.group(1)))

    # Quantization
    qm = _QUANT_RE.search(bare)
    if qm:
        out["quantization"] = qm.group(1).upper()

    return out


def _format_b(n: float) -> str:
    if n == int(n):
        return f"{int(n)}B"
    return f"{n:g}B"


# ── HuggingFace fetcher ───────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass


def _guess_hf_repo(model_id: str) -> Optional[str]:
    """
    LM Studio IDs sometimes embed the owner ('mistralai/ministral-3b'),
    sometimes don't ('qwen3-coder-30b@q4_k_m'). Only do an HF lookup
    when there's an owner prefix.
    """
    if "/" not in model_id:
        return None
    # Strip LM Studio's "@quant" suffix and any "-gguf" tail
    repo = model_id.split("@")[0]
    return repo


def fetch_hf_metadata(model_id: str) -> dict:
    """
    Hit huggingface.co/api/models/{repo}. Cached on disk for 7 days.
    Returns {} on any failure (network, 404, malformed response).
    """
    repo = _guess_hf_repo(model_id)
    if not repo:
        return {}

    cache = _load_cache()
    entry = cache.get(repo)
    now = time.time()
    if entry and (now - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
        return entry.get("data", {})

    data: dict = {}
    try:
        req = urllib.request.Request(
            _HF_API.format(repo=repo),
            headers={"User-Agent": "nimzo-chess-arena"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        # Cherry-pick the bits we want; the full response is huge
        data["hf_repo"] = repo
        data["hf_url"]  = f"https://huggingface.co/{repo}"
        if raw.get("pipeline_tag"):
            data["pipeline_tag"] = raw["pipeline_tag"]
        if raw.get("license"):
            data["license"] = raw["license"]
        elif isinstance(raw.get("cardData"), dict) and raw["cardData"].get("license"):
            data["license"] = raw["cardData"]["license"]

        # Architecture / context length from config.json if surfaced
        cfg = raw.get("config") or {}
        if cfg.get("model_type"):
            data["architecture"] = cfg["model_type"]
        for key in ("max_position_embeddings", "context_length", "max_seq_len"):
            if cfg.get(key):
                data["context_length"] = cfg[key]
                break

        # Total file size — sum siblings (filter to model weights to avoid
        # double-counting LFS pointers; treat the largest single file as a
        # decent proxy when the metadata is incomplete).
        siblings = raw.get("siblings") or []
        sizes = [s.get("size") or 0 for s in siblings if isinstance(s, dict)]
        if sizes:
            total = sum(sizes)
            if total > 0:
                data["file_size_bytes"] = total
                data["file_size_label"] = _fmt_size(total)

        # safetensors.total — total parameter count from tensor shapes (more
        # accurate than filename-parsing for MoE models like Mixtral, Qwen3-MoE)
        st = raw.get("safetensors") or {}
        if isinstance(st, dict) and st.get("total"):
            try:
                total_params = int(st["total"])
                if total_params >= 1_000_000:
                    data["safetensors_params"] = _format_b(total_params / 1e9)
            except (TypeError, ValueError):
                pass

        # Number of downloads (interesting on the card)
        if raw.get("downloads"):
            data["downloads"] = raw["downloads"]

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        # Network / parse / DNS failure — just leave data empty
        pass

    cache[repo] = {"fetched_at": now, "data": data}
    _save_cache(cache)
    return data


def _fmt_size(bytes_: int) -> str:
    """Format a byte count as a human-readable string (e.g. ``7.2 GB``)."""
    if bytes_ >= 1024 ** 3:
        return f"{bytes_ / 1024 ** 3:.1f} GB"
    if bytes_ >= 1024 ** 2:
        return f"{bytes_ / 1024 ** 2:.0f} MB"
    return f"{bytes_ / 1024:.0f} KB"


# ── Unified entry point ───────────────────────────────────────────────────

def get_model_metadata(model_id: str) -> dict:
    """
    Parse the filename + best-effort HF lookup, merged.  HF wins on
    conflicting fields (it's authoritative).  If the filename parser
    found no param count but HF returned safetensors_params, promote it.
    """
    parsed = parse_model_id(model_id)
    hf     = fetch_hf_metadata(model_id)
    merged = {**parsed, **hf}
    # Promote safetensors_params → param_count when filename-parse missed it
    if "param_count" not in merged and "safetensors_params" in merged:
        merged["param_count"] = merged["safetensors_params"]
    return merged
