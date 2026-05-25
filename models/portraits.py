"""
Portrait generation for Nimzo model characters.

Each LLM is personified as a unique illustrated chess grandmaster character,
derived deterministically from the model ID via Google AI Studio's Imagen API.

The portrait is generated once and cached on disk + in the DB.
Generation is best-effort — if the API key is missing or the call fails the
UI just shows a placeholder avatar.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from models.metadata import parse_model_id


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


# ── Imagen API call ───────────────────────────────────────────────────────

def generate_portrait(
    model_id: str,
    api_key: str,
    portraits_dir: Path,
) -> Optional[str]:
    """
    Generate a portrait for *model_id* using Google AI Studio Imagen.

    Returns the file path (relative to server root, e.g. ``portraits/abc123.png``)
    on success, or ``None`` on any failure.

    The caller is responsible for running this in an executor when called from
    an async context — it is intentionally synchronous.
    """
    try:
        from google import genai  # type: ignore[import]
        from google.genai import types  # type: ignore[import]
    except ImportError:
        print("[portraits] google-genai not installed — skipping portrait generation")
        return None

    portraits_dir.mkdir(parents=True, exist_ok=True)
    filename = portrait_filename(model_id)
    dest = portraits_dir / filename

    # Skip API call if file already exists
    if dest.exists():
        return f"portraits/{filename}"

    prompt = build_portrait_prompt(model_id)
    print(f"[portraits] Generating portrait for {model_id!r}")
    print(f"[portraits] Prompt: {prompt[:120]}…")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
                safety_filter_level="block_only_high",
                person_generation="allow_adult",
            ),
        )
        images = response.generated_images
        if not images:
            print(f"[portraits] No images returned for {model_id!r}")
            return None

        img_bytes = images[0].image.image_bytes
        dest.write_bytes(img_bytes)
        print(f"[portraits] Saved portrait → {dest}")
        return f"portraits/{filename}"

    except Exception as exc:
        print(f"[portraits] Generation failed for {model_id!r}: {exc}")
        return None
