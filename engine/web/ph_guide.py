"""Guide / help + download pages for the merged AlpaTrade app.

Ports ``web_app.py``'s ``/guide`` user guide, ``/download`` install page and the
``/install.sh`` passthrough into the PEHero house style. Everything renders
through :func:`engine.web.ph_layout.page` so the parchment / forest shell (left
command menu, center column) stays identical to the rest of the app. The news
pane is dropped on these long-form reading pages.

Feature-module contract: :func:`register(app, rt)` attaches the routes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fasthtml.common import (
    A, Button, Code, Div, H1, H2, H3, H4, Hr, Li, NotStr, Ol, P, Pre, Span,
    Strong, Style, Table, Tbody, Td, Th, Thead, Tr, Ul,
)
from starlette.responses import Response

from engine.web.ph_layout import page

# --- scoped styles (pehero tokens; only what .content doesn't already give) --
_GUIDE_CSS = """
.app{padding-right:0}
.guide{max-width:840px;margin:0 auto;padding-bottom:3rem}
.guide h1{margin-bottom:.2rem}
.guide h2{border-bottom:1px solid var(--line);padding-bottom:.3rem;scroll-margin-top:1rem;margin-top:1.6rem}
.guide h3{color:var(--accent);scroll-margin-top:1rem}
.guide ul,.guide ol{padding-left:1.2rem;margin:.4rem 0}
.guide li{font-size:.85rem;color:var(--ink-muted);line-height:1.5;margin-bottom:.25rem}
.guide strong{color:var(--ink)}
.guide .lead{color:var(--ink-dim)}
.guide .toc{background:var(--bg-elev);border:1px solid var(--line);padding:1rem 1.4rem;border-radius:.6rem;margin:1rem 0 1.5rem}
.guide .toc h4{margin:0 0 .4rem;font-size:.85rem;color:var(--ink)}
.guide .toc a{color:var(--accent);text-decoration:none;font-size:.82rem}
.guide .toc a:hover{text-decoration:underline}
.guide .toc ul{margin:.2rem 0 .2rem 1rem}
.guide .toc li{margin-bottom:.15rem}
.guide .param-grid{background:var(--bg-elev);border:1px solid var(--line);padding:.8rem 1.1rem;border-radius:.6rem;margin:.6rem 0}
.guide .tip{background:var(--accent-dim);border:1px solid var(--line);padding:.6rem 1rem;border-radius:.5rem;font-size:.8rem;color:var(--ink-muted);margin:.9rem 0}
.guide .tip::before{content:"Tip: ";font-weight:700;color:var(--accent)}
.guide .cmd-copy{position:relative;margin:.5rem 0}
.copy-btn{position:absolute;top:.4rem;right:.4rem;padding:.2rem .6rem;font-size:.7rem;font-family:var(--font-body);color:var(--accent);background:var(--accent-dim);border:1px solid var(--line);border-radius:.3rem;cursor:pointer}
.copy-btn:hover{background:var(--accent);color:var(--bg)}
.dl-req li{margin-bottom:.3rem}
"""


# ---------------------------------------------------------------------------
# shared chrome
# ---------------------------------------------------------------------------
def _header(title: str, sub_href: str = "/equities", sub_label: str = "Open app"):
    return Div(
        Div(
            Button("☰", cls="mobile-menu-btn", type="button", onclick="toggleLeftPane()"),
            Span(title, cls="chat-header-title"),
            cls="chat-header-left",
        ),
        Div(A(sub_label, href=sub_href, cls="news-toggle-btn"), cls="chat-header-right"),
        cls="chat-header",
    )


def _user(session):
    """Best-effort current user so the left footer shows profile vs. sign-in."""
    uid = session.get("user_id") if session else None
    if not uid:
        return None
    try:
        from engine.auth import get_user_by_id
        return get_user_by_id(uid)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# user guide — sections (ported verbatim from web_app.py)
# ---------------------------------------------------------------------------
def _guide_toc():
    return Div(
        H4("Table of Contents"),
        Ul(
            Li(A("Backtesting", href="#backtest")),
            Ul(
                Li(A("Quick Start", href="#bt-quickstart")),
                Li(A("Parameter Grid", href="#bt-grid")),
                Li(A("Parameters Reference", href="#bt-params")),
                Li(A("Reading Results", href="#bt-results")),
                Li(A("Equity Curve Chart", href="#bt-chart")),
            ),
            Li(A("Paper Trading", href="#paper")),
            Ul(
                Li(A("Starting a Session", href="#pt-start")),
                Li(A("Monitoring & Stopping", href="#pt-monitor")),
                Li(A("Email Reports", href="#pt-email")),
            ),
            Li(A("Full Cycle", href="#full")),
            Li(A("Validation", href="#validate")),
            Li(A("Reconciliation", href="#reconcile")),
            Li(A("Research Commands", href="#research")),
            Ul(
                Li(A("News", href="#r-news")),
                Li(A("Company Profile", href="#r-profile")),
                Li(A("Financials", href="#r-financials")),
                Li(A("Price & Technicals", href="#r-price")),
                Li(A("Market Movers", href="#r-movers")),
                Li(A("Analyst Ratings", href="#r-analysts")),
                Li(A("Valuation Comparison", href="#r-valuation")),
            ),
            Li(A("Query & Reporting", href="#query")),
            Ul(
                Li(A("Trades & Runs", href="#q-trades")),
                Li(A("Performance Reports", href="#q-report")),
                Li(A("Top Strategies", href="#q-top")),
            ),
            Li(A("Strategy Slugs", href="#slugs")),
            Ul(
                Li(A("Format", href="#s-format")),
                Li(A("Buy the Dip", href="#s-btd")),
                Li(A("Momentum", href="#s-mom")),
                Li(A("VIX Fear Index", href="#s-vix")),
                Li(A("Box-Wedge", href="#s-bwg")),
            ),
            Li(A("Options & Flags", href="#options")),
            Ul(
                Li(A("Extended Hours", href="#o-hours")),
                Li(A("Intraday Exits", href="#o-intraday")),
                Li(A("PDT Rule", href="#o-pdt")),
            ),
        ),
        cls="toc",
    )


def _guide_backtest():
    return (
        H2("Backtesting", id="backtest"),

        H3("Quick Start", id="bt-quickstart"),
        P("Run a parameterized backtest across multiple strategy configurations:"),
        Pre(Code("agent:backtest lookback:1m")),
        P("This runs the Buy the Dip strategy over the last month using the default "
          "7 symbols (AAPL, MSFT, GOOGL, AMZN, NVDA, TSLA, META) with $10,000 starting "
          "capital. The backtester automatically tests multiple parameter combinations and "
          "reports the best one."),

        H3("Parameter Grid", id="bt-grid"),
        P("The backtester doesn't run a single configuration — it builds a ",
          Strong("parameter grid"), " and tests every combination. This is how it finds "
          "the optimal strategy parameters for the given time period."),
        Div(
            P(Strong("Default grid for Buy the Dip:")),
            NotStr("""<table>
