"""Shared DeepAgents harness — tools, per-user agents, command interception.

Moved verbatim from ``agui_app.py`` (Phase 7 consolidation): the legacy AG-UI
app is now a thin FastHTML surface around this module. Prod chat
(``engine/web/ph_chat.py``), ``engine/ai/core.py``, ``ph_settings``, ``api.py``
and the tests/evals all reach the harness from here.
"""
from __future__ import annotations

import contextvars
import logging
import threading
from typing import Dict, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from utils.agui import StreamingCommand  # noqa: E402  (re-exported; see below)

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
    "You have NO tool to run a backtest, paper trade, or the full backtest→paper cycle. "
    "When a user asks for one in natural language (e.g. 'backtest AAPL', 'run a backtest on TSLA', "
    "'paper trade this strategy'), do NOT ask for more parameters or pretend to run it — reply with the "
    "exact CLI command they should type, e.g. `agent:backtest symbols:AAPL lookback:3m` (or "
    "`agent:paper duration:7d` for paper trading, `agent:full lookback:1m duration:1m` for the full cycle). "
    "For stock queries, always use the appropriate tool to get real data. "
    "When users ask for a graph or chart of a backtest run, use the show_equity_curve tool with the run_id. "
    "For stock price charts, use show_stock_chart. "
    "When users ask about their positions, holdings, or portfolio, use get_alpaca_positions. "
    "When users ask about their account, balance, buying power, or cash, use get_alpaca_account. "
    "When users ask about their linked accounts or want to see which accounts are configured, use list_user_accounts. "
    "When users ask about running agents, background tasks, or agent status, use show_running_agents. "
    "When users ask which strategies performed best, top strategies, or rankings, use get_top_strategies. "
    "When users ask to see/show a price chart, use show_stock_chart and reply that the chart is rendered "
    "below — do not re-describe the raw numbers. "
    "When users ask for premarket movers, premarket gainers/fallers, or what is moving before the open, "
    "use get_premarket_movers. When users ask for a market map, sector heatmap, or how the market/sectors are doing, use show_market_map "
    "and relay the tool's summary line verbatim (it names the up/down count and the best & worst sectors) — "
    "do not collapse it to just 'rendered below'. "
    "When users ask to compare the performance/returns of several stocks (X vs Y), use compare_stocks and relay "
    "its summary line (each ticker's return). "
    "For chart tools always keep the tool's summary sentence and add that the chart is rendered below. "
    "TRADING: when a user asks to buy or sell shares or place a trade, use place_paper_order to place "
    "the order directly and report the result. Use order_type='market' for a market order; if the user "
    "names a price (e.g. 'buy 10 AAPL at $180' or 'limit 180'), use order_type='limit' with that "
    "limit_price. All trading is PAPER (simulated) — no real money, so no separate confirmation step is "
    "needed; just place it and summarise the order status. "
    "INDEX OPTIONS: SPX, SPXW, VIX, VIXW, DJX, and XSP index options are available in paper only. "
    "Always call list_index_option_contracts before proposing or ordering a contract; never invent a symbol. "
    "Use place_index_option_paper_order only after an explicit trade request. Explain that these contracts "
    "are cash-settled and European-style, flag AM versus PM expiry risk, and do not invent index data or Greeks."
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
        from engine.config import get_settings
        mr = MarketResearch()
        # Honour the configured SEARCH_PROVIDER (defaults to Tavily, which returns
        # real fresh article links). Unknown providers fall back to the default order.
        sp = (get_settings().search_provider or "tavily").lower()
        provider = sp if sp in ("tavily", "xai") else "tavily"
        return mr.news(ticker=ticker.upper(), limit=limit, provider=provider)
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
        import re
        from utils.market_research_util import MarketResearch
        _stop = {"AND", "OR", "VS", "VERSUS", "THE", "WITH", "COMPARE", "TO"}
        syms = [t for t in re.split(r"[,\s]+", (tickers or "").upper())
                if t and t not in _stop]
        if not syms:
            return "Please provide one or more tickers, e.g. AAPL,MSFT,GOOGL."
        # valuation() expects a LIST — passing a string makes it iterate characters.
        return MarketResearch().valuation(tickers=syms)
    except Exception as e:
        return f"Error fetching valuation: {e}"


def get_top_strategies(trade_type: str = "backtest", limit: int = 5) -> str:
    """Rank the best-performing strategies by return/Sharpe. trade_type: 'backtest', 'paper', or 'all'."""
    try:
        from agents.report_agent import ReportAgent
        tt = (trade_type or "backtest").lower()
        rows = ReportAgent().top_strategies(trade_type=(None if tt == "all" else tt), limit=limit)
        if not rows:
            return "No strategy runs found yet — run a backtest first."
        md = ("| # | Strategy | Avg Return | Avg Sharpe | Win Rate | Runs |\n"
              "|---|----------|-----------|-----------|----------|------|\n")
        for i, r in enumerate(rows[:limit], 1):
            ret = float(r.get("avg_return") or 0)
            shp = float(r.get("avg_sharpe") or 0)
            wr = float(r.get("avg_win_rate") or 0)
            md += (f"| {i} | {r.get('strategy_slug', '?')} | {ret:.2f} | {shp:.2f} | "
                   f"{wr:.1f} | {r.get('total_runs', 0)} |\n")
        return f"**Top {tt} strategies** (ranked by return/Sharpe)\n\n" + md
    except Exception as e:  # noqa: BLE001
        return f"Error ranking strategies: {e}"



