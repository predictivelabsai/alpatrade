"""
AlpaTrade AG-UI — 3-pane chat interface powered by pydantic-ai + AG-UI protocol.

Left pane:  Auth / settings / navigation
Center:     Chat (WebSocket streaming)
Right:      Thinking trace / artifact canvas (toggled)

Launch:  python agui_app.py          # port 5003
         uvicorn agui_app:app --port 5003 --reload
"""

import os
import sys
import uuid as _uuid
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.ui import StateDeps
from fasthtml.common import *

from utils.agui import setup_agui, get_chat_styles
import threading

# ---------------------------------------------------------------------------
# pydantic-ai Agent with real tools
# ---------------------------------------------------------------------------

class AlpaTradeState(BaseModel):
    """Shared state between UI and agent — rendered in right pane."""
    last_action: str = ""

    def __ft__(self):
        if not self.last_action:
            return Div()
        return Div(
            Div(self.last_action, cls="state-value"),
            id="agui-state",
            hx_swap_oob="innerHTML",
        )


agent = Agent(
    "xai:grok-3-mini",
    name="AlpaTrade",
    instructions=(
        "You are AlpaTrade, an AI trading assistant. "
        "You have tools to look up real stock data, news, and analyst ratings. "
        "Use your tools when users ask about specific stocks or market data. "
        "Be concise and use markdown formatting with tables where appropriate. "
        "Users can type CLI commands directly in chat (e.g. agent:backtest lookback:1m, "
        "news:TSLA, trades, runs) and they will be executed automatically. "
        "For stock queries, always use the appropriate tool to get real data."
    ),
)


@agent.tool_plain
def get_stock_price(ticker: str) -> str:
    """Get current stock price and recent performance for a ticker symbol."""
    try:
        from utils.data_loader import get_intraday_data
        df = get_intraday_data(ticker.upper(), interval="1d", period="5d")
        if df.empty:
            return f"No price data found for {ticker.upper()}"
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        change = last["Close"] - prev["Close"]
        pct = (change / prev["Close"]) * 100
        sign = "+" if change >= 0 else ""
        return (
            f"**{ticker.upper()}** — ${last['Close']:.2f} "
            f"({sign}{change:.2f}, {sign}{pct:.2f}%)\n"
            f"Open: ${last['Open']:.2f} | High: ${last['High']:.2f} | "
            f"Low: ${last['Low']:.2f} | Vol: {int(last['Volume']):,}"
        )
    except Exception as e:
        return f"Error fetching price for {ticker}: {e}"


@agent.tool_plain
def get_stock_news(ticker: str, limit: int = 5) -> str:
    """Get latest news headlines for a stock ticker."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.news(ticker=ticker.upper(), limit=limit)
    except Exception as e:
        return f"Error fetching news for {ticker}: {e}"


@agent.tool_plain
def get_analyst_ratings(ticker: str) -> str:
    """Get analyst ratings and price targets for a stock."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.analysts(ticker=ticker.upper())
    except Exception as e:
        return f"Error fetching ratings for {ticker}: {e}"


@agent.tool_plain
def get_company_profile(ticker: str) -> str:
    """Get company profile, sector, and key details for a stock."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.profile(ticker=ticker.upper())
    except Exception as e:
        return f"Error fetching profile for {ticker}: {e}"


@agent.tool_plain
def get_financials(ticker: str, period: str = "annual") -> str:
    """Get financial data (revenue, earnings, margins) for a stock. Period: 'annual' or 'quarterly'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.financials(ticker=ticker.upper(), period=period)
    except Exception as e:
        return f"Error fetching financials for {ticker}: {e}"


@agent.tool_plain
def get_market_movers(direction: str = "both") -> str:
    """Get today's top market movers (gainers and losers). Direction: 'gainers', 'losers', or 'both'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.movers(direction=direction)
    except Exception as e:
        return f"Error fetching market movers: {e}"


@agent.tool_plain
def get_valuation(tickers: str) -> str:
    """Compare valuation metrics (P/E, P/B, EV/EBITDA) for multiple stocks. Pass comma-separated tickers like 'AAPL,MSFT,GOOGL'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.valuation(tickers=tickers.upper())
    except Exception as e:
        return f"Error fetching valuation: {e}"