<thead><tr><th>Parameter</th><th>Values tested</th><th>Count</th></tr></thead>
<tbody>
<tr><td><code>dip_threshold</code></td><td>3%, 5%, 7%</td><td>3</td></tr>
<tr><td><code>take_profit</code></td><td>1%, 1.5%</td><td>2</td></tr>
<tr><td><code>hold_days</code></td><td>1, 2, 3 days</td><td>3</td></tr>
<tr><td><code>stop_loss</code></td><td>0.5%</td><td>1</td></tr>
<tr><td><code>position_size</code></td><td>10%</td><td>1</td></tr>
</tbody></table>"""),
            P("Total combinations: 3 x 2 x 3 x 1 x 1 = ", Strong("18 variations")),
            cls="param-grid",
        ),
        P("Each variation runs a full backtest — fetching price data, simulating entries "
          "and exits, calculating P&L, fees, and risk metrics. The best configuration is "
          "selected by ", Strong("Sharpe ratio"), " (risk-adjusted return)."),
        Div("The grid uses itertools.product() internally, so adding more values to any "
            "parameter multiplies the total. Keep grids reasonable (under ~100 variations) "
            "to avoid long runtimes.", cls="tip"),

        H3("Parameters Reference", id="bt-params"),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Default</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>lookback:1m</code></td><td>3m</td><td>Data period — <code>1m</code>, <code>3m</code>, <code>6m</code>, <code>1y</code></td></tr>
<tr><td><code>symbols:AAPL,TSLA</code></td><td>7 large caps</td><td>Comma-separated ticker list</td></tr>
<tr><td><code>capital:50000</code></td><td>10000</td><td>Starting capital ($)</td></tr>
<tr><td><code>strategy:buy_the_dip</code></td><td>buy_the_dip</td><td>Strategy name</td></tr>
<tr><td><code>hours:extended</code></td><td>regular</td><td>Include pre/after-market (4AM-8PM ET)</td></tr>
<tr><td><code>intraday_exit:true</code></td><td>false</td><td>Use 5-min bars for precise TP/SL timing</td></tr>
<tr><td><code>pdt:false</code></td><td>auto</td><td>Disable Pattern Day Trader rule (for &gt;$25k accounts)</td></tr>
</tbody></table>"""),
        P(Strong("Examples:")),
        Pre(Code(
            "# 1-month backtest, custom symbols\n"
            "agent:backtest lookback:1m symbols:AAPL,TSLA,NVDA\n\n"
            "# 6-month backtest with extended hours\n"
            "agent:backtest lookback:6m hours:extended\n\n"
            "# Large account, no PDT rule, intraday exits\n"
            "agent:backtest lookback:3m capital:50000 pdt:false intraday_exit:true"
        )),

        H3("Reading Results", id="bt-results"),
        P("After a backtest completes, you'll see a results table:"),
        NotStr("""<table>
<thead><tr><th>Metric</th><th>What it means</th></tr></thead>
<tbody>
<tr><td><strong>Sharpe Ratio</strong></td><td>Risk-adjusted return. Higher is better. &gt;1 is good, &gt;2 is excellent</td></tr>
<tr><td><strong>Total Return</strong></td><td>Percentage gain/loss on initial capital</td></tr>
<tr><td><strong>Annualized Return</strong></td><td>Return projected to a 1-year basis</td></tr>
<tr><td><strong>Total P&amp;L</strong></td><td>Dollar profit or loss</td></tr>
<tr><td><strong>Win Rate</strong></td><td>Percentage of trades that were profitable</td></tr>
<tr><td><strong>Total Trades</strong></td><td>Number of trades executed across all symbols</td></tr>
<tr><td><strong>Max Drawdown</strong></td><td>Largest peak-to-trough decline. Lower is better</td></tr>
</tbody></table>"""),
        P("The ", Strong("Params"), " line shows which parameter combination won: "
          "dip threshold, take profit target, and hold days."),

        H3("Equity Curve Chart", id="bt-chart"),
        P("An interactive Plotly chart renders below the results showing:"),
        Ul(
            Li(Strong("Strategy"), " (blue solid) — your portfolio value over time"),
            Li(Strong("Buy & Hold SPY"), " (orange dashed) — S&P 500 benchmark"),
            Li(Strong("Buy & Hold Portfolio"), " (green dotted) — holding your symbols passively"),
            Li(Strong("Initial Capital"), " (gray dashed) — starting value reference"),
        ),
        P("Hover over the chart to compare values at any date. If the blue line is above "
          "the others, the strategy outperformed passive investing."),
    )


