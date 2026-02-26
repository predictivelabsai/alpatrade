#!/usr/bin/env python3
"""
prompt_toolkit CLI interface for AlpaTrade.
Dropdown auto-completion variant of the Rich CLI.
"""
import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.markdown import Markdown
from rich.panel import Panel

from tui.strategy_cli import StrategyCLI
from tui.pt_completer import PTCommandCompleter


class PTStrategyCLI(StrategyCLI):
    """StrategyCLI with prompt_toolkit dropdown completion instead of readline."""

    def __init__(self, user_id=None, user_email=None, user_display=None):
        super().__init__(user_id=user_id, user_email=user_email, user_display=user_display)

    async def run(self):
        """Run the CLI interactive loop with prompt_toolkit."""
        session = PromptSession(
            completer=PTCommandCompleter(),
            history=InMemoryHistory(),
            complete_while_typing=False,
        )

        if self.user_display:
            user_line = f"Logged in as [bold green]{self.user_display}[/bold green]"
        else:
            user_line = "[yellow]Not logged in[/yellow] — type [bold]login[/bold] to authenticate"

        welcome = Panel.fit(
            "[bold cyan]AlpaTrade CLI[/bold cyan] [dim](prompt_toolkit)[/dim]\n"
            f"{user_line}\n\n"
            "Type [yellow]'help'[/yellow] for commands, "
            "[yellow]TAB[/yellow] for dropdown, or [yellow]'q'[/yellow] to quit",
            border_style="cyan"
        )
        self.console.print("\n")
        self.console.print(welcome)
        self.console.print("\n")

        quick_start = """## Quick Start

```
trades                                    Show trades from DB
runs                                      Show runs from DB
agent:backtest lookback:1m                Run parameterized backtest
agent:backtest lookback:1m hours:extended Extended hours backtest
agent:paper duration:7d                   Paper trade in background
agent:full lookback:1m duration:1m        Full cycle
help                                      Full reference
```
"""
        self.console.print(Markdown(quick_start))
        self.console.print("")

        while True:
            try:
                default = self._suggested_command or ""
                self._suggested_command = ""

                prompt_prefix = f"{self.user_display} > " if self.user_display else "> "
                user_input = await session.prompt_async(
                    prompt_prefix,
                    default=default,
                )
                user_input = user_input.strip()

                if not user_input:
                    continue

                # Strip optional "/" prefix
                if user_input.startswith("/"):
                    user_input = user_input[1:]

                if user_input.lower() in ['exit', 'quit', 'q']:
                    self.console.print("\n[yellow]Goodbye![/yellow]\n")
                    break

                self.command_history.append(user_input)
                await self.process_command(user_input)

            except KeyboardInterrupt:
                self.console.print("\n\n[yellow]Goodbye![/yellow]\n")
                break
            except EOFError:
                self.console.print("\n\n[yellow]Goodbye![/yellow]\n")
                break
            except Exception as e:
                self.console.print(f"\n[red]Unexpected error:[/red] {str(e)}\n")
                import traceback
                traceback.print_exc()


def main():
    """Main entry point for prompt_toolkit CLI."""
    cli = PTStrategyCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
