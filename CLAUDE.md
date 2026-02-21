# AlpaTrade

Trading strategy simulator, backtester, and paper trader.

## Stack

- **Python 3.13**, virtualenv at `.venv/`
- **FastHTML** web UI (`web_app.py`)
- **FastAPI** REST server (`api_app.py`)
- **Rich CLI** (`tui/strategy_cli.py`, entry point: `alpatrade.py`)
- **Config**: `config/parameters.yaml` (strategy params), `.env` (API keys)

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `utils/` | Core logic (alpaca_util, buy_the_dip, vix_strategy, momentum, massive_util, backtester_util, pdt_tracker) |
| `utils/db/` | Database pool (`db_pool.py`) |
| `tasks/` | CLI tools (cli_trader.py, validate_backtest.py) |
| `tui/` | Rich CLI app |
| `agents/` | Multi-agent system (backtester, paper-trader, validator, orchestrator) |
| `agents/shared/` | Message bus, shared state, DB setup |
| `tests/` | Tests |
| `data/` | Runtime data (orders, agent messages, agent state) |
| `config/` | parameters.yaml |

## Strategies

- **Buy the Dip**: Buys on `dip_threshold%` drops from recent high, exits at `take_profit_threshold%` gain, `stop_loss_threshold%` loss, or after `hold_days`
- **VIX Fear Index**: Trades based on VIX levels exceeding threshold
- **Momentum**: Buys on strong upward momentum over lookback period
- **Box-Wedge**: Pattern-based strategy

## Secrets Policy

**NEVER copy, persist, log, or document actual secret values.** API keys, tokens, passwords, and connection strings from `.env` must only be used transiently during runtime. Specifically:
- Do not write secret values into source files, docs, markdown, YAML, or memory files
- Do not include secrets in commit messages, comments, or debug output
- Reference secrets by variable name only (e.g. `ALPACA_PAPER_API_KEY=...`)
- If a secret is accidentally committed, immediately purge it from git history with `git-filter-repo`

## Required Environment Variables (.env)

```
ALPACA_PAPER_API_KEY=...
ALPACA_PAPER_SECRET_KEY=...
MASSIVE_API_KEY=...        # Polygon.io compatible
EODHD_API_KEY=...
XAI_API_KEY=...
DATABASE_URL=...           # PostgreSQL connection string
```

## Multi-Agent System

Five agents collaborate to backtest, paper trade, validate, and reconcile strategies:

### Agent 1: Backtester (`agents/backtest_agent.py`)
- Runs parameterized backtests varying symbols, date ranges, and strategy parameters
- Stores results via `agent_storage.py` into `alpatrade.backtest_summaries` / `alpatrade.trades` tables
- Reports best-performing configuration to Portfolio Manager

### Agent 2: Paper Trader (`agents/paper_trade_agent.py`)
- Continuous paper trading via real Alpaca paper API
- Polls at configurable intervals, tracks positions and daily P&L
- Writes trades to `alpatrade.trades` DB table

### Agent 3: Validator (`agents/validate_agent.py`)
- Cross-checks trades against Massive market data for price accuracy
- Validates P&L math, market hours, weekend trades, TP/SL logic
- **Self-correction loop**: Attempts up to `n=10` iterations to fix anomalies
- After 10 failed iterations: stops, reports error behaviors, suggests fixes

### Agent 4: Portfolio Manager (`agents/orchestrator.py`)
- Orchestrator — dispatches work, tracks state, routes messages
- Workflow: Backtest -> Validate -> Paper Trade -> Validate -> Report

### Agent 5: Reconciler (`agents/reconcile_agent.py`)
- Compares DB positions/P&L vs actual Alpaca holdings for a given time window
- Checks: position match, trade match, P&L comparison, missing/extra trades
- Accepts `window_days` param (default 7)

### Communication
- File-based JSON message bus (`data/agent_messages/`)
- Messages: `{from_agent, to_agent, type, payload, timestamp}`
- State persistence: `data/agent_state.json`

### Running

```bash
# Rich CLI (primary interface)
python alpatrade.py

# CLI commands:
#   trades                                    Show trades from DB
#   runs                                      Show runs from DB
#   agent:backtest lookback:1m                Run parameterized backtest
#   agent:backtest lookback:1m hours:extended Extended hours backtest
#   agent:backtest lookback:1m intraday_exit:true  Intraday TP/SL exits
#   agent:backtest lookback:1m pdt:false      Disable PDT rule (>$25k accounts)
#   agent:paper duration:7d                   Paper trade in background
#   agent:paper duration:7d hours:extended    Extended hours paper trading
#   agent:full lookback:1m duration:1m        Full cycle
#   agent:reconcile window:7d                 Reconcile DB vs Alpaca

# Orchestrator (direct invocation)
python agents/orchestrator.py --mode full
python agents/orchestrator.py --mode backtest
python agents/orchestrator.py --mode validate --run-id <uuid>
python agents/orchestrator.py --mode paper --duration 1h
python agents/orchestrator.py --mode reconcile --window 7
```

### Extended Hours
- `hours:regular` (default) — 9:30 AM - 4:00 PM ET
- `hours:extended` — 4:00 AM - 8:00 PM ET (pre-market + after-hours)
- Flows through: CLI -> Orchestrator -> Agent -> Strategy util / Validator

### Intraday Exits
- `intraday_exit:true` — Use 5-min intraday bars for precise TP/SL exit timing
- Determines which of TP/SL is hit first within each day
- No same-day re-entry after exit

### PDT Rule (Pattern Day Trader)
- FINRA PDT rule enforced by default: max 3 day trades per rolling 5-business-day window
- `pdt:false` to disable for accounts > $25k
- Tracked via `utils/pdt_tracker.py` (`PDTTracker` class)
- Applies to both backtesting and paper trading
- Flows through: CLI -> Orchestrator -> Agent -> Strategy util

### Email Notifications
- Paper trading sends daily P&L reports via Postmark
- Requires: `POSTMARK_API_KEY`, `TO_EMAIL`, `FROM_EMAIL` in `.env`
- Disable with `email:false` on `agent:paper` command
