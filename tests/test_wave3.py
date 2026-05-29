"""
Wave 3 regression tests — M4 (puzzle path traversal) and m6 (proxy port allowlist).

M4: puzzle_loader.load_puzzles must reject paths that escape the project root.
m6: _check_proxy_url must reject 0.0.0.0 and ports outside the allowlist.
"""

from __future__ import annotations

import pytest


# ── M4: puzzle path traversal containment ────────────────────────────────────


class TestPuzzleLoaderPathContainment:
    """M4 — load_puzzles must reject paths outside the project root."""

    def test_dotdot_relative_path_raises_value_error(self):
        """../../etc/passwd-style traversal should raise ValueError, not open the file."""
        from puzzle_loader import load_puzzles

        with pytest.raises(ValueError, match="outside the project directory"):
            load_puzzles("../../etc/passwd")

    def test_dotdot_with_more_segments_raises(self):
        from puzzle_loader import load_puzzles

        with pytest.raises(ValueError, match="outside the project directory"):
            load_puzzles("../../../tmp/evil.toml")

    def test_absolute_path_outside_project_raises(self):
        """/etc/passwd (absolute path outside project root) must be rejected."""
        from puzzle_loader import load_puzzles

        with pytest.raises(ValueError, match="outside the project directory"):
            load_puzzles("/etc/passwd")

    def test_valid_relative_name_does_not_raise_value_error(self, tmp_path, monkeypatch):
        """A filename inside the project root should pass the containment check
        (may still raise FileNotFoundError — that's fine, not a traversal error)."""
        import puzzle_loader

        # Point _PROJECT_ROOT at tmp_path so the check passes
        monkeypatch.setattr(puzzle_loader, "_PROJECT_ROOT", tmp_path.resolve())

        with pytest.raises((FileNotFoundError, ValueError)) as exc_info:
            puzzle_loader.load_puzzles("nonexistent.toml")

        # Must NOT be a traversal ValueError
        if isinstance(exc_info.value, ValueError):
            assert "outside the project directory" not in str(exc_info.value)

    def test_valid_file_inside_project_loads(self, tmp_path, monkeypatch):
        """A well-formed TOML inside the project root should load successfully."""
        import puzzle_loader

        monkeypatch.setattr(puzzle_loader, "_PROJECT_ROOT", tmp_path.resolve())

        toml_file = tmp_path / "puzzles.toml"
        toml_file.write_text(
            '[[puzzle]]\nfen = "8/8/8/8/8/8/8/8 w - - 0 1"\nsolution_uci = "e2e4"\n'
        )

        puzzles = puzzle_loader.load_puzzles("puzzles.toml")
        assert len(puzzles) == 1
        assert puzzles[0]["fen"] == "8/8/8/8/8/8/8/8 w - - 0 1"
        assert puzzles[0]["solution_uci"] == "e2e4"


# ── m6: proxy port allowlist and 0.0.0.0 removal ────────────────────────────


class TestProxyPortAllowlist:
    """m6 — _check_proxy_url must check ports and reject 0.0.0.0."""

    @pytest.fixture()
    def check(self):
        from arena.routes.model_api import _check_proxy_url
        return _check_proxy_url

    def test_lmstudio_port_1234_allowed(self, check):
        check("http://localhost:1234/v1")   # must not raise

    def test_lmstudio_port_1235_allowed(self, check):
        check("http://localhost:1235/v1")   # must not raise

    def test_ollama_port_11434_allowed(self, check):
        check("http://127.0.0.1:11434/v1")  # must not raise

    def test_no_explicit_port_allowed(self, check):
        """URL with no port (uses protocol default) should pass."""
        check("http://localhost/v1")        # must not raise

    def test_unknown_local_port_blocked(self, check):
        """Port 8888 is not in the default allowlist."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check("http://127.0.0.1:8888/v1")
        assert exc_info.value.status_code == 403
        assert "allowlist" in exc_info.value.detail.lower()

    def test_port_22_blocked(self, check):
        """SSH port — definitely should not be proxied."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check("http://localhost:22/v1")
        assert exc_info.value.status_code == 403

    def test_0_0_0_0_host_blocked(self, check):
        """0.0.0.0 was removed from the host allowlist (wave 3)."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check("http://0.0.0.0:1234/v1")
        assert exc_info.value.status_code == 403

    def test_port_allowlist_extended_via_monkeypatch(self, check, monkeypatch):
        """Custom ports added to _PROXY_ALLOWED_PORTS should be permitted."""
        import arena.routes.model_api as _m

        monkeypatch.setattr(
            _m,
            "_PROXY_ALLOWED_PORTS",
            frozenset(_m._PROXY_ALLOWED_PORTS | {8080}),
        )
        _m._check_proxy_url("http://localhost:8080/v1")  # must not raise
