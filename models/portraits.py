"""
Portrait generation for Nimzo model characters.

Each LLM is personified as a unique illustrated chess grandmaster character,
derived deterministically from the model ID via Google AI Studio's Gemini
image-generation API (free tier compatible).

The portrait is generated once and cached on disk + in the DB.
Generation is best-effort — if the API key is missing or the call fails the
UI just shows a placeholder avatar.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from models.metadata import parse_model_id

logger = logging.getLogger(__name__)


# ── Character concept library ─────────────────────────────────────────────

# Maps model family → (scene description, colour palette, style note)
_FAMILY_CHARACTERS: dict[str, tuple[str, str]] = {
    "Qwen3-Coder": (
        "a focused hacker-scholar in a neon-lit cyberpunk server room, chess pieces "
        "rendered as glowing code constructs floating around them, "
        "sleek dark jacket with circuitboard embroidery",
        "electric blue and cyan on deep black",
    ),
    "Qwen3": (
        "a serene algorithmic strategist in a minimalist glass study, "
        "surrounded by floating holographic data streams shaped like chess notation, "
        "modern East Asian aesthetic",
        "cool white and luminous amber on dark indigo",
    ),
    "Qwen2.5": (
        "an ancient Chinese tactician in silk robes, studying a jade chess board "
        "by candlelight, folded fan in hand, intricate calligraphy on the walls",
        "jade green and imperial gold on rich black",
    ),
    "Qwen2": (
        "a meticulous Chinese strategist-scholar at an ornate lacquered desk, "
        "surrounded by scroll-maps of chess positions",
        "vermilion and ink black",
    ),
    "Qwen": (
        "an elegant East Asian chess grandmaster in a scholarly robe, "
        "contemplating a mid-game position with calm intensity",
        "cobalt blue and warm gold",
    ),
    "DeepSeek-R1": (
        "a brooding deep-sea explorer in a pressurised diving suit playing chess "
        "by bioluminescent light inside a sunken library, fish drifting past the porthole",
        "deep teal and silver bioluminescence on near-black",
    ),
    "DeepSeek": (
        "a submarine captain hunched over a chess board in a cramped pressurised capsule, "
        "sonar pings on the wall, lantern light flickering",
        "navy blue and brass on deep shadow",
    ),
    "Llama 3.3": (
        "a majestic llama knight in radiant golden plate armour, "
        "seated on a throne and holding a queen chess piece as a scepter, "
        "heraldic banners behind",
        "crimson and burnished gold on dark stone",
    ),
    "Llama 3.2": (
        "an adventurous llama ranger wearing a hooded travelling cloak, "
        "playing chess at a forest campfire, bow slung over shoulder",
        "forest green and warm firelight on dusk sky",
    ),
    "Llama 3.1": (
        "a llama wizard in sweeping star-covered robes, conjuring chess pieces "
        "from swirling magical energy",
        "deep violet and silver stardust",
    ),
    "Llama 3": (
        "a stoic llama warrior in battle-worn armour studying a chess board "
        "before a great campaign, serious expression",
        "steel grey and blood red",
    ),
    "Llama 2": (
        "a young llama apprentice chess player in a dusty academy library, "
        "wide-eyed and earnest over a textbook game",
        "warm ochre and brown",
    ),
    "Llama": (
        "a noble llama chess champion on a stage, trophy gleaming, "
        "crowd blurred in the background",
        "royal blue and gold",
    ),
    "Gemma 3": (
        "an elegant crystalline sorceress with gemstone eyes, "
        "weaving chess pieces out of emerald and sapphire light, "
        "jewel-studded robes catching every glint",
        "emerald green and sapphire on luminous white",
    ),
    "Gemma 2": (
        "a jewel-encrusted chess queen radiating cool magical radiance, "
        "commanding floating chess pieces with outstretched hands",
        "sapphire and silver on midnight",
    ),
    "Gemma": (
        "a brilliant gem-forger artisan at an enchanted forge, "
        "hammering glowing chess pieces from raw crystal",
        "rose quartz and warm gold",
    ),
    "Phi-4": (
        "a brilliant child prodigy in round glasses surrounded by impossibly complex "
        "equations and chess endgame studies, looking up with a knowing smile",
        "chalk white and midnight blue on blackboard green",
    ),
    "Phi-3": (
        "a Greek philosopher with a golden-ratio scroll and a laurel wreath, "
        "studying a chess board as if it were a proof",
        "marble white and Athenian gold",
    ),
    "Phi": (
        "a young mathematician wielding a glowing phi symbol like a torch, "
        "chess pieces arranged in geometric patterns around them",
        "pure white and electric cyan",
    ),
    "Mistral": (
        "a dashing French musketeer in an ink-dark cloak, windswept hair, "
        "playing chess on a parapet with the storm-tossed sea below",
        "midnight blue and silver-white",
    ),
    "Ministral": (
        "a nimble courier in a billowing coat sprinting through a castle courtyard "
        "with a chess move sealed in a letter, wind everywhere",
        "slate grey and gold wax seal red",
    ),
    "Mixtral": (
        "an eccentric alchemist mixing swirling elixirs from multiple flasks, "
        "each vial containing a glowing chess piece, laboratory in controlled chaos",
        "deep purple and vivid orange on alchemical gold",
    ),
    "Nemotron": (
        "a sleek humanoid android with glowing neural-network patterns etched into "
        "their chassis, playing chess on a floating holographic board in a futuristic arena",
        "electric blue and white chrome on carbon black",
    ),
    "Command R": (
        "a commanding naval admiral in a tall hat, studying a chess board "
        "as if charting a fleet battle, war galleon visible through the window",
        "deep navy and scarlet on polished mahogany",
    ),
    "Granite": (
        "a towering ancient stone golem chess master, carved from granite, "
        "enormous chess piece in one hand, sitting cross-legged on a mountain summit",
        "grey stone and iron on misty mountain",
    ),
    "Yi": (
        "a serene Chinese ink-painting master holding a calligraphy brush, "
        "each brushstroke forming a chess move on rice paper",
        "ink black and vermilion on cream white",
    ),
}

_DEFAULT_CHARACTER = (
    "a mysterious chess grandmaster in a dimly lit study, face half-shadowed, "
    "candlelight catching the gleam of a chess piece held between their fingers",
    "candlelight amber and shadow black",
)

_SIZE_EPITHETS = [
    (3,  "petite yet razor-sharp"),
    (13, "nimble and quick-witted"),
    (34, "formidable and methodical"),
    (999, "a towering titan of the chess world"),
]

_BASE_STYLE = (
    "illustrated digital art portrait, painterly style, "
    "dramatic chiaroscuro lighting, intricate character design, "
    "chess grandmaster aesthetic, cinematic composition, "
    "vivid expressive face, highly detailed, "
    "no text, no words, no letters"
)


def _size_epithet(param_str: Optional[str]) -> str:
    """Convert '30B' → size flavour text."""
    if not param_str:
        return ""
    try:
        n = float(param_str.rstrip("B"))
    except ValueError:
        return ""
    for threshold, label in _SIZE_EPITHETS:
        if n <= threshold:
            return label
    return _SIZE_EPITHETS[-1][1]


def build_portrait_prompt(model_id: str) -> str:
    """
    Build a deterministic Imagen prompt for the given model ID.

    Same model_id always produces the same prompt text, so repeated
    calls (if the image is somehow lost) produce the same character.
    """
    meta = parse_model_id(model_id)
    family = meta.get("family")

    scene, palette = _FAMILY_CHARACTERS.get(family, _DEFAULT_CHARACTER)

    size_note = _size_epithet(meta.get("param_count"))
    if size_note:
        scene = f"{scene}, {size_note}"

    return (
        f"Portrait of {scene}. "
        f"Colour palette: {palette}. "
        f"{_BASE_STYLE}."
    )


def portrait_filename(model_id: str) -> str:
    """Stable filename derived from model_id hash."""
    digest = hashlib.md5(model_id.encode("utf-8")).hexdigest()[:12]
    return f"{digest}.png"


# ── Gemini image generation API call ─────────────────────────────────────
#
# Google AI Studio's free tier supports image generation via the Gemini
# multimodal models (generate_content with response_modalities=["IMAGE"]).
# We try models in priority order so a future paid upgrade automatically
# uses the higher-quality model.

_IMAGE_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
]

# Session-level flag: set to True the first time every model returns 429 with
# a free-tier quota exhaustion message.  Subsequent calls are skipped silently
# rather than hammering the API and flooding the console.
_quota_exhausted: bool = False


def generate_portrait(
    model_id: str,
    api_key: str,
    portraits_dir: Path,
) -> Optional[str]:
    """
    Generate a portrait for *model_id* using Google AI Studio.

    Uses Gemini image-generation models (free tier compatible). Tries each
    model in ``_IMAGE_MODELS`` in order; returns the first successful result.

    Returns the file path relative to the server root (e.g.
    ``portraits/abc123.png``) on success, or ``None`` on any failure.

    Intentionally synchronous — the caller should run this in an executor.
    """
    global _quota_exhausted

    if _quota_exhausted:
        return None

    try:
        from google import genai  # type: ignore[import]
        from google.genai import types  # type: ignore[import]
    except ImportError:
        logger.warning("google-genai not installed — skipping portrait generation")
        return None

    portraits_dir.mkdir(parents=True, exist_ok=True)
    filename = portrait_filename(model_id)
    dest = portraits_dir / filename

    # Skip API call if file already exists on disk
    if dest.exists():
        return f"portraits/{filename}"

    prompt = build_portrait_prompt(model_id)
    logger.info("Generating portrait for %r", model_id)
    logger.debug("Portrait prompt: %s…", prompt[:120])

    client = genai.Client(api_key=api_key)

    quota_failures = 0
    for model_name in _IMAGE_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            # Extract image bytes from the first IMAGE part
            img_bytes: Optional[bytes] = None
            for candidate in (response.candidates or []):
                for part in (candidate.content.parts or []):
                    if part.inline_data and part.inline_data.data:
                        img_bytes = part.inline_data.data
                        break
                if img_bytes:
                    break

            if not img_bytes:
                logger.debug("%s: no image in response — skipping", model_name)
                continue

            dest.write_bytes(img_bytes)
            logger.info(
                "Saved portrait via %s → %s (%d KB)",
                model_name, dest, len(img_bytes) // 1024,
            )
            return f"portraits/{filename}"

        except Exception as exc:
            exc_str = str(exc)
            # Detect free-tier quota exhaustion — all three models will fail with
            # RESOURCE_EXHAUSTED and "limit: 0".  Once we see this pattern, set
            # the session flag so we stop hammering the API for the rest of the run.
            if "RESOURCE_EXHAUSTED" in exc_str and ("limit: 0" in exc_str or "free_tier" in exc_str.lower()):
                quota_failures += 1
            else:
                logger.warning("%s failed for %r: %s", model_name, model_id, exc)
            continue  # try next model

    if quota_failures == len(_IMAGE_MODELS):
        _quota_exhausted = True
        logger.warning(
            "Gemini free-tier quota exhausted — portrait generation disabled "
            "for this session. Upload a photo via the UI or wait 24 h for quota reset."
        )
    else:
        logger.warning("All portrait models failed for %r", model_id)
    return None
