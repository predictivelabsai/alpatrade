"""
AlpaTrade AG-UI — 3-pane chat interface powered by LangGraph + astream_events.

Left pane:  Auth / settings / navigation / help expanders
Center:     Chat (WebSocket streaming)
Right:      Thinking trace / artifact canvas (toggled)

Launch:  python agui_app.py          # port 5003
         uvicorn agui_app:app --port 5003 --reload
"""

import os
import sys
import uuid as _uuid
import logging
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import *

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google OAuth setup via authlib (optional — gracefully skip if no creds)
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
_oauth_enabled = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_authlib_oauth = None
if _oauth_enabled:
    from authlib.integrations.starlette_client import OAuth as AuthlibOAuth
    _authlib_oauth = AuthlibOAuth()
    _authlib_oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

_GOOGLE_SVG = """<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
<path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
<path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
<path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9s.38 1.572.957 3.042l3.007-2.332z" fill="#FBBC05"/>
<path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
</svg>"""

from utils.agui import setup_agui, get_chat_styles, StreamingCommand, list_conversations
import threading

# ---------------------------------------------------------------------------
# LangGraph Agent with StructuredTool wrappers
# ---------------------------------------------------------------------------

from langchain_openai import ChatOpenAI
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

SYSTEM_PROMPT = (
    "You are AlpaTrade, an AI trading assistant. "
    "You have tools to look up real stock data, news, and analyst ratings. "
    "Use your tools when users ask about specific stocks or market data. "
    "Be concise and use markdown formatting with tables where appropriate. "
    "Users can type CLI commands directly in chat (e.g. agent:backtest lookback:1m, "
    "news:TSLA, trades, runs) and they will be executed automatically. "
    "For stock queries, always use the appropriate tool to get real data. "
    "When users ask for a graph or chart of a backtest run, use the show_equity_curve tool with the run_id. "
    "For stock price charts, use show_stock_chart. "
    "When users ask about their positions, holdings, or portfolio, use get_alpaca_positions. "
    "When users ask about their account, balance, buying power, or cash, use get_alpaca_account. "
    "When users ask about their linked accounts or want to see which accounts are configured, use list_user_accounts. "
    "When users ask about running agents, background tasks, or agent status, use show_running_agents."
)


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



def get_stock_news(ticker: str, limit: int = 5) -> str:
    """Get latest news headlines for a stock ticker."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.news(ticker=ticker.upper(), limit=limit)
    except Exception as e:
        return f"Error fetching news for {ticker}: {e}"



def get_analyst_ratings(ticker: str) -> str:
    """Get analyst ratings and price targets for a stock."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.analysts(ticker=ticker.upper())
    except Exception as e:
        return f"Error fetching ratings for {ticker}: {e}"



def get_company_profile(ticker: str) -> str:
    """Get company profile, sector, and key details for a stock."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.profile(ticker=ticker.upper())
    except Exception as e:
        return f"Error fetching profile for {ticker}: {e}"



def get_financials(ticker: str, period: str = "annual") -> str:
    """Get financial data (revenue, earnings, margins) for a stock. Period: 'annual' or 'quarterly'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.financials(ticker=ticker.upper(), period=period)
    except Exception as e:
        return f"Error fetching financials for {ticker}: {e}"