def _guide_paper():
    return (
        H2("Paper Trading", id="paper"),

        H3("Starting a Session", id="pt-start"),
        P("Paper trading runs continuously in the background, placing real orders on "
          "Alpaca's paper trading API:"),
        Pre(Code("agent:paper duration:7d")),
        P("This monitors your symbols every 5 minutes for 7 days, executing the Buy the "
          "Dip strategy with real market data — but no real money is at risk."),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Default</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>duration:7d</code></td><td>7d</td><td>How long to run — <code>1h</code>, <code>1d</code>, <code>7d</code>, <code>1m</code></td></tr>
<tr><td><code>symbols:AAPL,MSFT</code></td><td>7 large caps</td><td>Tickers to trade</td></tr>
<tr><td><code>poll:60</code></td><td>300</td><td>Seconds between strategy checks</td></tr>
<tr><td><code>hours:extended</code></td><td>regular</td><td>Trade pre/after-market</td></tr>
<tr><td><code>email:false</code></td><td>true</td><td>Disable daily P&amp;L email reports</td></tr>
<tr><td><code>pdt:false</code></td><td>auto</td><td>Disable PDT rule</td></tr>
</tbody></table>"""),

        H3("Monitoring & Stopping", id="pt-monitor"),
        Pre(Code(
            "agent:status    # check paper trading state\n"
            "agent:stop      # cancel the background session"
        )),
        P("Paper trading logs appear in the console. When the session ends, a summary "
          "with total trades and P&L is shown."),

        H3("Email Reports", id="pt-email"),
        P("When enabled (default), a daily P&L summary is emailed via Postmark. "
          "Requires ", Code("POSTMARK_API_KEY"), ", ", Code("TO_EMAIL"), ", and ",
          Code("FROM_EMAIL"), " in your ", Code(".env"), " file."),
    )


def _guide_full():
    return (
        H2("Full Cycle", id="full"),
        P("The full cycle chains all phases automatically:"),
        Pre(Code("agent:full lookback:1m duration:1m")),
        P("Workflow:"),
        Ol(
            Li(Strong("Backtest"), " — find the optimal parameters"),
            Li(Strong("Validate"), " — check backtest trades for anomalies"),
            Li(Strong("Paper Trade"), " — deploy the winning config live (paper)"),
            Li(Strong("Validate"), " — verify paper trades against market data"),
        ),
        P("Each phase passes its results to the next. If validation finds issues, "
          "it attempts up to 10 self-correction iterations before stopping."),
        NotStr("""<table>
<thead><tr><th>Parameter</th><th>Description</th></tr></thead>
<tbody>
<tr><td><code>lookback:3m</code></td><td>Backtest data period</td></tr>
<tr><td><code>duration:1m</code></td><td>Paper trading duration</td></tr>
<tr><td><code>symbols:AAPL,TSLA</code></td><td>Tickers to trade</td></tr>
<tr><td><code>hours:extended</code></td><td>Extended trading hours</td></tr>
</tbody></table>"""),
    )


def _guide_validate():
    return (
        H2("Validation", id="validate"),
        P("Validate backtest or paper trade results against real market data:"),
        Pre(Code(
            "agent:validate run-id:abc12345\n"
            "agent:validate run-id:abc12345 source:paper_trade"
        )),
        P("The validator checks:"),
        Ul(
            Li("Price accuracy — do entry/exit prices match actual market data?"),
            Li("P&L math — is profit/loss calculated correctly?"),
            Li("Market hours — were trades placed during valid trading hours?"),
            Li("Weekend trades — no trades should occur on weekends"),
            Li("TP/SL logic — did take-profit and stop-loss triggers fire correctly?"),
        ),
        P("If anomalies are found, the validator attempts up to ", Strong("10 self-correction "
          "iterations"), " to fix them. After 10 failures, it stops and reports the issues "
          "with suggestions."),
    )


def _guide_reconcile():
    return (
        H2("Reconciliation", id="reconcile"),
        P("Compare your database records against your actual Alpaca account:"),
        Pre(Code(
            "agent:reconcile              # last 7 days\n"
            "agent:reconcile window:14d   # last 14 days"
        )),
        P("Reports:"),
        Ul(
            Li(Strong("Position mismatches"), " — DB says you hold X shares but Alpaca disagrees"),
            Li(Strong("Missing trades"), " — orders in Alpaca not recorded in DB"),
            Li(Strong("Extra trades"), " — DB trades not found in Alpaca"),
            Li(Strong("P&L comparison"), " — DB total P&L vs Alpaca equity/cash"),
        ),
    )


def _guide_research():
    return (
        H2("Research Commands", id="research"),
        P("Market research commands use the ", Code("command:TICKER"), " syntax. "
          "Data is sourced from XAI Grok and Tavily APIs."),

        H3("News", id="r-news"),
        Pre(Code(
            "news:TSLA                    # company news (default 10 articles)\n"
            "news:TSLA limit:20           # more articles\n"
            "news:TSLA provider:xai       # force XAI Grok provider\n"
            "news:TSLA provider:tavily    # force Tavily search\n"
            "news                         # general market news"
        )),
        P("Returns headlines with source and date. By default, the system tries XAI first "
          "and falls back to Tavily."),

        H3("Company Profile", id="r-profile"),
        Pre(Code("profile:TSLA")),
        P("Company overview: sector, industry, market cap, description, and key stats."),

        H3("Financials", id="r-financials"),
        Pre(Code(
            "financials:AAPL              # annual income & balance sheet\n"
            "financials:AAPL period:quarterly"
        )),
        P("Revenue, net income, EPS, debt, and other fundamental data."),

        H3("Price & Technicals", id="r-price"),
        Pre(Code("price:TSLA")),
        P("Current quote, daily change, volume, 52-week range, and technical indicators."),

        H3("Market Movers", id="r-movers"),
        Pre(Code(
            "movers              # top gainers and losers\n"
            "movers gainers      # only gainers\n"
            "movers losers       # only losers"
        )),
        P("Today's biggest price movers in the US market."),

        H3("Analyst Ratings", id="r-analysts"),
        Pre(Code("analysts:AAPL")),
        P("Consensus rating (buy/hold/sell), price targets, and recent analyst actions."),

        H3("Valuation Comparison", id="r-valuation"),
        Pre(Code(
            "valuation:AAPL              # single stock valuation\n"
            "valuation:AAPL,MSFT,GOOGL   # side-by-side comparison"
        )),
        P("P/E, P/S, P/B, EV/EBITDA, and other valuation multiples. Compare "
          "multiple tickers to spot relative value."),
    )


def _guide_query():
    return (
        H2("Query & Reporting", id="query"),

        H3("Trades & Runs", id="q-trades"),
        Pre(Code(
            "trades                       # latest run's trades (current account)\n"
            "trades paper                 # paper trades only\n"
            "trades backtest              # backtest trades only\n"
            "trades paper btd             # paper + strategy slug filter\n"
            "trades backtest btd-3dp      # backtest + specific slug\n"
            "trades all                   # all accounts (not just active)\n"
            "runs                         # recent runs\n"
            "runs paper                   # paper runs only\n"
            "runs backtest                # backtest runs only"
        )),
        P("Filter order: ", Code("type"), " → ", Code("slug"), " → ",
          Code("run-id"), " (all optional). Add ", Code("all"),
          " to see across all linked accounts. Default: current user + active account, latest run."),

        H3("Performance Reports", id="q-report"),
        Pre(Code(
            "report                       # summary of recent runs\n"
            "report paper                 # paper runs summary\n"
            "report backtest              # backtest runs summary\n"
            "report <run-id>              # detailed single-run report\n"
            "report paper btd             # paper + strategy slug filter\n"
            "report all                   # all accounts"
        )),
        P("The summary view shows a compact table with return, Sharpe ratio, P&L, "
          "and trade count for each run. The detail view shows full metrics for a "
          "specific run."),

        H3("Top Strategies", id="q-top"),
        Pre(Code(
            "top                          # rank strategies (backtest)\n"
            "top paper                    # rank paper trade results\n"
            "top paper btd               # paper + slug filter\n"
            "top all                      # all accounts"
        )),
        P("Aggregates across all runs to rank strategy configurations by average "
          "annualized return. Shows Sharpe ratio, return, win rate, drawdown, and "
          "how many times each config has been tested."),
    )


def _guide_slugs():
    return (
        H2("Strategy Slugs", id="slugs"),
        P("Each backtest variation gets a human-readable ", Strong("slug"),
          " that encodes the strategy type, parameters, and lookback period "
          "into a compact identifier. Slugs let you compare configurations at "
          "a glance and filter results with ", Code("agent:top"), " or ",
          Code("agent:report"), "."),

        H3("Format", id="s-format"),
        Pre(Code("{strategy}-{param1}-{param2}-...-{lookback}")),
        P("Units use consistent suffixes: ", Code("d"), " = days, ",
          Code("m"), " = months. Percentages drop the decimal point for "
          "fractional values (0.5% becomes ", Code("05"), ")."),

        H3("Buy the Dip", id="s-btd"),
        P("Prefix: ", Code("btd")),
        Pre(Code("btd-7dp-05sl-1tp-1d-3m")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("btd")), Td("Strategy: buy_the_dip")),
                Tr(Td(Code("{n}dp")), Td("Dip threshold %")),
                Tr(Td(Code("{n}sl")), Td("Stop loss %")),
                Tr(Td(Code("{n}tp")), Td("Take profit %")),
                Tr(Td(Code("{n}d")), Td("Hold (days)")),
                Tr(Td(Code("{period}")), Td("Lookback (e.g. 1m, 3m)")),
            ),
        ),
        P("Example: ", Code("btd-7dp-05sl-1tp-1d-3m"),
          " = 7% dip, 0.5% stop loss, 1% take profit, 1 day hold, 3-month lookback"),

        H3("Momentum", id="s-mom"),
        P("Prefix: ", Code("mom")),
        Pre(Code("mom-20lb-5mt-5d-10tp-5sl-1m")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("mom")), Td("Strategy: momentum")),
                Tr(Td(Code("{n}lb")), Td("Lookback period (days)")),
                Tr(Td(Code("{n}mt")), Td("Momentum threshold %")),
                Tr(Td(Code("{n}d")), Td("Hold (days)")),
                Tr(Td(Code("{n}tp")), Td("Take profit %")),
                Tr(Td(Code("{n}sl")), Td("Stop loss %")),
                Tr(Td(Code("{period}")), Td("Lookback")),
            ),
        ),

        H3("VIX Fear Index", id="s-vix"),
        P("Prefix: ", Code("vix")),
        Pre(Code("vix-20t-on")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("vix")), Td("Strategy: vix")),
                Tr(Td(Code("{n}t")), Td("VIX threshold")),
                Tr(Td(Code("{type}")), Td("Hold type (e.g. on = overnight)")),
            ),
        ),

        H3("Box-Wedge", id="s-bwg"),
        P("Prefix: ", Code("bwg")),
        Pre(Code("bwg-2r-5ct")),
        Table(
            Thead(Tr(Th("Token"), Th("Meaning"))),
            Tbody(
                Tr(Td(Code("bwg")), Td("Strategy: box_wedge")),
                Tr(Td(Code("{n}r")), Td("Risk %")),
                Tr(Td(Code("{n}ct")), Td("Contraction threshold %")),
            ),
        ),

        Div(
            "The ", Strong("PDT (Pattern Day Trader)"), " rule is enforced by default "
            "for accounts under $25k: max 3 day trades per rolling 5-business-day window. "
            "PDT status does not affect the slug itself — two backtests with identical "
            "parameters but different PDT settings share the same slug. Use ",
            Code("pdt:false"), " to disable for accounts with $25k+ equity.",
            cls="tip",
        ),
    )


def _guide_options():
    return (
        H2("Options & Flags", id="options"),
        P("These flags can be appended to backtest, paper trade, and full cycle commands."),

        H3("Extended Hours", id="o-hours"),
        Pre(Code("agent:backtest lookback:1m hours:extended")),
        P("Regular hours: 9:30 AM - 4:00 PM ET. Extended hours: 4:00 AM - 8:00 PM ET "
          "(pre-market + after-hours). Extended hours backtests include more trading "
          "opportunities but may have lower liquidity and wider spreads."),

        H3("Intraday Exits", id="o-intraday"),
        Pre(Code("agent:backtest lookback:1m intraday_exit:true")),
        P("When enabled, the backtester uses ", Strong("5-minute intraday bars"), " to "
          "determine exactly when take-profit or stop-loss would trigger within each "
          "trading day. This is more accurate than daily bars (which only check "
          "open/high/low/close) but takes longer to run."),
        P("Key behavior: determines which of TP/SL is hit first. No same-day re-entry "
          "after exit."),

        H3("PDT Rule", id="o-pdt"),
        Pre(Code("agent:backtest lookback:1m pdt:false")),
        P("The ", Strong("Pattern Day Trader (PDT)"), " rule is a FINRA regulation: "
          "accounts under $25,000 are limited to 3 day trades per rolling 5-business-day "
          "window. AlpaTrade enforces this by default."),
        P("Set ", Code("pdt:false"), " if your account has $25k+ equity. This removes "
          "the day-trade limit and allows the strategy to trade more aggressively."),
    )


def _guide_body():
    return Div(
        H1("User Guide"),
        P("Complete reference for all AlpaTrade commands. Type any command in the chat "
          "composer on the ", A("home page", href="/"), ".", cls="lead"),
        _guide_toc(),
        *_guide_backtest(),
        *_guide_paper(),
        *_guide_full(),
        *_guide_validate(),
        *_guide_reconcile(),
        *_guide_research(),
        *_guide_query(),
        *_guide_slugs(),
        *_guide_options(),
        Hr(),
        P("Need quick help? Type ", Code("help"), " in the chat composer for a "
          "compact command reference.", cls="lead"),
        cls="content guide",
    )


# ---------------------------------------------------------------------------
# download page
# ---------------------------------------------------------------------------
def _copy_block(cmd: str, el_id: str):
    return Div(
        Pre(Code(cmd), id=el_id),
        Button("Copy", cls="copy-btn", type="button",
                onclick=f"navigator.clipboard.writeText(document.getElementById('{el_id}').textContent)"),
        cls="cmd-copy",
    )


def _download_body():
    uv_cmd = "uv tool install alpatrade"
    curl_cmd = "curl -fsSL https://alpatrade.chat/install.sh | bash"
    return Div(
        H1("Install AlpaTrade"),
        H3("uv (recommended)"),
        P("Install with uv (requires Python 3.11+):"),
        _copy_block(uv_cmd, "uv-cmd"),
        P("After install, create a ", Code(".env"), " file with your API keys, then run:"),
        Pre(Code("alpatrade")),
        Hr(),
        H3("One-line install (alternative)"),
        P("Installs uv automatically if needed:"),
        _copy_block(curl_cmd, "curl-cmd"),
        Hr(),
        H3("From source"),
        Pre(Code(
            "git clone https://github.com/predictivelabsai/alpatrade.git ~/.alpatrade\n"
            "cd ~/.alpatrade\n"
            "python3 -m venv .venv\n"
            "source .venv/bin/activate\n"
            "pip install -e .\n"
            "cp .env.example .env   # edit with your API keys\n"
            "alpatrade"
        )),
        Hr(),
        H3("Requirements"),
        Ul(
            Li("Python 3.11+"),
            Li("PostgreSQL (for trade history)"),
            Li("Alpaca paper trading account"),
            Li("Massive (Polygon) API key for market data"),
            cls="dl-req",
        ),
        cls="content guide",
    )


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------
def register(app, rt):
    """Attach the guide / download / install.sh routes to the FastHTML app."""

    @rt("/guide", methods=["GET"])
    def guide_get(session):
        center = Div(_header("User Guide"), _guide_body(), cls="center-pane")
        return page(None, Style(_GUIDE_CSS), center, user=_user(session),
                    title="User Guide · AlpaTrade", right_news=False)

    @rt("/download", methods=["GET"])
    def download_get(session):
        center = Div(_header("Download"), _download_body(), cls="center-pane")
        return page(None, Style(_GUIDE_CSS), center, user=_user(session),
                    title="Download · AlpaTrade", right_news=False)

    @rt("/install.sh", methods=["GET"])
    def install_sh():
        script_path = Path(__file__).resolve().parents[2] / "install.sh"
        if script_path.exists():
            content = script_path.read_text()
        else:
            content = "#!/bin/bash\necho 'install.sh not found on server'\nexit 1\n"
        return Response(content, media_type="text/plain",
                        headers={"Content-Disposition": "attachment; filename=install.sh"})

    return ["/guide", "/download", "/install.sh"]
