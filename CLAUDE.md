# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AlpaTrade — a multi-asset trading platform with a **shared backtesting & paper-trading
engine**. Published on PyPI as `alpatrade`.

This repo (renamed from `alpatrade`) is the platform base. It currently holds the **equities /
Alpaca** vertical; per the migration plan it is being consolidated into a single monorepo that
also absorbs crypto (rl-agent-swarm), FX/macro (macrohero), prediction markets (polytrade), and
equities research (alpha-agents) behind one `engine/` + `verticals/` structure.

### Migration state (as of Phase 1b)

The `engine/` + `verticals/` refactor is **in progress**, done in numbered phases:

- **Phase 1a (done)** — shared infra extracted into `engine/`: `engine.auth`, `engine.db.pool`,
  `engine.brokers.alpaca`, `engine.feeds.{market_data,yf,eodhd}`, `engine.agents.{message_bus,state,db_setup}`,
  `engine.ai.*` (LangGraph chat), `engine.web.layout`. **`engine.*` is now the canonical location.**
  The old `utils/*` paths (e.g. `utils/auth.py`, `utils/db/db_pool.py`) are **compatibility shims**
  that `sys.modules`-alias to the relocated `engine` module (removed in Phase 7). **New code should
  import from `engine.*`, not `utils.*`.**
- **Phase 1b (done)** — unified web entry point `app.py` plus the namespaced `api.py` compatibility
  shell; production REST traffic uses the canonical `api_app.py` `/v2/*` contract. The equities web
  vertical lives in `verticals/equities/routes.py`, mounted under `/equities/*`. Crypto / FX /
  prediction / research are stubs until their merge phases.
  The web app is composed of feature modules under `engine/web/` (`ph_landing`, `ph_auth`, `ph_chat`,
  `ph_guide`, `ph_charts`, `ph_settings`), each exposing `register(app, rt)` — see **Web layer** below.
- **Phase 0 (done)** — the methodology-faithful backtest layer `engine.backtest` (see Architecture).
- **`engine.config`** is the canonical model/provider resolver (model, market-data, search, agent-framework),
  layering per-user DB overrides over env defaults; the DeepAgents harness and tools resolve through it. See
  **Model & provider configuration** below.

Not everything has moved: strategies, the grid-search backtester, and the multi-agent orchestrator
still live under `utils/` and `agents/`. When a module has both an `engine.*` and a `utils.*` path,
prefer `engine.*`.

## Stack

- **Python 3.13**, virtualenv at `.venv/`, managed with `uv`
- **Unified web app** (`app.py`, port 5001) — FastHTML house-style shell + verticals switcher; mounts the equities vertical
- **Production REST API** (`api_app.py`, port 5001) — FastAPI; typed `/v2/*` contract, agent catalog, Swagger and ReDoc
- **Canonical DeepAgents API** (`engine/ai/deepagents.py`) — authenticated
  `POST /v2/deepagents`, durable PostgreSQL checkpoints/transcripts, JSON or SSE,
  tenant-scoped tools and six native specialists (including the read-only daily advisor)
- **Namespaced API shell** (`api.py`, port 5002) — optional compatibility mount under `/api/v1/equities`
- **AG-UI Chat** (`agui_app.py`, port 5003) — LangGraph chat agent (XAI Grok) with WebSocket streaming
- **Rich CLI** (entry point: `cli.py` → `tui/pt_cli.py` → `tui/command_processor.py`; console script `alpatrade`)
- **PostgreSQL** with `alpatrade` schema, accessed via SQLAlchemy (`engine.db.pool`)
- **Config**: `config/parameters.yaml` (strategy params), `.env` (API keys)

`main.py` is a thin shim that imports the merged `app.py` and `serve()`s it — **this is what prod runs**
(see **Deployment**). `agui_app.py` still exists and defines the shared DeepAgents harness
(`agui_app.primary_agent`, `agent_for_user()`) + tools that `engine/web/ph_chat.py` imports; it is no
longer the prod web server. Ports are overridable via `ASSETHERO_WEB_PORT` / `ASSETHERO_API_PORT`.

**`api_app.py` is the canonical production API** and is also mounted by the optional `api.py`
compatibility shell under `/api/v1/equities`.
**`web_app.py` is retired** in the container topology (do not target it for new work).

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

