#!/usr/bin/env python3
"""
AlpaTrade CLI - Main Entry Point
Interactive CLI with prompt_toolkit dropdown auto-completion.
"""
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

    from rich.console import Console
    from tui.cli_auth import cli_login

    console = Console()
    user_id, user_email, user_display = cli_login(console)

    from tui.pt_cli import PTStrategyCLI
    import asyncio
    cli = PTStrategyCLI(user_id=user_id, user_email=user_email, user_display=user_display)
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
