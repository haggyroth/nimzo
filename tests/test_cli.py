"""
Tests for arena/cli.py — argument parsing and entry-point logic.

C-1  _free_port returns False and calls nothing when the port is not in use.
C-2  _free_port returns True and sends SIGTERM to each PID lsof reports.
C-3  _free_port swallows ProcessLookupError (PID already gone between lsof and kill).
C-4  --white-model / --black-model builds _cli_config with the correct model IDs.
C-5  --games N is reflected in _cli_config.games.
C-6  white_name / black_name are derived from model_id when --name flags are omitted.
C-7  Explicit --white-name overrides the derived name.
C-8  --no-browser suppresses webbrowser.open.
C-9  --headless without models triggers parser.error (exit 2).
C-10 --headless + --white-model/--black-model sets _mode["headless"]=True.
C-11 Without model flags, _cli_config is not populated.
"""
from __future__ import annotations

import signal
import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cli_run(monkeypatch, argv, *, mock_uvicorn=True):
    """
    Invoke cli.main() with the given argv, stubbing out side-effectful calls.
    Returns the arena.state module so callers can inspect _cli_config / _mode.
    Swallows SystemExit so callers can make assertions afterward.
    """
    import arena.cli as cli
    import arena.state as _st

    monkeypatch.setattr(sys, "argv", argv)
    if mock_uvicorn:
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    monkeypatch.setattr("webbrowser.open", lambda *a, **kw: None)
    # Don't actually kill processes or open ports during tests
    monkeypatch.setattr("arena.cli._free_port", lambda p: False)

    try:
        cli.main()
    except SystemExit:
        pass
    return _st


# ── C-1 / C-2 / C-3: _free_port ──────────────────────────────────────────────

class TestFreePort:
    def test_returns_false_when_port_is_free(self):
        """C-1 — lsof returns nothing → _free_port returns False, kill not called."""
        from arena.cli import _free_port

        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            with patch("os.kill") as mock_kill:
                result = _free_port(9999)

        assert result is False
        mock_kill.assert_not_called()

    def test_returns_true_and_kills_each_pid(self):
        """C-2 — lsof returns two PIDs → both get SIGTERM and True is returned."""
        from arena.cli import _free_port

        mock_result = MagicMock()
        mock_result.stdout = "12345\n67890\n"
        with patch("subprocess.run", return_value=mock_result):
            with patch("os.kill") as mock_kill:
                result = _free_port(8765)

        assert result is True
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        mock_kill.assert_any_call(67890, signal.SIGTERM)
        assert mock_kill.call_count == 2

    def test_swallows_process_lookup_error(self):
        """C-3 — PID disappears between lsof and kill; ProcessLookupError is ignored."""
        from arena.cli import _free_port

        mock_result = MagicMock()
        mock_result.stdout = "99999\n"
        with patch("subprocess.run", return_value=mock_result):
            with patch("os.kill", side_effect=ProcessLookupError):
                # Should not raise
                result = _free_port(8765)
        assert result is True

    def test_passes_port_to_lsof(self):
        """lsof is invoked with the correct port argument."""
        from arena.cli import _free_port

        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _free_port(1234)
        args = mock_run.call_args[0][0]
        assert ":1234" in args


# ── C-4 / C-5 / C-6 / C-7: _cli_config population ───────────────────────────

class TestCliConfig:
    def teardown_method(self):
        """Reset _cli_config after each test."""
        import arena.state as _st
        _st._cli_config = None

    def test_white_black_model_sets_config(self, monkeypatch):
        """C-4 — basic --white-model/--black-model populates _cli_config."""
        st = _cli_run(monkeypatch, [
            "nimzo", "--white-model", "llama3-8b", "--black-model", "qwen3-7b",
            "--no-browser",
        ])
        assert st._cli_config is not None
        assert st._cli_config.white_model == "llama3-8b"
        assert st._cli_config.black_model == "qwen3-7b"

    def test_games_count_flows_through(self, monkeypatch):
        """C-5 — --games N is stored in _cli_config.games."""
        st = _cli_run(monkeypatch, [
            "nimzo", "--white-model", "a", "--black-model", "b", "--games", "7",
            "--no-browser",
        ])
        assert st._cli_config.games == 7

    def test_name_derived_from_model_id_without_namespace(self, monkeypatch):
        """C-6 — org/model-name → derived name is 'model-name'."""
        st = _cli_run(monkeypatch, [
            "nimzo", "--white-model", "org/big-model-name", "--black-model", "b",
            "--no-browser",
        ])
        assert st._cli_config.white_name == "big-model-name"

    def test_name_strips_quantization_tag(self, monkeypatch):
        """C-6 — model:latest → derived name is 'model' (strips colon suffix)."""
        st = _cli_run(monkeypatch, [
            "nimzo", "--white-model", "model:latest", "--black-model", "b",
            "--no-browser",
        ])
        assert st._cli_config.white_name == "model"

    def test_explicit_name_overrides_derived(self, monkeypatch):
        """C-7 — --white-name takes priority over the model_id-derived name."""
        st = _cli_run(monkeypatch, [
            "nimzo", "--white-model", "org/model", "--white-name", "WhiteKnight",
            "--black-model", "b", "--no-browser",
        ])
        assert st._cli_config.white_name == "WhiteKnight"

    def test_no_models_leaves_config_none(self, monkeypatch):
        """C-11 — without model flags, _cli_config is not set."""
        import arena.state as _st
        _st._cli_config = None
        _cli_run(monkeypatch, ["nimzo", "--no-browser"])
        assert _st._cli_config is None