# Run the full regression suite (74 tests, requires DB + .env; hits Alpaca/XAI)
python tests/regression_suite.py

# Run with pytest (alternative)
python -m pytest tests/regression_suite.py -v

# Run a single test class
python -m pytest tests/regression_suite.py::TestStrategySlug -v

# Agent/tool evals (DeepEval, grok LLM-as-judge) → eval-results/evals-*.csv|xlsx
uv run python evals/run_evals.py                 # 32 cases; --include-slow adds backtest/paper
python -m pytest tests/llm_test.py tests/tavily_test.py -v   # provider connectivity

# Deploy to prod via the Coolify API (needs COOLIFY_URL + COOLIFY_API_TOKEN in .env)
python scripts/coolify_deploy.py list
python scripts/coolify_deploy.py deploy --name agui

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
  `brokers/` (Alpaca client), `feeds/` (Yahoo Finance/Alpaca market data), `db/` (SQLAlchemy pool),
  `auth.py`, `backtest/` (methodology backtester, below), `agents/` (message bus / state / db setup),
  `ai/` (LangGraph chat core), `web/layout.py` (house-style 3-pane shell).
- **`verticals/`** — per-asset-class code. `verticals/equities/routes.py` is the equities web vertical;
  it exposes `register(app, rt, current_user)` called from `app.py`, mounting routes under `/equities/*`.
- **`utils/`, `agents/`, `tui/`** — not-yet-relocated equities code: strategies, grid-search backtester,
  the five-agent orchestrator, and the CLI dispatcher.

### Command Flow

1. **CLI**: `cli.py` → `tui/pt_cli.py` (prompt_toolkit REPL) → `tui/command_processor.py` dispatches commands
2. **AG-UI**: `agui_app.py` intercepts CLI commands via `_CLI_BASES`/`_CLI_EXACT` sets, routes to `CommandProcessor`; free-form text goes to the DeepAgents harness with `StructuredTool` wrappers
3. **Canonical agent API**: `api_app.py` → `engine.ai.deepagents.DeepAgentService` →
   tenant-context tools/native specialists; long actions enqueue the autonomy worker
4. **Other Web/API routes**: handlers call `Orchestrator` or `CommandProcessor` directly

`CommandProcessor` is the central dispatcher. It parses positional params (e.g., `trades paper btd-3dp`) and routes to handler methods (`_agent_trades`, `_agent_runs`, `_agent_top`, etc.). Unknown input falls through to the AI chat agent.

### Model & provider configuration (`engine/config.py`)

`get_settings(user_id)` resolves the effective **model / market-data / search / agent-framework**
providers by layering, highest-precedence first: per-user overrides in `alpatrade.user_settings` →
env vars → `_DEFAULTS`. `build_chat_model(settings)` turns that into a LangChain chat model
(XAI/OpenAI are OpenAI-compatible via `ChatOpenAI(base_url=…)`; Anthropic needs `langchain-anthropic`).

- Model comes from `DEFAULT_MODEL` **or** `MODEL_NAME` (DEFAULT_MODEL wins), provider from `MODEL_PROVIDER`.
  Default is **`grok-4-1-fast-reasoning`**.
- **Self-heal:** for XAI, `build_chat_model` probes the model and falls back to the first working entry in
  `MODEL_NAMES["xai"]` if it's unavailable — this is why a stale/region-locked `MODEL_NAME` (e.g. the
  region-locked `grok-4.5`) still yields a working agent. Keep the preferred model first in that list.
- `agui_app.agent_for_user(user_id)` returns a per-user agent cached by `(provider, model, framework)`; DeepAgents is the default harness.
- `POST /v2/deepagents` always calls `create_deep_agent` directly, caches graphs by
  effective provider/model, and never uses the runtime fallback chain. It returns
  503 when DeepAgents, the model, or the PostgreSQL checkpointer is unavailable.
- **Voice** (`engine/voice.py`) has its OWN model (`XAI_VOICE_MODEL`, default `grok-4-fast`) and is NOT
  routed through this self-heal (realtime models differ from chat-completion models).
- `get_stock_news` (chat tool) forces the configured `SEARCH_PROVIDER` (default **Tavily**).

### Web layer (`engine/web/`)