def get_market_movers(direction: str = "both") -> str:
    """Get today's top market movers (gainers and losers). Direction: 'gainers', 'losers', or 'both'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.movers(direction=direction)
    except Exception as e:
        return f"Error fetching market movers: {e}"



def get_valuation(tickers: str) -> str:
    """Compare valuation metrics (P/E, P/B, EV/EBITDA) for multiple stocks. Pass comma-separated tickers like 'AAPL,MSFT,GOOGL'."""
    try:
        from utils.market_research_util import MarketResearch
        mr = MarketResearch()
        return mr.valuation(tickers=tickers.upper())
    except Exception as e:
        return f"Error fetching valuation: {e}"



def get_alpaca_positions(account_id: Optional[str] = None) -> str:
    """Get current open positions from the Alpaca paper trading account. Shows symbol, qty, entry price, current price, and unrealized P&L."""
    try:
        from utils.alpaca_util import AlpacaAPI
        client = AlpacaAPI(paper=True, account_id=account_id)
        positions = client.get_positions()
        if isinstance(positions, dict) and "error" in positions:
            return f"Error fetching positions: {positions['error']}"
        if not positions:
            return "No open positions."
        md = "| Symbol | Qty | Entry | Current | Unrealized P&L | P&L% |\n"
        md += "|--------|-----|-------|---------|----------------|------|\n"
        for p in positions:
            symbol = p.get("symbol", "?")
            qty = p.get("qty", "0")
            entry = float(p.get("avg_entry_price", 0))
            current = float(p.get("current_price", 0))
            pnl = float(p.get("unrealized_pl", 0))
            pnl_pct = float(p.get("unrealized_plpc", 0)) * 100
            sign = "+" if pnl >= 0 else ""
            md += f"| {symbol} | {qty} | ${entry:.2f} | ${current:.2f} | {sign}${pnl:.2f} | {sign}{pnl_pct:.2f}% |\n"
        return md + f"\n*{len(positions)} open positions*"
    except Exception as e:
        return f"Error fetching positions: {e}"



def get_alpaca_account(account_id: Optional[str] = None) -> str:
    """Get Alpaca paper trading account summary — portfolio value, cash, buying power, and P&L."""
    try:
        from utils.alpaca_util import AlpacaAPI
        client = AlpacaAPI(paper=True, account_id=account_id)
        acct = client.get_account()
        if "error" in acct:
            return f"Error fetching account: {acct['error']}"
        equity = float(acct.get("equity", 0))
        cash = float(acct.get("cash", 0))
        buying_power = float(acct.get("buying_power", 0))
        portfolio_value = float(acct.get("portfolio_value", 0))
        pnl = float(acct.get("unrealized_pl", 0) or 0)
        daytrade_count = acct.get("daytrade_count", "?")
        return (
            f"**Account Summary**\n\n"
            f"| Metric | Value |\n|--------|-------|\n"
            f"| Portfolio Value | ${portfolio_value:,.2f} |\n"
            f"| Equity | ${equity:,.2f} |\n"
            f"| Cash | ${cash:,.2f} |\n"
            f"| Buying Power | ${buying_power:,.2f} |\n"
            f"| Unrealized P&L | ${pnl:,.2f} |\n"
            f"| Day Trades (5d) | {daytrade_count} |\n"
        )
    except Exception as e:
        return f"Error fetching account: {e}"



def list_user_accounts() -> str:
    """List all Alpaca brokerage accounts linked to the current user. Shows account name, API key hint, and status."""
    try:
        from utils.auth import get_user_accounts
        # Use a placeholder — the interceptor will inject the real user_id
        # This tool is mainly for the AI to describe what accounts exist
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            result = session.execute(
                text("""
                    SELECT ua.account_name, ua.account_id, ua.created_at
                    FROM alpatrade.user_accounts ua
                    WHERE ua.is_active = TRUE
                    ORDER BY ua.created_at ASC
                    LIMIT 20
                """)
            )
            rows = result.fetchall()
        if not rows:
            return "No accounts found. Use `account:add <API_KEY> <SECRET_KEY>` to add one."
        md = "**Your Alpaca Accounts**\n\n"
        md += "| # | Name | Account ID | Added |\n"
        md += "|---|------|------------|-------|\n"
        for i, r in enumerate(rows, 1):
            created = str(r[2])[:10] if r[2] else "-"
            short_id = str(r[1])[:8]
            md += f"| {i} | {r[0]} | `{short_id}` | {created} |\n"
        md += f"\n*{len(rows)} accounts*\n"
        md += "\nUse `account:switch <number>` to change active account."
        return md
    except Exception as e:
        return f"Error listing accounts: {e}"



def show_running_agents() -> str:
    """Show all currently running background trading agents (paper trade, backtest, etc.) and their status."""
    try:
        from utils.agent_runner import get_all_running_agents
        agents = get_all_running_agents()
        if not agents:
            return "No agents are currently running."
        md = "**Running Agents**\n\n"
        md += "| Run ID | Mode | Account | Status | PID |\n"
        md += "|--------|------|---------|--------|-----|\n"
        for a in agents:
            short_id = str(a.get('run_id', '?'))[:8]
            mode = a.get('mode', '?')
            acct = a.get('account_id', '-')
            if acct and len(acct) > 8:
                acct = acct[:8]
            status = a.get('status', 'running')
            pid = a.get('pid', '?')
            md += f"| `{short_id}` | {mode} | `{acct}` | {status} | {pid} |\n"
        md += f"\n*{len(agents)} agent(s) running*\n"
        md += "\nUse `agent:stop id:<run_id>` to stop an agent."
        return md
    except Exception as e:
        return f"Error checking agents: {e}"



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



def show_equity_curve(run_id: str) -> str:
    """Show the equity curve chart for a backtest run. Accepts full or partial (prefix) run IDs."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        import json

        pool = DatabasePool()
        with pool.get_session() as session:
            # Prefix matching — find full run_id from partial
            rid = run_id.strip()
            if len(rid) < 36:
                row = session.execute(
                    text("SELECT run_id FROM alpatrade.runs WHERE CAST(run_id AS TEXT) LIKE :prefix ORDER BY created_at DESC LIMIT 1"),
                    {"prefix": f"{rid}%"},
                ).fetchone()
                if not row:
                    return f"No run found matching prefix `{rid}`"
                rid = str(row[0])

            # Get initial_capital from runs.config JSONB
            run_row = session.execute(
                text("SELECT config FROM alpatrade.runs WHERE run_id = :rid"),
                {"rid": rid},
            ).fetchone()
            initial_capital = 10000.0
            if run_row and run_row[0]:
                cfg = run_row[0] if isinstance(run_row[0], dict) else json.loads(run_row[0])
                initial_capital = float(cfg.get("initial_capital", 10000))

            # Get equity data from trades — exit_time + capital_after
            trades = session.execute(
                text("""
                    SELECT exit_time, capital_after
                    FROM alpatrade.trades
                    WHERE run_id = :rid AND exit_time IS NOT NULL AND capital_after IS NOT NULL
                    ORDER BY exit_time ASC
                """),
                {"rid": rid},
            ).fetchall()

        if not trades:
            return f"No trade data with equity info for run `{rid[:8]}`"

        dates = [t[0].isoformat() if hasattr(t[0], 'isoformat') else str(t[0]) for t in trades]
        equity = [round(float(t[1]), 2) for t in trades]

        chart_data = json.dumps({
            "type": "equity_curve",
            "run_id": rid,
            "dates": dates,
            "equity": equity,
            "initial_capital": initial_capital,
        })
        return f"__CHART_DATA__{chart_data}__END_CHART__"
    except Exception as e:
        return f"Error generating equity curve: {e}"


# ---------------------------------------------------------------------------
# Build LangGraph agent from tool functions
# ---------------------------------------------------------------------------

TOOLS = [
    StructuredTool.from_function(get_stock_price, name="get_stock_price",
        description="Get current stock price and recent performance for a ticker symbol."),
    StructuredTool.from_function(get_stock_news, name="get_stock_news",
        description="Get latest news headlines for a stock ticker."),
    StructuredTool.from_function(get_analyst_ratings, name="get_analyst_ratings",
        description="Get analyst ratings and price targets for a stock."),
    StructuredTool.from_function(get_company_profile, name="get_company_profile",
        description="Get company profile, sector, and key details for a stock."),
    StructuredTool.from_function(get_financials, name="get_financials",
        description="Get financial data (revenue, earnings, margins) for a stock. Period: 'annual' or 'quarterly'."),
    StructuredTool.from_function(get_market_movers, name="get_market_movers",
        description="Get today's top market movers (gainers and losers). Direction: 'gainers', 'losers', or 'both'."),
    StructuredTool.from_function(get_valuation, name="get_valuation",
        description="Compare valuation metrics (P/E, P/B, EV/EBITDA) for multiple stocks. Pass comma-separated tickers like 'AAPL,MSFT,GOOGL'."),
    StructuredTool.from_function(get_alpaca_positions, name="get_alpaca_positions",
        description="Get current open positions from the Alpaca paper trading account."),
    StructuredTool.from_function(get_alpaca_account, name="get_alpaca_account",
        description="Get Alpaca paper trading account summary — portfolio value, cash, buying power, and P&L."),
    StructuredTool.from_function(list_user_accounts, name="list_user_accounts",
        description="List all Alpaca brokerage accounts linked to the current user."),
    StructuredTool.from_function(show_running_agents, name="show_running_agents",
        description="Show all currently running background trading agents and their status."),
    StructuredTool.from_function(show_recent_trades, name="show_recent_trades",
        description="Show recent trades from the AlpaTrade database."),
    StructuredTool.from_function(show_stock_chart, name="show_stock_chart",
        description="Show a price chart for a stock. Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."),
    StructuredTool.from_function(show_recent_runs, name="show_recent_runs",
        description="Show recent backtest/paper trade runs from the AlpaTrade database."),
    StructuredTool.from_function(show_equity_curve, name="show_equity_curve",
        description="Show the equity curve chart for a backtest run. Accepts full or partial (prefix) run IDs."),
]