@agent.tool_plain
def show_recent_trades(limit: int = 20) -> str:
    """Show recent trades from the AlpaTrade database."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(
                text("""
                    SELECT symbol, direction, shares, entry_price, exit_price,
                           pnl, pnl_pct, trade_type
                    FROM alpatrade.trades
                    ORDER BY created_at DESC LIMIT :lim
                """),
                {"lim": limit},
            )
            rows = result.fetchall()
        if not rows:
            return "No trades found in database."
        md = "| Symbol | Dir | Shares | Entry | Exit | P&L | P&L% | Type |\n"
        md += "|--------|-----|--------|-------|------|-----|------|------|\n"
        for r in rows:
            md += (
                f"| {r[0]} | {r[1]} | {float(r[2] or 0):.0f} | "
                f"${float(r[3] or 0):.2f} | ${float(r[4] or 0):.2f} | "
                f"${float(r[5] or 0):.2f} | {float(r[6] or 0):.2f}% | {r[7]} |\n"
            )
        return md + f"\n*{len(rows)} trades shown*"
    except Exception as e:
        return f"Error fetching trades: {e}"


@agent.tool_plain
def show_stock_chart(ticker: str, period: str = "3mo") -> str:
    """Show a price chart for a stock. Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."""
    try:
        from utils.data_loader import get_intraday_data
        interval = "1d" if period not in ("1d", "5d") else "5m"
        df = get_intraday_data(ticker.upper(), interval=interval, period=period)
        if df.empty:
            return f"No chart data for {ticker.upper()}"
        dates = [d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in df.index]
        closes = [round(float(c), 2) for c in df["Close"]]
        highs = [round(float(h), 2) for h in df["High"]]
        lows = [round(float(l), 2) for l in df["Low"]]
        import json
        chart_data = json.dumps({
            "ticker": ticker.upper(),
            "period": period,
            "dates": dates,
            "close": closes,
            "high": highs,
            "low": lows,
        })
        return f"__CHART_DATA__{chart_data}__END_CHART__"
    except Exception as e:
        return f"Error generating chart for {ticker}: {e}"


@agent.tool_plain
def show_recent_runs(limit: int = 20) -> str:
    """Show recent backtest/paper trade runs from the AlpaTrade database."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(
                text("""
                    SELECT run_id, mode, strategy, status, started_at
                    FROM alpatrade.runs
                    ORDER BY created_at DESC LIMIT :lim
                """),
                {"lim": limit},
            )
            rows = result.fetchall()
        if not rows:
            return "No runs found in database."
        md = "| Run ID | Mode | Strategy | Status | Started |\n"
        md += "|--------|------|----------|--------|---------|\n"
        for r in rows:
            short_id = str(r[0])[:8]
            started = str(r[4])[:19] if r[4] else "-"
            md += f"| `{short_id}` | {r[1]} | {r[2] or '-'} | {r[3]} | {started} |\n"
        return md + f"\n*{len(rows)} runs shown*"
    except Exception as e:
        return f"Error fetching runs: {e}"


# ---------------------------------------------------------------------------
# FastHTML app
# ---------------------------------------------------------------------------