The merged FastHTML app (`app.py`) registers feature modules, each exposing `register(app, rt)`:
`ph_landing` (`/`), `ph_auth` (`/signin`, `/profile`), `ph_chat` (`/app` chat + `/news`),
`ph_guide` (`/guide` user + shortcut guide), `ph_charts` (`/map` finviz-style market-map treemap via
`engine/market_map.py`, `/charts` candlestick + compare), `ph_settings` (`/settings` — BYOK Alpaca keys +
provider dropdowns). `engine.voice.register_voice_routes(app)` adds the `/ws/voice` WebSocket proxy to
x.ai's realtime agent (voice mode). The 3-pane shell is `engine/web/ph_layout.py::page(active, …)`; the
current user is resolved per-request from `session["user_id"]` (no `current_user` is passed to `register`).
Inline chat charts use `__CHART_DATA__{json}__END_CHART__` markers rendered client-side in `ph_chat.py`.

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

**Workflow**: Backtest → Validate → Paper Trade → Validate → Reconcile → Report

### Data Flow

- **Market data**: `engine.feeds.market_data` routes to Yahoo Finance by default or Alpaca when configured.
- **Trading**: `engine.brokers.alpaca` (Alpaca paper API; old `utils/alpaca_util.py`)
- **Strategies**: `utils/buy_the_dip.py`, `utils/vix_strategy.py`, `utils/momentum.py`, `utils/box_wedge.py` (not yet relocated)
- **Backtesting engine**: `utils/backtester_util.py` (grid-search; runs strategies, calculates metrics)
- **Storage**: `utils/agent_storage.py` (DB writes), `utils/backtest_db_util.py` (DB reads)
- **Strategy slugs**: `utils/strategy_slug.py` — encodes params into compact IDs like `btd-7dp-05sl-1tp-1d-3m`
- **PDT tracking**: `utils/pdt_tracker.py` — FINRA Pattern Day Trader rule enforcement

### Database

PostgreSQL with `alpatrade` schema. Key tables: `runs`, `trades`, `backtest_summaries`, `users`,
`user_accounts` (per-user Alpaca keys, Fernet-encrypted BYTEA — this is where keys actually live, not
`users`), `user_settings` (per-user provider prefs, `sql/14`), `chat_messages`, Hermes-owned
`strategy_candidates`/`hermes_jobs` (`sql/18`–`sql/20`), and the autonomy engine tables
`autonomy_runs`/`autonomy_run_steps`/`autonomy_events`/`autonomy_promotions` (`sql/15`), plus
`alpha_research_runs` for user-scoped Growth/Value reports (`sql/17`), and
`deepagent_responses`/`deepagent_events`/`deepagent_actions` for durable API
idempotency and sanitized traces (`sql/22`), plus tenant/account-scoped
`advisor_reports`/`advisor_deliveries` for the daily DeepAgent advisor (`sql/23`).
Official LangGraph checkpoint tables are created in the `alpatrade` search path by
`AsyncPostgresSaver.setup()`.
Migrations in `sql/` (numbered `01_` through `24_`, idempotent migrations). Apply one with
`python run_migration.py sql/NN_name.sql` (no migration-tracking table). All data tables carry `user_id`
(and `account_id`) for isolation.

Connection pool: `engine.db.pool` → `DatabasePool` with `get_session()` context manager (old `utils/db/db_pool.py` shim resolves here). Reads `DATABASE_URL` from env.

### Authentication

- **Web/AG-UI**: Email/password + Google OAuth → session-based
- **API**: JWT bearer token (`POST /auth/login`, `/auth/register`)
- **CLI**: No auth — `user_id=None`, Alpaca keys from `.env`
- Per-user Alpaca keys: Fernet-encrypted in `alpatrade.user_accounts` (`store_alpaca_keys`/`get_alpaca_keys`);
  when a user has none, the app falls back to the `.env` `ALPACA_PAPER_*` keys
- Per-user provider prefs: `get_user_settings`/`store_user_settings` (`alpatrade.user_settings`)
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

## Deployment (Coolify)

Prod (`alpatrade.chat` / `alpatrade.dev`) runs on **Coolify** (`https://coolify.finespresso.org` — note: **not** `coolify.predictivelabs.ai`, which is a separate instance hosting polytrade / rl-agent-swarm / macrohero / plai-crm and has different logins)
from `docker-compose.yaml`. The web service is **`agui`** (`Dockerfile.agui` → `python main.py` →
merged `app.py`, `ASSETHERO_WEB_PORT=5003`); the `api` service is `Dockerfile.api` (`api_app`). The old
`web` service (`web_app.py`) is retired.

