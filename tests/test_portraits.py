"""
Tests for models/portraits.py — portrait generation helpers and API calls.

PO-1  build_portrait_prompt returns a non-empty string with chess/portrait keywords.
PO-2  portrait_filename is deterministic, .png extension, hex-only stem.
PO-3  generate_portrait happy path: writes bytes, returns relative path.
PO-4  generate_portrait skips API when file already exists on disk.
PO-5  generate_portrait returns None when response contains no image bytes.
PO-6  generate_portrait returns None and sets _quota_exhausted when all models
      return RESOURCE_EXHAUSTED with limit:0.
PO-7  generate_portrait returns None gracefully when google-genai is not installed.
PO-8  generate_portrait returns None immediately when _quota_exhausted is already True.
PO-9  Non-quota API errors do NOT set _quota_exhausted.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import models.portraits as portraits


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_modules(img_bytes: bytes):
    """
    Build a minimal fake google.genai + google.genai.types that returns img_bytes
    on the first generate_content call.
    """
    fake_part = MagicMock()
    fake_part.inline_data.data = img_bytes
    fake_candidate = MagicMock()
    fake_candidate.content.parts = [fake_part]
    fake_response = MagicMock()
    fake_response.candidates = [fake_candidate]

    fake_genai = MagicMock()
    fake_genai.Client.return_value.models.generate_content.return_value = fake_response
    fake_types = MagicMock()
    fake_google = MagicMock()
    fake_google.genai = fake_genai
    return fake_google, fake_genai, fake_types


def _inject(fake_google, fake_genai, fake_types):
    """Return a patch.dict context that makes `from google import genai` use our fakes."""
    return patch.dict(sys.modules, {
        'google':              fake_google,
        'google.genai':        fake_genai,
        'google.genai.types':  fake_types,
    })


# ── PO-1: build_portrait_prompt ───────────────────────────────────────────────

class TestBuildPortraitPrompt:
    def test_returns_non_empty_string(self):
        prompt = portraits.build_portrait_prompt("llama3-8b")
        assert isinstance(prompt, str) and prompt

    def test_contains_chess_and_portrait_keywords(self):
        prompt = portraits.build_portrait_prompt("llama3-8b")
        low = prompt.lower()
        assert "chess" in low
        assert "portrait" in low

    def test_known_family_influences_prompt(self):
        # "mistral-7b" should match the Mistral family character
        prompt = portraits.build_portrait_prompt("mistral-7b")
        low = prompt.lower()
        assert "mistral" in low or "musketeer" in low or "french" in low

    def test_unknown_model_uses_default_character(self):
        prompt = portraits.build_portrait_prompt("totally-unknown-xyz-model")
        low = prompt.lower()
        # Default character is a "mysterious chess grandmaster"
        assert "chess grandmaster" in low or "mysterious" in low or "grandmaster" in low

    def test_same_id_produces_identical_prompt(self):
        """Prompts are deterministic — same ID always gives the same string."""
        a = portraits.build_portrait_prompt("deepseek-r1-7b")
        b = portraits.build_portrait_prompt("deepseek-r1-7b")
        assert a == b

    def test_different_ids_produce_different_prompts(self):
        a = portraits.build_portrait_prompt("llama3-8b")
        b = portraits.build_portrait_prompt("qwen3-30b")
        assert a != b


# ── PO-2: portrait_filename ───────────────────────────────────────────────────

class TestPortraitFilename:
    def test_extension_is_png(self):
        assert portraits.portrait_filename("any-model").endswith(".png")

    def test_deterministic(self):
        f1 = portraits.portrait_filename("qwen3-30b")
        f2 = portraits.portrait_filename("qwen3-30b")
        assert f1 == f2

    def test_different_ids_produce_different_filenames(self):
        f1 = portraits.portrait_filename("model-a")
        f2 = portraits.portrait_filename("model-b")
        assert f1 != f2

    def test_stem_is_hex(self):
        stem = Path(portraits.portrait_filename("test-model")).stem
        assert all(c in "0123456789abcdef" for c in stem), \
            f"stem {stem!r} contains non-hex characters"

    def test_stem_length(self):
        # portrait_filename uses md5 digest[:12] → 12-char hex stem
        stem = Path(portraits.portrait_filename("test-model")).stem
        assert len(stem) == 12


# ── Generate portrait fixtures ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_quota():
    """Restore _quota_exhausted after each test."""
    orig = portraits._quota_exhausted
    yield
    portraits._quota_exhausted = orig


# ── PO-3: happy path ─────────────────────────────────────────────────────────

class TestGeneratePortraitHappyPath:
    def test_returns_relative_path(self, tmp_path):
        """PO-3 — successful call returns a portraits/<file>.png path string."""
        portraits._quota_exhausted = False
        fg, genai, types = _fake_modules(b'\x89PNG\r\nfake-bytes')
        with _inject(fg, genai, types):
            result = portraits.generate_portrait("llama3-8b", "fake-key", tmp_path)
        assert result is not None
        assert result.startswith("portraits/")
        assert result.endswith(".png")

    def test_bytes_written_to_disk(self, tmp_path):
        """PO-3 — image bytes are written to portraits_dir/<filename>."""
        portraits._quota_exhausted = False
        fake_bytes = b'\x89PNG\r\ntest-image-data'
        fg, genai, types = _fake_modules(fake_bytes)
        with _inject(fg, genai, types):
            result = portraits.generate_portrait("llama3-8b", "fake-key", tmp_path)
        dest = tmp_path / Path(result).name
        assert dest.exists()
        assert dest.read_bytes() == fake_bytes

    def test_api_client_receives_correct_api_key(self, tmp_path):
        """The genai.Client is constructed with the provided API key."""
        portraits._quota_exhausted = False
        fg, genai, types = _fake_modules(b'\x89PNG\r\n')
        with _inject(fg, genai, types):
            portraits.generate_portrait("llama3-8b", "my-real-key", tmp_path)
        genai.Client.assert_called_once_with(api_key="my-real-key")


# ── PO-4: file already on disk ────────────────────────────────────────────────

class TestGeneratePortraitFileExists:
    def test_skips_api_call_when_file_exists(self, tmp_path):
        """PO-4 — if the portrait PNG already exists, no generate_content call is made."""
        portraits._quota_exhausted = False
        fname = portraits.portrait_filename("llama3-8b")
        (tmp_path / fname).write_bytes(b'existing-portrait')
        fg, genai, types = _fake_modules(b'should-not-be-used')
        with _inject(fg, genai, types):
            result = portraits.generate_portrait("llama3-8b", "fake-key", tmp_path)
        assert result == f"portraits/{fname}"
        genai.Client.return_value.models.generate_content.assert_not_called()

    def test_returns_correct_path_for_existing_file(self, tmp_path):
        portraits._quota_exhausted = False
        fname = portraits.portrait_filename("qwen3-7b")
        (tmp_path / fname).write_bytes(b'cached')
        fg, genai, types = _fake_modules(b'')
        with _inject(fg, genai, types):
            result = portraits.generate_portrait("qwen3-7b", "fake-key", tmp_path)
        assert result == f"portraits/{fname}"


# ── PO-5: no image bytes in response ─────────────────────────────────────────

class TestGeneratePortraitNoBytes:
    def test_returns_none_when_response_has_no_image_data(self, tmp_path):
        """PO-5 — response with no inline_data.data returns None."""
        portraits._quota_exhausted = False
        # All models return a response with parts but no bytes
        fake_part = MagicMock()
        fake_part.inline_data.data = None
        fake_candidate = MagicMock()
        fake_candidate.content.parts = [fake_part]
        fake_response = MagicMock()
        fake_response.candidates = [fake_candidate]

        fake_genai = MagicMock()
        fake_genai.Client.return_value.models.generate_content.return_value = fake_response
        fg = MagicMock(genai=fake_genai)
        with _inject(fg, fake_genai, MagicMock()):
            result = portraits.generate_portrait("llama3-8b", "fake-key", tmp_path)
        assert result is None

    def test_returns_none_when_candidates_empty(self, tmp_path):
        portraits._quota_exhausted = False
        fake_response = MagicMock()
        fake_response.candidates = []
        fake_genai = MagicMock()
        fake_genai.Client.return_value.models.generate_content.return_value = fake_response
        fg = MagicMock(genai=fake_genai)
        with _inject(fg, fake_genai, MagicMock()):
            result = portraits.generate_portrait("llama3-8b", "fake-key", tmp_path)
        assert result is None


# ── PO-6: RESOURCE_EXHAUSTED quota ───────────────────────────────────────────

class TestGeneratePortraitQuotaExhausted:
    def test_all_models_resource_exhausted_sets_flag(self, tmp_path):
        """PO-6 — RESOURCE_EXHAUSTED on every model sets _quota_exhausted=True."""
        portraits._quota_exhausted = False
        fake_genai = MagicMock()
        fake_genai.Client.return_value.models.generate_content.side_effect = Exception(
            "RESOURCE_EXHAUSTED: limit: 0 free_tier exceeded"
        )
        fg = MagicMock(genai=fake_genai)
        with _inject(fg, fake_genai, MagicMock()):
            result = portraits.generate_portrait("test-model", "fake-key", tmp_path)
        assert result is None
        assert portraits._quota_exhausted is True

    def test_quota_flag_already_true_skips_api(self, tmp_path):
        """PO-8 — _quota_exhausted=True short-circuits without calling the API."""
        portraits._quota_exhausted = True
        fake_genai = MagicMock()
        fg = MagicMock(genai=fake_genai)
        with _inject(fg, fake_genai, MagicMock()):
            result = portraits.generate_portrait("test-model", "fake-key", tmp_path)
        assert result is None
        fake_genai.Client.assert_not_called()


# ── PO-9: non-quota errors ────────────────────────────────────────────────────

class TestGeneratePortraitNonQuotaErrors:
    def test_non_quota_exception_does_not_set_flag(self, tmp_path):
        """PO-9 — generic API error returns None but leaves _quota_exhausted=False."""
        portraits._quota_exhausted = False
        fake_genai = MagicMock()
        fake_genai.Client.return_value.models.generate_content.side_effect = Exception(
            "INTERNAL: backend error"
        )
        fg = MagicMock(genai=fake_genai)
        with _inject(fg, fake_genai, MagicMock()):
            result = portraits.generate_portrait("test-model", "fake-key", tmp_path)
        assert result is None
        assert portraits._quota_exhausted is False


# ── PO-7: missing google-genai package ───────────────────────────────────────

class TestGeneratePortraitImportError:
    def test_missing_genai_returns_none(self, tmp_path):
        """PO-7 — ImportError for google-genai returns None without raising."""
        portraits._quota_exhausted = False
        # Setting sys.modules entry to None blocks the import with ImportError
        with patch.dict(sys.modules, {
            'google': None,
            'google.genai': None,
            'google.genai.types': None,
        }):
            result = portraits.generate_portrait("test-model", "fake-key", tmp_path)
        assert result is None
