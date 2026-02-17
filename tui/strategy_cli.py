#!/usr/bin/env python3
"""
Rich CLI interface for AlpaTrade.
Interactive command loop with Rich formatting and built-in trades/runs views.
"""
import asyncio
import readline  # noqa: F401 — enables arrow keys, history in input()
import threading
from typing import Optional
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table


class StrategyCLI:
    """Rich-based CLI application for AlpaTrade trading system."""

    def __init__(self):
        self.console = Console()
        self.command_history = []
        self.current_strategy = None
        self.current_symbols = []
        # Agent state — shared with CommandProcessor
        self._orch = None
        self._bg_task = None
        self._bg_stop = threading.Event()
        self._suggested_command: str = ""

    def _show_trades_table(self):
        """Render trades from DB as a Rich Table."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT symbol, direction, shares, entry_price, exit_price,
                               pnl, pnl_pct, trade_type, run_id
                        FROM alpatrade.trades
                        ORDER BY created_at DESC
                        LIMIT 100
                    """)
                )
                rows = result.fetchall()

            if not rows:
                self.console.print("\n[yellow]No trades found in database.[/yellow]\n")
                return

            table = Table(title="Recent Trades", show_lines=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Dir")
            table.add_column("Shares", justify="right")
            table.add_column("Entry $", justify="right")
            table.add_column("Exit $", justify="right")
            table.add_column("P&L", justify="right")
            table.add_column("P&L %", justify="right")
            table.add_column("Type")
            table.add_column("Run ID")

            for r in rows:
                pnl = float(r[5] or 0)
                pnl_style = "green" if pnl >= 0 else "red"
                table.add_row(
                    str(r[0] or ""),
                    str(r[1] or ""),
                    f"{float(r[2] or 0):.0f}",
                    f"${float(r[3] or 0):.2f}",
                    f"${float(r[4] or 0):.2f}",
                    f"[{pnl_style}]${pnl:.2f}[/{pnl_style}]",
                    f"{float(r[6] or 0):.2f}%",
                    str(r[7] or ""),
                    str(r[8] or "")[:8] + "...",
                )

            self.console.print("\n")
            self.console.print(table)
            self.console.print(f"\n[dim]{len(rows)} trades shown[/dim]\n")

        except Exception as e:
            self.console.print(f"\n[red]Error loading trades:[/red] {e}\n")

    def _show_runs_table(self):
        """Render runs from DB as a Rich Table."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT run_id, mode, strategy, status, started_at
                        FROM alpatrade.runs
                        ORDER BY created_at DESC
                        LIMIT 50
                    """)
                )
                rows = result.fetchall()

            if not rows:
                self.console.print("\n[yellow]No runs found in database.[/yellow]\n")
                return

            table = Table(title="Recent Runs", show_lines=True)
            table.add_column("Run ID", style="cyan")
            table.add_column("Mode")
            table.add_column("Strategy")
            table.add_column("Status")
            table.add_column("Started (ET)")

            for r in rows:
                from utils.tz_util import format_et
                status = str(r[3] or "")
                status_style = "green" if status == "completed" else "red" if "fail" in status else "yellow"
                table.add_row(
                    str(r[0])[:8] + "...",
                    str(r[1] or ""),
                    str(r[2] or "-"),
                    f"[{status_style}]{status}[/{status_style}]",
                    format_et(r[4]) if r[4] else "-",
                )

            self.console.print("\n")
            self.console.print(table)
            self.console.print(f"\n[dim]{len(rows)} runs shown[/dim]\n")

        except Exception as e:
            self.console.print(f"\n[red]Error loading runs:[/red] {e}\n")

    async def process_command(self, command: str):
        """Process a user command and display results."""
        cmd_lower = command.strip().lower()

        # Handle built-in table views directly (fast, no markdown)
        if cmd_lower == "trades":
            self._show_trades_table()
            return
        if cmd_lower == "runs":
            self._show_runs_table()
            return

        # Analysts: render as Rich 3-column layout instead of markdown
        if cmd_lower.startswith("analysts"):
            ticker = cmd_lower.split(":")[1].strip() if ":" in cmd_lower else cmd_lower.split()[1] if len(cmd_lower.split()) > 1 else None
            if not ticker:
                self.console.print("\n[red]Usage:[/red] analysts:AAPL\n")
                return
            from utils.market_research_util import MarketResearch
            import asyncio
            research = MarketResearch()
            renderable = await asyncio.to_thread(research.analysts_rich, ticker)
            self.console.print("\n")
            self.console.print(renderable)
            self.console.print("\n")
            return

        from tui.command_processor import CommandProcessor

        processor = CommandProcessor(self)

        try:
            result = await processor.process_command(command)

            if result:
                self.console.print("\n")
                self.console.print(Markdown(result))
                self.console.print("\n")
        except Exception as e:
            self.console.print(f"\n[red]Error:[/red] {str(e)}\n")
            import traceback
            traceback.print_exc()

    async def run(self):
        """Run the CLI interactive loop."""
        from tui.completer import setup_completer
        setup_completer()

        welcome = Panel.fit(
            "[bold cyan]AlpaTrade CLI[/bold cyan]\n"
            "Backtest, paper trade, and monitor the multi-agent trading system\n\n"
            "Type [yellow]'help'[/yellow] for commands or [yellow]'q'[/yellow] to quit",
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
                # Pre-fill suggested command so user can press Enter to accept
                if self._suggested_command:
                    def _prefill_hook():
                        readline.insert_text(self._suggested_command)
                        readline.redisplay()
                    readline.set_pre_input_hook(_prefill_hook)

                user_input = input("> ").strip()
                readline.set_pre_input_hook(None)
                self._suggested_command = ""

                if not user_input:
                    continue

                # Strip optional "/" prefix (e.g. /agent:backtest → agent:backtest)
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
    """Main entry point for Strategy CLI."""
    cli = StrategyCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
