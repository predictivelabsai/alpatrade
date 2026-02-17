#!/usr/bin/env python3
"""
AlpaTrade Mobile Client — lightweight terminal client for Termux/Android.
Talks to the AlpaTrade API server over HTTPS.

Dependencies: requests, rich (no DB drivers, no alpaca-py, no pandas/numpy)

Usage:
    python ac.py
    python ac.py --server http://localhost:5001
    ALPATRADE_API=http://localhost:5001 python ac.py
"""
import argparse
import os
import readline  # noqa: F401 — enables arrow keys + history
import sys

import requests
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

DEFAULT_SERVER = "https://api.alpatrade.dev"
TIMEOUT = 300  # 5 minutes — backtests are slow

console = Console()


def send_command(server: str, command: str) -> str:
    """POST a command to /cmd and return the markdown result."""
    try:
        resp = requests.post(
            f"{server}/cmd",
            json={"command": command},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", "")
    except requests.ConnectionError:
        return f"# Connection Error\n\nCannot reach `{server}`. Is the server running?"
    except requests.Timeout:
        return "# Timeout\n\nThe request timed out after 5 minutes."
    except Exception as e:
        return f"# Error\n\n```\n{e}\n```"


def main():
    parser = argparse.ArgumentParser(description="AlpaTrade Mobile Client")
    parser.add_argument(
        "--server", "-s",
        default=os.environ.get("ALPATRADE_API", DEFAULT_SERVER),
        help=f"API server URL (default: {DEFAULT_SERVER})",
    )
    args = parser.parse_args()
    server = args.server.rstrip("/")

    # Health check
    try:
        r = requests.get(f"{server}/health", timeout=5)
        r.raise_for_status()
    except Exception:
        console.print(f"[red]Cannot reach {server}[/red]")
        console.print("Start the API server or pass --server URL")
        sys.exit(1)

    console.print()
    console.print(Panel.fit(
        "[bold cyan]AlpaTrade[/bold cyan]\n"
        f"Connected to [dim]{server}[/dim]\n\n"
        "Type [yellow]'help'[/yellow] for commands or [yellow]'q'[/yellow] to quit",
        border_style="cyan",
    ))
    console.print()

    while True:
        try:
            user_input = input("> ").strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                user_input = user_input[1:]

            if user_input.lower() in ("exit", "quit", "q"):
                console.print("\n[yellow]Goodbye![/yellow]\n")
                break

            result = send_command(server, user_input)
            if result:
                console.print()
                console.print(Markdown(result))
                console.print()

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Goodbye![/yellow]\n")
            break
        except EOFError:
            console.print("\n\n[yellow]Goodbye![/yellow]\n")
            break


if __name__ == "__main__":
    main()
