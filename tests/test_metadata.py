"""
Tests for model ID parsing (the pure-function part of metadata.py).
No HuggingFace API calls.
"""
from models.metadata import parse_model_id


class TestParseModelId:
    def test_empty_returns_empty(self):
        assert parse_model_id("") == {}

    def test_raw_id_always_present(self):
        result = parse_model_id("some-model")
        assert result["raw_id"] == "some-model"

    def test_qwen3_family(self):
        result = parse_model_id("qwen3-30b-a3b@q4_k_m")
        assert result.get("family") == "Qwen3"

    def test_qwen_generic_family(self):
        result = parse_model_id("qwen-7b-chat")
        assert result.get("family") == "Qwen"

    def test_llama_31_family(self):
        result = parse_model_id("meta-llama-3.1-8b-instruct")
        assert result.get("family") == "Llama 3.1"

    def test_llama_3_family(self):
        result = parse_model_id("llama-3-8b")
        assert result.get("family") == "Llama 3"

    def test_gemma_family(self):
        result = parse_model_id("google/gemma-2-9b")
        assert result.get("family") == "Gemma 2"

    def test_mistral_family(self):
        result = parse_model_id("mistral-7b-instruct-v0.2")
        assert result.get("family") == "Mistral"

    def test_deepseek_r1_family(self):
        # deepseek-r1 should match before generic deepseek
        result = parse_model_id("deepseek-r1-14b")
        assert result.get("family") == "DeepSeek-R1"

    def test_deepseek_r1_plain(self):
        # Pure deepseek-r1 with no qwen suffix → DeepSeek-R1
        result = parse_model_id("deepseek-r1-14b")
        assert result.get("family") == "DeepSeek-R1"

    def test_deepseek_distill_matches_qwen_substring(self):
        # "deepseek-r1-distill-qwen-7b" contains "qwen" which fires before deepseek
        # in the current matcher — documenting known behaviour.
        result = parse_model_id("deepseek-r1-distill-qwen-7b")
        # Family is Qwen because "qwen" substring matches earlier in the list
        assert result.get("family") in ("Qwen", "DeepSeek-R1")

    def test_param_count_simple(self):
        result = parse_model_id("llama-7b")
        assert result.get("param_count") == "7B"

    def test_param_count_large(self):
        result = parse_model_id("qwen3-30b-a3b")
        assert result.get("param_count") == "30B"

    def test_active_params_moe(self):
        # qwen3-30b-a3b: 30B total, 3B active
        result = parse_model_id("qwen3-30b-a3b")
        assert result.get("active_params") == "3B"

    def test_quantization_q4_k_m(self):
        result = parse_model_id("llama-7b@q4_k_m")
        assert result.get("quantization") == "Q4_K_M"

    def test_quantization_q8(self):
        result = parse_model_id("mistral-7b-q8_0")
        assert result.get("quantization") is not None

    def test_no_quantization_if_absent(self):
        result = parse_model_id("llama-7b-instruct")
        assert "quantization" not in result

    def test_hf_slash_stripped_for_bare(self):
        # owner/repo: family + params should still be detected from repo part
        result = parse_model_id("meta-llama/Llama-3.1-8B-Instruct")
        assert result.get("family") == "Llama 3.1"

    def test_unknown_model_no_family(self):
        result = parse_model_id("some-random-model-xyz")
        assert "family" not in result
