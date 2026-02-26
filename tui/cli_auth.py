"""
CLI authentication helper.

Prompts for email/password using Rich, authenticates against the DB
(same auth module as the web app), and returns (user_id, email) on success.
"""

import getpass
from typing import Optional, Tuple

from rich.console import Console
from rich.panel import Panel


PROD_URL = "https://alpatrade.dev"
LOCAL_URL = "http://localhost:5002"
MAX_ATTEMPTS = 3


def _get_signup_url() -> str:
    """Return local URL if the web app is running, otherwise the prod URL."""
    import socket
    try:
        s = socket.create_connection(("localhost", 5002), timeout=1)
        s.close()
        return LOCAL_URL
    except OSError:
        return PROD_URL


def cli_login(console: Console) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Interactive login prompt.

    Returns (user_id, email, display_name) on success, or (None, None, None)
    if the user skips or exhausts all attempts.
    """
    from utils.auth import authenticate

    signup_url = _get_signup_url()
    web_hint = (
        "[bold green]Web app detected![/bold green] "
        if signup_url == LOCAL_URL
        else ""
    )

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]AlpaTrade Login[/bold cyan]\n"
            "Enter your credentials to link trades to your account.\n\n"
            f"[yellow]No account?[/yellow] {web_hint}Type [bold]signup[/bold] "
            f"to open [cyan]{signup_url}/register[/cyan]\n"
            "Type [yellow]'skip'[/yellow] to continue without login "
            "(trades won't be linked to a user).",
            border_style="cyan",
        )
    )
    console.print()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            email = input("  Email: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Login cancelled.[/yellow]\n")
            return None, None, None

        if email.lower() == "skip":
            console.print("[yellow]Continuing without login.[/yellow]\n")
            return None, None, None

        if email.lower() == "signup":
            _open_signup(console)
            continue

        if not email or "@" not in email:
            console.print("[red]  Invalid email. Try again.[/red]\n")
            continue

        try:
            password = getpass.getpass("  Password: ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Login cancelled.[/yellow]\n")
            return None, None, None

        if not password:
            console.print("[red]  Password cannot be empty.[/red]\n")
            continue

        user = authenticate(email, password)
        if user:
            user_id = user["user_id"]
            display = user.get("display_name") or email
            console.print(
                f"\n  [green]Logged in as [bold]{display}[/bold][/green]\n"
            )
            return user_id, user["email"], display

        remaining = MAX_ATTEMPTS - attempt
        if remaining > 0:
            console.print(
                f"[red]  Invalid credentials.[/red] "
                f"({remaining} attempt{'s' if remaining != 1 else ''} left)\n"
            )
            console.print(
                f"  [dim]No account? Type [bold]signup[/bold] to create one.[/dim]\n"
            )
        else:
            console.print("[red]  Login failed.[/red]\n")

    # Exhausted all attempts
    final_url = _get_signup_url()
    console.print(
        Panel.fit(
            f"[yellow]Don't have an account?[/yellow]\n"
            f"Sign up at [bold cyan]{final_url}/register[/bold cyan]\n"
            f"then come back and run [bold]login[/bold] in the CLI.",
            border_style="yellow",
        )
    )
    console.print()
    console.print("[dim]Continuing without login...[/dim]\n")
    return None, None, None


def _open_signup(console: Console):
    """Open the web app signup page in the default browser."""
    import webbrowser
    url = f"{_get_signup_url()}/register"
    try:
        webbrowser.open(url)
        console.print(
            f"\n  [green]Opened [bold]{url}[/bold] in your browser.[/green]\n"
            f"  Create your account, then come back and enter your email here.\n"
        )
    except Exception:
        console.print(
            f"\n  [yellow]Could not open browser.[/yellow]\n"
            f"  Go to [bold cyan]{url}[/bold cyan] to create your account.\n"
        )
