#!/usr/bin/env python3
"""
AlpaTrade CLI - prompt_toolkit Entry Point
Dropdown auto-completion variant. Use alpaca_code.py for the readline variant.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv


def main():
    """Main entry point for AlpaTrade CLI (prompt_toolkit)."""
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

    from tui.pt_cli import PTStrategyCLI
    import asyncio
    cli = PTStrategyCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