app, rt = fast_app(
    exts="ws",
    secret_key=os.getenv("JWT_SECRET", os.urandom(32).hex()),
    hdrs=[
        Script(src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"),
        Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js"),
    ],
)

# ---------------------------------------------------------------------------
# CLI command interceptor — routes agent:*, trades, runs, news:* etc. to
# the existing CommandProcessor instead of the AI agent
# ---------------------------------------------------------------------------

class _AppState:
    """Lightweight namespace used by CommandProcessor for shared state."""
    _orch = None
    _bg_task = None
    _bg_stop = threading.Event()
    command_history: list = []

_app_state = _AppState()

# Commands that should bypass the AI agent and go to CommandProcessor
_CLI_BASES = {"news", "profile", "financials", "price", "movers", "analysts", "valuation"}
_CLI_EXACT = {"trades", "runs", "status", "help", "guide"}


async def _command_interceptor(msg: str, session):
    """Detect CLI commands and route to CommandProcessor. Returns markdown or None."""
    cmd_lower = msg.strip().lower()
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    base = first_word.split(":")[0]

    is_command = (
        first_word.startswith("agent:") or
        first_word.startswith("alpaca:") or
        cmd_lower in _CLI_EXACT or
        base in _CLI_BASES
    )

    if not is_command:
        return None

    # Special case: "help" returns chat-friendly markdown (Rich tables don't work here)
    if cmd_lower in ("help", "h", "?"):
        return _AGUI_HELP

    from tui.command_processor import CommandProcessor
    user_id = session.get("user", {}).get("user_id") if session.get("user") else None
    cp = CommandProcessor(_app_state, user_id=user_id)
    try:
        result = await cp.process_command(msg)
    except Exception as e:
        result = f"# Error\n\n```\n{e}\n```"
    return result or "Command executed."


_AGUI_HELP = """# AlpaTrade Commands

## Backtest
- `agent:backtest lookback:1m` — 1-month backtest
- `agent:backtest lookback:3m symbols:AAPL,TSLA` — custom symbols
- `agent:backtest hours:extended` — extended hours (4AM-8PM ET)
- `agent:backtest intraday_exit:true` — 5-min TP/SL bars
- `agent:backtest pdt:false` — disable PDT rule (>$25k)

## Paper Trading
- `agent:paper duration:7d` — paper trade for 7 days
- `agent:paper symbols:AAPL,MSFT poll:60` — custom config
- `agent:stop` — stop background paper trading

## Full Cycle
- `agent:full lookback:1m duration:1m` — backtest → validate → paper → validate

## Validate & Reconcile
- `agent:validate run-id:<uuid>` — validate a run
- `agent:reconcile window:14d` — DB vs Alpaca

## Query & Monitor
- `trades` — recent trades from DB
- `runs` — recent runs from DB
- `agent:report` — performance summary
- `agent:report run-id:<uuid>` — single run detail
- `agent:top` — rank strategies
- `agent:status` — agent states
- `agent:logs` — paper trade log tail

## Market Research
- `news:TSLA` — company news
- `price:AAPL` — stock quote
- `profile:MSFT` — company profile
- `analysts:GOOGL` — analyst ratings
- `financials:AAPL` — income & balance sheet
- `valuation:AAPL,MSFT` — valuation comparison
- `movers` — top gainers & losers

## AI Chat
Type any question to chat with AI about stocks & trading.
"""

agui = setup_agui(app, agent, AlpaTradeState(), AlpaTradeState,
                  command_interceptor=_command_interceptor)


# ---------------------------------------------------------------------------
# CSS — 3-pane layout
# ---------------------------------------------------------------------------

LAYOUT_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
  background: #0f172a;
  color: #e2e8f0;
  height: 100vh;
  overflow: hidden;
}

/* === 3-Pane Grid === */
.app-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100vh;
  transition: grid-template-columns 0.3s ease;
}

.app-layout .right-pane {
  display: none;
}

.app-layout.right-open {
  grid-template-columns: 260px 1fr 380px;
}

.app-layout.right-open .right-pane {
  display: flex;
}

/* === Left Pane (Sidebar) === */
.left-pane {
  background: #1e293b;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 1rem;
  gap: 1.25rem;
}

.brand {
  font-size: 1.25rem;
  font-weight: 700;
  color: #f1f5f9;
  text-decoration: none;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #334155;
}

