"""
Tests for providers.py — the cloud provider registry.

P-1  All expected provider keys are present in CLOUD_PROVIDERS.
P-2  Each provider has the required structural keys (label, base_url, key_env, models).
P-3  All base_urls use HTTPS (no plaintext endpoints).
P-4  All key_env values follow the *_API_KEY convention.
P-5  Every provider has a non-empty models list with no duplicate IDs.
P-6  Specific known-good values are spot-checked against the documented API.
"""
from __future__ import annotations

import pytest

import providers as _providers

# The five documented cloud providers
_EXPECTED = frozenset({"openai", "deepseek", "qwen", "gemini", "xai"})


# ── P-1: registry completeness ────────────────────────────────────────────────

class TestRegistryCompleteness:
    """P-1 — CLOUD_PROVIDERS contains exactly the five documented providers."""

    def test_all_expected_providers_present(self):
        assert set(_providers.CLOUD_PROVIDERS.keys()) == _EXPECTED

    def test_no_extra_providers(self):
        extras = set(_providers.CLOUD_PROVIDERS.keys()) - _EXPECTED
        assert not extras, f"unexpected provider keys: {extras}"


# ── P-2: structural keys ──────────────────────────────────────────────────────

class TestProviderStructure:
    """P-2 — each entry has all required keys with appropriate types."""

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_required_keys_present(self, name):
        p = _providers.CLOUD_PROVIDERS[name]
        for key in ("label", "base_url", "key_env", "models"):
            assert key in p, f"{name!r} is missing required key {key!r}"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_label_is_non_empty_string(self, name):
        label = _providers.CLOUD_PROVIDERS[name]["label"]
        assert isinstance(label, str) and label.strip(), \
            f"{name!r} label is empty or not a string"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_base_url_is_string(self, name):
        assert isinstance(_providers.CLOUD_PROVIDERS[name]["base_url"], str)

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_key_env_is_string(self, name):
        assert isinstance(_providers.CLOUD_PROVIDERS[name]["key_env"], str)

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_models_is_list(self, name):
        assert isinstance(_providers.CLOUD_PROVIDERS[name]["models"], list)


# ── P-3: HTTPS ────────────────────────────────────────────────────────────────

class TestHttpsSecurity:
    """P-3 — all base_urls use HTTPS (no plaintext endpoints)."""

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_base_url_uses_https(self, name):
        url = _providers.CLOUD_PROVIDERS[name]["base_url"]
        assert url.startswith("https://"), \
            f"{name!r} base_url must use HTTPS, got: {url!r}"


# ── P-4: key_env convention ───────────────────────────────────────────────────

class TestKeyEnvConvention:
    """P-4 — all key_env values end with _API_KEY."""

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_key_env_ends_with_api_key(self, name):
        env = _providers.CLOUD_PROVIDERS[name]["key_env"]
        assert env.endswith("_API_KEY"), \
            f"{name!r} key_env {env!r} must end with _API_KEY"


# ── P-5: model lists ──────────────────────────────────────────────────────────

class TestModelLists:
    """P-5 — each provider has a non-empty, duplicate-free model list."""

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_models_non_empty(self, name):
        models = _providers.CLOUD_PROVIDERS[name]["models"]
        assert len(models) > 0, f"{name!r} has an empty models list"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_no_duplicate_model_ids(self, name):
        models = _providers.CLOUD_PROVIDERS[name]["models"]
        assert len(models) == len(set(models)), \
            f"{name!r} has duplicate model IDs: {models}"

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_all_model_ids_are_non_empty_strings(self, name):
        for mid in _providers.CLOUD_PROVIDERS[name]["models"]:
            assert isinstance(mid, str) and mid.strip(), \
                f"{name!r} has a blank or non-string model ID: {mid!r}"


# ── P-6: spot-checks ─────────────────────────────────────────────────────────

class TestKnownValues:
    """P-6 — spot-check specific provider values against documented API."""

    def test_openai_base_url(self):
        assert _providers.CLOUD_PROVIDERS["openai"]["base_url"] == "https://api.openai.com/v1"

    def test_openai_key_env(self):
        assert _providers.CLOUD_PROVIDERS["openai"]["key_env"] == "OPENAI_API_KEY"

    def test_openai_has_gpt4_model(self):
        models = _providers.CLOUD_PROVIDERS["openai"]["models"]
        assert any("gpt-4" in m for m in models), \
            "OpenAI provider should include at least one gpt-4 variant"

    def test_deepseek_key_env(self):
        assert _providers.CLOUD_PROVIDERS["deepseek"]["key_env"] == "DEEPSEEK_API_KEY"

    def test_deepseek_includes_reasoner(self):
        assert "deepseek-reasoner" in _providers.CLOUD_PROVIDERS["deepseek"]["models"]

    def test_qwen_uses_dashscope_key(self):
        assert _providers.CLOUD_PROVIDERS["qwen"]["key_env"] == "DASHSCOPE_API_KEY"

    def test_gemini_key_env(self):
        assert _providers.CLOUD_PROVIDERS["gemini"]["key_env"] == "GEMINI_API_KEY"

    def test_xai_key_env(self):
        assert _providers.CLOUD_PROVIDERS["xai"]["key_env"] == "XAI_API_KEY"

    def test_xai_has_grok_model(self):
        models = _providers.CLOUD_PROVIDERS["xai"]["models"]
        assert any("grok" in m for m in models), \
            "xAI provider should include at least one grok variant"
