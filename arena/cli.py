"""
arena/cli.py — Argument parsing and entry point logic.

Invoked via `python -m arena` (through arena/__main__.py).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _free_port(port: int) -> bool:
    """Kill whatever is holding the port. Returns True if anything was killed."""
    import signal
    import subprocess
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    if not pids:
        return False
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    return True


def main():
    import argparse
    import asyncio as _asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from dotenv import load_dotenv
    load_dotenv()

    # Import state and models — safe since arena package is already initialised
    import arena.state as _st
    from arena.models import TournamentStartConfig

    parser = argparse.ArgumentParser(
        description="Nimzo — AI chess tournament server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "GUI mode (recommended):\n"
            "  python -m arena\n"
            "  -> opens http://localhost:8765 — configure everything in the browser\n\n"
            "CLI mode (auto-starts tournament):\n"
            "  python -m arena --white-model qwen3-30b --black-model llama-70b\n\n"
            "Config file mode:\n"
            "  python -m arena --config tournament.toml\n\n"
            "Headless benchmarking:\n"
            "  python -m arena --config tournament.toml --headless\n"
        ),
    )
    # --config loads everything from a TOML file; individual flags still override
    parser.add_argument("--config",        default="",
                        help="Path to a tournament.toml config file")
    # Model IDs intentionally NOT read from env vars — they must be passed
    # explicitly to trigger CLI mode.  Connection URLs and other non-model
    # settings are still env-configurable for convenience.
    parser.add_argument("--white-backend", default=os.environ.get("WHITE_BACKEND", "lmstudio"))
    parser.add_argument("--white-name",    default="")
    parser.add_argument("--white-model",   default="")   # explicit only — no env fallback
    parser.add_argument("--white-url",     default=os.environ.get("WHITE_URL", os.environ.get("LMSTUDIO_BASE_URL", _st._DEFAULT_LMSTUDIO_URL)))
    parser.add_argument("--black-backend", default=os.environ.get("BLACK_BACKEND", "lmstudio"))
    parser.add_argument("--black-name",    default="")
    parser.add_argument("--black-model",   default="")   # explicit only — no env fallback
    parser.add_argument("--black-url",     default=os.environ.get("BLACK_URL",     _st._DEFAULT_LMSTUDIO_URL))
    parser.add_argument("--tutor-backend", default=os.environ.get("TUTOR_BACKEND", "lmstudio"))
    parser.add_argument("--tutor-model",   default=os.environ.get("TUTOR_MODEL",   ""))
    parser.add_argument("--tutor-url",     default=os.environ.get("TUTOR_URL",     _st._DEFAULT_LMSTUDIO_URL))
    parser.add_argument("--judge-model",   default=os.environ.get("JUDGE_MODEL",   ""),
                        help="Model for reasoning coherence scoring (defaults to tutor model)")
    parser.add_argument("--games",         type=int, default=int(os.environ.get("GAMES", 1)))
    parser.add_argument("--move-timeout",  type=int, default=0,
                        help="Per-move timeout in seconds (0 = no limit)")
    parser.add_argument("--thinking",      action="store_true", default=False,
                        help="Enable extended thinking for both players (LM Studio)")
    parser.add_argument("--headless",      action="store_true", default=False,
                        help="Run without HTTP server or browser — DB only, fast benchmarking")
    parser.add_argument("--port",          type=int, default=int(os.environ.get("PORT", _st._DEFAULT_PORT)))
    parser.add_argument("--listen",        default=os.environ.get("NIMZO_HOST", "127.0.0.1"),
                        metavar="HOST",
                        help="Interface to bind (default 127.0.0.1; use 0.0.0.0 to expose on LAN)")
    parser.add_argument("--no-browser",    action="store_true", default=False,
                        help="Don't auto-open the browser on startup")
    args = parser.parse_args()

    # ── Config file mode ──────────────────────────────────────────────
    if args.config:
        from config_loader import load_config as _load_config
        _st._cli_config = _load_config(args.config)
        # CLI flags override config file values when explicitly non-default
        if args.move_timeout:
            _st._cli_config.move_timeout = args.move_timeout
        if args.headless:
            _st._mode["headless"] = True
    else:
        _st._mode["headless"] = args.headless

    port = args.port
    host = args.listen

    if _st._mode["headless"]:
        # ── Headless mode: skip uvicorn entirely ──────────────────────
        import db as database

        database.init_db()

        cli_mode = bool(args.config or (args.white_model and args.black_model))
        if not cli_mode:
            parser.error("--headless requires --config or --white-model/--black-model")

        if not args.config:
            _st._cli_config = TournamentStartConfig(
                white_backend=args.white_backend,
                white_name=args.white_name or args.white_model.split("/")[-1].split("@")[0].split(":")[0],
                white_model=args.white_model,
                white_url=args.white_url,
                white_thinking=args.thinking,
                black_backend=args.black_backend,
                black_name=args.black_name or args.black_model.split("/")[-1].split("@")[0].split(":")[0],
                black_model=args.black_model,
                black_url=args.black_url,
                black_thinking=args.thinking,
                tutor_backend=args.tutor_backend,
                tutor_model=args.tutor_model,
                tutor_url=args.tutor_url,
                judge_model=args.judge_model,
                games=args.games,
                move_timeout=args.move_timeout,
            )

        w = _st._cli_config.white_name or _st._cli_config.white_model
        b = _st._cli_config.black_name or _st._cli_config.black_model
        g = _st._cli_config.games
        print(f"Nimzo headless  {w} vs {b}  {g} game(s)")

        from arena.routes.tournament import api_start as _api_start

        async def _run_headless():
            """Run a headless tournament: start it, then await completion."""
            _st._pause_event.set()
            await _api_start(_st._cli_config)
            # Wait for the task to finish
            if _st._tournament_task:
                await _st._tournament_task

        _asyncio.run(_run_headless())
        raise SystemExit(0)

    # ── Normal (GUI) mode ─────────────────────────────────────────────
    import uvicorn

    # Free the port if something is already holding it
    if _free_port(port):
        logger.warning("Port %d was in use — cleared stale process.", port)
        import time
        time.sleep(0.4)   # brief pause for OS to release the socket

    cli_mode = bool(args.white_model and args.black_model) or bool(args.config)

    if cli_mode and not args.config:
        _st._cli_config = TournamentStartConfig(
            white_backend=args.white_backend,
            white_name=args.white_name or args.white_model.split("/")[-1].split("@")[0].split(":")[0],
            white_model=args.white_model,
            white_url=args.white_url,
            white_thinking=args.thinking,
            black_backend=args.black_backend,
            black_name=args.black_name or args.black_model.split("/")[-1].split("@")[0].split(":")[0],
            black_model=args.black_model,
            black_url=args.black_url,
            black_thinking=args.thinking,
            tutor_backend=args.tutor_backend,
            tutor_model=args.tutor_model,
            tutor_url=args.tutor_url,
            judge_model=args.judge_model,
            games=args.games,
            move_timeout=args.move_timeout,
        )

    display_host = "localhost" if host in ("127.0.0.1", "::1") else host
    if _st._cli_config:
        w = _st._cli_config.white_name or _st._cli_config.white_model
        b = _st._cli_config.black_name or _st._cli_config.black_model
        g = _st._cli_config.games
        print(f"Nimzo  ->  http://{display_host}:{port}")
        print(f"  {w} vs {b}  {g} game(s)")
        if _st._cli_config.tutor_model:
            print(f"  Tutor: {_st._cli_config.tutor_model}")
        if _st._cli_config.move_timeout:
            print(f"  Move timeout: {_st._cli_config.move_timeout}s")
    else:
        print(f"Nimzo  ->  http://{display_host}:{port}")
        print("    Open the browser to configure and start a tournament.")

    # Auto-open browser unless suppressed or in CLI mode with --no-browser
    if not args.no_browser:
        import threading
        import webbrowser

        def _open_browser():
            """Open the viewer in the default browser after uvicorn is ready."""
            import time
            time.sleep(1.2)   # wait for uvicorn to be ready
            webbrowser.open(f"http://localhost:{port}")

        threading.Thread(target=_open_browser, daemon=True).start()

    from arena import app
    uvicorn.run(app, host=host, port=port, log_level="warning")
