"""
Tests for model profile matching and loading.
"""
import json
import pytest
from pathlib import Path
from models.model_profiles import get_profile, ModelProfile, reload


class TestGetProfile:
    def setup_method(self):
        reload()  # clear cache before each test

    def test_qwen_matches(self):
        p = get_profile("qwen3-30b-a3b@q4_k_m")
        assert p is not None
        assert p.no_think_prefix is True

    def test_qwen_case_insensitive(self):
        p = get_profile("Qwen3-30B")
        assert p is not None

    def test_deepseek_matches(self):
        p = get_profile("deepseek-r1-distill-qwen-7b")
        assert p is not None

    def test_llama_matches(self):
        p = get_profile("meta-llama-3.1-8b-instruct")
        assert p is not None

    def test_unknown_model_returns_none(self):
        p = get_profile("some-unknown-model-xyz")
        assert p is None

    def test_first_match_wins(self):
        # qwen string also contains no deepseek — qwen profile should win
        p = get_profile("qwen3-coder-30b")
        assert p is not None
        assert p.match == "qwen"

    def test_empty_model_id(self):
        p = get_profile("")
        assert p is None


class TestModelProfileDefaults:
    def test_default_max_tokens_default(self):
        p = ModelProfile(match="test")
        assert p.max_tokens_default == 512

    def test_default_max_tokens_thinking(self):
        p = ModelProfile(match="test")
        assert p.max_tokens_thinking == 2048

    def test_default_no_think_prefix_false(self):
        p = ModelProfile(match="test")
        assert p.no_think_prefix is False

    def test_default_thinking_budget_zero(self):
        p = ModelProfile(match="test")
        assert p.thinking_budget_tokens == 0


class TestProfileFromJson:
    def test_profiles_file_exists(self):
        path = Path(__file__).parent.parent / "model_profiles.json"
        assert path.exists(), "model_profiles.json must exist at project root"

    def test_profiles_file_valid_json(self):
        path = Path(__file__).parent.parent / "model_profiles.json"
        data = json.loads(path.read_text())
        assert "profiles" in data
        assert isinstance(data["profiles"], list)

    def test_each_profile_has_match(self):
        path = Path(__file__).parent.parent / "model_profiles.json"
        data = json.loads(path.read_text())
        for p in data["profiles"]:
            assert "match" in p, f"Profile missing 'match': {p}"

    def test_reload_clears_cache(self):
        # First call to prime the cache
        get_profile("qwen3-30b")
        reload()
        # After reload, should still work
        p = get_profile("qwen3-30b")
        assert p is not None