.brand:hover { color: #3b82f6; }

.sidebar-section { display: flex; flex-direction: column; gap: 0.5rem; }

.sidebar-section h4 {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.sidebar-section a {
  color: #94a3b8;
  text-decoration: none;
  font-size: 0.85rem;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  transition: all 0.15s;
}

.sidebar-section a:hover {
  background: #334155;
  color: #f1f5f9;
}

.sidebar-section a.active {
  background: #3b82f6;
  color: white;
}

/* Auth forms in sidebar */
.sidebar-auth { display: flex; flex-direction: column; gap: 0.75rem; }

.sidebar-auth input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 0.375rem;
  color: #e2e8f0;
  font-family: inherit;
  font-size: 0.8rem;
}

.sidebar-auth input:focus {
  outline: none;
  border-color: #3b82f6;
}

.sidebar-auth button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.sidebar-auth button:hover { background: #2563eb; }

.alt-link { font-size: 0.75rem; color: #64748b; }
.alt-link a { color: #3b82f6; }

.error-msg { color: #f87171; font-size: 0.8rem; }
.success-msg { color: #4ade80; font-size: 0.8rem; }

.user-info {
  background: #0f172a;
  border-radius: 0.5rem;
  padding: 0.75rem;
  font-size: 0.8rem;
}

.user-info .name { font-weight: 600; color: #f1f5f9; }
.user-info .email { color: #64748b; font-size: 0.75rem; }

.key-status {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.7rem;
  font-weight: 500;
}
.key-status.configured { background: #065f46; color: #6ee7b7; }
.key-status.not-configured { background: #7f1d1d; color: #fca5a5; }

.keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 0.375rem;
  color: #e2e8f0;
  font-family: inherit;
  font-size: 0.8rem;
  margin-bottom: 0.5rem;
}

.keys-form input:focus { outline: none; border-color: #3b82f6; }

.keys-form button {
  width: 100%;
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.8rem;
}

/* Logout */
.logout-btn {
  display: block;
  padding: 0.35rem 0.5rem;
  color: #f87171;
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: 0.375rem;
}
.logout-btn:hover { background: #7f1d1d33; }

/* === Center Pane (Chat) === */
.center-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0f172a;
  overflow: hidden;
}

.center-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #334155;
  min-height: 3rem;
}

.center-header h2 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #f1f5f9;
}

.toggle-trace-btn {
  padding: 0.3rem 0.7rem;
  background: #334155;
  color: #94a3b8;
  border: 1px solid #475569;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.toggle-trace-btn:hover { background: #475569; color: #f1f5f9; }

.center-chat {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.center-chat > div {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* Override agui chat styles for dark theme */
.center-chat .chat-container {
  height: 100%;
  flex: 1;
  border: none;
  border-radius: 0;
  background: #0f172a;
  display: flex;
  flex-direction: column;
}

.center-chat .chat-messages {
  background: #0f172a;
  flex: 1;
}

.center-chat .chat-input {
  background: #1e293b;
  border-top: 1px solid #334155;
}

.center-chat .chat-input-field {
  background: #0f172a;
  border-color: #334155;
  color: #e2e8f0;
}

.center-chat .chat-input-field:focus {
  border-color: #3b82f6;
}

.center-chat .chat-message.chat-assistant .chat-message-content {
  background: #1e293b;
  color: #e2e8f0;
}

.center-chat .chat-message.chat-user .chat-message-content {
  background: #3b82f6;
  color: white;
}

.center-chat .chat-message.chat-tool .chat-message-content {
  background: #334155;
  color: #94a3b8;
}

.center-chat .chat-messages:empty::before {
  content: "Ask anything about stocks, trading, or type a CLI command...";
  color: #475569;
}

/* === Right Pane (Trace / Artifacts) === */
.right-pane {
  background: #1e293b;
  border-left: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #334155;
}

.right-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: #f1f5f9;
}

.close-trace-btn {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.2rem;
}
.close-trace-btn:hover { color: #f1f5f9; }

.right-tabs {
  display: flex;
  border-bottom: 1px solid #334155;
}

.right-tab {
  flex: 1;
  padding: 0.5rem;
  text-align: center;
  font-size: 0.75rem;
  color: #64748b;
  cursor: pointer;
  border: none;
  background: none;
  font-family: inherit;
}

.right-tab:hover { color: #94a3b8; }
.right-tab.active { color: #3b82f6; border-bottom: 2px solid #3b82f6; }

.right-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
}

/* === Trace Entries === */
.trace-entry {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.5rem;
  border-left: 3px solid #334155;
  border-radius: 0 0.25rem 0.25rem 0;
  background: #0f172a;
  font-size: 0.8rem;
  animation: trace-in 0.2s ease-out;
}

@keyframes trace-in {
  from { opacity: 0; transform: translateX(-0.5rem); }
  to { opacity: 1; transform: translateX(0); }
}

.trace-label {
  color: #94a3b8;
  font-weight: 500;
}

.trace-detail {
  color: #64748b;
  font-size: 0.75rem;
  font-family: ui-monospace, monospace;
  word-break: break-all;
}

.trace-run-start { border-left-color: #3b82f6; }
.trace-run-start .trace-label { color: #60a5fa; }

.trace-run-end { border-left-color: #22c55e; }
.trace-run-end .trace-label { color: #4ade80; }

.trace-streaming { border-left-color: #a78bfa; }
.trace-streaming .trace-label { color: #a78bfa; }

.trace-tool-active { border-left-color: #f59e0b; }
.trace-tool-active .trace-label { color: #fbbf24; }

.trace-tool-done { border-left-color: #22c55e; }
.trace-tool-done .trace-label { color: #4ade80; }

.trace-done { border-left-color: #22c55e; }
.trace-done .trace-label { color: #4ade80; }

.trace-error { border-left-color: #ef4444; }
.trace-error .trace-label { color: #f87171; }

#trace-content {
  font-size: 0.8rem;
  color: #94a3b8;
  overflow-y: auto;
  flex: 1;
}

/* === Artifact Pane === */
#artifact-content {
  display: none;
}

#artifact-content .artifact-chart {
  width: 100%;
  min-height: 300px;
  border-radius: 0.5rem;
  overflow: hidden;
}

#artifact-content .artifact-table {
  width: 100%;
  overflow-x: auto;
  font-size: 0.8rem;
}

/* === Query Badge === */
.query-badge {
  font-size: 0.7rem;
  color: #64748b;
  padding: 0.2rem 0.5rem;
}

/* === Help Expander === */
.help-expander { border: none; }

.help-summary {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
  cursor: pointer;
  padding: 0.25rem 0;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.help-summary::before {
  content: '\\25B6';
  font-size: 0.5rem;
  transition: transform 0.2s;
}

details[open] > .help-summary::before {
  transform: rotate(90deg);
}

.help-summary::-webkit-details-marker { display: none; }

.help-content {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.help-group {
  font-size: 0.75rem;
  color: #94a3b8;
  line-height: 1.5;
}

.help-group p {
  margin: 0;
  font-family: ui-monospace, monospace;
  font-size: 0.7rem;
  color: #64748b;
  padding-left: 0.25rem;
}

.help-cat {
  font-size: 0.7rem;
  font-weight: 600;
  color: #94a3b8;
}

/* === Responsive === */
@media (max-width: 768px) {
  .app-layout {
    grid-template-columns: 1fr !important;
  }
  .left-pane { display: none; }
  .right-pane { display: none; }
}
"""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

FREE_QUERY_LIMIT = 50


def _session_login(session, user: Dict):
    display = user.get("display_name") or ""
    if display.startswith("$2") or not display.strip():
        display = user.get("email", "user").split("@")[0]
    session["user"] = {
        "user_id": str(user["user_id"]),
        "email": user["email"],
        "display_name": display,
    }
    session["query_count"] = 0


# ---------------------------------------------------------------------------
# Left pane builder
# ---------------------------------------------------------------------------

def _left_pane(session):
    """Build the left sidebar: auth + navigation + status."""
    user = session.get("user")

    sections = [A("AlpaTrade", href="/", cls="brand")]

    # Auth section
    if user:
        name = user.get("display_name") or user.get("email", "user")
        email = user.get("email", "")

        # Check Alpaca key status
        keys_configured = False
        try:
            from utils.auth import get_alpaca_keys
            keys = get_alpaca_keys(user["user_id"])
            keys_configured = keys is not None
        except Exception:
            pass

        key_badge = (
            Span("Keys OK", cls="key-status configured")
            if keys_configured
            else Span("No keys", cls="key-status not-configured")
        )

        sections.append(
            Div(
                Div(
                    Div(name, cls="name"),
                    Div(email, cls="email"),
                    Div(key_badge, style="margin-top: 0.5rem;"),
                    cls="user-info",
                ),
                cls="sidebar-section",
            )
        )
    else:
        sections.append(
            Div(
                H4("Account"),
                Div(
                    id="auth-forms",
                    hx_get="/agui-auth/login-form",
                    hx_trigger="load",
                    hx_swap="innerHTML",
                ),
                cls="sidebar-section",
            )
        )

    # Navigation
    nav_links = [
        A("Home", href="/"),
        A("Guide", href="/guide", target="_blank"),
        A("Dashboard", href="https://alpatrade.dev", target="_blank"),
        A("Screenshots", href="/screenshots", target="_blank"),
    ]
    if user:
        nav_links.append(A("Profile", href="/profile"))
        nav_links.append(A("Logout", href="/logout", cls="logout-btn"))

    sections.append(Div(H4("Navigation"), *nav_links, cls="sidebar-section"))

    # Help expander — collapsible command reference
    sections.append(
        Details(
            Summary("Quick Reference", cls="help-summary"),
            Div(
                Div(
                    Span("Backtest", cls="help-cat"),
                    P("agent:backtest lookback:1m"),
                    P("  symbols:AAPL,TSLA hours:extended"),
                    P("  intraday_exit:true pdt:false"),
                    cls="help-group",
                ),
                Div(
                    Span("Paper Trade", cls="help-cat"),
                    P("agent:paper duration:7d"),
                    P("agent:stop"),
                    cls="help-group",
                ),
                Div(
                    Span("Research", cls="help-cat"),
                    P("news:TSLA  price:AAPL"),
                    P("analysts:GOOGL  profile:MSFT"),
                    P("financials:AAPL  movers"),
                    P("valuation:AAPL,MSFT"),
                    cls="help-group",
                ),
                Div(
                    Span("Query", cls="help-cat"),
                    P("trades  runs  agent:status"),
                    P("agent:report  agent:top"),
                    P("agent:logs"),
                    cls="help-group",
                ),
                cls="help-content",
            ),
            cls="sidebar-section help-expander",
        )
    )

    # Query status
    if not user:
        count = session.get("query_count", 0)
        remaining = max(0, FREE_QUERY_LIMIT - count)
        sections.append(
            Div(
                H4("Status"),
                Span(f"{remaining}/{FREE_QUERY_LIMIT} free queries", cls="query-badge"),
                cls="sidebar-section",
            )
        )

    return Div(*sections, cls="left-pane", id="left-pane")


# ---------------------------------------------------------------------------
# Right pane builder
# ---------------------------------------------------------------------------

def _right_pane():
    """Build the right pane: thinking trace + artifacts."""
    return Div(
        Div(
            H3("Trace"),
            Div(
                Button(
                    "Clear",
                    cls="close-trace-btn",
                    onclick="document.getElementById('trace-content').innerHTML="
                    "'<div style=\"color:#475569;font-style:italic\">"
                    "Tool calls and reasoning will appear here.</div>';",
                    style="margin-right: 0.5rem; font-size: 0.7rem;",
                ),
                Button("x", cls="close-trace-btn", onclick="toggleRightPane()"),
                style="display: flex; align-items: center;",
            ),
            cls="right-header",
        ),
        Div(
            Button("Thinking", cls="right-tab active", onclick="showTab('trace')"),
            Button("Artifacts", cls="right-tab", onclick="showTab('artifact')"),
            cls="right-tabs",
        ),
        Div(
            Div(
                Div("Tool calls and reasoning will appear here during agent runs.",
                    style="color: #475569; font-style: italic;"),
                id="trace-content",
            ),
            Div(
                Div("Charts and data will appear here when tools generate visual output.",
                    style="color: #475569; font-style: italic;"),
                id="artifact-content",
            ),
            cls="right-content",
        ),
        cls="right-pane",
    )


# ---------------------------------------------------------------------------
# Layout JS
# ---------------------------------------------------------------------------

LAYOUT_JS = """
function toggleRightPane() {
    var layout = document.querySelector('.app-layout');
    layout.classList.toggle('right-open');
}

function showTab(tab) {
    var trace = document.getElementById('trace-content');
    var artifact = document.getElementById('artifact-content');
    var tabs = document.querySelectorAll('.right-tab');

    tabs.forEach(function(t) { t.classList.remove('active'); });

    if (tab === 'trace') {
        trace.style.display = 'flex';
        artifact.style.display = 'none';
        tabs[0].classList.add('active');
    } else {
        trace.style.display = 'none';
        artifact.style.display = 'block';
        tabs[1].classList.add('active');
    }
}

/* Chart rendering — detect __CHART_DATA__ markers in assistant messages */
function renderChart(chartJson) {
    try {
        var data = JSON.parse(chartJson);
        var container = document.getElementById('artifact-content');
        if (!container || !window.Plotly) return;

        container.innerHTML = '';
        var chartDiv = document.createElement('div');
        chartDiv.id = 'plotly-chart';
        chartDiv.className = 'artifact-chart';
        container.appendChild(chartDiv);

        var trace = {
            x: data.dates,
            y: data.close,
            type: 'scatter',
            mode: 'lines',
            name: data.ticker,
            line: { color: '#3b82f6', width: 2 },
            fill: 'tozeroy',
            fillcolor: 'rgba(59, 130, 246, 0.1)',
        };

        var rangeLine = {
            x: data.dates,
            y: data.high,
            type: 'scatter',
            mode: 'lines',
            name: 'High',
            line: { color: '#22c55e', width: 1, dash: 'dot' },
            opacity: 0.5,
        };

        var lowLine = {
            x: data.dates,
            y: data.low,
            type: 'scatter',
            mode: 'lines',
            name: 'Low',
            line: { color: '#ef4444', width: 1, dash: 'dot' },
            opacity: 0.5,
        };

        var layout = {
            title: { text: data.ticker + ' — ' + data.period, font: { color: '#f1f5f9', size: 14 } },
            paper_bgcolor: '#1e293b',
            plot_bgcolor: '#0f172a',
            font: { color: '#94a3b8', family: 'ui-monospace, monospace', size: 11 },
            xaxis: { gridcolor: '#1e293b', linecolor: '#334155' },
            yaxis: { gridcolor: '#1e293b', linecolor: '#334155', tickprefix: '$' },
            legend: { orientation: 'h', y: -0.15 },
            margin: { t: 40, r: 20, b: 40, l: 60 },
            showlegend: true,
        };

        Plotly.newPlot(chartDiv, [trace, rangeLine, lowLine], layout, {
            responsive: true,
            displayModeBar: false,
        });

        // Switch to artifacts tab
        showTab('artifact');
    } catch(e) {
        console.error('Chart render error:', e);
    }
}

/* Watch for chart data markers in messages */
(function() {
    var chartObs = new MutationObserver(function() {
        document.querySelectorAll('.marked, .marked-done').forEach(function(el) {
            var text = el.textContent || '';
            var match = text.match(/__CHART_DATA__(.+?)__END_CHART__/);
            if (match) {
                renderChart(match[1]);
                // Clean up the marker from the message
                el.innerHTML = el.innerHTML.replace(/__CHART_DATA__.*?__END_CHART__/, '');
            }
        });
    });
    setTimeout(function() {
        var body = document.body;
        if (body) chartObs.observe(body, {childList: true, subtree: true, characterData: true});
    }, 500);
})();
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@rt("/")
def get(session):
    thread_id = session.get("thread_id")
    if not thread_id:
        thread_id = str(_uuid.uuid4())
        session["thread_id"] = thread_id

    return (
        Title("AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            _left_pane(session),
            Div(
                Div(
                    H2("AlpaTrade Chat"),
                    Button(
                        "Trace",
                        cls="toggle-trace-btn",
                        onclick="toggleRightPane()",
                    ),
                    cls="center-header",
                ),
                Div(agui.chat(thread_id), cls="center-chat"),
                cls="center-pane",
            ),
            _right_pane(),
            cls="app-layout",
        ),
        Script(LAYOUT_JS),
    )


# ---------------------------------------------------------------------------
# Auth routes (sidebar-based, return HTML fragments)
# ---------------------------------------------------------------------------

@rt("/agui-auth/login-form")
def login_form_fragment():
    """Return the login form for the sidebar."""
    return Div(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password", required=True),
            Button("Login", type="submit"),
            hx_post="/agui-auth/login",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "No account? ",
            A("Sign up", href="#", hx_get="/agui-auth/register-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    )


@rt("/agui-auth/register-form")
def register_form_fragment():
    """Return the register form for the sidebar."""
    return Div(
        Form(
            Input(type="email", name="email", placeholder="Email", required=True),
            Input(type="password", name="password", placeholder="Password (min 8 chars)",
                  required=True, minlength="8"),
            Input(type="text", name="display_name", placeholder="Display name (optional)"),
            Button("Create Account", type="submit"),
            hx_post="/agui-auth/register",
            hx_target="#auth-forms",
            hx_swap="innerHTML",
            cls="sidebar-auth",
        ),
        Div(
            "Have an account? ",
            A("Login", href="#", hx_get="/agui-auth/login-form",
              hx_target="#auth-forms", hx_swap="innerHTML"),
            cls="alt-link",
        ),
    )


@rt("/agui-auth/login")
def auth_login(session, email: str = "", password: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   login_form_fragment())
    from utils.auth import authenticate
    user = authenticate(email, password)
    if not user:
        return Div(P("Invalid email or password.", cls="error-msg"),
                   login_form_fragment())
    _session_login(session, user)
    # Refresh the whole page to update sidebar
    return Div(
        P("Logged in!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/agui-auth/register")
def auth_register(session, email: str = "", password: str = "", display_name: str = ""):
    if not email or not password:
        return Div(P("Email and password required.", cls="error-msg"),
                   register_form_fragment())
    if len(password) < 8:
        return Div(P("Password must be at least 8 characters.", cls="error-msg"),
                   register_form_fragment())
    from utils.auth import create_user
    user = create_user(email=email, password=password, display_name=display_name or None)
    if not user:
        return Div(P("Email already registered.", cls="error-msg"),
                   register_form_fragment())
    _session_login(session, user)
    return Div(
        P("Account created!", cls="success-msg"),
        Script("setTimeout(function(){ window.location.reload(); }, 500);"),
    )


@rt("/logout")
def logout(session):
    session.clear()
    return RedirectResponse("/", status_code=307)


@rt("/profile")
def profile(session, msg: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")

    keys_configured = False
    try:
        from utils.auth import get_alpaca_keys
        keys = get_alpaca_keys(user["user_id"])
        keys_configured = keys is not None
    except Exception:
        pass

    key_badge = (
        Span("Configured", cls="key-status configured")
        if keys_configured
        else Span("Not configured", cls="key-status not-configured")
    )

    return (
        Title("Profile — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("AlpaTrade", href="/", cls="brand"),
                Div(
                    H4("Profile"),
                    Div(
                        Div(user.get("display_name", ""), cls="name"),
                        Div(user.get("email", ""), cls="email"),
                        Div(key_badge, style="margin-top: 0.5rem;"),
                        cls="user-info",
                    ),
                    cls="sidebar-section",
                ),
                Div(
                    H4("Alpaca Paper Keys"),
                    P("Encrypted at rest. Used for paper trading.",
                      style="color: #64748b; font-size: 0.75rem; margin-bottom: 0.5rem;"),
                    Form(
                        Input(type="password", name="api_key",
                              placeholder="Alpaca Paper API Key", required=True),
                        Input(type="password", name="secret_key",
                              placeholder="Alpaca Paper Secret Key", required=True),
                        Button("Save Keys", type="submit"),
                        method="post", action="/profile/keys",
                        cls="keys-form",
                    ),
                    P(msg, cls="success-msg") if msg else "",
                    cls="sidebar-section",
                ),
                Div(
                    A("Back to Chat", href="/"),
                    A("Logout", href="/logout", cls="logout-btn"),
                    cls="sidebar-section",
                ),
                cls="left-pane",
                style="max-width: 400px; margin: 2rem auto; height: auto;",
            ),
            style="display: flex; justify-content: center; min-height: 100vh; background: #0f172a;",
        ),
    )


@rt("/profile/keys")
def profile_keys(session, api_key: str = "", secret_key: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not api_key or not secret_key:
        return RedirectResponse("/profile?msg=Both+keys+required")
    from utils.auth import store_alpaca_keys
    store_alpaca_keys(user["user_id"], api_key, secret_key)
    return RedirectResponse("/profile?msg=Keys+saved+successfully", status_code=303)


# ---------------------------------------------------------------------------
# Static content routes (open in new tabs from sidebar)
# ---------------------------------------------------------------------------

@rt("/guide")
def guide(session):
    """Minimal guide redirect — full guide lives on web_app.py."""
    return (
        Title("Guide — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("AlpaTrade", href="/", cls="brand"),
                Div(
                    H4("Quick Reference"),
                    P("Full guide available at ",
                      A("alpatrade.chat/guide", href="https://alpatrade.chat/guide",
                        target="_blank"),
                      style="font-size: 0.85rem; color: #94a3b8;"),
                    cls="sidebar-section",
                ),
                Div(
                    H4("Common Commands"),
                    P("agent:backtest lookback:1m", style="font-size: 0.8rem;"),
                    P("agent:paper duration:7d", style="font-size: 0.8rem;"),
                    P("price AAPL", style="font-size: 0.8rem;"),
                    P("news TSLA", style="font-size: 0.8rem;"),
                    P("trades / runs / status", style="font-size: 0.8rem;"),
                    cls="sidebar-section",
                ),
                Div(A("Back to Chat", href="/"), cls="sidebar-section"),
                cls="left-pane",
                style="max-width: 400px; margin: 2rem auto; height: auto;",
            ),
            style="display: flex; justify-content: center; min-height: 100vh; background: #0f172a;",
        ),
    )


@rt("/screenshots")
def screenshots():
    """Redirect to main app screenshots."""
    return RedirectResponse("https://alpatrade.chat/screenshots", status_code=307)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agui_app:app",
        host="0.0.0.0",
        port=5003,
        reload=True,
    )
