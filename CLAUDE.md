# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AssetHero — a multi-asset trading platform with a **shared backtesting & paper-trading
engine**. Published on PyPI as `assethero` (the `alpatrade` package is a deprecated alias).

This repo (renamed from `alpatrade`) is the platform base. It currently holds the **equities /
Alpaca** vertical; per the migration plan it is being consolidated into a single monorepo that
also absorbs crypto (rl-agent-swarm), FX/macro (macrohero), prediction markets (polytrade), and
equities research (alpha-agents) behind one `engine/` + `verticals/` structure.

### Migration state (as of Phase 1b)

The `engine/` + `verticals/` refactor is **in progress**, done in numbered phases:

- **Phase 1a (done)** — shared infra extracted into `engine/`: `engine.auth`, `engine.db.pool`,
  `engine.brokers.alpaca`, `engine.feeds.{massive,yf,eodhd}`, `engine.agents.{message_bus,state,db_setup}`,
  `engine.ai.*` (LangGraph chat), `engine.web.layout`. **`engine.*` is now the canonical location.**
  The old `utils/*` paths (e.g. `utils/auth.py`, `utils/db/db_pool.py`) are **compatibility shims**
  that `sys.modules`-alias to the relocated `engine` module (removed in Phase 7). **New code should
  import from `engine.*`, not `utils.*`.**
- **Phase 1b (done)** — unified entry points `app.py` (web) and `api.py` (REST) with a house-style
  3-pane shell and asset-class switcher; the equities web vertical lives in `verticals/equities/routes.py`,
  mounted under `/equities/*`. Crypto / FX / prediction / research are stubs until their merge phases.
- **Phase 0 (done)** — the methodology-faithful backtest layer `engine.backtest` (see Architecture).

Not everything has moved: strategies, the grid-search backtester, and the multi-agent orchestrator
still live under `utils/` and `agents/`. When a module has both an `engine.*` and a `utils.*` path,
prefer `engine.*`.

## Stack

- **Python 3.13**, virtualenv at `.venv/`, managed with `uv`
- **Unified web app** (`app.py`, port 5001) — FastHTML house-style shell + verticals switcher; mounts the equities vertical
- **Unified REST API** (`api.py`, port 5002) — FastAPI; mounts each vertical under `/api/v1/<vertical>`
- **AG-UI Chat** (`agui_app.py`, port 5003) — LangGraph chat agent (XAI Grok) with WebSocket streaming
- **Rich CLI** (entry point: `cli.py` → `tui/pt_cli.py` → `tui/command_processor.py`; console scripts `assethero` / `alpatrade`)
- **PostgreSQL** with `alpatrade` schema, accessed via SQLAlchemy (`engine.db.pool`)
- **Config**: `config/parameters.yaml` (strategy params), `.env` (API keys)

**Legacy standalone apps still exist** and hold most of the equities UI/endpoints that the unified
apps wrap: `web_app.py` (FastHTML, port 5002) and `api_app.py` (FastAPI, port 5001) — `api.py` mounts
`api_app.app` under `/api/v1/equities`. Note the port swap: `app.py`=5001/`api.py`=5002 vs the legacy
`api_app`=5001/`web_app`=5002. Ports are overridable via `ASSETHERO_WEB_PORT` / `ASSETHERO_API_PORT`.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run python cli.py

# Run the unified web app (port 5001) — house-style shell + /equities vertical
uv run python app.py

# Run the unified REST API (port 5002) — verticals under /api/v1/*
uv run python api.py

# Run the AG-UI Chat (port 5003)
uv run uvicorn agui_app:app --host 0.0.0.0 --port 5003 --reload

# Legacy standalone apps (still functional)
uv run python web_app.py                                              # FastHTML, port 5002
uv run uvicorn api_app:app --host 0.0.0.0 --port 5001 --reload        # FastAPI, port 5001

# Run a methodology-faithful (Alpaca-skill) backtest → dated artifact folder in backtest-results/
python -m engine.backtest.runner --symbols AAPL,MSFT --start 2024-01-01 --end 2024-06-30

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

The entry points share one backend, increasingly routed through the extracted `engine/`:

```
CLI (cli.py) ──────────────┐
AG-UI Chat (agui_app.py) ──┤
Unified web (app.py) ──────┤──→ CommandProcessor / Orchestrator ──→ engine/ (brokers, feeds,
Unified API (api.py) ──────┤        + verticals/equities/routes        db, auth, backtest, agents)
Legacy web/api apps ───────┘                                       ──→ DB + Alpaca + Market Data
```

### Package layout

