"""
Cloud provider registry for Nimzo.

Maps backend name → base URL, API key env var, display label, and a list of
known model IDs.  All providers listed here use the OpenAI-compatible API
format and are served by LMStudioPlayer / _call_tutor_like's openai-compat
branch.  The "lmstudio" and "anthropic" backends are handled separately.

Adding a new provider:
  1. Add an entry to CLOUD_PROVIDERS below.
  2. Set the corresponding API key env var in your environment.
  3. Restart the server — no code changes required.
"""

from __future__ import annotations

CLOUD_PROVIDERS: dict[str, dict] = {
    "openai": {
        "label":   "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env":  "OPENAI_API_KEY",
        "models": [
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "o4-mini",
            "o3",
            "o3-mini",
        ],
    },
    "deepseek": {
        "label":   "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "key_env":  "DEEPSEEK_API_KEY",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    "qwen": {
        "label":   "Qwen (Dashscope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env":  "DASHSCOPE_API_KEY",
        "models": [
            "qwen3-235b-a22b",
            "qwen3-32b",
            "qwen3-14b",
            "qwen3-8b",
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
        ],
    },
    "gemini": {
        "label":   "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env":  "GEMINI_API_KEY",
        "models": [
            "gemini-2.5-pro-preview-05-06",
            "gemini-2.5-flash-preview-04-17",
            "gemini-2.0-flash",
            "gemini-2.0-flash-thinking-exp-01-21",
        ],
    },
    "xai": {
        "label":   "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "key_env":  "XAI_API_KEY",
        "models": [
            "grok-3",
            "grok-3-fast",
            "grok-3-mini",
            "grok-3-mini-fast",
            "grok-2-1212",
        ],
    },
}
