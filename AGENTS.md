# AGENTS.md

Compact cheat sheet. **Read `CLAUDE.md` first** — it has the full architecture, migration state,
provider config, and deployment notes. This file only captures what an agent would otherwise guess wrong.

## Entry points & ports

| App | Entry | Port | Notes |
|-----|-------|------|-------|
| Web (prod) | `python main.py` → `app.py` | 5001 (env `ASSETHERO_WEB_PORT`) | Thin shim; this is what Coolify runs via `Dockerfile.agui` |
| REST API (prod) | `python api_app.py` | 5001 | Coolify runs this via `Dockerfile.api`; Swagger `/docs`, ReDoc `/redoc`, OpenAPI `/openapi.json` |
| Namespaced API | `python api.py` | 5002 (env `ASSETHERO_API_PORT`) | Compatibility shell mounting the production API under `/api/v1/equities` |
| AG-UI chat | `uvicorn agui_app:app --port 5003 --reload` | 5003 | Defines the DeepAgents-backed `primary_agent` / `agent_for_user()`; `langgraph_agent` remains a compatibility alias |
| CLI | `python cli.py` (or `alpatrade` console script) | — | `cli.py` → `tui/pt_cli.py` → `tui/command_processor.py` |

`web_app.py` is **retired** (don't target it for new work). `api_app.py` is the canonical production
API contract; `api.py` is the optional namespaced compatibility shell.
The canonical external agent endpoint is authenticated `POST /v2/deepagents`,
implemented by `engine/ai/deepagents.py`; `/v2/chat` and
`/v2/agents/chat/invoke` are compatibility transports over that service.

## Commands

```bash
uv sync --all-extras                 # install (extras: web, agents, agui, e2e, all)
uv run python cli.py                 # interactive CLI
uv run python app.py                 # web UI
python -m compileall -q app.py api.py engine verticals tui utils agents   # fast syntax check (matches CI)
python -m pytest tests/regression_suite.py -v            # full suite — requires DB + .env + Alpaca/XAI
python -m pytest tests/regression_suite.py::TestStrategySlug -v   # single class
python -m pytest tests/test_index_options.py tests/test_ui_navigation.py tests/test_premarket.py tests/test_research.py tests/test_chat_chart_transport.py tests/test_objective.py tests/test_refit.py tests/test_regime.py tests/test_vol_sizing.py tests/test_promotion.py tests/test_agent_framework_default.py tests/test_scout_reasoning.py tests/test_backtest_reasoning.py tests/test_daily_advisor.py tests/test_web_advisor_page.py tests/test_pnl_dashboard.py tests/test_autonomy_worker.py -q   # DB-free unit tests (CI default)
python -m engine.autonomy.worker                          # worker + advisor scheduler (full autonomy needs AUTONOMY_ENABLED=true)
python -m engine.backtest.runner --symbols AAPL --start 2024-01-01 --end 2024-06-30  # methodology backtest → backtest-results/
python run_migration.py sql/NN_name.sql                  # apply a migration (no tracking table; idempotent)
python scripts/coolify_deploy.py deploy --name agui      # deploy to prod (needs COOLIFY_* in .env)
scripts/verify_no_secrets.sh                            # pre-commit gate — run before pushing
```

CI (`.github/workflows/ci.yml`) uses **pip**, not uv: `pip install -e ".[all]"` plus
`authlib pytest`. The regression suite step only runs when the `DATABASE_URL` repo secret is set;
otherwise CI runs only the explicit DB-free unit-test list above (mirrors the "Unit tests" step in
ci.yml). Add new DB-free tests to that explicit list if they should run in CI.

## Parallel agent sessions

Multiple agents work this repo concurrently, each in its own worktree + branch:

- **Divide by PR domain** — each agent owns its feature/fix domain and its PRs; never have two
  agents edit the same branch.
- **Worktree discipline** — branch off a committed ref (the shared checkout's working tree may hold
  another agent's in-flight edits); commit and push from your worktree only.
- **Rebase before opening a PR** — `git fetch` first: if a dependency PR (e.g. a base feature
  branch) or `fix/web-*` work landed on `main`, rebase onto it before review so conflicts are
  resolved once, in the right order. Stacked PRs (base = a feature branch) are fine; say which PR
  each stacked PR waits on.

## Architecture facts that aren't obvious from filenames

- **`engine/` is canonical; `utils/*` are compat shims** that `sys.modules`-alias to relocated
  `engine` modules (removed in Phase 7). **New code imports `engine.*`, not `utils.*`.** When both
  paths exist, prefer `engine.*`.
- **Two distinct backtest engines**: grid-search (`utils/backtester_util.py`, driven by
  `agents/backtest_agent.py`, used by CLI/web/orchestrator) and methodology-faithful
  (`engine.backtest`, vendored Alpaca skill, writes deterministic dated folders to
  `backtest-results/`). Don't conflate them.
- **`CommandProcessor`** (`tui/command_processor.py`) is the central dispatcher for CLI commands;
  positional params are parsed there (e.g. `trades paper btd-3dp`). Unknown input falls through to the AI agent.
- **Five-agent orchestrator** (`agents/orchestrator.py`): Backtest → Validate → Paper Trade →
  Validate → Reconcile → Report. Communication is a file-based JSON message bus
  (`data/agent_messages/`).
- **Verticals**: `verticals/equities/` is the equities web vertical; `verticals/publicmarkets/` is
  the newer IPO/SEC/hedge-fund tools vertical. Provider-neutral logic stays in `engine/`.
- **Autonomy engine** (`engine/autonomy/`): Postgres-backed durable run engine over the
  Orchestrator phases — DB queue (`FOR UPDATE SKIP LOCKED`), checkpointed pipeline, continuous
  worker with full autonomy gated by `AUTONOMY_ENABLED` (paper-only by design). The same
  worker still drains scheduled advisor jobs when full autonomy is off. Controls surface in
  `engine/web/ph_monitoring.py`.
- **DB**: PostgreSQL with `alpatrade` schema. Migrations in `sql/` (numbered `01_`–`25_`,
  idempotent `CREATE TABLE IF NOT EXISTS`). Per-user Alpaca keys live in `user_accounts`
  (Fernet-encrypted BYTEA), **not** `users`. All data tables carry `user_id` (+ `account_id`).

## Model & provider config

- `engine/config.py::get_settings(user_id)` layers per-user DB overrides over env over defaults.
  Default model `grok-4-1-fast-reasoning`; `DEFAULT_MODEL` wins over `MODEL_NAME`.
- `build_chat_model` **self-heals** for XAI: probes the model, falls back to the first working entry
  in `MODEL_NAMES["xai"]` if unavailable. Keep the preferred model first in that list.
- Voice (`engine/voice.py`) has its own model (`XAI_VOICE_MODEL`, default `grok-4-fast`) and is **not**
  routed through the self-heal.

## Conventions

- Python 3.13 in CI (pyproject floor is `>=3.11`). PEP 8, four-space indent, type hints on public
  interfaces. **No repo-wide formatter** — follow nearby code.
- Commits: Conventional Commit subjects (`feat(backtest): …`, `fix(auth): …`, `docs: …`).
- **Version bumps**: for major features/releases, bump `pyproject.toml` **and** `uv.lock`, and
  update `docs/change_log.md` in the same commit (date, version, user-visible changes, tests, deploy notes).
- Trading changes default to **paper mode**; flag any path capable of live orders explicitly.

## Secrets

NEVER copy/log/commit secret values — reference by variable name only. `XAI_API_KEY` is especially
sensitive (a prior key was leaked via GitHub and revoked). Run `scripts/verify_no_secrets.sh` before
pushing (also wired as a pre-commit hook). If a secret is ever committed, purge with `git-filter-repo`.
Required `.env` keys: `ALPACA_PAPER_API_KEY`, `ALPACA_PAPER_SECRET_KEY`,
`DATABASE_URL`, `ENCRYPTION_KEY`, `JWT_SECRET`. See CLAUDE.md for the full optional list.

## Skills (user-invocable, in `.claude/skills/`)

- `coolify-deploy` — trigger/inspect Coolify deploys via API token (never the account password).
- `linkedin-post` — post to LinkedIn via OAuth token (no password/2FA entered).
- `alpaca-trading-backtest` — deterministic historical backtest via the Alpaca CLI skill.