llm = ChatOpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
    model="grok-3-mini",
    temperature=0.5,
    max_tokens=3000,
    streaming=True,
)

langgraph_agent = create_react_agent(model=llm, tools=TOOLS, prompt=SYSTEM_PROMPT)


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
_CLI_BASES = {"news", "profile", "financials", "price", "movers", "analysts", "valuation", "chart", "equity"}
_CLI_EXACT = {"trades", "runs", "status", "help", "guide", "positions", "account", "accounts"}

# Long-running commands that get streamed with log console instead of blocking
_STREAMING_COMMANDS = {
    "agent:backtest", "agent:paper", "agent:full",
    "agent:validate", "agent:reconcile",
}


async def _command_interceptor(msg: str, session):
    """Detect CLI commands and route to CommandProcessor. Returns markdown or None."""
    cmd_lower = msg.strip().lower()
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    base = first_word.split(":")[0]

    is_command = (
        first_word.startswith("agent:") or
        first_word.startswith("alpaca:") or
        first_word.startswith("account:") or
        cmd_lower in _CLI_EXACT or
        base in _CLI_BASES
    )

    if not is_command:
        return None

    # Special case: "help" returns chat-friendly markdown (Rich tables don't work here)
    if cmd_lower in ("help", "h", "?"):
        return _AGUI_HELP

    # chart:<TICKER> — stock price chart (bypass CommandProcessor)
    if base == "chart":
        ticker = first_word.split(":", 1)[1].upper() if ":" in first_word else None
        if ticker:
            # Catch common mistake: "chart:equity" should be "equity:<run_id>"
            if ticker.lower() == "equity":
                return "Did you mean `equity:<run_id>`? Use `runs` to see recent run IDs, then `equity:abc12345`."
            period = "3mo"
            import re as _re
            pm = _re.search(r'period:(\S+)', msg.strip().lower())
            if pm:
                period = pm.group(1)
            return show_stock_chart(ticker, period)
        return "Usage: `chart:AAPL` or `chart:AAPL period:1y`"

    # equity:<RUN_ID> — equity curve chart (bypass CommandProcessor)
    if base == "equity":
        rid = msg.strip().split(":", 1)[1].strip() if ":" in msg.strip() else None
        if rid:
            return show_equity_curve(rid)
        return "Usage: `equity:<run_id>`"

    # Alpaca account/positions — direct tool call, bypass CommandProcessor
    if cmd_lower == "positions":
        return get_alpaca_positions()
    if cmd_lower == "account":
        return get_alpaca_account()

    # Account management commands
    if cmd_lower == "accounts":
        return list_user_accounts()

    if cmd_lower.startswith("account:add"):
        parts = msg.strip().split()
        if len(parts) < 3:
            return "**Usage:** `account:add <API_KEY> <SECRET_KEY>`\n\nExample: `account:add PKXXXXXXXX ECpXXXXXXXX`"
        api_key, sec_key = parts[1], parts[2]
        acc_name = f"Account ({api_key[:6]}...)"
        try:
            from utils.alpaca_util import AlpacaAPI
            client = AlpacaAPI(api_key=api_key, secret_key=sec_key, paper=True)
            acct_info = client.get_account()
            if "error" not in acct_info:
                acct_num = acct_info.get("account_number", "")
                acc_name = f"Paper-{acct_num}" if acct_num else acc_name
        except Exception:
            pass
        user_id = session.get("user", {}).get("user_id") if session.get("user") else None
        if not user_id:
            return "Not logged in. Please sign in first."
        from utils.auth import store_alpaca_keys
        try:
            new_id = store_alpaca_keys(user_id, api_key, sec_key, account_name=acc_name)
            return f"✓ **Account '{acc_name}' saved!**\n\nID: `{new_id}`\n\nThis account is now active."
        except Exception as e:
            return f"✗ Failed to add account: {e}"

    if cmd_lower.startswith("account:switch"):
        query = msg.strip().split(maxsplit=1)[1].strip() if len(msg.strip().split(maxsplit=1)) > 1 else ""
        if not query:
            return "**Usage:** `account:switch <number|name>`"
        user_id = session.get("user", {}).get("user_id") if session.get("user") else None
        if not user_id:
            return "Not logged in."
        from utils.auth import get_user_accounts
        accounts = get_user_accounts(user_id)
        if not accounts:
            return "No accounts found. Use `account:add` first."
        matched = None
        try:
            idx = int(query) - 1
            if 0 <= idx < len(accounts):
                matched = accounts[idx]
        except ValueError:
            pass
        if not matched:
            q = query.lower()
            for acc in accounts:
                if q in acc["account_name"].lower():
                    matched = acc
                    break
        if matched:
            _app_state.account_id = matched["account_id"]
            _app_state._orch = None
            return f"✓ **Switched to: {matched['account_name']}** (`{matched.get('api_key_hint', '****')}`)"
        return f"✗ No account matches '{query}'. Type `accounts` to see the list."

    # Long-running commands → return StreamingCommand sentinel
    if first_word in _STREAMING_COMMANDS:
        return StreamingCommand(msg, session, _app_state)

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

## Alpaca Account
- `positions` — open positions from Alpaca paper account
- `account` — account summary (portfolio value, cash, buying power)

## Charts
- `chart:AAPL` — stock price chart (3mo default)
- `chart:TSLA period:1y` — custom period
- `equity:<run_id>` — equity curve for a backtest run

## AI Chat
Type any question to chat with AI about stocks & trading.
"""

agui = setup_agui(app, langgraph_agent, command_interceptor=_command_interceptor)


# ---------------------------------------------------------------------------
# CSS — 3-pane layout
# ---------------------------------------------------------------------------

LAYOUT_CSS = """
/* === Layout — Light Only === */

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f8fafc;
  color: #1e293b;
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
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 1rem;
  gap: 1.25rem;
}

.brand {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  text-decoration: none;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
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
  background: #f1f5f9;
  color: #1e293b;
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
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  color: #1e293b;
  font-family: inherit;
  font-size: 0.8rem;
}

.sidebar-auth input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
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

.sidebar-auth .google-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem;
  background: #4285f4;
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  text-decoration: none;
  text-align: center;
}

.sidebar-auth .google-btn:hover { background: #3367d6; }

.sidebar-auth .divider {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.7rem;
  color: #94a3b8;
}

.sidebar-auth .divider::before,
.sidebar-auth .divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid #e2e8f0;
}

