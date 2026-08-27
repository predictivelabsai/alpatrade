"""Command-menu data for the AlpaTrade in-app shell (left collapsible menu).

Three registries, each a list of ``(group_label, [(command, description), ...])``:

* ``AGENT_SHORTCUTS`` — agent-orchestration groups (Backtest, Validate,
  Reconcile, Paper Trade, Full Cycle) that kick off the multi-agent workflow.
* ``ALPHA_RESEARCH_SHORTCUTS`` — local Growth, Value, and combined research views.
* ``MAIN_NAV`` — data / reporting navigation (Trades, Runs & Reports,
  Rankings & P&L, Monitor, Research, Charts & Equity, Accounts).

Every command string is a real ``CommandProcessor`` input (see
``tui/command_processor.py`` / ``agui_app.py`` routing). Clicking a menu item
fills the chat composer via ``fillChat(...)`` so the user can run or edit it.
Kept in sync with the CLI so the CLI, AG-UI chat and web UI share one command
surface.
"""
from __future__ import annotations

# (group, [(command, description), ...]) — agent orchestration shortcuts.
AGENT_SHORTCUTS = [
    ("Backtest", [
        ("agent:backtest lookback:1m", "1-month grid-search backtest"),
        ("agent:backtest symbols:AAPL,TSLA", "custom symbols"),
        ("agent:backtest lookback:3m", "3-month backtest"),
        ("agent:backtest hours:extended", "pre / after-market"),
        ("agent:backtest intraday_exit:true", "5-min TP/SL bars"),
        ("agent:backtest pdt:false", "disable PDT rule"),
    ]),
    ("Validate", [
        ("agent:validate run-id:<uuid>", "validate a run vs market data"),
        ("agent:validate", "validate latest run"),
    ]),
    ("Reconcile", [
        ("agent:reconcile window:7d", "7-day DB vs broker"),
        ("agent:reconcile window:14d", "14-day reconcile"),
        ("agent:reconcile window:30d", "30-day reconcile"),
    ]),
    ("Paper Trade", [
        ("agent:paper duration:1h", "paper trade 1 hour"),
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
]

# Guided Hermes workflow. These are intentionally natural-language commands
# accepted by the deterministic Hermes broker. The common path does not require
# users to copy UUIDs; ID-based commands remain available for choosing one job
# when an account owns several.
HERMES_SHORTCUTS = [
    ("Hermes — Start Here", [
        ("/hermes help", "guided workflow and ID explanation"),
        ("/hermes show my recent jobs", "find jobs, runs, and candidates"),
    ]),
    ("Hermes — Backtest", [
        ("/hermes run a 6-month buy_the_dip backtest for AAPL, MSFT and NVDA and optimize Sharpe",
         "optimize and save the best candidate"),
        ("/hermes show my latest backtest result",
         "metrics and parameters from the latest result"),
    ]),
    ("Hermes — Paper Trade", [
        ("/hermes construct an optimal portfolio from my best completed candidate",
         "portfolio advice without copying an ID"),
        ("/hermes start my best candidate in continuous paper trading, email daily reports, and notify me both",
         "start the best eligible candidate"),
    ]),
    ("Hermes — Monitor", [
        ("/hermes show my running jobs", "only queued, running, or paused jobs"),
        ("/hermes analyze my running paper job", "P&L, drift, and next actions"),
        ("/hermes pause my running paper job", "pause the latest running Hermes job"),
        ("/hermes resume my paused paper job", "resume the latest paused Hermes job"),
        ("/hermes stop my running paper job", "stop the latest running Hermes job"),
    ]),
]

# Local, read-only equity research ported from the Alpha Agents methodology.
ALPHA_RESEARCH_SHORTCUTS = [
    ("Growth Agent", [
        ("alpha:growth ticker:AAPL", "durable growth and moat review"),
    ]),
    ("Value Agent", [
        ("alpha:value ticker:BBY", "undervaluation and value-trap review"),
    ]),
    ("Combined View", [
        ("alpha:compare ticker:AAPL", "compact growth and value perspectives"),
    ]),
    ("Saved Reports", [
        ("alpha:runs limit:10", "recent saved reports"),
        ("alpha:show run-id:<uuid>", "open a saved report"),
    ]),
]

# (group, [(command, description), ...]) — data / reporting navigation.
MAIN_NAV = [
    ("AI Runtime", [
        ("/hermes ", "use Hermes for one message"),
        ("/deepagents ", "use DeepAgents for one message"),
        ("/langgraph ", "use LangGraph for one message"),
    ]),
    ("Trades", [
        ("trades:backtest", "backtest trades"),
        ("trades:paper", "paper trades"),
        ("trades:all", "all types + accounts"),
        ("trades:backtest slug:btd", "filter by strategy slug"),
        ("trades:paper run-id:<uuid>", "trades for a run"),
    ]),
    ("Runs & Reports", [
        ("runs:backtest", "backtest runs"),
        ("runs:paper", "paper runs"),
        ("report:backtest", "backtest summary"),
        ("report:paper", "paper summary"),
        ("report run-id:<uuid>", "single-run detail"),
    ]),
    ("Rankings & P&L", [
        ("top:backtest", "rank backtest strategies"),
        ("top:paper", "rank paper strategies"),
        ("top:all", "all types + accounts"),
        ("pnl run-id:<uuid>", "P&L breakdown"),
    ]),
    ("Monitor", [
        ("positions", "broker positions"),
        ("agent:status", "agent states"),
        ("agent:logs", "log tail"),
        ("agent:stop", "stop background task"),
    ]),
    ("Research", [
        ("Show me the premarket movers", "top premarket gainers & fallers"),
        ("load:AAPL", "quote + inline chart"),
        ("load:TSLA period:1y", "custom period"),
        ("news:TSLA", "company news"),
        ("price:AAPL", "latest quote"),
        ("profile:MSFT", "company profile"),
        ("analysts:GOOGL", "analyst ratings"),
        ("financials:AAPL", "income & balance sheet"),
        ("valuation:AAPL,MSFT", "valuation comparison"),
        ("movers", "top gainers & losers"),
        ("chart:AAPL period:1y", "price chart"),
    ]),
    ("Charts & Equity", [
        ("Show me a market map", "S&P sector return treemap"),
        ("Compare AAPL vs MSFT vs NVDA", "relative-return chart"),
        ("Show me a candlestick chart of AAPL", "OHLC + volume"),
        ("equity", "latest run equity curve"),
        ("equity backtest", "latest backtest equity"),
        ("equity paper", "latest paper equity"),
        ("equity paper btd", "paper equity + slug"),
    ]),
    ("Accounts", [
        ("accounts", "list linked accounts"),
        ("account:add <KEY> <SECRET>", "add a new account"),
        ("account:switch <num>", "switch active account"),
    ]),
]