- **Detecting a live deploy:** new routes 404 on the old image — `curl -s -o /dev/null -w '%{http_code}'
  https://alpatrade.chat/map` should be `200` once the current build is live. To check the **api** service
  specifically, compare `curl -s https://api.alpatrade.chat/openapi.json | jq '.info.version'` to
  `pyproject.toml`.
- **CD via GitHub Actions** (`.github/workflows/deploy.yml`): runs after CI succeeds on `main`, triggers a
  Coolify deploy over the API, waits, and smoke-tests prod. Needs repo secrets `COOLIFY_URL` /
  `COOLIFY_API_TOKEN` / `COOLIFY_APP_UUID`. Two bugs are fixed: it POSTs to `/api/v1/deploy` (a Coolify
  upgrade made GET return 405), and it **forces a no-cache rebuild by default** (`force=true`) — a
  cache-reusing deploy had been silently serving stale images (e.g. the `api` service sat several versions
  behind while reporting a newer version string). Manual run: `gh workflow run deploy.yml` (add
  `-f force=false` for a fast cache-reusing deploy), or the `coolify-deploy` skill /
  `scripts/coolify_deploy.py deploy --name agui`.
- Never deploy with the Coolify **account password** — use an API token only.

## Skills & operational scripts

`.claude/skills/` holds user-invocable skills (each guarded — publish/deploy actions confirm first):
- **`coolify-deploy`** — trigger/inspect Coolify deploys via API token (`scripts/coolify_deploy.py`).
- **`linkedin-post`** — post to LinkedIn via an OAuth access token (`scripts/linkedin_post.py`,
  `scripts/linkedin_auth.py`). No password/2FA is ever entered — the user completes OAuth.

Other scripts: `scripts/notify_on_ship.py` (polls prod, emails on ship via `utils/email_util.py`
Postmark), `scripts/generate_keys.py` (Fernet/JWT), `scripts/verify_no_secrets.sh` (pre-commit gate).

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
MARKET_DATA_PROVIDER=yfinance  # or alpaca
DATABASE_URL=...           # PostgreSQL connection string
ENCRYPTION_KEY=...         # Fernet key (generate: python scripts/generate_keys.py)
JWT_SECRET=...             # JWT secret (generate: python scripts/generate_keys.py)
```

Optional:
- **LLM / providers**: `XAI_API_KEY`, `MODEL_PROVIDER` (xai/openai/anthropic), `MODEL_NAME` /
  `DEFAULT_MODEL` (default `grok-4-1-fast-reasoning`), `XAI_VOICE_MODEL` (default `grok-4-fast`),
  `SEARCH_PROVIDER` (default tavily) + `TAVILY_API_KEY`, `MARKET_DATA_PROVIDER`/`MARKED_DATA_PROVIDER`
  (yfinance/alpaca), `AGENT_FRAMEWORK`, `ANTHROPIC_API_KEY` (+ `langchain-anthropic` for Claude)
- **Data/feeds**: `EODHD_API_KEY`
- **Daily advisor**: `ADVISOR_ENABLED` (default true in Compose),
  `ADVISOR_EMAIL_ENABLED` (default false), `ADVISOR_CLOSE_DELAY_MINUTES` (15),
  `ADVISOR_WORKER_POLL_SECONDS` (10),
  plus optional `ADVISOR_MIN_CLOSED_TRADES`, `ADVISOR_DRIFT_RATIO`,
  `ADVISOR_LOSING_SESSIONS`, `ADVISOR_DRAWDOWN_PCT`, and
  `ADVISOR_URGENT_DAILY_LOSS_PCT` overrides
- **Fixed paper service attribution**: set both `PAPER_USER_ID` and
  `PAPER_ACCOUNT_ID` to bind `scripts/run_paper_strategy.py` to an owned linked
  account; without them it remains a legacy unscoped run
- **Email**: `POSTMARK_API_KEY`, `FROM_EMAIL` (`TO_EMAIL` remains for legacy scripts;
  advisor delivery always uses each active user's login email)
- **OAuth**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- **Deploy**: `COOLIFY_URL`, `COOLIFY_API_TOKEN`, `COOLIFY_APP_UUID`
- **LinkedIn skill**: `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`