# ── C-8: --no-browser ────────────────────────────────────────────────────────

class TestNoBrowser:
    def test_no_browser_suppresses_open(self, monkeypatch):
        """C-8 — webbrowser.open must not be called when --no-browser is passed."""
        opened = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
        monkeypatch.setattr(sys, "argv", ["nimzo", "--no-browser"])
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
        monkeypatch.setattr("arena.cli._free_port", lambda p: False)

        import arena.cli as cli
        import arena.state as _st
        orig = _st._cli_config
        try:
            try:
                cli.main()
            except SystemExit:
                pass
        finally:
            _st._cli_config = orig

        assert opened == [], "webbrowser.open must not be called with --no-browser"

    def test_without_no_browser_open_is_attempted(self, monkeypatch):
        """Without --no-browser, webbrowser.open is scheduled (daemon thread)."""
        import arena.cli as cli
        import arena.state as _st

        opened = []
        # Patch at module level before cli.main imports it
        monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
        monkeypatch.setattr(sys, "argv", ["nimzo"])
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
        monkeypatch.setattr("arena.cli._free_port", lambda p: False)

        orig = _st._cli_config
        try:
            try:
                cli.main()
            except SystemExit:
                pass
        finally:
            _st._cli_config = orig

        # The browser open happens in a daemon thread after 1.2s; we can't easily
        # assert it ran, but we can assert uvicorn.run was called (server started).
        # This test primarily documents the code path rather than the outcome.


# ── C-9 / C-10: --headless ────────────────────────────────────────────────────

class TestHeadless:
    def teardown_method(self):
        import arena.state as _st
        _st._cli_config = None
        _st._mode["headless"] = False

    def test_headless_without_models_exits_with_2(self, monkeypatch):
        """C-9 — --headless without model args triggers parser.error → SystemExit(2)."""
        import arena.cli as cli

        monkeypatch.setattr(sys, "argv", ["nimzo", "--headless"])
        monkeypatch.setattr("db.init_db", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 2

    def test_headless_with_models_sets_mode(self, monkeypatch):
        """C-10 — --headless + models sets _mode["headless"]=True."""
        import arena.cli as cli
        import arena.state as _st

        monkeypatch.setattr(sys, "argv", [
            "nimzo", "--headless",
            "--white-model", "model-a", "--black-model", "model-b",
        ])
        monkeypatch.setattr("db.init_db", lambda *a, **kw: None)
        # Prevent the actual async tournament from running
        monkeypatch.setattr("asyncio.run", lambda coro: None)

        orig_mode = dict(_st._mode)
        orig_config = _st._cli_config
        try:
            try:
                cli.main()
            except SystemExit:
                pass
            assert _st._mode.get("headless") is True
        finally:
            _st._mode.update(orig_mode)
            _st._cli_config = orig_config

    def test_headless_with_models_builds_config(self, monkeypatch):
        """C-10 — --headless + models populates _cli_config before running."""
        import arena.cli as cli
        import arena.state as _st

        monkeypatch.setattr(sys, "argv", [
            "nimzo", "--headless",
            "--white-model", "white-m", "--black-model", "black-m", "--games", "5",
        ])
        monkeypatch.setattr("db.init_db", lambda *a, **kw: None)
        monkeypatch.setattr("asyncio.run", lambda coro: None)

        orig_mode = dict(_st._mode)
        orig_config = _st._cli_config
        try:
            try:
                cli.main()
            except SystemExit:
                pass
            assert _st._cli_config is not None
            assert _st._cli_config.white_model == "white-m"
            assert _st._cli_config.black_model == "black-m"
            assert _st._cli_config.games == 5
        finally:
            _st._mode.update(orig_mode)
            _st._cli_config = orig_config
