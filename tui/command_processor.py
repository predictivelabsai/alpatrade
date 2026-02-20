"""
Command Processor for Strategy Simulator TUI
Handles command parsing and execution for both legacy backtests and the
multi-agent orchestrator framework.
"""
import sys
import asyncio
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from rich.console import Console

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class CommandProcessor:
    """Processes commands for the Strategy Simulator TUI."""

    def __init__(self, app_instance):
        self.app = app_instance
        self.console = Console()

        # Default parameters
        self.default_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"]
        self.default_capital = 10000
        self.default_position_size = 10  # percentage

        # Agent state (shared across calls via app instance)
        if not hasattr(self.app, '_orch'):
            self.app._orch = None
        if not hasattr(self.app, '_bg_task'):
            self.app._bg_task = None
        if not hasattr(self.app, '_bg_stop'):
            self.app._bg_stop = threading.Event()

    # ------------------------------------------------------------------
    # Main dispatcher
    # ------------------------------------------------------------------

    async def process_command(self, user_input: str) -> Optional[str]:
        """
        Process a command and return markdown result.
        Returns markdown string to display or None.
        """
        cmd_lower = user_input.strip().lower()

        # Basic commands
        if cmd_lower in ["help", "h", "?"]:
            return self._show_help()
        elif cmd_lower in ["exit", "quit", "q"]:
            if hasattr(self.app, 'exit'):
                self.app.exit()
            return None
        elif cmd_lower in ["clear", "cls"]:
            return ""
        elif cmd_lower == "guide":
            return self._show_guide()
        elif cmd_lower == "status":
            return self._show_status()
        elif cmd_lower == "trades":
            return self._agent_trades({})
        elif cmd_lower == "runs":
            return self._agent_runs()

        # Market research commands (colon syntax: news:TSLA, profile:AAPL)
        research_cmds = ("news", "profile", "financials", "price", "movers", "analysts", "valuation")
        first_word = cmd_lower.split()[0]
        research_base = first_word.split(":")[0]
        if research_base in research_cmds:
            return await self._handle_research_command(user_input)

        # Legacy backtest commands
        if cmd_lower.startswith("alpaca:backtest"):
            return await self._handle_backtest(user_input)

        # Agent framework commands
        if cmd_lower.startswith("agent:"):
            return await self._handle_agent_command(user_input)

        # No structured command matched — send to AI chat agent
        return await self._chat_agent(user_input)

    # ------------------------------------------------------------------
    # Free-form AI chat (fallback for unrecognized input)
    # ------------------------------------------------------------------

    # Broker-related keywords → alpaca_agent
    _BROKER_KEYWORDS = {
        "buy", "sell", "order", "orders", "position", "positions",
        "holdings", "holding", "portfolio", "account", "balance",
        "buying power", "equity", "assets", "tradable",
    }

    def _is_broker_query(self, text: str) -> bool:
        """Return True if the input looks like a broker / trading interaction."""
        lower = text.lower()
        return any(kw in lower for kw in self._BROKER_KEYWORDS)

    async def _chat_agent(self, user_input: str) -> str:
        """Route free-form text to the appropriate LangGraph agent."""
        import uuid

        # Separate thread ids per agent so conversation context doesn't bleed
        if not hasattr(self.app, '_broker_thread_id'):
            self.app._broker_thread_id = str(uuid.uuid4())
        if not hasattr(self.app, '_research_thread_id'):
            self.app._research_thread_id = str(uuid.uuid4())

        is_broker = self._is_broker_query(user_input)

        if is_broker:
            self.console.print("[dim]Asking broker...[/dim]")
            from utils.alpaca_agent import get_response
            thread_id = self.app._broker_thread_id
        else:
            self.console.print("[dim]Researching...[/dim]")
            from utils.research_agent import get_response
            thread_id = self.app._research_thread_id

        try:
            state = await asyncio.to_thread(get_response, user_input, thread_id)

            # Walk backwards to find the last AI message without tool_calls
            for msg in reversed(state.get("messages", [])):
                if getattr(msg, "type", None) == "ai" and not getattr(msg, "tool_calls", None):
                    return msg.content or "(no response)"

            return "(no response from agent)"

        except Exception as e:
            return f"# Chat Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # Market research command dispatcher
    # ------------------------------------------------------------------

    async def _handle_research_command(self, user_input: str) -> str:
        """Dispatch market research commands: news:TSLA, profile:AAPL, etc."""
        import asyncio
        from utils.market_research_util import MarketResearch

        parts = user_input.strip().split()
        first = parts[0]
        research = MarketResearch()

        # Parse colon syntax: "news:TSLA" → cmd="news", ticker="TSLA"
        # Also supports legacy positional: "news TSLA"
        if ":" in first:
            cmd, ticker_part = first.split(":", 1)
            cmd = cmd.lower()
            tickers = [ticker_part] if ticker_part else []
        else:
            cmd = first.lower()
            tickers = []

        # Remaining parts: key:value params or positional tickers (legacy)
        params = {}
        for part in parts[1:]:
            if ":" in part:
                key, value = part.split(":", 1)
                params[key.lower()] = value
            else:
                # Positional argument — ticker(s) or direction for movers
                tickers.append(part)

        ticker = tickers[0].upper() if tickers else None

        try:
            if cmd == "news":
                limit = int(params.get("limit", "10"))
                prov = params.get("provider")
                return await asyncio.to_thread(research.news, ticker, limit, prov)
            elif cmd == "profile":
                if not ticker:
                    return "# Error\n\nUsage: `profile TSLA`"
                return await asyncio.to_thread(research.profile, ticker)
            elif cmd == "financials":
                if not ticker:
                    return "# Error\n\nUsage: `financials AAPL` or `financials AAPL period:quarterly`"
                period = params.get("period", "annual")
                return await asyncio.to_thread(research.financials, ticker, period)
            elif cmd == "price":
                if not ticker:
                    return "# Error\n\nUsage: `price TSLA`"
                return await asyncio.to_thread(research.price, ticker)
            elif cmd == "movers":
                direction = "both"
                if ticker:
                    d = ticker.lower()
                    if d in ("gainers", "losers"):
                        direction = d
                return await asyncio.to_thread(research.movers, direction)
            elif cmd == "analysts":
                if not ticker:
                    return "# Error\n\nUsage: `analysts AAPL`"
                return await asyncio.to_thread(research.analysts, ticker)
            elif cmd == "valuation":
                if not tickers:
                    return "# Error\n\nUsage: `valuation AAPL` or `valuation AAPL,MSFT,GOOGL`"
                # Support both "valuation AAPL,MSFT" and "valuation AAPL MSFT"
                all_tickers = []
                for t in tickers:
                    all_tickers.extend(t.split(","))
                return await asyncio.to_thread(research.valuation, all_tickers)
            else:
                return f"# Error\n\nUnknown research command: `{cmd}`"
        except Exception as e:
            return f"# Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # Agent command dispatcher
    # ------------------------------------------------------------------

    async def _handle_agent_command(self, user_input: str) -> str:
        """Dispatch agent:* commands."""
        parts = user_input.strip().split()
        subcmd = parts[0].lower()
        params = self._parse_kv_params(parts[1:])

        if subcmd == "agent:backtest":
            return await self._agent_backtest(params)
        elif subcmd == "agent:validate":
            return await self._agent_validate(params)
        elif subcmd == "agent:paper":
            return await self._agent_paper(params)
        elif subcmd == "agent:full":
            return await self._agent_full(params)
        elif subcmd == "agent:reconcile":
            return await self._agent_reconcile(params)
        elif subcmd == "agent:status":
            return self._agent_status()
        elif subcmd == "agent:runs":
            return self._agent_runs()
        elif subcmd == "agent:trades":
            return self._agent_trades(params)
        elif subcmd == "agent:report":
            return self._agent_report(params)
        elif subcmd == "agent:top":
            return self._agent_top(params)
        elif subcmd == "agent:stop":
            return self._agent_stop()
        else:
            return (
                f"# Unknown Agent Command\n\n`{subcmd}` is not recognized.\n\n"
                "Available: `agent:backtest`, `agent:validate`, `agent:paper`, "
                "`agent:full`, `agent:reconcile`, `agent:report`, `agent:top`, "
                "`agent:status`, `agent:runs`, `agent:trades`, `agent:stop`"
            )

    def _parse_kv_params(self, parts: list) -> Dict[str, str]:
        """Parse key:value pairs from command parts."""
        params = {}
        for part in parts:
            if ":" in part:
                key, value = part.split(":", 1)
                params[key.lower()] = value
        return params

    def _get_orchestrator(self) -> "Orchestrator":
        """Get or create an Orchestrator instance."""
        from agents.orchestrator import Orchestrator
        if self.app._orch is None:
            self.app._orch = Orchestrator()
        return self.app._orch

    def _new_orchestrator(self) -> "Orchestrator":
        """Create a fresh Orchestrator (new run_id, clean state)."""
        from agents.orchestrator import Orchestrator
        orch = Orchestrator()
        # Clear stale state loaded from disk so status shows current run only
        orch.state.mode = None
        orch.state.best_config = None
        orch.state.validation_results = []
        self.app._orch = orch
        return orch

    # ------------------------------------------------------------------
    # agent:backtest
    # ------------------------------------------------------------------

    async def _agent_backtest(self, params: Dict) -> str:
        """Run orchestrator backtest mode."""
        from agents.orchestrator import parse_duration

        orch = self._new_orchestrator()
        symbols_str = params.get("symbols", ",".join(self.default_symbols))
        symbols = [s.strip().upper() for s in symbols_str.split(",")]

        # PDT protection: default True (None lets strategy decide), pdt:false disables
        pdt_val = params.get("pdt")
        pdt_protection = None  # let strategy default (True if capital < $25k)
        if pdt_val is not None:
            pdt_protection = pdt_val.lower() not in ("false", "no", "0", "off")

        config = {
            "strategy": params.get("strategy", "buy_the_dip"),
            "symbols": symbols,
            "lookback": params.get("lookback", "3m"),
            "initial_capital": float(params.get("capital", self.default_capital)),
            "extended_hours": params.get("hours") == "extended",
            "intraday_exit": params.get("intraday_exit", "false").lower() in ("true", "yes", "1", "on"),
            "pdt_protection": pdt_protection,
        }

        result = await asyncio.to_thread(orch.run_backtest, config)

        if "error" in result:
            return f"# Backtest Failed\n\n```\n{result['error']}\n```"

        best = result.get("best_config", {})
        p = best.get("params", {})
        run_id = result.get('run_id', '')

        # Pre-fill the next prompt with the validate command
        if hasattr(self.app, '_suggested_command'):
            self.app._suggested_command = f"agent:validate run-id:{run_id}"

        # Generate equity chart for web UI (stored on app, ignored by CLI)
        self._build_equity_chart(result.get("trades", []), config)

        return (
            f"# Backtest Complete\n\n"
            f"- **Run ID**: `{run_id}`\n"
            f"- **Strategy**: {result.get('strategy')}\n"
            f"- **Variations**: {result.get('total_variations')}\n\n"
            f"## Best Configuration\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Sharpe Ratio | {best.get('sharpe_ratio', 0):.2f} |\n"
            f"| Total Return | {best.get('total_return', 0):.1f}% |\n"
            f"| Annualized Return | {best.get('annualized_return', 0):.1f}% |\n"
            f"| Total P&L | ${best.get('total_pnl', 0):,.2f} |\n"
            f"| Win Rate | {best.get('win_rate', 0):.1f}% |\n"
            f"| Total Trades | {best.get('total_trades', 0)} |\n"
            f"| Max Drawdown | {best.get('max_drawdown', 0):.2f}% |\n\n"
            f"**Params**: dip={p.get('dip_threshold')}, "
            f"tp={p.get('take_profit')}, hold={p.get('hold_days')}\n\n"
            f"Press Enter to validate, or type a new command."
        )

    def _build_equity_chart(self, trades: list, config: Dict) -> None:
        """Build Plotly equity chart JSON from backtest trades and store on app."""
        try:
            import plotly.graph_objects as go
            import plotly.io as pio
            import pandas as pd
            from utils.backtester_util import calculate_buy_and_hold, calculate_single_buy_and_hold

            if not trades:
                return

            # Sort trades by exit_time
            trades_sorted = sorted(trades, key=lambda t: str(t.get("exit_time", "")))

            exit_times = [t.get("exit_time") for t in trades_sorted]
            capital_values = [t.get("capital_after") for t in trades_sorted]

            # Filter out None values
            valid = [(t, c) for t, c in zip(exit_times, capital_values) if t is not None and c is not None]
            if not valid:
                return

            exit_times, capital_values = zip(*valid)
            exit_times = list(exit_times)
            capital_values = list(capital_values)

            # Build daily equity curve (end-of-day snapshots) for a smooth line
            trades_df = pd.DataFrame({"exit_time": exit_times, "capital_after": capital_values})
            trades_df["date"] = pd.to_datetime(trades_df["exit_time"]).dt.date
            daily_equity = trades_df.groupby("date")["capital_after"].last().reset_index()
            daily_equity = daily_equity.sort_values("date")
            chart_dates = pd.to_datetime(daily_equity["date"]).tolist()
            chart_values = daily_equity["capital_after"].tolist()

            # Parse dates for benchmark calculation (strip tz for compatibility)
            start_dt = pd.Timestamp(chart_dates[0])
            end_dt = pd.Timestamp(chart_dates[-1])
            if start_dt.tzinfo is not None:
                start_dt = start_dt.tz_localize(None)
            if end_dt.tzinfo is not None:
                end_dt = end_dt.tz_localize(None)
            initial_capital = config.get("initial_capital", 10000)
            symbols = config.get("symbols", [])

            fig = go.Figure()

            # Strategy equity curve (daily end-of-day snapshots)
            fig.add_trace(go.Scatter(
                x=chart_dates, y=chart_values,
                mode='lines',
                name='Strategy',
                line=dict(color='#1f77b4', width=2),
            ))

            # Benchmarks — run with timeout to avoid hanging on slow API calls
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

            def _fetch_spy():
                return calculate_single_buy_and_hold(
                    'SPY', start_dt.to_pydatetime(), end_dt.to_pydatetime(), initial_capital
                )

            def _fetch_portfolio():
                return calculate_buy_and_hold(
                    symbols, start_dt.to_pydatetime(), end_dt.to_pydatetime(), initial_capital
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                # SPY buy & hold benchmark
                try:
                    spy_dates, spy_values = pool.submit(_fetch_spy).result(timeout=15)
                    if not spy_values.empty:
                        fig.add_trace(go.Scatter(
                            x=spy_dates.tolist(), y=spy_values.tolist(),
                            mode='lines',
                            name='Buy & Hold (SPY)',
                            line=dict(color='#ff7f0e', width=2, dash='dash'),
                        ))
                except (Exception, FuturesTimeout):
                    pass

                # Portfolio buy & hold benchmark
                try:
                    if symbols:
                        pf_dates, pf_values = pool.submit(_fetch_portfolio).result(timeout=15)
                        if not pf_values.empty:
                            label = ', '.join(symbols[:3])
                            if len(symbols) > 3:
                                label += '...'
                            fig.add_trace(go.Scatter(
                                x=pf_dates.tolist(), y=pf_values.tolist(),
                                mode='lines',
                                name=f'Buy & Hold ({label})',
                                line=dict(color='#2ca02c', width=2, dash='dot'),
                            ))
                except (Exception, FuturesTimeout):
                    pass

            # Initial capital line
            fig.add_hline(
                y=initial_capital,
                line_dash="dash", line_color="gray",
                annotation_text="Initial Capital",
                annotation_position="right",
            )

            fig.update_layout(
                title='Portfolio Value Over Time',
                xaxis_title='Date',
                yaxis_title='Portfolio Value ($)',
                hovermode='x unified',
                height=500,
                showlegend=True,
                template='plotly_dark',
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(26,26,46,0.8)',
                legend=dict(
                    yanchor="top", y=0.99,
                    xanchor="left", x=0.01,
                    bgcolor="rgba(0,0,0,0.5)",
                ),
                margin=dict(t=50, b=50, l=60, r=80),
            )

            self.app._last_chart_json = pio.to_json(fig)

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not build equity chart: {e}")

    # ------------------------------------------------------------------
    # agent:validate
    # ------------------------------------------------------------------

    async def _agent_validate(self, params: Dict) -> str:
        """Run validation against a run."""
        run_id = params.get("run-id")
        source = params.get("source", "backtest")

        orch = self._get_orchestrator()
        result = await asyncio.to_thread(
            orch.run_validation, run_id=run_id, source=source
        )

        if "error" in result:
            return f"# Validation Failed\n\n```\n{result['error']}\n```"

        status = result.get("status", "unknown")
        suggestions_md = ""
        if result.get("suggestions"):
            suggestions_md = "\n## Suggestions\n" + "\n".join(
                f"- {s}" for s in result["suggestions"]
            )

        return (
            f"# Validation: {status.upper()}\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Status | {status} |\n"
            f"| Anomalies Found | {result.get('anomalies_found', 0)} |\n"
            f"| Anomalies Corrected | {result.get('anomalies_corrected', 0)} |\n"
            f"| Iterations Used | {result.get('iterations_used', 0)} |\n"
            f"{suggestions_md}"
        )

    # ------------------------------------------------------------------
    # agent:paper (background)
    # ------------------------------------------------------------------

    async def _agent_paper(self, params: Dict) -> str:
        """Start paper trading in the background."""
        import logging
        from agents.orchestrator import parse_duration

        if self.app._bg_task and not self.app._bg_task.done():
            return (
                "# Paper Trading Already Running\n\n"
                "Use `agent:stop` to cancel, or `agent:status` to check progress."
            )

        orch = self._new_orchestrator()
        orch._mode = "paper"  # set eagerly so agent:status shows correct mode
        self.app._bg_stop.clear()

        symbols_str = params.get("symbols", ",".join(self.default_symbols))
        symbols = [s.strip().upper() for s in symbols_str.split(",")]
        duration = params.get("duration", "7d")

        # PDT protection
        pdt_val = params.get("pdt")
        pdt_protection = None
        if pdt_val is not None:
            pdt_protection = pdt_val.lower() not in ("false", "no", "0", "off")

        config = {
            "strategy": params.get("strategy", "buy_the_dip"),
            "symbols": symbols,
            "duration_seconds": parse_duration(duration),
            "poll_interval_seconds": int(params.get("poll", "300")),
            "extended_hours": params.get("hours") == "extended",
            "email_notifications": params.get("email", "true").lower() not in ("false", "no", "0", "off"),
            "pdt_protection": pdt_protection,
        }

        run_id = orch.run_id
        log_path = Path("data/paper_trade.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stop_event = self.app._bg_stop

        async def _run_paper():
            # Redirect logs to file so they don't flood the console
            root = logging.getLogger()
            original_handlers = root.handlers[:]
            file_handler = logging.FileHandler(str(log_path), mode="w")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
            )
            # Swap: remove console handlers, add file handler
            for h in original_handlers:
                root.removeHandler(h)
            root.addHandler(file_handler)
            try:
                result = await asyncio.to_thread(
                    orch.run_paper_trade, config, stop_event=stop_event
                )
                # Notify TUI when done
                if hasattr(self.app, 'notify'):
                    trades = result.get("total_trades", 0)
                    pnl = result.get("total_pnl", 0)
                    self.app.notify(
                        f"Paper trading done: {trades} trades, P&L: ${pnl:.2f}"
                    )
            except asyncio.CancelledError:
                # Update agent state so agent:status reflects the stop
                agent_state = orch.state.get_agent("paper_trader")
                agent_state.set_idle()
                orch.state.save()
                from utils.agent_storage import update_run
                update_run(orch.run_id, "cancelled")
            finally:
                # Restore original console handlers
                root.removeHandler(file_handler)
                file_handler.close()
                for h in original_handlers:
                    root.addHandler(h)

        self.app._bg_task = asyncio.create_task(_run_paper())

        return (
            f"# Paper Trading Started\n\n"
            f"- **Run ID**: `{run_id}`\n"
            f"- **Duration**: {duration}\n"
            f"- **Strategy**: {config['strategy']}\n"
            f"- **Symbols**: {', '.join(symbols)}\n"
            f"- **Poll Interval**: {config['poll_interval_seconds']}s\n"
            f"- **Log**: `{log_path}`\n\n"
            f"Running in background. Use `agent:status` to monitor, "
            f"`agent:stop` to cancel."
        )

    # ------------------------------------------------------------------
    # agent:full
    # ------------------------------------------------------------------

    async def _agent_full(self, params: Dict) -> str:
        """Run full cycle: backtest -> validate -> paper -> validate."""
        from agents.orchestrator import parse_duration

        orch = self._new_orchestrator()
        symbols_str = params.get("symbols", ",".join(self.default_symbols))
        symbols = [s.strip().upper() for s in symbols_str.split(",")]
        duration = params.get("duration", "1m")

        # PDT protection
        pdt_val = params.get("pdt")
        pdt_protection = None
        if pdt_val is not None:
            pdt_protection = pdt_val.lower() not in ("false", "no", "0", "off")

        config = {
            "strategy": params.get("strategy", "buy_the_dip"),
            "symbols": symbols,
            "lookback": params.get("lookback", "3m"),
            "initial_capital": float(params.get("capital", self.default_capital)),
            "duration_seconds": parse_duration(duration),
            "poll_interval_seconds": int(params.get("poll", "300")),
            "extended_hours": params.get("hours") == "extended",
            "intraday_exit": params.get("intraday_exit", "false").lower() in ("true", "yes", "1", "on"),
            "pdt_protection": pdt_protection,
        }

        result = await asyncio.to_thread(orch.run_full, config)

        status = result.get("status", "unknown")
        phases = result.get("phases", {})

        md = f"# Full Cycle: {status.upper()}\n\n"
        md += f"- **Run ID**: `{result.get('run_id', '')}`\n\n"

        # Backtest phase
        bt = phases.get("backtest", {})
        if bt and "error" not in bt:
            best = bt.get("best_config", {})
            md += (
                f"## Backtest\n"
                f"- Variations: {bt.get('total_variations')}\n"
                f"- Best Sharpe: {best.get('sharpe_ratio', 0):.2f}\n"
                f"- Best Return: {best.get('total_return', 0):.1f}%\n\n"
            )

        # Backtest validation
        bv = phases.get("backtest_validation", {})
        if bv:
            md += (
                f"## Backtest Validation: {bv.get('status', 'n/a')}\n"
                f"- Anomalies: {bv.get('anomalies_found', 0)} found, "
                f"{bv.get('anomalies_corrected', 0)} corrected\n\n"
            )

        # Paper trade
        pt = phases.get("paper_trade", {})
        if pt and "error" not in pt:
            md += (
                f"## Paper Trade\n"
                f"- Trades: {pt.get('total_trades', 0)}\n"
                f"- P&L: ${pt.get('total_pnl', 0):.2f}\n\n"
            )

        # Paper validation
        pv = phases.get("paper_trade_validation", {})
        if pv:
            md += (
                f"## Paper Validation: {pv.get('status', 'n/a')}\n"
                f"- Anomalies: {pv.get('anomalies_found', 0)} found\n"
            )

        return md

    # ------------------------------------------------------------------
    # agent:reconcile
    # ------------------------------------------------------------------

    async def _agent_reconcile(self, params: Dict) -> str:
        """Run reconciliation against Alpaca actual holdings."""
        orch = self._new_orchestrator()

        window_str = params.get("window", "7d")
        # Parse window: "7d" -> 7
        window_days = int(window_str.rstrip("d")) if window_str.endswith("d") else int(window_str)

        config = {"window_days": window_days}
        result = await asyncio.to_thread(orch.run_reconciliation, config)

        if "error" in result:
            return f"# Reconciliation Failed\n\n```\n{result['error']}\n```"

        status = result.get("status", "unknown")
        total_issues = result.get("total_issues", 0)

        md = f"# Reconciliation: {status.upper()}\n\n"
        md += f"- **Total Issues**: {total_issues}\n\n"

        # Position mismatches
        pos = result.get("position_mismatches", [])
        if pos:
            md += "## Position Mismatches\n\n"
            md += "| Type | Symbol | Details |\n|------|--------|---------|\n"
            for p in pos:
                md += f"| {p.get('type', '')} | {p.get('symbol', '')} | {p.get('message', '')} |\n"
            md += "\n"

        # Missing trades (in Alpaca not in DB)
        missing = result.get("missing_trades", [])
        if missing:
            md += f"## Missing Trades ({len(missing)} in Alpaca, not in DB)\n\n"
            md += "| Symbol | Side | Qty | Filled At |\n|--------|------|-----|-----------|\n"
            for t in missing[:20]:
                md += f"| {t.get('symbol', '')} | {t.get('side', '')} | {t.get('qty', '')} | {str(t.get('filled_at', ''))[:19]} |\n"
            md += "\n"

        # Extra trades (in DB not in Alpaca)
        extra = result.get("extra_trades", [])
        if extra:
            md += f"## Extra Trades ({len(extra)} in DB, not in Alpaca)\n\n"
            md += "| Symbol | Side | Message |\n|--------|------|---------|\n"
            for t in extra[:20]:
                md += f"| {t.get('symbol', '')} | {t.get('side', '')} | {t.get('message', '')} |\n"
            md += "\n"

        # P&L comparison
        pnl = result.get("pnl_comparison", {})
        if pnl:
            md += "## P&L Comparison\n\n"
            md += "| Metric | Value |\n|--------|-------|\n"
            md += f"| Alpaca Equity | ${pnl.get('alpaca_equity', 0):,.2f} |\n"
            md += f"| Alpaca Cash | ${pnl.get('alpaca_cash', 0):,.2f} |\n"
            md += f"| Alpaca Portfolio Value | ${pnl.get('alpaca_portfolio_value', 0):,.2f} |\n"
            md += f"| DB Total P&L | ${pnl.get('db_total_pnl', 0):,.2f} |\n"

        return md

    # ------------------------------------------------------------------
    # agent:status
    # ------------------------------------------------------------------

    def _agent_status(self) -> str:
        """Show current agent states."""
        orch = self.app._orch
        if orch is None:
            return "# Agent Status\n\nNo session active. Run an `agent:*` command first.\n"

        # Use instance mode (not persisted state which may be stale)
        mode = getattr(orch, '_mode', None) or orch.state.mode or 'n/a'
        bg_running = self.app._bg_task and not self.app._bg_task.done()
        bg_done = self.app._bg_task and self.app._bg_task.done()

        # Header with status
        if bg_running:
            status_label = "RUNNING"
        elif bg_done:
            status_label = "COMPLETED"
        else:
            status_label = "IDLE"

        md = f"# {mode.replace('_', ' ').title()} — {status_label}\n\n"
        md += f"- **Run ID**: `{orch.run_id}`\n"

        # Show started time in ET
        from utils.tz_util import format_et
        started = orch.state.started_at or 'n/a'
        if started != 'n/a':
            started = format_et(started)
        md += f"- **Started**: {started}\n\n"

        # Agents table — only show agents relevant to the mode
        md += "| Agent | Status | Task |\n|-------|--------|------|\n"
        for name, agent in orch.state.agents.items():
            md += f"| {name} | {agent.status} | {agent.current_task or '-'} |\n"

        # Best config (only for modes that involve backtesting)
        if orch.state.best_config and mode in ('backtest', 'full'):
            best = orch.state.best_config
            md += (
                f"\n## Best Config\n"
                f"- Sharpe: {best.get('sharpe_ratio', 0):.2f}\n"
                f"- Return: {best.get('total_return', 0):.1f}%\n"
                f"- Annualized: {best.get('annualized_return', 0):.1f}%\n"
            )

        # Last validation (only if we ran validation)
        if orch.state.validation_results and mode in ('validate', 'full'):
            last = orch.state.validation_results[-1]
            md += (
                f"\n## Last Validation\n"
                f"- Status: {last.get('status')}\n"
                f"- Anomalies: {last.get('anomalies_found', 0)}\n"
            )

        # Show elapsed time for paper trading
        if mode == 'paper' and started != 'n/a':
            try:
                from datetime import timezone as tz
                started_dt = orch.state.started_at
                if started_dt:
                    elapsed = datetime.now(tz.utc) - started_dt
                    hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                    mins, secs = divmod(remainder, 60)
                    md += f"\n**Elapsed**: {hours}h {mins}m {secs}s\n"
            except Exception:
                pass

        # Show recent log lines for paper trading
        if mode == 'paper' and (bg_running or bg_done):
            log_path = Path("data/paper_trade.log")
            if log_path.exists():
                try:
                    lines = log_path.read_text().splitlines()
                    tail = lines[-10:] if len(lines) > 10 else lines
                    if tail:
                        md += "\n## Recent Logs\n```\n"
                        md += "\n".join(tail)
                        md += "\n```\n"
                except Exception:
                    pass

        return md

    # ------------------------------------------------------------------
    # agent:runs (DB query)
    # ------------------------------------------------------------------

    def _agent_runs(self) -> str:
        """List recent runs from alpatrade.runs."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT run_id, mode, strategy, status, started_at, completed_at
                        FROM alpatrade.runs
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                )
                rows = result.fetchall()

            if not rows:
                return "# Runs\n\nNo runs found in database."

            from utils.tz_util import format_et
            md = "# Recent Runs\n\n"
            md += "| Run ID | Mode | Strategy | Status | Started (ET) |\n"
            md += "|--------|------|----------|--------|--------------|\n"
            for r in rows:
                short_id = str(r[0])[:8]
                started = format_et(r[4]) if r[4] else "-"
                md += f"| `{short_id}...` | {r[1]} | {r[2] or '-'} | {r[3]} | {started} |\n"

            md += f"\n*{len(rows)} runs shown*"
            return md

        except Exception as e:
            return f"# Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # agent:trades (DB query)
    # ------------------------------------------------------------------

    def _agent_trades(self, params: Dict) -> str:
        """Query trades from alpatrade.trades."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            run_id = params.get("run-id")
            trade_type = params.get("type")
            limit = int(params.get("limit", "20"))

            pool = DatabasePool()
            with pool.get_session() as session:
                where_clauses = []
                bind = {}
                if run_id:
                    where_clauses.append("run_id = :run_id")
                    bind["run_id"] = run_id
                if trade_type:
                    where_clauses.append("trade_type = :trade_type")
                    bind["trade_type"] = trade_type

                where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

                result = session.execute(
                    text(f"""
                        SELECT symbol, direction, shares, entry_price, exit_price,
                               pnl, pnl_pct, trade_type, run_id
                        FROM alpatrade.trades
                        {where_sql}
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {**bind, "lim": limit},
                )
                rows = result.fetchall()

            if not rows:
                return "# Trades\n\nNo trades found."

            md = "# Trades\n\n"
            md += "| Symbol | Dir | Shares | Entry | Exit | P&L | P&L% | Type |\n"
            md += "|--------|-----|--------|-------|------|-----|------|------|\n"
            for r in rows:
                pnl_str = f"${float(r[5] or 0):.2f}"
                pct_str = f"{float(r[6] or 0):.2f}%"
                md += (
                    f"| {r[0]} | {r[1]} | {float(r[2] or 0):.0f} | "
                    f"${float(r[3] or 0):.2f} | ${float(r[4] or 0):.2f} | "
                    f"{pnl_str} | {pct_str} | {r[7]} |\n"
                )

            md += f"\n*{len(rows)} trades shown*"
            return md

        except Exception as e:
            return f"# Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # agent:report
    # ------------------------------------------------------------------

    def _agent_report(self, params: Dict) -> str:
        """Generate performance report from DB data."""
        try:
            from agents.report_agent import ReportAgent
            from utils.tz_util import format_et

            agent = ReportAgent()
            run_id = params.get("run-id")

            # Detail mode: single run
            if run_id:
                data = agent.detail(run_id)
                if not data:
                    return f"# Report\n\nRun `{run_id}` not found."

                short_id = str(data["run_id"])[:8]
                ds = format_et(data["data_start"], "%Y-%m-%d") if data.get("data_start") else "-"
                de = format_et(data["data_end"], "%Y-%m-%d") if data.get("data_end") else "-"
                rd = format_et(data["run_date"], "%Y-%m-%d %H:%M ET") if data.get("run_date") else "-"
                w = data["winning_trades"]
                l = data["losing_trades"]

                md = f"# Report: {short_id}...\n\n"
                md += "| Metric | Value |\n|--------|-------|\n"
                md += f"| Mode | {data['mode']} |\n"
                md += f"| Strategy | {data['strategy'] or '-'} |\n"
                if data.get("strategy_slug"):
                    md += f"| Strategy Slug | `{data['strategy_slug']}` |\n"
                md += f"| Status | {data['status']} |\n"
                md += f"| Data Period | {ds} → {de} |\n"
                md += f"| Run Date | {rd} |\n"
                md += f"| Initial Capital | ${data['initial_capital']:,.2f} |\n"
                md += f"| Final Capital | ${data['final_capital']:,.2f} |\n"
                md += f"| Total P&L | ${data['total_pnl']:,.2f} |\n"
                md += f"| Total Return | {data['total_return']:.2f}% |\n"
                md += f"| Annualized Return | {data['annualized_return']:.2f}% |\n"
                md += f"| Sharpe Ratio | {data['sharpe_ratio']:.2f} |\n"
                md += f"| Max Drawdown | {data['max_drawdown']:.2f}% |\n"
                md += f"| Win Rate | {data['win_rate']:.1f}% |\n"
                md += f"| Trades (W/L) | {data['total_trades']} ({w}W / {l}L) |\n"
                return md

            # Summary mode: list of runs
            trade_type = params.get("type")
            strategy_filter = params.get("strategy")
            limit = int(params.get("limit", "10"))
            rows = agent.summary(trade_type=trade_type, limit=limit)

            # Filter by strategy slug prefix if provided
            if strategy_filter:
                rows = [r for r in rows
                        if r.get("strategy_slug") and
                        r["strategy_slug"].startswith(strategy_filter)]

            if not rows:
                msg = "# Performance Summary\n\nNo runs found."
                if strategy_filter:
                    msg += f" (filter: `{strategy_filter}`)"
                return msg

            md = "# Performance Summary"
            if strategy_filter:
                md += f" (filter: `{strategy_filter}`)"
            md += "\n\n"
            md += "| Run | Slug | Period | Ran | Cap | P&L | Ret | Ann | Sharpe | # | Status |\n"
            md += "|-----|------|--------|-----|-----|-----|-----|-----|--------|---|--------|\n"
            for r in rows:
                short_id = str(r["run_id"])[:6]
                ds = format_et(r["data_start"], "%m/%d") if r.get("data_start") else "-"
                de = format_et(r["data_end"], "%m/%d") if r.get("data_end") else "-"
                period = f"{ds}-{de}" if ds != "-" else "-"
                rd = format_et(r["run_date"], "%m/%d") if r.get("run_date") else "-"
                cap = r['initial_capital']
                cap_str = f"${cap / 1000:.0f}k" if cap >= 1000 else f"${cap:.0f}"
                pnl = r['total_pnl']
                pnl_str = f"${pnl / 1000:.1f}k" if abs(pnl) >= 1000 else f"${pnl:.0f}"
                ret_str = f"{r['total_return']:.1f}%"
                ann_str = f"{r['annualized_return']:.0f}%" if r["annualized_return"] else "-"
                sharpe_str = f"{r['sharpe_ratio']:.2f}" if r["sharpe_ratio"] else "-"
                slug_str = r.get('strategy_slug') or '-'
                md += (
                    f"| `{short_id}` | {slug_str} | {period} | {rd} | {cap_str} | "
                    f"{pnl_str} | {ret_str} | {ann_str} | {sharpe_str} | "
                    f"{r['total_trades']} | {r['status']} |\n"
                )

            md += f"\n*{len(rows)} runs shown*"
            return md

        except Exception as e:
            return f"# Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # agent:top
    # ------------------------------------------------------------------

    def _agent_top(self, params: Dict) -> str:
        """Rank strategy slugs by average annualized return."""
        try:
            from agents.report_agent import ReportAgent

            agent = ReportAgent()
            strategy = params.get("strategy")
            limit = int(params.get("limit", "20"))
            rows = agent.top_strategies(strategy=strategy, limit=limit)

            if not rows:
                msg = "# Top Strategies\n\nNo strategy slugs found."
                if strategy:
                    msg += f" (filter: `{strategy}`)"
                return msg

            md = "# Top Strategies"
            if strategy:
                md += f" (filter: `{strategy}`)"
            md += "\n\n"
            md += "| # | Strategy Slug | Avg Sharpe | Avg Ret | Avg Ann | Win% | Avg DD | Avg P&L | Trades | Runs |\n"
            md += "|---|---------------|------------|---------|---------|------|--------|---------|--------|------|\n"
            for i, r in enumerate(rows, 1):
                pnl = r['avg_pnl']
                pnl_str = f"${pnl / 1000:.1f}k" if abs(pnl) >= 1000 else f"${pnl:.0f}"
                md += (
                    f"| {i} | `{r['strategy_slug']}` | "
                    f"{r['avg_sharpe']:.2f} | "
                    f"{r['avg_return']:.1f}% | "
                    f"{r['avg_ann_return']:.0f}% | "
                    f"{r['avg_win_rate']:.0f}% | "
                    f"{r['avg_drawdown']:.1f}% | "
                    f"{pnl_str} | "
                    f"{r['total_trades']} | "
                    f"{r['total_runs']} |\n"
                )

            md += f"\n*{len(rows)} strategies shown*"
            return md

        except Exception as e:
            return f"# Error\n\n```\n{e}\n```"

    # ------------------------------------------------------------------
    # agent:stop
    # ------------------------------------------------------------------

    def _agent_stop(self) -> str:
        """Stop background paper trading."""
        if self.app._bg_task and not self.app._bg_task.done():
            self.app._bg_stop.set()
            self.app._bg_task.cancel()
            return "# Paper Trading Stopped\n\nBackground task cancelled."
        return "# No Background Task\n\nNo paper trading session is currently running."

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_help(self) -> str:
        """Show help as compact Rich tables."""
        from rich.table import Table
        from rich.columns import Columns
        from rich.panel import Panel
        from rich.text import Text

        c = self.console

        c.print()
        c.print("[bold cyan]AlpaTrade CLI — Help[/bold cyan]")
        c.print()

        # --- Column 1: Agent commands ---
        col1 = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        col1.add_column(style="bold yellow", no_wrap=True)
        col1.add_column(style="dim")

        col1.add_row("[bold white]Backtest[/bold white]", "")
        col1.add_row("agent:backtest lookback:1m", "1-month backtest")
        col1.add_row("  symbols:AAPL,TSLA", "custom symbols")
        col1.add_row("  hours:extended", "pre/after-market")
        col1.add_row("  intraday_exit:true", "5-min TP/SL bars")
        col1.add_row("  pdt:false", "disable PDT rule")
        col1.add_row("", "")
        col1.add_row("[bold white]Validate[/bold white]", "")
        col1.add_row("agent:validate run-id:<uuid>", "validate a run")
        col1.add_row("  source:paper_trade", "validate paper trades")
        col1.add_row("", "")
        col1.add_row("[bold white]Reconcile[/bold white]", "")
        col1.add_row("agent:reconcile", "DB vs Alpaca (7d)")
        col1.add_row("  window:14d", "custom window")

        # --- Column 2: Paper / Full / Query ---
        col2 = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        col2.add_column(style="bold yellow", no_wrap=True)
        col2.add_column(style="dim")

        col2.add_row("[bold white]Paper Trade[/bold white]", "")
        col2.add_row("agent:paper duration:7d", "run in background")
        col2.add_row("  symbols:AAPL,MSFT poll:60", "custom config")
        col2.add_row("  hours:extended", "extended hours")
        col2.add_row("  email:false", "disable email reports")
        col2.add_row("  pdt:false", "disable PDT rule")
        col2.add_row("", "")
        col2.add_row("[bold white]Full Cycle[/bold white]", "BT > Val > PT > Val")
        col2.add_row("agent:full lookback:1m duration:1m", "")
        col2.add_row("  hours:extended", "extended hours")
        col2.add_row("", "")
        col2.add_row("[bold white]Query & Monitor[/bold white]", "")
        col2.add_row("trades / runs", "DB tables")
        col2.add_row("agent:report", "performance summary")
        col2.add_row("  type:backtest run-id:<uuid>", "filter / detail")
        col2.add_row("  strategy:btd", "filter by slug prefix")
        col2.add_row("agent:top", "rank strategies by Avg Ann Return")
        col2.add_row("  strategy:btd", "filter by slug prefix")
        col2.add_row("agent:status", "agent states")
        col2.add_row("agent:stop", "stop background task")

        # --- Column 3: Research & Options ---
        col3 = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        col3.add_column(style="bold yellow", no_wrap=True)
        col3.add_column(style="dim")

        col3.add_row("[bold white]Research[/bold white]", "")
        col3.add_row("news:TSLA", "company news")
        col3.add_row("  provider:xai|tavily", "force provider")
        col3.add_row("profile:TSLA", "company profile")
        col3.add_row("financials:AAPL", "income & balance sheet")
        col3.add_row("price:TSLA", "quote & technicals")
        col3.add_row("movers", "top gainers & losers")
        col3.add_row("analysts:AAPL", "ratings & targets")
        col3.add_row("valuation:AAPL,MSFT", "valuation comparison")
        col3.add_row("", "")
        col3.add_row("[bold white]Options[/bold white]", "")
        col3.add_row("hours:extended", "4AM-8PM ET")
        col3.add_row("intraday_exit:true", "5-min bar exits")
        col3.add_row("pdt:false", "disable PDT (>$25k)")
        col3.add_row("", "")
        col3.add_row("[bold white]General[/bold white]", "")
        col3.add_row("help / guide / status / q", "")
        col3.add_row("", "")
        col3.add_row("[bold white]Tips[/bold white]", "")
        col3.add_row("Tab", "autocomplete commands")
        col3.add_row("agent:stop", "stop any background task")
        col3.add_row("(any question)", "ask AI about stocks, portfolio")

        c.print(Columns([col1, col2, col3], equal=True, expand=True))
        c.print()
        return ""

    def _show_guide(self) -> str:
        """Open the user guide in the browser."""
        import webbrowser
        url = "https://alpatrade.dev/guide"
        try:
            webbrowser.open(url)
            return f"# User Guide\n\nOpened [{url}]({url}) in your browser."
        except Exception:
            return f"# User Guide\n\nVisit the full guide at: [{url}]({url})"

    def _show_status(self) -> str:
        """Show current status and configuration."""
        return f"""# Current Configuration

## Default Settings
- **Symbols**: {', '.join(self.default_symbols)}
- **Initial Capital**: ${self.default_capital:,}
- **Position Size**: {self.default_position_size}%

## Recent Commands
{self._format_command_history()}

Type 'help' for available commands.
"""

    def _format_command_history(self) -> str:
        """Format command history."""
        if not self.app.command_history:
            return "No commands executed yet."

        history = self.app.command_history[-5:]
        return "\n".join([f"{i+1}. `{cmd}`" for i, cmd in enumerate(history)])

    # ------------------------------------------------------------------
    # Legacy backtest handlers (unchanged)
    # ------------------------------------------------------------------

    async def _handle_backtest(self, command: str) -> str:
        """Handle alpaca:backtest command."""
        try:
            params = self._parse_backtest_command(command)

            if 'strategy' not in params:
                return "# Error\n\nMissing required parameter: `strategy`\n\nExample: `alpaca:backtest strategy:buy-the-dip lookback:1m`"
            if 'lookback' not in params:
                return "# Error\n\nMissing required parameter: `lookback`\n\nExample: `alpaca:backtest strategy:buy-the-dip lookback:1m`"

            end_date = datetime.now()
            lookback = params['lookback']
            start_date = self._calculate_start_date(end_date, lookback)

            strategy = params['strategy']
            symbols = params.get('symbols', self.default_symbols)
            initial_capital = params.get('capital', self.default_capital)
            position_size = params.get('position', self.default_position_size)
            interval = params.get('interval', '1d')

            if strategy == 'buy-the-dip':
                dip_threshold = params.get('dip', 2.0)
                hold_days = params.get('hold', 1)
                take_profit = params.get('takeprofit', 1.0)
                stop_loss = params.get('stoploss', 0.5)
                data_source = params.get('data_source', 'massive').replace('polygon', 'massive').replace('polymarket', 'massive')

                return await self._run_buy_the_dip_backtest(
                    symbols=symbols, start_date=start_date, end_date=end_date,
                    initial_capital=initial_capital, position_size=position_size,
                    dip_threshold=dip_threshold, hold_days=hold_days,
                    take_profit=take_profit, stop_loss=stop_loss,
                    interval=interval, data_source=data_source
                )

            elif strategy == 'momentum':
                lookback_period = params.get('lookback_period', 20)
                momentum_threshold = params.get('momentum_threshold', 5.0)
                hold_days = params.get('hold', 5)
                take_profit = params.get('takeprofit', 10.0)
                stop_loss = params.get('stoploss', 5.0)
                data_source = params.get('data_source', 'massive').replace('polygon', 'massive').replace('polymarket', 'massive')

                return await self._run_momentum_backtest(
                    symbols=symbols, start_date=start_date, end_date=end_date,
                    initial_capital=initial_capital, position_size=position_size,
                    lookback_period=lookback_period, momentum_threshold=momentum_threshold,
                    hold_days=hold_days, take_profit=take_profit, stop_loss=stop_loss,
                    interval=interval, data_source=data_source
                )
            else:
                return f"# Error\n\nUnknown strategy: `{strategy}`\n\nAvailable strategies: buy-the-dip, momentum"

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            return f"# Error\n\n```\n{str(e)}\n\n{error_trace}\n```"

    def _parse_backtest_command(self, command: str) -> Dict[str, Any]:
        """Parse backtest command into parameters."""
        params = {}
        parts = command.split()

        for part in parts[1:]:
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.lower()
                if key == 'strategy':
                    params['strategy'] = value.lower()
                elif key == 'lookback':
                    params['lookback'] = value.lower()
                elif key == 'symbols':
                    params['symbols'] = [s.strip().upper() for s in value.split(',')]
                elif key == 'capital':
                    params['capital'] = float(value)
                elif key == 'position':
                    params['position'] = float(value)
                elif key == 'dip':
                    params['dip'] = float(value)
                elif key == 'hold':
                    params['hold'] = int(value)
                elif key == 'takeprofit':
                    params['takeprofit'] = float(value)
                elif key == 'stoploss':
                    params['stoploss'] = float(value)
                elif key == 'interval':
                    params['interval'] = value.lower()
                elif key == 'lookback_period':
                    params['lookback_period'] = int(value)
                elif key == 'momentum_threshold':
                    params['momentum_threshold'] = float(value)
                elif key == 'data_source':
                    params['data_source'] = value.lower()

        return params

    def _calculate_start_date(self, end_date: datetime, lookback: str) -> datetime:
        """Calculate start date from lookback period."""
        if lookback.endswith('m'):
            months = int(lookback[:-1])
            return end_date - timedelta(days=months * 30)
        elif lookback.endswith('y'):
            years = int(lookback[:-1])
            return end_date - timedelta(days=years * 365)
        else:
            raise ValueError(f"Invalid lookback format: {lookback}. Use format like '1m', '3m', '1y'")

    async def _run_buy_the_dip_backtest(self, symbols, start_date, end_date,
                                         initial_capital, position_size,
                                         dip_threshold, hold_days, take_profit,
                                         stop_loss, interval, data_source) -> str:
        """Run buy-the-dip backtest and return markdown results."""
        from utils.backtester_util import backtest_buy_the_dip
        import pandas as pd

        results = backtest_buy_the_dip(
            symbols=symbols, start_date=start_date, end_date=end_date,
            initial_capital=initial_capital, position_size=position_size / 100,
            dip_threshold=dip_threshold / 100, hold_days=hold_days,
            take_profit=take_profit / 100, stop_loss=stop_loss / 100,
            interval=interval, data_source=data_source,
            include_taf_fees=True, include_cat_fees=True
        )

        if results is not None:
            trades_df, _, _ = results
            output_dir = Path("backtest-results")
            output_dir.mkdir(exist_ok=True)
            from utils.tz_util import now_et
            timestamp = now_et().strftime("%Y%m%d_%H%M%S")
            filename = f"backtests_details_buy_the_dip_{timestamp}.csv"
            trades_df.to_csv(output_dir / filename, index=False)

        if results is None:
            return "# No Results\n\nNo trades were generated. Try adjusting parameters."

        trades_df, metrics, _ = results
        return self._format_backtest_results(
            strategy="Buy-The-Dip", symbols=symbols, start_date=start_date,
            end_date=end_date, initial_capital=initial_capital,
            trades_df=trades_df, metrics=metrics,
            params={
                'Position Size': f"{position_size}%", 'Dip Threshold': f"{dip_threshold}%",
                'Hold Days': hold_days, 'Take Profit': f"{take_profit}%",
                'Stop Loss': f"{stop_loss}%", 'Interval': interval
            }
        )

    async def _run_momentum_backtest(self, symbols, start_date, end_date,
                                      initial_capital, position_size,
                                      lookback_period, momentum_threshold,
                                      hold_days, take_profit, stop_loss,
                                      interval, data_source) -> str:
        """Run momentum backtest and return markdown results."""
        from utils.backtester_util import backtest_momentum_strategy
        import pandas as pd

        results = backtest_momentum_strategy(
            symbols=symbols, start_date=start_date, end_date=end_date,
            initial_capital=initial_capital, position_size_pct=position_size,
            lookback_period=lookback_period, momentum_threshold=momentum_threshold,
            hold_days=hold_days, take_profit_pct=take_profit, stop_loss_pct=stop_loss,
            interval=interval, data_source=data_source,
            include_taf_fees=True, include_cat_fees=True
        )

        if results is not None:
            trades_df, _, _ = results
            output_dir = Path("backtest-results")
            output_dir.mkdir(exist_ok=True)
            from utils.tz_util import now_et
            timestamp = now_et().strftime("%Y%m%d_%H%M%S")
            filename = f"backtests_details_momentum_{timestamp}.csv"
            trades_df.to_csv(output_dir / filename, index=False)

        if results is None:
            return "# No Results\n\nNo trades were generated. Try adjusting parameters."

        trades_df, metrics, _ = results
        return self._format_backtest_results(
            strategy="Momentum", symbols=symbols, start_date=start_date,
            end_date=end_date, initial_capital=initial_capital,
            trades_df=trades_df, metrics=metrics,
            params={
                'Position Size': f"{position_size}%",
                'Lookback Period': f"{lookback_period} days",
                'Momentum Threshold': f"{momentum_threshold}%",
                'Hold Days': hold_days, 'Take Profit': f"{take_profit}%",
                'Stop Loss': f"{stop_loss}%", 'Interval': interval
            }
        )

    def _format_backtest_results(self, strategy, symbols, start_date, end_date,
                                  initial_capital, trades_df, metrics, params) -> str:
        """Format backtest results as markdown."""
        import pandas as pd

        md = f"# {strategy} Strategy Backtest Results\n\n"
        md += "## Configuration\n\n"
        md += f"- **Symbols**: {', '.join(symbols)}\n"
        from utils.tz_util import format_et
        md += f"- **Period**: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n"
        md += f"- **Initial Capital**: ${initial_capital:,.2f}\n"
        for key, value in params.items():
            md += f"- **{key}**: {value}\n"
        md += "\n"

        md += "## Performance Metrics\n\n"
        md += "| Metric | Value |\n|--------|-------|\n"
        md += f"| Total Return | {metrics['total_return']:.2f}% |\n"
        md += f"| Total P&L | ${metrics['total_pnl']:,.2f} |\n"
        md += f"| Annualized Return | {metrics['annualized_return']:.2f}% |\n"
        md += f"| Total Trades | {metrics['total_trades']} |\n"
        md += f"| Win Rate | {metrics['win_rate']:.1f}% |\n"
        md += f"| Max Drawdown | {metrics['max_drawdown']:.2f}% |\n"
        md += f"| Sharpe Ratio | {metrics['sharpe_ratio']:.2f} |\n\n"

        md += "## Recent Trades (Last 10)\n\n"
        recent_trades = trades_df.tail(10)
        md += "| Entry Time | Exit Time | Ticker | Shares | Entry $ | Exit $ | P&L | P&L % |\n"
        md += "|------------|-----------|--------|--------|---------|--------|-----|-------|\n"
        for _, trade in recent_trades.iterrows():
            entry_time = format_et(trade['entry_time'])
            exit_time = format_et(trade['exit_time'])
            md += (
                f"| {entry_time} | {exit_time} | {trade['ticker']} | {trade['shares']} | "
                f"${trade['entry_price']:.2f} | ${trade['exit_price']:.2f} | "
                f"${trade['pnl']:.2f} | {trade['pnl_pct']:.2f}% |\n"
            )

        final_capital = trades_df['capital_after'].iloc[-1]
        md += f"\n## Summary\n\n"
        md += (
            f"Starting with **${initial_capital:,.2f}**, the {strategy} strategy generated "
            f"**{metrics['total_trades']}** trades, resulting in a "
            f"**{metrics['total_return']:.2f}%** return (${metrics['total_pnl']:,.2f}). "
            f"Final portfolio value: **${final_capital:,.2f}**.\n"
        )

        return md