.alt-link { font-size: 0.75rem; color: #64748b; }
.alt-link a { color: #3b82f6; }

.error-msg { color: #dc2626; font-size: 0.8rem; }
.success-msg { color: #16a34a; font-size: 0.8rem; }

.user-info {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.75rem;
  font-size: 0.8rem;
}

.user-info .name { font-weight: 600; color: #1e293b; }
.user-info .email { color: #64748b; font-size: 0.75rem; }

.key-status {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.7rem;
  font-weight: 500;
}
.key-status.configured { background: #dcfce7; color: #166534; }
.key-status.not-configured { background: #fef2f2; color: #991b1b; }

.keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  color: #1e293b;
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
  color: #dc2626;
  text-decoration: none;
  font-size: 0.85rem;
  border-radius: 0.375rem;
}
.logout-btn:hover { background: rgba(220, 38, 38, 0.08); }

/* === Center Pane (Chat) === */
.center-pane {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f8fafc;
  overflow: hidden;
}

.center-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  min-height: 3rem;
}

.center-header h2 {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.toggle-trace-btn {
  padding: 0.3rem 0.7rem;
  background: transparent;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-trace-btn:hover {
  background: #f1f5f9;
  color: #3b82f6;
  border-color: #3b82f6;
}

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

/* Override agui chat styles for layout integration */
.center-chat .chat-container {
  height: 100%;
  flex: 1;
  border: none;
  border-radius: 0;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
}

.center-chat .chat-messages {
  background: #f8fafc;
  flex: 1;
}

.center-chat .chat-input {
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
}

.center-chat .chat-input-field {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #1e293b;
}

.center-chat .chat-input-field:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.center-chat .chat-message.chat-assistant .chat-message-content {
  background: #f8fafc;
  color: #1e293b;
}

.center-chat .chat-message.chat-user .chat-message-content {
  background: #3b82f6;
  color: white;
}

.center-chat .chat-message.chat-tool .chat-message-content {
  background: #e2e8f0;
  color: #64748b;
}

/* === Right Pane (Trace / Artifacts) === */
.right-pane {
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.right-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
}

.close-trace-btn {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.2rem;
}
.close-trace-btn:hover { color: #1e293b; }

.right-tabs {
  display: flex;
  border-bottom: 1px solid #e2e8f0;
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
  border-left: 3px solid #e2e8f0;
  border-radius: 0 0.25rem 0.25rem 0;
  background: #f1f5f9;
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
.trace-run-start .trace-label { color: #3b82f6; }

.trace-run-end { border-left-color: #16a34a; }
.trace-run-end .trace-label { color: #16a34a; }

.trace-streaming { border-left-color: #7c3aed; }
.trace-streaming .trace-label { color: #7c3aed; }

.trace-tool-active { border-left-color: #d97706; }
.trace-tool-active .trace-label { color: #d97706; }

.trace-tool-done { border-left-color: #16a34a; }
.trace-tool-done .trace-label { color: #16a34a; }

.trace-done { border-left-color: #16a34a; }
.trace-done .trace-label { color: #16a34a; }

.trace-error { border-left-color: #dc2626; }
.trace-error .trace-label { color: #dc2626; }

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

#detail-content {
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

/* === Sidebar Header === */
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}

.sidebar-header .brand {
  border-bottom: none;
  padding-bottom: 0;
}

.chat-badge {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  background: #3b82f6;
  color: white;
  padding: 0.15rem 0.4rem;
  border-radius: 0.25rem;
}

/* === New Chat Button === */
.new-chat-btn {
  width: 100%;
  padding: 0.5rem;
  background: transparent;
  border: 1px dashed #cbd5e1;
  border-radius: 0.5rem;
  color: #3b82f6;
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.new-chat-btn:hover {
  background: #eff6ff;
  border-color: #93c5fd;
}

/* === Conversation List === */
.conv-section {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.conv-section h4 {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.conv-item {
  display: block;
  font-size: 0.8rem;
  padding: 0.5rem 0.6rem;
  color: #475569;
  text-decoration: none;
  border-radius: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s;
}

.conv-item:hover { background: #f1f5f9; color: #1e293b; }
.conv-active { background: #eff6ff; border-left: 2px solid #3b82f6; color: #1e293b; }
.conv-empty { font-style: italic; color: #94a3b8; font-size: 0.75rem; padding: 0.5rem; }

/* === Sidebar Nav === */
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e2e8f0;
}

.sidebar-nav a {
  color: #64748b;
  text-decoration: none;
  font-size: 0.8rem;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  transition: all 0.15s;
}

.sidebar-nav a:hover { background: #f1f5f9; color: #1e293b; }

/* === Sidebar User Compact === */
.sidebar-user-compact {
  margin-top: auto;
  border-top: 1px solid #e2e8f0;
  padding-top: 0.75rem;
}

.sidebar-user-compact .name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #1e293b;
}

.sidebar-user-compact .email {
  font-size: 0.7rem;
  color: #64748b;
}

/* === Sidebar Footer === */
.sidebar-footer {
  font-size: 0.7rem;
  color: #94a3b8;
  text-align: center;
  padding-top: 0.5rem;
}

/* === Help Expanders (sidebar command reference) === */
.help-section {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.help-toggle {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0.35rem 0.5rem;
  background: none;
  border: none;
  border-radius: 0.375rem;
  color: #475569;
  font-family: inherit;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.help-toggle:hover { background: #f1f5f9; color: #1e293b; }

.help-cnt {
  margin-left: auto;
  margin-right: 0.35rem;
  font-size: 0.65rem;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 0.1rem 0.4rem;
  border-radius: 1rem;
}

.help-arrow {
  color: #94a3b8;
  font-size: 0.65rem;
  transition: transform 0.2s;
}

.help-toggle.open .help-arrow { transform: rotate(90deg); }

.help-list {
  display: none;
  flex-direction: column;
  gap: 0.1rem;
  padding-left: 0.5rem;
}

.help-list.open { display: flex; }

.help-item {
  display: block;
  width: 100%;
  padding: 0.3rem 0.5rem;
  background: none;
  border: none;
  border-radius: 0.25rem;
  color: #3b82f6;
  font-family: ui-monospace, monospace;
  font-size: 0.7rem;
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s;
}

.help-item:hover {
  background: #eff6ff;
  color: #2563eb;
}

/* === Profile Page === */
.profile-container {
  max-width: 600px;
  margin: 2rem auto;
  padding: 2rem;
  background: #ffffff;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
}

.profile-container h2 {
  font-size: 1.25rem;
  color: #1e293b;
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}

.profile-container h3 {
  font-size: 1rem;
  color: #1e293b;
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
}

.profile-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.profile-info dt { color: #64748b; font-weight: 500; }
.profile-info dd { color: #1e293b; margin: 0; }

.profile-container .accounts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin-bottom: 1rem;
}

.profile-container .accounts-table th {
  text-align: left;
  color: #64748b;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.profile-container .accounts-table td {
  padding: 0.5rem;
  border-bottom: 1px solid #f1f5f9;
  color: #1e293b;
}

.profile-container .keys-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.profile-container .keys-form input {
  width: 100%;
  padding: 0.5rem 0.6rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
  color: #1e293b;
  font-family: inherit;
  font-size: 0.8rem;
}

.profile-container .keys-form input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.profile-container .keys-form button {
  padding: 0.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.8rem;
}

.profile-container .keys-form button:hover { background: #2563eb; }

.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.7rem; border-radius: 0.25rem; cursor: pointer; border: none; }
.btn-danger { background: #fee2e2; color: #dc2626; }
.btn-danger:hover { background: #fecaca; }

.profile-container .back-link {
  display: inline-block;
  margin-top: 1.5rem;
  color: #3b82f6;
  text-decoration: none;
  font-size: 0.85rem;
}

.profile-container .back-link:hover { text-decoration: underline; }

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
# Help expanders — collapsible command reference in sidebar
# ---------------------------------------------------------------------------

_HELP_CATEGORIES = [
    ("Backtest", [
        ("agent:backtest lookback:1m", "1-month backtest"),
        ("agent:backtest symbols:AAPL,TSLA", "custom symbols"),
        ("agent:backtest hours:extended", "pre/after-market"),
        ("agent:backtest intraday_exit:true", "5-min TP/SL bars"),
        ("agent:backtest pdt:false", "disable PDT rule"),
    ]),
    ("Validate", [
        ("agent:validate run-id:<uuid>", "validate a run"),
        ("agent:reconcile window:14d", "DB vs Alpaca"),
    ]),
    ("Reconcile", [
        ("agent:reconcile window:7d", "7-day reconcile"),
        ("agent:reconcile window:30d", "30-day reconcile"),
    ]),
    ("Paper Trade", [
        ("agent:paper duration:7d", "paper trade 7 days"),
        ("agent:paper symbols:AAPL,MSFT", "custom symbols"),
        ("agent:paper poll:60", "60-second poll"),
        ("agent:paper hours:extended", "extended hours"),
        ("agent:stop", "stop paper trading"),
    ]),
    ("Full Cycle", [
        ("agent:full lookback:1m duration:1m", "backtest + validate + paper"),
        ("agent:full lookback:3m duration:7d", "3-month + 7-day paper"),
    ]),
    ("Query & Monitor", [
        ("trades", "recent trades from DB"),
        ("runs", "recent runs from DB"),
        ("agent:report", "performance summary"),
        ("agent:report run-id:<uuid>", "single run detail"),
        ("agent:top", "rank strategies"),
        ("agent:status", "agent states"),
        ("agent:logs", "paper trade log tail"),
        ("positions", "Alpaca open positions"),
    ]),
    ("Research", [
        ("news:TSLA", "company news"),
        ("price:AAPL", "stock quote"),
        ("profile:MSFT", "company profile"),
        ("analysts:GOOGL", "analyst ratings"),
        ("financials:AAPL", "income & balance sheet"),
        ("valuation:AAPL,MSFT", "valuation comparison"),
        ("movers", "top gainers & losers"),
        ("chart:AAPL period:1y", "stock chart"),
    ]),
    ("Accounts", [
        ("accounts", "list linked accounts"),
        ("account:add <KEY> <SECRET>", "add new account"),
        ("account:switch <num>", "switch active account"),
    ]),
    ("Options", [
        ("hours:extended", "pre/after-market hours"),
        ("pdt:false", "disable PDT rule"),
        ("intraday_exit:true", "intraday TP/SL exits"),
    ]),
]


def _help_expanders():
    """Build collapsible help category groups for the sidebar."""
    groups = []
    for cat_name, items in _HELP_CATEGORIES:
        cat_id = f"help-{cat_name.lower().replace(' ', '-').replace('&', '')}"
        toggle_btn = Button(
            cat_name,
            Span(f"{len(items)}", cls="help-cnt"),
            Span(">", cls="help-arrow"),
            cls="help-toggle",
            onclick=f"toggleGroup('{cat_id}')",
        )
        tool_items = []
        for cmd, desc in items:
            tool_items.append(
                Button(
                    cmd,
                    cls="help-item",
                    onclick=f"fillChat({repr(cmd)})",
                    title=desc,
                )
            )
        tool_list = Div(*tool_items, cls="help-list", id=cat_id)
        groups.append(toggle_btn)
        groups.append(tool_list)

    return Div(*groups, cls="help-section")


# ---------------------------------------------------------------------------
# Left pane builder
# ---------------------------------------------------------------------------

def _left_pane(session):
    """Build the left sidebar: brand, new chat, conversations, nav, auth/user."""
    user = session.get("user")
    thread_id = session.get("thread_id", "")

    parts = []

    # Header: Brand + CHAT badge
    parts.append(
        Div(
            A("AlpaTrade", href="/", cls="brand"),
            Span("CHAT", cls="chat-badge"),
            cls="sidebar-header",
        )
    )

    # New Chat button
    parts.append(
        Button(
            "+ New Chat",
            cls="new-chat-btn",
            onclick="window.location.href='/?new=1'",
        )
    )

    # Help expanders — collapsible command reference
    parts.append(_help_expanders())

    # Conversation list
    parts.append(
        Div(
            H4("Recent"),
            Div(
                id="conv-list",
                hx_get="/agui-conv/list",
                hx_trigger="load",
                hx_swap="innerHTML",
            ),
            cls="conv-section",
        )
    )

    # Navigation
    nav = Div(cls="sidebar-nav")
    nav_links = [A("Dashboard", href="https://alpatrade.dev", target="_blank")]
    if user:
        nav_links.append(A("Profile", href="/profile"))
        nav_links.append(A("Logout", href="/logout", cls="logout-btn"))
    nav = Div(*nav_links, cls="sidebar-nav")
    parts.append(nav)

    # Auth section (compact, at bottom) or user info
    if user:
        name = user.get("display_name") or user.get("email", "user")
        email = user.get("email", "")

        account_count = 0
        try:
            from utils.auth import get_user_accounts
            account_count = len(get_user_accounts(user["user_id"]))
        except Exception:
            pass

        key_badge = (
            Span(f"{account_count} account{'s' if account_count != 1 else ''}", cls="key-status configured")
            if account_count > 0
            else Span("No keys", cls="key-status not-configured")
        )

        parts.append(
            Div(
                Div(name, cls="name"),
                Div(email, cls="email"),
                Div(key_badge, style="margin-top: 0.35rem;"),
                cls="sidebar-user-compact",
            )
        )
    else:
        parts.append(
            Div(
                Div(
                    id="auth-forms",
                    hx_get="/agui-auth/login-form",
                    hx_trigger="load",
                    hx_swap="innerHTML",
                ),
                cls="sidebar-section",
                style="margin-top: auto;",
            )
        )

    # Footer
    parts.append(Div("Powered by AlpaTrade", cls="sidebar-footer"))

    return Div(*parts, cls="left-pane", id="left-pane")


# ---------------------------------------------------------------------------
# Right pane builder
# ---------------------------------------------------------------------------

def _right_pane():
    """Build the right pane: thinking trace + artifacts + details."""
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
            Button("Details", cls="right-tab", onclick="showTab('detail')"),
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
            Div(
                Div("Select a run ID from the chat to view details.",
                    style="color: #475569; font-style: italic;"),
                id="detail-content",
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

/* Help expander toggle */
function toggleGroup(catId) {
    var list = document.getElementById(catId);
    if (!list) return;
    list.classList.toggle('open');
    // Find the toggle button (previous sibling)
    var btn = list.previousElementSibling;
    if (btn) btn.classList.toggle('open');
}

/* Fill chat input from sidebar help item */
function fillChat(cmd) {
    if (window._aguiProcessing) return;
    var ta = document.getElementById('chat-input');
    var fm = document.getElementById('chat-form');
    if (ta && fm) {
        ta.value = cmd;
        ta.focus();
    }
}

function showTab(tab) {
    var trace = document.getElementById('trace-content');
    var artifact = document.getElementById('artifact-content');
    var detail = document.getElementById('detail-content');
    var tabs = document.querySelectorAll('.right-tab');

    tabs.forEach(function(t) { t.classList.remove('active'); });
    if (trace) trace.style.display = 'none';
    if (artifact) artifact.style.display = 'none';
    if (detail) detail.style.display = 'none';

    if (tab === 'trace') {
        if (trace) trace.style.display = 'flex';
        tabs[0].classList.add('active');
    } else if (tab === 'artifact') {
        if (artifact) artifact.style.display = 'block';
        tabs[1].classList.add('active');
    } else if (tab === 'detail') {
        if (detail) detail.style.display = 'block';
        tabs[2].classList.add('active');
    }
}

/* Chart rendering — detect __CHART_DATA__ markers in assistant messages */
function renderChart(chartJson) {
    try {
        var data = JSON.parse(chartJson);
        if (data.type === 'equity_curve') {
            renderEquityCurve(data);
        } else {
            renderStockChart(data);
        }
    } catch(e) {
        console.error('Chart render error:', e);
    }
}

function renderStockChart(data) {
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

    showTab('artifact');
}

function renderEquityCurve(data) {
    var container = document.getElementById('artifact-content');
    if (!container || !window.Plotly) return;

    container.innerHTML = '';
    var chartDiv = document.createElement('div');
    chartDiv.id = 'plotly-chart';
    chartDiv.className = 'artifact-chart';
    container.appendChild(chartDiv);

    var equityTrace = {
        x: data.dates,
        y: data.equity,
        type: 'scatter',
        mode: 'lines',
        name: 'Equity',
        line: { color: '#3b82f6', width: 2 },
        fill: 'tozeroy',
        fillcolor: 'rgba(59, 130, 246, 0.1)',
    };

    var capitalLine = {
        x: [data.dates[0], data.dates[data.dates.length - 1]],
        y: [data.initial_capital, data.initial_capital],
        type: 'scatter',
        mode: 'lines',
        name: 'Initial Capital',
        line: { color: '#94a3b8', width: 1, dash: 'dash' },
    };

    var shortId = data.run_id ? data.run_id.substring(0, 8) : 'unknown';
    var layout = {
        title: { text: 'Equity Curve — ' + shortId, font: { color: '#f1f5f9', size: 14 } },
        paper_bgcolor: '#1e293b',
        plot_bgcolor: '#0f172a',
        font: { color: '#94a3b8', family: 'ui-monospace, monospace', size: 11 },
        xaxis: { gridcolor: '#1e293b', linecolor: '#334155' },
        yaxis: { gridcolor: '#1e293b', linecolor: '#334155', tickprefix: '$' },
        legend: { orientation: 'h', y: -0.15 },
        margin: { t: 40, r: 20, b: 40, l: 60 },
        showlegend: true,
    };

    Plotly.newPlot(chartDiv, [equityTrace, capitalLine], layout, {
        responsive: true,
        displayModeBar: false,
    });

    showTab('artifact');
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
def get(session, new: str = "", thread: str = ""):
    # Force new thread
    if new == "1":
        thread_id = str(_uuid.uuid4())
        session["thread_id"] = thread_id
    elif thread:
        # Resume a specific thread
        thread_id = thread
        session["thread_id"] = thread_id
    else:
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
# Conversation list route
# ---------------------------------------------------------------------------

@rt("/agui-conv/list")
def get(session):
    """Return the conversation list for the sidebar (DB-backed)."""
    current_tid = session.get("thread_id", "")
    user_id = session.get("user", {}).get("user_id") if session.get("user") else None

    try:
        convs = list_conversations(user_id=user_id, limit=20)
    except Exception:
        convs = []

    if not convs:
        return Div(Span("No conversations yet", cls="conv-empty"))

    items = []
    for c in convs:
        tid = c["thread_id"]
        title = c.get("first_msg") or c.get("title") or "New chat"
        if len(title) > 40:
            title = title[:40] + "..."
        cls = "conv-item conv-active" if tid == current_tid else "conv-item"
        items.append(A(title, href=f"/?thread={tid}", cls=cls))

    return Div(*items)


# ---------------------------------------------------------------------------
# Detail panel route — shows run + backtest summary + trades
# ---------------------------------------------------------------------------

@rt("/agui/detail/{run_id}")
def get(run_id: str, session):
    """Fetch run details for the right-pane detail panel."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()

        with pool.get_session() as db:
            # Fetch run info
            run = db.execute(
                text("SELECT run_id, mode, strategy, status, started_at, completed_at FROM alpatrade.runs WHERE run_id = :rid"),
                {"rid": run_id},
            ).fetchone()

            if not run:
                return Div(P(f"Run {run_id[:8]}... not found.", style="color: #dc2626;"))

            # Fetch backtest summary
            summary = db.execute(
                text("""SELECT sharpe_ratio, total_return, annualized_return, total_pnl,
                               win_rate, total_trades, max_drawdown
                        FROM alpatrade.backtest_summaries WHERE run_id = :rid LIMIT 1"""),
                {"rid": run_id},
            ).fetchone()

            # Fetch trades count
            trade_count = db.execute(
                text("SELECT count(*) FROM alpatrade.trades WHERE run_id = :rid"),
                {"rid": run_id},
            ).scalar() or 0

        # Build detail HTML
        sections = []

        # Key info
        sections.append(Div(
            H4("Run Info", style="font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem;"),
            Div(
                Div(Span("ID: ", style="color: #64748b;"), Span(str(run[0])[:8], style="font-family: monospace;")),
                Div(Span("Mode: ", style="color: #64748b;"), Span(str(run[1]))),
                Div(Span("Strategy: ", style="color: #64748b;"), Span(str(run[2] or "-"))),
                Div(Span("Status: ", style="color: #64748b;"), Span(str(run[3]))),
                Div(Span("Started: ", style="color: #64748b;"), Span(str(run[4])[:19] if run[4] else "-")),
                style="display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem;",
            ),
            style="margin-bottom: 1rem;",
        ))

        # Metrics (if backtest)
        if summary:
            metrics = [
                ("Sharpe", f"{float(summary[0] or 0):.2f}"),
                ("Return", f"{float(summary[1] or 0):.2f}%"),
                ("Ann. Return", f"{float(summary[2] or 0):.2f}%"),
                ("P&L", f"${float(summary[3] or 0):,.2f}"),
                ("Win Rate", f"{float(summary[4] or 0):.1f}%"),
                ("Trades", str(summary[5] or 0)),
                ("Max DD", f"{float(summary[6] or 0):.2f}%"),
            ]
            metric_els = []
            for label, value in metrics:
                val_style = "font-weight: 600; font-size: 0.85rem;"
                try:
                    num = float(value.replace('%', '').replace(',', '').replace('$', ''))
                    if label in ('Sharpe', 'Return', 'Ann. Return', 'P&L'):
                        val_style += f" color: {'#16a34a' if num >= 0 else '#dc2626'};"
                except ValueError:
                    pass
                metric_els.append(Div(
                    Div(label, style="font-size: 0.65rem; color: #64748b; text-transform: uppercase;"),
                    Div(value, style=val_style),
                ))

            sections.append(Div(
                H4("Metrics", style="font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem;"),
                Div(
                    *metric_els,
                    style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;",
                ),
                style="margin-bottom: 1rem;",
            ))

        # Trade count
        sections.append(Div(
            Span(f"{trade_count} trades", style="font-size: 0.8rem; color: #64748b;"),
        ))

        return Div(*sections, id="detail-content", hx_swap_oob="innerHTML")

    except Exception as e:
        return Div(P(f"Error loading details: {e}", style="color: #dc2626; font-size: 0.8rem;"))


# ---------------------------------------------------------------------------
# Auth routes (sidebar-based, return HTML fragments)
# ---------------------------------------------------------------------------

@rt("/agui-auth/login-form")
def login_form_fragment():
    """Return the login form for the sidebar."""
    parts = []
    if _oauth_enabled:
        parts.append(A(NotStr(_GOOGLE_SVG), "Sign in with Google", href="/login", cls="google-btn"))
        parts.append(Div("or", cls="divider"))
    parts.extend([
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
    ])
    return Div(*parts, cls="sidebar-auth")


@rt("/agui-auth/register-form")
def register_form_fragment():
    """Return the register form for the sidebar."""
    parts = []
    if _oauth_enabled:
        parts.append(A(NotStr(_GOOGLE_SVG), "Sign up with Google", href="/login", cls="google-btn"))
        parts.append(Div("or", cls="divider"))
    parts.extend([
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
    ])
    return Div(*parts, cls="sidebar-auth")


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

    # Fetch all accounts for this user (includes keys added from CLI)
    accounts = []
    try:
        from utils.auth import get_user_accounts
        accounts = get_user_accounts(user["user_id"])
    except Exception:
        pass

    account_count = len(accounts)
    key_badge = (
        Span(f"{account_count} account{'s' if account_count != 1 else ''}", cls="key-status configured")
        if account_count > 0
        else Span("Not configured", cls="key-status not-configured")
    )

    # Check if user has a password set (Google-only users may not)
    user_has_password = False
    try:
        from utils.auth import has_password
        user_has_password = has_password(user["user_id"])
    except Exception:
        pass

    parts = [
        H2("Profile"),
    ]

    if msg:
        parts.append(P(msg, cls="success-msg"))

    # --- Display Name & Email section ---
    parts.extend([
        H3("Account Info"),
        Form(
            Label("Email", For="email"),
            Input(type="email", id="email", value=user.get("email", ""), disabled=True,
                  style="background: #e2e8f0; cursor: not-allowed;"),
            Label("Display Name", For="display_name"),
            Input(type="text", id="display_name", name="display_name",
                  value=user.get("display_name", ""), placeholder="Your display name", required=True),
            Button("Update Name", type="submit"),
            method="post", action="/profile/name", cls="keys-form",
        ),
    ])

    # --- Password section ---
    parts.append(H3("Change Password" if user_has_password else "Set Password"))
    if user_has_password:
        parts.append(
            Form(
                Input(type="password", name="current_password",
                      placeholder="Current password", required=True),
                Input(type="password", name="new_password",
                      placeholder="New password (min 8 chars)", required=True, minlength="8"),
                Input(type="password", name="confirm_password",
                      placeholder="Confirm new password", required=True, minlength="8"),
                Button("Change Password", type="submit"),
                method="post", action="/profile/password", cls="keys-form",
            )
        )
    else:
        parts.append(
            Form(
                P("You signed in with Google. Set a password to also log in with email.",
                  style="color: #64748b; font-size: 0.85rem;"),
                Input(type="password", name="new_password",
                      placeholder="New password (min 8 chars)", required=True, minlength="8"),
                Input(type="password", name="confirm_password",
                      placeholder="Confirm new password", required=True, minlength="8"),
                Button("Set Password", type="submit"),
                method="post", action="/profile/password", cls="keys-form",
            )
        )

    # --- Alpaca accounts badge ---
    parts.append(H3("Alpaca Accounts"))
    parts.append(P(key_badge))

    # Show existing accounts table (synced from CLI and web)
    if accounts:
        rows = []
        for i, acct in enumerate(accounts, 1):
            rows.append(Tr(
                Td(str(i)),
                Td(acct.get("account_name", "—")),
                Td(Code(acct.get("api_key_hint", "****"))),
                Td(
                    Form(
                        Input(type="hidden", name="account_id", value=acct["account_id"]),
                        Button("Remove", type="submit", cls="btn-sm btn-danger"),
                        method="post", action="/profile/keys/remove",
                    )
                ),
            ))
        parts.extend([
            H3("Your Alpaca Accounts"),
            P("Accounts added from the web, chat, or CLI all appear here. Keys are encrypted at rest.",
              style="color: #64748b; font-size: 0.8rem;"),
            Table(
                Thead(Tr(Th("#"), Th("Name"), Th("API Key"), Th(""))),
                Tbody(*rows),
                cls="accounts-table",
            ),
        ])

    # Add new account form
    parts.extend([
        H3("Add Alpaca Account"),
        Form(
            Input(type="text", name="account_name",
                  placeholder="Account name (optional)", value=""),
            Input(type="password", name="api_key",
                  placeholder="Alpaca Paper API Key", required=True),
            Input(type="password", name="secret_key",
                  placeholder="Alpaca Paper Secret Key", required=True),
            Button("Save Keys", type="submit"),
            method="post", action="/profile/keys", cls="keys-form",
        ),
    ])

    return (
        Title("Profile — AlpaTrade"),
        Style(LAYOUT_CSS),
        Div(
            Div(
                A("← Back to Chat", href="/", cls="back-link"),
                *parts,
                A("← Back to Chat", href="/", cls="back-link", style="margin-top: 1.5rem;"),
                cls="profile-container",
            ),
            style="height: 100vh; overflow-y: auto; background: #f8fafc; padding: 1rem;",
        ),
    )


@rt("/profile/name")
def profile_name(session, display_name: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not display_name.strip():
        return RedirectResponse("/profile?msg=Display+name+cannot+be+empty", status_code=303)
    try:
        from utils.auth import update_display_name
        if update_display_name(user["user_id"], display_name):
            session["user"]["display_name"] = display_name.strip()
            return RedirectResponse("/profile?msg=Display+name+updated", status_code=303)
        return RedirectResponse("/profile?msg=Failed+to+update+name", status_code=303)
    except Exception as e:
        logger.error(f"Failed to update display name: {e}")
        return RedirectResponse("/profile?msg=Error+updating+name", status_code=303)


@rt("/profile/password")
def profile_password(session, current_password: str = "", new_password: str = "", confirm_password: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if new_password != confirm_password:
        return RedirectResponse("/profile?msg=Passwords+do+not+match", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse("/profile?msg=Password+must+be+at+least+8+characters", status_code=303)
    try:
        from utils.auth import has_password, verify_password, get_user_by_email, update_password
        # If user already has a password, verify the current one
        if has_password(user["user_id"]):
            if not current_password:
                return RedirectResponse("/profile?msg=Current+password+is+required", status_code=303)
            db_user = get_user_by_email(user["email"])
            if not db_user or not verify_password(current_password, db_user["password_hash"]):
                return RedirectResponse("/profile?msg=Current+password+is+incorrect", status_code=303)
        if update_password(user["user_id"], new_password):
            return RedirectResponse("/profile?msg=Password+updated+successfully", status_code=303)
        return RedirectResponse("/profile?msg=Failed+to+update+password", status_code=303)
    except Exception as e:
        logger.error(f"Failed to update password: {e}")
        return RedirectResponse("/profile?msg=Error+updating+password", status_code=303)


@rt("/profile/keys")
def profile_keys(session, api_key: str = "", secret_key: str = "", account_name: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not api_key or not secret_key:
        return RedirectResponse("/profile?msg=Both+keys+are+required", status_code=303)
    try:
        from utils.auth import store_alpaca_keys
        name = account_name.strip() or "Default Account"
        store_alpaca_keys(user["user_id"], api_key, secret_key, account_name=name)
        return RedirectResponse("/profile?msg=Alpaca+keys+saved+successfully", status_code=303)
    except Exception as e:
        logger.error(f"Failed to store Alpaca keys: {e}")
        return RedirectResponse("/profile?msg=Error+saving+keys", status_code=303)


@rt("/profile/keys/remove")
def profile_keys_remove(session, account_id: str = ""):
    user = session.get("user")
    if not user:
        return RedirectResponse("/")
    if not account_id:
        return RedirectResponse("/profile", status_code=303)
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as db:
            db.execute(
                text("""
                    UPDATE alpatrade.user_accounts
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE account_id = :account_id AND user_id = :user_id
                """),
                {"account_id": account_id, "user_id": user["user_id"]},
            )
        return RedirectResponse("/profile?msg=Account+removed", status_code=303)
    except Exception as e:
        logger.error(f"Failed to remove account: {e}")
        return RedirectResponse("/profile?msg=Error+removing+account", status_code=303)


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
# Google OAuth routes
# ---------------------------------------------------------------------------

if _oauth_enabled:
    @rt("/login")
    async def login_get(request):
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/auth/callback"
        return await _authlib_oauth.google.authorize_redirect(request, redirect_uri)

    @rt("/auth/callback")
    async def auth_callback(request, session):
        try:
            token = await _authlib_oauth.google.authorize_access_token(request)
        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}")
            return RedirectResponse("/?error=Google+login+failed")

        userinfo = token.get("userinfo", {})
        if not userinfo:
            userinfo = await _authlib_oauth.google.userinfo(token=token)

        google_id = userinfo.get("sub", "")
        email = userinfo.get("email", "")
        name = userinfo.get("name", "")

        if not email:
            return RedirectResponse("/?error=Google+did+not+provide+email")

        from utils.auth import get_user_by_google_id, get_user_by_email, create_user, link_google_id

        user = get_user_by_google_id(google_id) if google_id else None

        if not user:
            user = get_user_by_email(email)
            if user and google_id:
                link_google_id(email, google_id)
            elif not user:
                user = create_user(email=email, google_id=google_id, display_name=name)

        if user:
            _session_login(session, user)
        else:
            return RedirectResponse("/?error=Could+not+create+account")

        return RedirectResponse("/")

if not _oauth_enabled:
    @rt("/login")
    def login_get():
        return RedirectResponse("/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import socket
    import uvicorn

    DEFAULT_PORT = 5003
    MAX_TRIES = 10

    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    port = DEFAULT_PORT
    for p in range(DEFAULT_PORT, DEFAULT_PORT + MAX_TRIES):
        if _port_free(p):
            port = p
            break

    if port != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} in use, using port {port}")

    reload = os.environ.get("AGUI_RELOAD", "true").lower() == "true"
    uvicorn.run(
        "agui_app:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
    )
