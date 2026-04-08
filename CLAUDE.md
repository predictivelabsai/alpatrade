# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AlpaTrade — trading strategy backtester, paper trader, and AI research CLI powered by Alpaca Markets. Published on PyPI as `alpatrade`.

## Stack

- **Python 3.13**, virtualenv at `.venv/`, managed with `uv`
- **FastHTML** web UI (`web_app.py`, port 5002)
- **FastAPI** REST server (`api_app.py`, port 5001)
- **AG-UI Chat** (`agui_app.py`, port 5003) — pydantic-ai agent (XAI Grok-3-mini) with WebSocket streaming
- **Rich CLI** (entry point: `alpatrade.py` → `tui/pt_cli.py` → `tui/command_processor.py`)
- **PostgreSQL** with `alpatrade` schema, accessed via SQLAlchemy (`utils/db/db_pool.py`)
- **Config**: `config/parameters.yaml` (strategy params), `.env` (API keys)

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run python alpatrade.py

# Run the AG-UI Chat (port 5003)
uv run uvicorn agui_app:app --host 0.0.0.0 --port 5003 --reload

# Run the Web UI (port 5002)
uv run python web_app.py

# Run the API Server (port 5001)
uv run uvicorn api_app:app --host 0.0.0.0 --port 5001 --reload

# Run the full regression suite (~65 tests, requires DB)
python tests/regression_suite.py

# Run with pytest (alternative)
python -m pytest tests/regression_suite.py -v

# Run a single test class
python -m pytest tests/regression_suite.py::TestStrategySlug -v

# Orchestrator direct invocation
python agents/orchestrator.py --mode backtest
python agents/orchestrator.py --mode paper --duration 1h
python agents/orchestrator.py --mode validate --run-id <uuid>
python agents/orchestrator.py --mode reconcile --window 7
python agents/orchestrator.py --mode full
```

When the user says "run regression" or "run tests", execute `python tests/regression_suite.py`.
Run the regression suite after significant changes to verify nothing is broken.

## Architecture

Four entry points share the same backend:

```
CLI (alpatrade.py) ──┐
AG-UI Chat (agui_app.py) ──┤──→ CommandProcessor / Orchestrator ──→ Agents ──→ DB + Alpaca + Market Data
Web UI (web_app.py) ──┤
REST API (api_app.py) ──┘
```

### Command Flow

1. **CLI**: `alpatrade.py` → `tui/pt_cli.py` (prompt_toolkit REPL) → `tui/command_processor.py` dispatches commands
2. **AG-UI**: `agui_app.py` intercepts CLI commands via `_CLI_BASES`/`_CLI_EXACT` sets, routes to `CommandProcessor`; free-form text goes to LangGraph agent with `StructuredTool` wrappers
3. **Web/API**: route handlers call `Orchestrator` or `CommandProcessor` directly

`CommandProcessor` is the central dispatcher. It parses positional params (e.g., `trades paper btd-3dp`) and routes to handler methods (`_agent_trades`, `_agent_runs`, `_agent_top`, etc.). Unknown input falls through to the AI chat agent.

### Multi-Agent System

Five agents coordinated by the Orchestrator (`agents/orchestrator.py`):

| Agent | File | Role |
|-------|------|------|
| Backtester | `agents/backtest_agent.py` | Parameterized grid-search backtests, stores to DB |
| Paper Trader | `agents/paper_trade_agent.py` | Live paper trading via Alpaca API, background polling |
| Validator | `agents/validate_agent.py` | Cross-checks trades against market data, self-correction loop (max 10 iterations) |
| Reconciler | `agents/reconcile_agent.py` | Compares DB positions vs Alpaca holdings |
| Reporter | `agents/report_agent.py` | Queries DB for summaries, top strategies, run details |

**Communication**: File-based JSON message bus (`agents/shared/message_bus.py` → `data/agent_messages/`). State persistence: `agents/shared/state.py` → `data/agent_state.json`.

**Workflow**: Backtest → Validate → Paper Trade → Validate → Report

### Data Flow

- **Market data**: `utils/massive_util.py` (Polygon.io), `utils/yf_util.py` (yfinance fallback), `utils/eodhd_util.py` (intraday)
- **Trading**: `utils/alpaca_util.py` (Alpaca paper API)
- **Strategies**: `utils/buy_the_dip.py`, `utils/vix_strategy.py`, `utils/momentum.py`, `utils/box_wedge.py`
- **Backtesting engine**: `utils/backtester_util.py` (runs strategies, calculates metrics)
- **Storage**: `utils/agent_storage.py` (DB writes), `utils/backtest_db_util.py` (DB reads)
- **Strategy slugs**: `utils/strategy_slug.py` — encodes params into compact IDs like `btd-7dp-05sl-1tp-1d-3m`
- **PDT tracking**: `utils/pdt_tracker.py` — FINRA Pattern Day Trader rule enforcement

### Database

PostgreSQL with `alpatrade` schema. Key tables: `runs`, `trades`, `backtest_summaries`, `users`, `user_accounts`, `chat_messages`. Migrations in `sql/` (numbered `01_` through `13_`). All tables have `user_id` column for data isolation.

Connection pool: `utils/db/db_pool.py` → `DatabasePool` with `get_session()` context manager. Reads `DATABASE_URL` from env.

### Authentication

- **Web/AG-UI**: Email/password + Google OAuth → session-based
- **API**: JWT bearer token (`POST /auth/login`, `/auth/register`)
- **CLI**: No auth — `user_id=None`, Alpaca keys from `.env`
- Per-user Alpaca keys: Fernet-encrypted in `alpatrade.users` table
- Auth module: `utils/auth.py` (bcrypt, Fernet, JWT, user CRUD)

## Strategies

- **Buy the Dip** (`btd`): Buys on dip_threshold% drops, exits at take_profit%, stop_loss%, or hold_days
- **VIX Fear Index** (`vix`): Trades based on VIX levels exceeding threshold
- **Momentum** (`mom`): Buys on strong upward momentum over lookback period
- **Box-Wedge** (`bwg`): Pattern-based strategy

### Strategy Options

- `hours:extended` — 4:00 AM - 8:00 PM ET (pre-market + after-hours)
- `intraday_exit:true` — 5-min bars for precise TP/SL exit timing
- `pdt:false` — Disable PDT rule for accounts > $25k

## Secrets Policy

**NEVER copy, persist, log, or document actual secret values.** Reference by variable name only.
- **XAI_API_KEY** especially sensitive — a prior key was leaked via GitHub and revoked
- Before committing, verify no secrets appear in `git diff` output

### Required Environment Variables (.env)

```
ALPACA_PAPER_API_KEY=...
ALPACA_PAPER_SECRET_KEY=...
MASSIVE_API_KEY=...        # Polygon.io compatible
DATABASE_URL=...           # PostgreSQL connection string
ENCRYPTION_KEY=...         # Fernet key (generate: python scripts/generate_keys.py)
JWT_SECRET=...             # JWT secret (generate: python scripts/generate_keys.py)
```

Optional: `XAI_API_KEY`, `EODHD_API_KEY`, `POSTMARK_API_KEY`, `TO_EMAIL`, `FROM_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
