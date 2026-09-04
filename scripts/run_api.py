#!/usr/bin/env python3
"""Load local environment configuration and run the Biosafe API."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.logging import configure_logging  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Biosafe FastAPI service.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="dotenv file to load (default: repository .env)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="listen host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="listen port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="reload when Python files change")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    env_file = args.env_file.expanduser().resolve()
    if not env_file.is_file():
        raise SystemExit(f"Environment file not found: {env_file}")

    load_dotenv(env_file, override=False)
    settings = Settings.from_env()
    log_file = _resolve_from_project(settings.log_file)
    configure_logging(settings.log_level, log_file)
    logging.getLogger(__name__).info(
        "starting biosafe api host=%s port=%s env_file=%s log_file=%s reload=%s",
        args.host,
        args.port,
        env_file,
        log_file,
        args.reload,
    )

    # The app factory configures the same JSON handlers after Uvicorn imports it.
    uvicorn.run(
        "services.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=True,
        log_config=None,
    )


def _resolve_from_project(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