- **`engine/`** — asset-agnostic shared infra (canonical; `utils/*` shims redirect here). Subpackages:
  `brokers/` (Alpaca client), `feeds/` (massive/yf/eodhd market data), `db/` (SQLAlchemy pool),
  `auth.py`, `backtest/` (methodology backtester, below), `agents/` (message bus / state / db setup),
  `ai/` (LangGraph chat core), `web/layout.py` (house-style 3-pane shell).
- **`verticals/`** — per-asset-class code. `verticals/equities/routes.py` is the equities web vertical;
  it exposes `register(app, rt, current_user)` called from `app.py`, mounting routes under `/equities/*`.
- **`utils/`, `agents/`, `tui/`** — not-yet-relocated equities code: strategies, grid-search backtester,
  the five-agent orchestrator, and the CLI dispatcher.

### Command Flow

1. **CLI**: `cli.py` → `tui/pt_cli.py` (prompt_toolkit REPL) → `tui/command_processor.py` dispatches commands
2. **AG-UI**: `agui_app.py` intercepts CLI commands via `_CLI_BASES`/`_CLI_EXACT` sets, routes to `CommandProcessor`; free-form text goes to LangGraph agent with `StructuredTool` wrappers
3. **Web/API**: route handlers call `Orchestrator` or `CommandProcessor` directly

`CommandProcessor` is the central dispatcher. It parses positional params (e.g., `trades paper btd-3dp`) and routes to handler methods (`_agent_trades`, `_agent_runs`, `_agent_top`, etc.). Unknown input falls through to the AI chat agent.

### Backtesting: two distinct engines

- **Grid-search backtester** (`utils/backtester_util.py`, driven by `agents/backtest_agent.py`) — sweeps
  strategy params, encodes them as slugs, and stores runs/trades/summaries to the DB. This is what the
  CLI/web `backtest` commands and the orchestrator use.
- **Methodology-faithful backtester** (`engine.backtest`, Phase 0) — a code implementation of the Alpaca
  `alpaca-trading-backtest` skill (vendored under `engine/backtest/skills/`). Fetches Alpaca bars via
  `alpaca-py`, then writes a **deterministic dated artifact folder** to `backtest-results/`
  (`summary.json`, `report.md`, `run.py`, data fingerprints, trades/equity CSVs, mandatory hypothetical-
  results disclosure). Guardrails: `next_open` default fill (no look-ahead), Sharpe uses sample stddev
  (N-1), every run emits the disclosure. Entry point: `engine.backtest.runner.run_backtest` /
  `python -m engine.backtest.runner`.

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

- **Market data**: `engine.feeds.massive` (Polygon.io), `engine.feeds.yf` (yfinance fallback), `engine.feeds.eodhd` (intraday) — old `utils/{massive,yf,eodhd}_util.py` shims still resolve
- **Trading**: `engine.brokers.alpaca` (Alpaca paper API; old `utils/alpaca_util.py`)
- **Strategies**: `utils/buy_the_dip.py`, `utils/vix_strategy.py`, `utils/momentum.py`, `utils/box_wedge.py` (not yet relocated)
- **Backtesting engine**: `utils/backtester_util.py` (grid-search; runs strategies, calculates metrics)
- **Storage**: `utils/agent_storage.py` (DB writes), `utils/backtest_db_util.py` (DB reads)
- **Strategy slugs**: `utils/strategy_slug.py` — encodes params into compact IDs like `btd-7dp-05sl-1tp-1d-3m`
- **PDT tracking**: `utils/pdt_tracker.py` — FINRA Pattern Day Trader rule enforcement

### Database

PostgreSQL with `alpatrade` schema. Key tables: `runs`, `trades`, `backtest_summaries`, `users`, `user_accounts`, `chat_messages`. Migrations in `sql/` (numbered `01_` through `13_`). All tables have `user_id` column for data isolation.

Connection pool: `engine.db.pool` → `DatabasePool` with `get_session()` context manager (old `utils/db/db_pool.py` shim resolves here). Reads `DATABASE_URL` from env.

### Authentication

- **Web/AG-UI**: Email/password + Google OAuth → session-based
- **API**: JWT bearer token (`POST /auth/login`, `/auth/register`)
- **CLI**: No auth — `user_id=None`, Alpaca keys from `.env`
- Per-user Alpaca keys: Fernet-encrypted in `alpatrade.users` table
- Auth module: `engine.auth` (bcrypt, Fernet, JWT, user CRUD; old `utils/auth.py` shim resolves here)

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
- Do not write secret values into source, docs, markdown, YAML, notebooks, or tool output
- Do not include secrets in commit messages, comments, or debug output; never hardcode keys
- **XAI_API_KEY** especially sensitive — a prior key was leaked via GitHub and revoked
- Before committing, verify no secrets appear in `git diff`; run `scripts/verify_no_secrets.sh`
  (also wired as a pre-commit gate). If a secret is ever committed, purge it from history with
  `git-filter-repo` immediately.

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