# ---------------------------------------------------------------------------
# Per-request user context for Alpaca tool resolution
# ---------------------------------------------------------------------------
# The chat agent is built once and shared across users, so its Alpaca tools
# cannot capture a user_id at construction time. Instead, each request binds
# the signed-in user to a contextvar (set_request_user) and the tools resolve
# per-user keys from user_accounts via get_alpaca_keys. A signed-in user with
# no linked account raises _NoLinkedAccount so we never silently fall back to
# the shared env account (which would leak another user's positions/orders).

_current_user_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "agui_user_id", default=None
)
_current_account_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "agui_account_id", default=None
)


def set_request_user(user_id: Optional[str], account_id: Optional[str] = None) -> None:
    """Bind the current request's user/account for Alpaca tool resolution."""
    _current_user_id.set(user_id)
    _current_account_id.set(account_id)


class _NoLinkedAccount(Exception):
    """A signed-in user has no linked Alpaca account (never fall back to env)."""


def _alpaca_client(account_id: Optional[str] = None):
    """Build an AlpacaAPI client for the current request's user.

    - Signed-in user with a linked account → their keys.
    - Signed-in user with no linked account → raise _NoLinkedAccount.
    - Anonymous (no user in context) → env keys (legacy / eval / CLI path).
    """
    from utils.alpaca_util import AlpacaAPI
    user_id = _current_user_id.get()
    if user_id:
        from utils.auth import get_alpaca_keys
        try:
            keys = get_alpaca_keys(user_id, account_id or _current_account_id.get())
        except Exception:
            keys = None
        if not keys:
            raise _NoLinkedAccount(user_id)
        return AlpacaAPI(api_key=keys[0], secret_key=keys[1], paper=True)
    return AlpacaAPI(paper=True)


def get_alpaca_positions(account_id: Optional[str] = None) -> str:
    """Get current open positions from the Alpaca paper trading account. Shows symbol, qty, entry price, current price, and unrealized P&L."""
    try:
        client = _alpaca_client(account_id)
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
    except _NoLinkedAccount:
        return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
    except Exception as e:
        return f"Error fetching positions: {e}"



def get_alpaca_account(account_id: Optional[str] = None) -> str:
    """Get Alpaca paper trading account summary — portfolio value, cash, buying power, and P&L."""
    try:
        client = _alpaca_client(account_id)
        # Alpaca's REST API occasionally returns a transient error; retry once
        # before surfacing a failure so a blip doesn't read as "unavailable".
        acct = client.get_account()
        if isinstance(acct, dict) and "error" in acct:
            import time as _t
            _t.sleep(0.6)
            acct = client.get_account()
        if not isinstance(acct, dict) or "error" in acct:
            err = acct.get("error") if isinstance(acct, dict) else acct
            return f"Error fetching account: {err}"
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
    except _NoLinkedAccount:
        return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
    except Exception as e:
        return f"Error fetching account: {e}"


