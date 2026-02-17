#!/usr/bin/env python3
"""
AlpaTrade CLI - Main Entry Point
Launches the Rich-based interactive CLI for backtesting, paper trading,
and monitoring the multi-agent trading system.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv


def main():
    """Main entry point for AlpaTrade CLI."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # Configure logging so agent progress is visible in the CLI
    from rich.logging import RichHandler
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # Suppress noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("alpaca").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    from tui.strategy_cli import StrategyCLI
    import asyncio
    cli = StrategyCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