def get_pnl_report() -> str:
    """Get today's paper-trading account P&L summary: day P&L, portfolio value, and open positions with unrealised P&L."""
    try:
        from scripts.daily_pnl_report import gather
        user_id = _current_user_id.get()
        keys = None
        if user_id:
            from utils.auth import get_alpaca_keys
            try:
                keys = get_alpaca_keys(user_id, _current_account_id.get())
            except Exception:
                keys = None
            if not keys:
                return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
        d = gather(keys=keys)
        lines = [
            f"**Paper account** — day P&L **{'+' if d['day_pnl'] >= 0 else ''}${d['day_pnl']:,.2f} "
            f"({d['day_pct']:+.2f}%)**",
            f"Portfolio ${d['equity']:,.2f} · cash ${d['cash']:,.2f} · buying power ${d['buying_power']:,.2f} "
            f"· open unrealised ${d['unrealized_pl']:,.2f}",
            "",
            "| Symbol | Qty | Entry | Price | Value | Unrealised P&L |",
            "|--------|-----|-------|-------|-------|----------------|",
        ]
        for p in sorted(d["positions"], key=lambda x: float(x.get("unrealized_pl", 0) or 0), reverse=True):
            def _n(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0
            lines.append(
                f"| {p.get('symbol','')} | {_n(p.get('qty')):g} | ${_n(p.get('avg_entry_price')):,.2f} | "
                f"${_n(p.get('current_price')):,.2f} | ${_n(p.get('market_value')):,.0f} | "
                f"${_n(p.get('unrealized_pl')):,.0f} ({_n(p.get('unrealized_plpc'))*100:+.1f}%) |")
        if not d["positions"]:
            lines.append("| _(no open positions)_ | | | | | |")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching PnL report: {e}"


def get_premarket_movers(limit: int = 10, refresh: bool = False) -> str:
    """Show top US premarket movers, gainers and fallers with catalysts.

    Set refresh only when the user explicitly asks for a fresh full-universe
    scan; otherwise the latest persisted scan is returned immediately.
    """
    try:
        from agents.premarket_agent import PremarketAgent
        agent = PremarketAgent()
        if refresh:
            agent.run(refresh=True, limit=min(max(limit, 1), 20))
        return agent.report(limit=min(max(limit, 1), 20))
    except Exception as e:  # noqa: BLE001
        return f"Error loading premarket movers: {e}"


def analyze_prediction_correlation(industry: str = "", event: str = "",
                                   min_samples: int = 5,
                                   view: str = "heatmap") -> str:
    """Analyze Finespresso predicted versus realized moves.

    ``view`` may be ``heatmap`` (event × industry) or ``scatter``.
    The calling user's configured provider interprets the deterministic data.
    """
    try:
        import json
        from engine.research.data import correlation_summary
        data = correlation_summary(industry, event, min_samples)
        corr = data["correlation"]
        summary = (
            f"Prediction research — {data['count']:,} matched observations; "
            f"Pearson correlation **{corr:.3f}**; MAE **{data['mae']:.3f}%**."
            if corr is not None and data["mae"] is not None
            else f"Prediction research — {data['count']:,} matched observations; insufficient variance."
        )
        payload = {
            "type": "research_correlation_scatter" if view.lower() == "scatter"
                    else "research_correlation_heatmap",
            "points": data["points"] if view.lower() == "scatter" else [],
            "matrix": data["matrix"] if view.lower() != "scatter" else [],
            "industry": industry, "event": event, "min_samples": min_samples,
        }
        return summary + "\n\n__CHART_DATA__" + json.dumps(payload) + "__END_CHART__"
    except Exception as e:  # noqa: BLE001
        return f"Error loading prediction research: {e}"


def get_press_releases(query: str = "", ticker: str = "", limit: int = 15) -> str:
    """Search company press releases / news by headline keyword and/or ticker (with a modeled directional read). Use for 'press releases for NVDA', 'news about earnings', 'latest headlines on TSLA'."""
    try:
        from engine.publicmarkets.news import news_summary
        return news_summary(query, ticker.upper() if ticker else "", limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching press releases: {e}"


def get_spacs(limit: int = 15) -> str:
    """List SPACs (special-purpose acquisition companies) with trust size, NAV premium, status, and target. Use for 'SPACs', 'de-SPAC', 'SPACs by trust size'."""
    try:
        from engine.publicmarkets.spacs import spac_summary
        return spac_summary(limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching SPACs: {e}"


def get_ipo_map(limit: int = 12) -> str:
    """Recent priced IPOs with best/worst performers since listing. Use for 'recent IPOs', 'IPO map', 'how are new IPOs doing'."""
    try:
        from engine.publicmarkets.ipo import ipo_summary
        return ipo_summary(limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching IPOs: {e}"


def get_ipo_pipeline(limit: int = 15) -> str:
    """Pre-IPO private companies and upcoming/filed listings. Use for 'IPO pipeline', 'upcoming IPOs', 'who's about to go public'."""
    try:
        from engine.publicmarkets.ipo import ipo_pipeline_summary
        return ipo_pipeline_summary(limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching IPO pipeline: {e}"


def get_top_funds(limit: int = 15) -> str:
    """Largest institutional managers by 13F portfolio value (AUM). Use for 'biggest hedge funds', 'top institutional managers', 'largest 13F filers'."""
    try:
        from engine.publicmarkets.hedge_funds import top_funds_summary
        return top_funds_summary(limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching top funds: {e}"


def get_activist_filings(ticker: str = "", limit: int = 15) -> str:
    """Recent activist / 13D filings, optionally filtered by target ticker. Use for 'activist filings', 'who's an activist in TSLA', 'recent 13D filings'."""
    try:
        from engine.publicmarkets.hedge_funds import activist_summary
        return activist_summary(ticker.upper() if ticker else "", limit)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching activist filings: {e}"


def search_sec_filings(query: str, ticker: str = "", forms: str = "") -> str:
    """Search SEC EDGAR filings by full-text query (optionally filter by ticker or form type like 10-K/10-Q/8-K/S-1)."""
    try:
        from engine.publicmarkets import edgar
        d = edgar.search_filings(query, forms=forms, ticker=ticker.upper(), limit=15)
        if d.get("error"):
            return f"SEC search error: {d['error']}"
        rows = d.get("results", [])
        if not rows:
            return f"No SEC filings found for “{query}”."
        md = [f"**SEC filings — {d.get('total', 0)} hits for “{query}”**", "",
              "| Form | Entity | Date | Link |", "|---|---|---|---|"]
        for r in rows[:15]:
            md.append(f"| {r.get('form_type','')} | {r.get('entity_name','')[:40]} | "
                      f"{r.get('filing_date','')} | [view]({r.get('file_url','#')}) |")
        return "\n".join(md)
    except Exception as e:  # noqa: BLE001
        return f"Error searching SEC filings: {e}"


def get_company_filings(ticker: str, form_type: str = "") -> str:
    """List a company's recent SEC filings by ticker (optionally a single form type like 10-K, 8-K, 13F-HR)."""
    try:
        from engine.publicmarkets import edgar
        d = edgar.get_company_filings(ticker.upper(), form_type=form_type, limit=20)
        if d.get("error"):
            return d["error"]
        rows = d.get("filings", [])
        md = [f"**{d.get('company_name', ticker)} — recent filings**", "",
              "| Form | Date | Document |", "|---|---|---|"]
        for f in rows[:20]:
            md.append(f"| {f.get('form_type','')} | {f.get('filing_date','')} | "
                      f"[{f.get('description') or 'view'}]({f.get('url','#')}) |")
        return "\n".join(md)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching filings for {ticker}: {e}"


def get_sector_performance(years: int = 5) -> str:
    """Sector-ETF annual returns — which S&P sectors are leading/lagging over the last N years (default 5)."""
    try:
        from engine.publicmarkets.market_intel import sector_insights
        return sector_insights(years)
    except Exception as e:  # noqa: BLE001
        return f"Error fetching sector performance: {e}"


def place_paper_order(symbol: str, qty: float, side: str = "buy",
                      order_type: str = "market", limit_price: Optional[float] = None,
                      confirm: bool = True, account_id: Optional[str] = None) -> str:
    """Place a PAPER (simulated) order on Alpaca and execute it. Paper trading only —
    no real money — so it places directly (no confirmation step needed).

    order_type: 'market' (fills at the current price) or 'limit' (fills only at
    limit_price or better — pass limit_price when the user names a price, e.g.
    'buy 10 AAPL at $180'). Pass confirm=false only to preview instead of placing."""
    symbol = (symbol or "").upper().strip()
    side = (side or "buy").lower().strip()
    order_type = (order_type or "market").lower().strip()
    if side not in ("buy", "sell"):
        return "Side must be 'buy' or 'sell'."
    if order_type not in ("market", "limit"):
        return "order_type must be 'market' or 'limit'."
    try:
        qty = float(qty)
    except Exception:  # noqa: BLE001
        return "Quantity must be a number."
    if qty <= 0:
        return "Quantity must be greater than zero."
    if order_type == "limit":
        try:
            limit_price = float(limit_price)
        except Exception:  # noqa: BLE001
            return "A limit order needs a numeric limit_price (the price to buy/sell at)."

    if order_type == "limit":
        price_txt = f" @ ${limit_price:,.2f} limit"
        est_total = f" (≈ ${limit_price * qty:,.2f})"
    else:
        est = None
        try:
            from utils.data_loader import get_intraday_data
            df = get_intraday_data(symbol, interval="1d", period="5d")
            if df is not None and not df.empty:
                est = float(df["Close"].iloc[-1])
        except Exception:  # noqa: BLE001
            est = None
        price_txt = f" @ ~${est:,.2f} market" if est else " (market)"
        est_total = f" (≈ ${est * qty:,.2f})" if est else ""

    if not confirm:
        return (f"🧾 **Order preview — PAPER (simulated)**\n\n"
                f"{side.upper()} **{qty:g} {symbol}**{price_txt}{est_total}.\n\n"
                f"This is a paper trade — no real money. Reply **confirm** to place it.")

    try:
        client = _alpaca_client(account_id)
        order = client.create_order(symbol=symbol, qty=qty, side=side, type=order_type,
                                    limit_price=limit_price if order_type == "limit" else None)
        if isinstance(order, dict) and order.get("error"):
            return f"Order failed: {order['error']}"
        oid = (order or {}).get("id", "?") if isinstance(order, dict) else "?"
        status = (order or {}).get("status", "submitted") if isinstance(order, dict) else "submitted"
        return (f"✅ **Paper order placed** — {side.upper()} {qty:g} {symbol}{price_txt}.\n\n"
                f"Order id `{oid}`, status: {status}. Simulated paper trade — no real money.")
    except _NoLinkedAccount:
        return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "wash trade" in msg.lower():
            return (f"⚠️ Couldn't place that {side} order for {symbol} — the broker flagged a "
                    f"**potential wash trade** (there's an open opposite-side order for {symbol}). "
                    f"Cancel that order or let it fill first, then retry.")
        return f"Order failed: {msg}"



def list_user_accounts() -> str:
    """List all Alpaca brokerage accounts linked to the current user. Shows account name, API key hint, and status."""
    try:
        from utils.auth import get_user_accounts
        user_id = _current_user_id.get()
        if not user_id:
            return "Not logged in. Sign in to see your linked Alpaca accounts."
        accounts = get_user_accounts(user_id)
        if not accounts:
            return "No accounts found. Use `account:add <API_KEY> <SECRET_KEY>` to add one."
        md = "**Your Alpaca Accounts**\n\n"
        md += "| # | Name | Account ID | Added |\n"
        md += "|---|------|------------|-------|\n"
        for i, acc in enumerate(accounts, 1):
            created = str(acc.get("created_at", ""))[:10] if acc.get("created_at") else "-"
            short_id = str(acc.get("account_id", ""))[:8]
            md += f"| {i} | {acc.get('account_name', '')} | `{short_id}` | {created} |\n"
        md += f"\n*{len(accounts)} accounts*\n"
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



def show_recent_trades(limit: int = 20, trade_type: str = "") -> str:
    """Show recent trades from the AlpaTrade database. Use trade_type='paper' or 'backtest' to filter."""
    try:
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text
        pool = DatabasePool()
        with pool.get_session() as session:
            where = ""
            bind = {"lim": limit}
            if trade_type:
                where = "WHERE trade_type = :trade_type"
                bind["trade_type"] = trade_type
            result = session.execute(
                text(f"""
                    SELECT symbol, direction, shares, entry_price, exit_price,
                           pnl, pnl_pct, trade_type
                    FROM alpatrade.trades
                    {where}
                    ORDER BY created_at DESC LIMIT :lim
                """),
                bind,
            )
            rows = result.fetchall()
        if not rows:
            label = f" ({trade_type})" if trade_type else ""
            return f"No trades{label} found in database."
        label = f" ({trade_type})" if trade_type else ""
        md = f"**Trades{label}**\n\n"
        md += "| Symbol | Dir | Shares | Entry | Exit | P&L | P&L% | Type |\n"
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
    """Show a candlestick price chart (with volume) for a stock.
    Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."""
    try:
        from utils.data_loader import get_intraday_data
        interval = "1d" if period not in ("1d", "5d") else "5m"
        df = get_intraday_data(ticker.upper(), interval=interval, period=period)
        if df.empty:
            return f"No chart data for {ticker.upper()}"
        dates = [d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in df.index]
        _r = lambda s: [round(float(v), 2) for v in df[s]]  # noqa: E731
        vols = [int(v) for v in df["Volume"]] if "Volume" in df else []
        import json
        chart_data = json.dumps({
            "type": "candlestick",
            "ticker": ticker.upper(),
            "period": period,
            "dates": dates,
            "open": _r("Open"),
            "high": _r("High"),
            "low": _r("Low"),
            "close": _r("Close"),
            "volume": vols,
        })
        return (f"📈 Here is the **{ticker.upper()}** {period} candlestick chart, rendered below.\n\n"
                f"__CHART_DATA__{chart_data}__END_CHART__")
    except Exception as e:
        return f"Error generating chart for {ticker}: {e}"


def show_market_map(period: str = "1mo") -> str:
    """Show a finviz-style market map — a treemap of S&P 500 sectors and stocks
    coloured by return (green up / red down), sized by liquidity. Use when the
    user asks for a market map, sector heatmap, or 'how is the market doing'.
    Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, ytd."""
    try:
        from engine.market_map import market_map_data
        import json
        d = market_map_data(period)
        if d.get("error") or not d.get("stocks"):
            return f"Couldn't build the market map right now ({d.get('error', 'no data')})."
        up = sum(1 for s in d["stocks"] if s["return"] > 0)
        best = d["sectors"][0] if d["sectors"] else None
        worst = d["sectors"][-1] if d["sectors"] else None
        chart_data = json.dumps({"type": "treemap", **d})
        summary = f"🗺️ **Market map** ({d['period']}) — {up}/{len(d['stocks'])} names green."
        if best and worst:
            summary += (f" Best sector: **{best['name']}** ({best['return']:+.1f}%); "
                        f"worst: **{worst['name']}** ({worst['return']:+.1f}%).")
        return f"{summary} Rendered below.\n\n__CHART_DATA__{chart_data}__END_CHART__"
    except Exception as e:  # noqa: BLE001
        return f"Error building market map: {e}"


def compare_stocks(tickers: str, period: str = "6mo") -> str:
    """Compare the normalised total return of several stocks on one chart.
    `tickers` is a comma/space-separated list (e.g. 'AAPL, MSFT, NVDA').
    Period: 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd."""
    try:
        import re, json
        from utils.data_loader import get_intraday_data
        syms = [t for t in re.split(r"[,\s]+", (tickers or "").upper()) if t][:8]
        if not syms:
            return "Give me at least one ticker to compare."
        series, summary = [], []
        for sym in syms:
            df = get_intraday_data(sym, interval="1d", period=period)
            if df.empty or len(df) < 2:
                continue
            closes = [float(c) for c in df["Close"]]
            base = closes[0] or closes[-1]
            pct = [round((c - base) / base * 100.0, 2) for c in closes]
            dates = [d.isoformat() if hasattr(d, "isoformat") else str(d) for d in df.index]
            series.append({"name": sym, "dates": dates, "pct": pct})
            summary.append((sym, pct[-1]))
        if not series:
            return f"No data for {', '.join(syms)}."
        summary.sort(key=lambda x: x[1], reverse=True)
        line = ", ".join(f"**{s}** {p:+.1f}%" for s, p in summary)
        chart_data = json.dumps({"type": "compare", "period": period, "series": series})
        return (f"📊 **{period} return comparison** — {line}. Rendered below.\n\n"
                f"__CHART_DATA__{chart_data}__END_CHART__")
    except Exception as e:  # noqa: BLE001
        return f"Error comparing stocks: {e}"



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


def list_index_option_contracts(
    underlying: str, contract_type: str = "", min_expiration: str = "",
    max_expiration: str = "", limit: int = 20,
) -> str:
    """List active Alpaca PAPER contracts for SPX/SPXW/VIX/VIXW/DJX/XSP."""
    try:
        from engine.brokers.index_options import list_contracts
        client = _alpaca_client()
        contracts = list_contracts(
            client.trading_client, underlying, contract_type=contract_type or None,
            min_expiration=min_expiration or None, max_expiration=max_expiration or None,
            limit=limit,
        )
        if not contracts:
            return "No matching active index-option contracts found."
        lines = ["| Symbol | Type | Strike | Expiration | Style |", "|---|---|---:|---|---|"]
        for contract in contracts:
            lines.append(
                f"| {contract.get('symbol', '')} | {contract.get('type', '')} | "
                f"{contract.get('strike_price', '')} | {contract.get('expiration_date', '')} | "
                f"{contract.get('style', '')} |"
            )
        return "\n".join(lines)
    except _NoLinkedAccount:
        return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
    except Exception as e:  # noqa: BLE001
        return f"Error listing index-option contracts: {e}"


def place_index_option_paper_order(
    symbol: str, qty: int, side: str = "buy", limit_price: Optional[float] = None,
) -> str:
    """Submit a paper-only index-option DAY order using a discovered contract symbol."""
    try:
        from engine.brokers.index_options import submit_order
        client = _alpaca_client()
        order = submit_order(
            client.trading_client, symbol, qty, side, limit_price=limit_price,
        )
        return (
            "🧾 **Index-option PAPER order submitted**\n\n"
            f"- Contract: `{order.get('symbol', symbol)}`\n"
            f"- Side / quantity: {order.get('side', side)} {order.get('qty', qty)}\n"
            f"- Status: {order.get('status', 'submitted')}\n"
            f"- Order ID: `{order.get('id', 'unknown')}`\n\n"
            "Cash-settled, European-style contract; submission does not guarantee a fill."
        )
    except _NoLinkedAccount:
        return "No linked Alpaca account. Use `account:add <API_KEY> <SECRET_KEY>` to connect your paper account."
    except Exception as e:  # noqa: BLE001
        return f"Error placing index-option paper order: {e}"



def show_equity_curve(run_id: str = "", trade_type: str = "", strategy: str = "") -> str:
    """Show equity curve chart — delegates to shared utility."""
    from utils.equity_chart import show_equity_curve as _show
    return _show(run_id=run_id, trade_type=trade_type, strategy=strategy)


# ---------------------------------------------------------------------------
# Build the primary DeepAgents harness from tool functions
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
        description="Show recent trades from the database. Use trade_type='paper' for paper trades only, 'backtest' for backtests only."),
    StructuredTool.from_function(show_stock_chart, name="show_stock_chart",
        description="Show a candlestick price chart (with volume) for a single stock. Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."),
    StructuredTool.from_function(show_market_map, name="show_market_map",
        description="Show a finviz-style market map: a treemap of S&P sectors/stocks coloured by return. Use for 'market map', 'sector heatmap', 'how's the market'. Period: 1d, 5d, 1mo, 3mo, 6mo, 1y, ytd."),
    StructuredTool.from_function(compare_stocks, name="compare_stocks",
        description="Compare normalised returns of multiple stocks on one chart. tickers is a comma/space list. Use for 'compare X vs Y', 'X vs Y vs Z performance'. Period: 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd."),
    StructuredTool.from_function(show_recent_runs, name="show_recent_runs",
        description="Show recent backtest/paper trade runs from the AlpaTrade database."),
    StructuredTool.from_function(get_top_strategies, name="get_top_strategies",
        description="Rank the best-performing strategies by return/Sharpe. Use when the user asks which strategies performed best / top strategies / rankings. trade_type: 'backtest', 'paper', or 'all'."),
    StructuredTool.from_function(show_equity_curve, name="show_equity_curve",
        description="Show equity curve chart. Use trade_type='paper' or 'backtest' to filter. Use run_id for a specific run. Default: latest run."),
    StructuredTool.from_function(place_paper_order, name="place_paper_order",
        description="Place a PAPER (simulated) buy/sell order and execute it (paper only — no real money). order_type='market' or 'limit' (pass limit_price for limit). Use for any buy/sell request."),
    StructuredTool.from_function(list_index_option_contracts, name="list_index_option_contracts",
        description="Discover active European-style Alpaca PAPER index-option contracts for SPX, SPXW, VIX, VIXW, DJX, or XSP. Dates use YYYY-MM-DD."),
    StructuredTool.from_function(place_index_option_paper_order, name="place_index_option_paper_order",
        description="Submit a paper-only DAY order for an index-option contract previously returned by list_index_option_contracts."),
    StructuredTool.from_function(get_pnl_report, name="get_pnl_report",
        description="Get today's paper account P&L report: day P&L, portfolio value, and open positions with unrealised P&L. Use for 'how's my P&L', 'pnl report', 'how am I doing today', 'show my paper account'."),
    StructuredTool.from_function(get_premarket_movers, name="get_premarket_movers",
        description="Show top US premarket movers, gainers and fallers by sector with press-release catalysts. Set refresh=true only when explicitly asked for a fresh 165-stock scan."),
    StructuredTool.from_function(analyze_prediction_correlation, name="analyze_prediction_correlation",
        description="Analyze stored Finespresso model predictions versus realized next-day moves. Filter by normalized event or industry and render an event×industry heatmap or predicted-vs-actual scatter."),
    StructuredTool.from_function(search_sec_filings, name="search_sec_filings",
        description="Search SEC EDGAR filings by full-text query. Optional ticker filter and form type (10-K, 10-Q, 8-K, S-1, DEF 14A, 13F-HR). Use for 'find SEC filings mentioning X', 'search 8-Ks about layoffs'."),
    StructuredTool.from_function(get_company_filings, name="get_company_filings",
        description="List a company's recent SEC filings by ticker (optional single form type). Use for 'recent filings for AAPL', 'latest 10-K of MSFT', 'NVDA 8-Ks'."),
    StructuredTool.from_function(get_sector_performance, name="get_sector_performance",
        description="Sector-ETF annual returns — which S&P sectors are leading/lagging over the last N years. Use for 'sector performance', 'which sectors are hot', 'sector rotation'."),
    StructuredTool.from_function(get_ipo_map, name="get_ipo_map",
        description="Recent priced IPOs and their performance since listing (best/worst). Use for 'recent IPOs', 'how are IPOs doing', 'IPO map'."),
    StructuredTool.from_function(get_ipo_pipeline, name="get_ipo_pipeline",
        description="Pre-IPO private companies + upcoming/filed listings. Use for 'IPO pipeline', 'upcoming IPOs', 'who's about to go public'."),
    StructuredTool.from_function(get_top_funds, name="get_top_funds",
        description="Largest institutional managers by 13F AUM. Use for 'biggest hedge funds', 'top institutional managers', 'largest 13F filers'."),
    StructuredTool.from_function(get_activist_filings, name="get_activist_filings",
        description="Recent activist / 13D filings, optionally by target ticker. Use for 'activist filings', 'activists in TSLA', 'recent 13D filings'."),
    StructuredTool.from_function(get_press_releases, name="get_press_releases",
        description="Search company press releases / news by headline keyword and/or ticker, with a modeled directional read. Use for 'press releases for NVDA', 'news about earnings', 'headlines on TSLA'."),
    StructuredTool.from_function(get_spacs, name="get_spacs",
        description="List SPACs with trust size, NAV premium, status, and target. Use for 'SPACs', 'de-SPAC candidates', 'SPACs by trust size'."),
]

from engine.config import get_settings, build_chat_model
from engine.agents.runtime import get_runtime, RoleSpec

# The chat agent is built through the pluggable AgentRuntime adapter (AGENT_FRAMEWORK,
# default DeepAgents). DeepAgents compiles to a LangGraph-compatible graph, so the
# existing astream_events transport keeps working. The LLM axis is separate:
# MODEL_PROVIDER / MODEL_NAME
# come from engine.config, which self-heals an unavailable model (region-locked
# grok-4.5 → grok-4-1-fast-reasoning). Per-user overrides are applied by agent_for_user().
chat_runtime = get_runtime()


def _chat_role(model=None) -> RoleSpec:
    return RoleSpec(name="alpatrade-chat", instructions=SYSTEM_PROMPT, tools=TOOLS, model=model)


primary_agent = chat_runtime.build(_chat_role())
# Compatibility alias for integrations which imported this public symbol before
# DeepAgents became the primary harness.
langgraph_agent = primary_agent


# Per-user agents, cached by (provider, model, framework) so a user's Settings
# choice takes effect without rebuilding the tool graph on every request.
# Phase 3b: framework is now part of the cache key and resolved per-miss, so
# changing agent_framework in the UI takes effect on the next message (no restart).
_agent_cache: dict = {}


def agent_for_user(user_id: str | None):
    """Return the chat agent for a user's resolved model + framework settings.

    Falls back to the shared default agent when the user has no override or the
    override matches the default (keeping a single hot agent for anonymous use)."""
    if not user_id:
        return primary_agent
    try:
        s = get_settings(user_id)
        # A BYOK model client must never be shared across users.
        key = (user_id if s.api_key else None, s.model_provider, s.model_name,
               s.agent_framework)
        default = get_settings()
        if not s.api_key and (s.model_provider, s.model_name, s.agent_framework) == (
            default.model_provider, default.model_name, default.agent_framework
        ):
            return primary_agent
        if key not in _agent_cache:
            # Resolve the runtime per-miss so a framework change is picked up.
            user_runtime = get_runtime(s.agent_framework)
            _agent_cache[key] = user_runtime.build(_chat_role(build_chat_model(s, streaming=True)))
        return _agent_cache[key]
    except Exception:  # noqa: BLE001 — never let model selection break chat
        return primary_agent


def clear_agent_cache() -> None:
    """Evict all cached per-user agents. Call on settings change (Phase 3b)."""
    _agent_cache.clear()

# ---------------------------------------------------------------------------
# CLI command interceptor — routes agent:*, trades, runs, news:* etc. to
# the existing CommandProcessor instead of the AI agent
# ---------------------------------------------------------------------------

class _AppState:
    """Lightweight namespace used by CommandProcessor for shared state.

    One instance per signed-in user (keyed by ``user_id``) so that account
    switches, orchestrator handles, background tasks and command history never
    leak across users. ``None`` is the anonymous / legacy CLI key.
    """
    def __init__(self):
        self._orch = None
        self._bg_task = None
        self._bg_stop = threading.Event()
        self.command_history: list = []
        self.account_id: Optional[str] = None


# Per-user app state (None key = anonymous / legacy CLI path).
_app_states: Dict[Optional[str], _AppState] = {}
_app_states_lock = threading.Lock()


def get_app_state(user_id: Optional[str] = None) -> _AppState:
    """Return (creating if needed) the per-user app state for ``user_id``."""
    with _app_states_lock:
        if user_id not in _app_states:
            _app_states[user_id] = _AppState()
        return _app_states[user_id]

# Commands that should bypass the AI agent and go to CommandProcessor
_CLI_BASES = {"news", "profile", "financials", "price", "movers", "analysts", "valuation",
              "chart", "equity", "trades", "runs", "top", "report", "load", "pnl"}
_CLI_EXACT = {"status", "help", "guide", "positions", "account", "accounts"}

# Long-running commands that get streamed with log console instead of blocking
_STREAMING_COMMANDS = {
    "agent:backtest", "agent:paper", "agent:full",
    "agent:validate", "agent:reconcile",
    "alpha:growth", "alpha:value", "alpha:compare",
}


async def _command_interceptor(msg: str, session):
    """Detect CLI commands and route to CommandProcessor. Returns markdown or None."""
    # Bind the signed-in user so Alpaca tools (positions/account) resolve
    # per-user keys even when the interceptor is invoked directly.
    _uid = session.get("user", {}).get("user_id") if session.get("user") else None
    set_request_user(_uid)
    app_state = get_app_state(_uid)
    cmd_lower = msg.strip().lower()
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    base = first_word.split(":")[0]

    is_command = (
        first_word.startswith("agent:") or
        first_word.startswith("alpha:") or
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

    # equity [paper|backtest] [slug] [run-id] — equity curve chart
    if base == "equity":
        _TYPES = {"paper", "backtest"}
        parts = msg.strip().split()
        rid = ""
        trade_type = ""
        strategy = ""
        # Parse: equity:RUN_ID or equity paper btd RUN_ID
        if ":" in parts[0] and parts[0].split(":", 1)[1].strip():
            suffix = parts[0].split(":", 1)[1].strip()
            if suffix in _TYPES:
                trade_type = suffix
            else:
                rid = suffix
        for p in parts[1:]:
            pl = p.lower()
            if pl in _TYPES and not trade_type:
                trade_type = pl
            elif len(p) >= 8 and "-" in p and not rid:
                rid = p
            elif not strategy:
                strategy = pl
        return show_equity_curve(run_id=rid, trade_type=trade_type, strategy=strategy)

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
            app_state.account_id = matched["account_id"]
            app_state._orch = None
            return f"✓ **Switched to: {matched['account_name']}** (`{matched.get('api_key_hint', '****')}`)"
        return f"✗ No account matches '{query}'. Type `accounts` to see the list."

    # Long-running commands → return StreamingCommand sentinel
    if first_word in _STREAMING_COMMANDS:
        return StreamingCommand(msg, session, app_state)

    from tui.command_processor import CommandProcessor
    user_id = session.get("user", {}).get("user_id") if session.get("user") else None
    cp = CommandProcessor(app_state, user_id=user_id)
    try:
        result = await cp.process_command(msg)
    except Exception as e:
        result = f"# Error\n\n```\n{e}\n```"
    return result or "Command executed."


_AGUI_HELP = """# AlpaTrade Commands

## Choose an AI Runtime
- `/hermes your request` — use Hermes for one message
- `/hermes start my best candidate in continuous paper trading and email daily reports`
- `/hermes show my recent jobs` or pause/resume/stop an owned paper job by ID
- `/hermes help` — portfolio advice, notification, and paper-control commands
- `/hermes notify me both in app and email for paper job <job-id>`
- `/deepagents your request` — use DeepAgents for one message
- `/langgraph your request` — use LangGraph for one message

An unprefixed message continues using the framework selected in Settings.

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
Use `command:type` to filter by backtest or paper. Add optional params after.

| Command | Description |
|---------|-------------|
| `trades:backtest` | backtest trades |
| `trades:paper` | paper trades |
| `trades:all` | both types, all accounts |
| `runs:backtest` / `runs:paper` | recent runs by type |
| `report:backtest` / `report:paper` | performance summary |
| `report run-id:<uuid>` | single run detail |
| `top:backtest` / `top:paper` | rank strategies |
| `top:all` | all types + accounts |
| `pnl run-id:<uuid>` | P&L breakdown |
| `positions` | open Alpaca positions |
| `agent:status` | agent states |
| `agent:logs` | paper trade log tail |
| `agent:stop` | stop background task |

**Optional filters** (append to any query command):
- `slug:btd` — filter by strategy slug
- `run-id:<uuid>` — specific run
- `limit:10` — limit rows
- `scope:all` — all accounts (default: active account)

## Market Research
- `load:AAPL` — stock quote + inline price chart
- `load:TSLA period:1y` — custom period
- `news:TSLA` — company news
- `price:AAPL` — stock quote
- `profile:MSFT` — company profile
- `analysts:GOOGL` — analyst ratings
- `financials:AAPL` — income & balance sheet
- `valuation:AAPL,MSFT` — valuation comparison
- `movers` — top gainers & losers

## Alpha Research
- `alpha:growth ticker:AAPL` — durable growth and moat review
- `alpha:value ticker:BBY` — undervaluation and value-trap review
- `alpha:compare ticker:AAPL` — compact Growth and Value perspectives
- `alpha:runs limit:10` — recent saved Alpha Research reports
- `alpha:show run-id:<uuid>` — open one saved Alpha Research report

## Alpaca Account
- `positions` — open positions from Alpaca paper account
- `account` — account summary (portfolio value, cash, buying power)

## Charts (rendered inline with download button)
- `chart:AAPL` — stock price chart (3mo default)
- `chart:TSLA period:1y` — custom period
- `equity` — equity curve for latest run
- `equity backtest` — latest backtest equity
- `equity paper` — latest paper trade equity
- `equity paper btd` — paper + slug filter
- `equity <run-id>` — specific run equity curve

## AI Chat
Type any question to chat with AI about stocks & trading.
"""
