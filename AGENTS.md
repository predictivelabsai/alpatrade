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

Run these commands from the **repository root**, with an already provisioned Python
installation/environment. `uv run` can synchronise dependencies; use it only when installation
is authorised. These are reference commands, not a checklist to execute during onboarding.

```powershell
uv sync --all-extras                 # installation only; extras declared in pyproject.toml
uv run python cli.py                 # interactive CLI; may load .env and contact services
uv run python app.py                 # long-running web UI, local default port 5001
python -m compileall -q app.py api.py engine verticals tui utils agents   # CI syntax check; writes bytecode
python -m pytest tests/regression_suite.py -vv --durations=20   # CI regression command; DB/provider access
python -m pytest tests/regression_suite.py::TestStrategySlug -v   # class exists; module imports still need dependencies
python -m pytest tests/test_llm_usage.py -q             # separate CI unit-test step
python -m pytest tests/test_news_worker.py -q           # separate CI unit-test step
python -m pytest tests/test_activity_logging.py tests/test_alpha_research.py tests/test_ipo.py tests/test_index_options.py tests/test_ui_navigation.py tests/test_premarket.py tests/test_research.py tests/test_chat_chart_transport.py tests/test_chat_persistence.py tests/test_objective.py tests/test_refit.py tests/test_regime.py tests/test_vol_sizing.py tests/test_promotion.py tests/test_short_exits.py tests/test_agent_framework_default.py tests/test_hermes_runtime.py tests/test_hermes_access.py tests/test_hermes_jobs.py tests/test_hermes_backtest_quality.py tests/test_hermes_backtest_results.py tests/test_hermes_data_qa.py tests/test_scout_reasoning.py tests/test_backtest_reasoning.py tests/test_mobile_api_contract.py tests/test_deepagents_api.py tests/test_chat_routing.py tests/test_chat_alpaca_keys.py tests/test_news_panel.py tests/test_daily_advisor.py tests/test_pnl_dashboard.py tests/test_autonomy_worker.py tests/test_run_recovery.py tests/test_daily_pnl_tenant_report.py tests/test_email_util.py tests/test_report_analytics.py tests/test_voice_alpaca_keys.py tests/test_key_fallback.py tests/test_equities_routes.py tests/test_state_isolation.py tests/test_email_verification.py tests/test_paper_strategies.py tests/test_paper_signals.py tests/test_shareable_reports.py tests/test_strategy_presets.py tests/test_web_advisor_page.py tests/test_xai_byok.py -q   # main CI Unit tests step
python -m engine.autonomy.worker                       # persistent worker and advisor scheduler
python -m engine.backtest.runner --symbols AAPL --start 2024-01-01 --end 2024-06-30   # loads .env, fetches data, writes backtest-results/
python run_migration.py sql/23_daily_advisor.sql         # example existing migration; changes the configured DB
python scripts/coolify_deploy.py deploy --name agui     # deployment; explicit authorisation required
```

CI (`.github/workflows/ci.yml`) uses **pip**, not uv: `pip install -e ".[all]"` plus
`authlib pytest pytest-asyncio`. `all` includes web/agents/agui; `uv sync --all-extras`
also includes `e2e`. The regression suite step only runs when the `DATABASE_URL` repo secret
is set. The three unit-test commands above match CI; the main Unit tests step uses an
`XAI_API_KEY` placeholder for client construction. DB-free does not mean import-side-effect-free.
Add new DB-free tests to the explicit CI lists if they should run there.

`scripts/verify_no_secrets.sh` is the existing pre-commit/pre-push gate and defaults to scanning
staged files. Its Bash shebang, arrays, `grep` and process substitution require a Bash-compatible
environment such as Git Bash/Linux; the bare script path is **not a native PowerShell command**.
Keep the gate before pushing; do not execute shell scripts through PowerShell as though they were
PowerShell scripts. Verification status and source references: [docs/onboard-verification.md](docs/onboard-verification.md).

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
- **DB**: PostgreSQL with `alpatrade` schema. Migrations in `sql/` (numbered `01_`–`30_`,
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
- Use British English and no em dashes in new copy. Finish tasks with what changed,
  how it was tested and open questions. Never commit secrets or push to `main`/`master`.
- Put shared provider-neutral logic in `engine/`, asset surfaces in `verticals/`, and CLI
  dispatch in `tui/command_processor.py`. Import relocated modules through `engine.*`:
  `utils/auth.py` aliases `engine.auth` via `sys.modules`, rather than defining a second API.
- FastHTML features expose `register(app, rt)` and are wired in `app.py`; use
  `engine.web.ph_layout.page` for the shared shell. Equities registration additionally takes
  `ph_auth.current_user`. Follow `engine/web/ph_advisor.py` for request-session handling and
  escaping dynamic values before using `NotStr` HTML.
- Use `engine.db.pool.DatabasePool().get_session()` and parameterised SQLAlchemy `text()`
  queries in the `alpatrade` schema. The context manager commits on success, rolls back on
  failure and closes the session. Follow `engine/autonomy/store.py` for bound `:uid`/`:aid`
  parameters and caller-scoped lookups; never interpolate identifiers supplied by users into SQL.
- Authenticate tenant API routes with `api_app.require_tenant_user`, derive the caller from
  that dependency and check account ownership. Preserve `user_id` and `account_id` scoping
  across queries, jobs and reports; see `get_run_for_user` and `sql/23_daily_advisor.sql`.
- Keep unit tests isolated with fakes/monkeypatches as in `tests/test_web_advisor_page.py`.
  Add their targets to `.github/workflows/ci.yml`; do not assume pytest discovery covers CI.
- Preserve methodology backtest reproducibility and disclosures from
  `engine/backtest/artifacts.py`, and `next_open` as the default execution assumption.

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

## Stack

- Docker
- FastAPI
- Python

## Builders

codex: yes
muse: no

## Do not touch

- Never read or commit secrets, credentials or local environment files.
- Never deploy or push without explicit authorisation.
- Do not modify unrelated application code.
- Do not replace `main.py`/`app.py` or the production `api_app.py` contract with retired
  `web_app.py`; preserve the `/v2/deepagents` endpoint and compatibility transports.
- Do not remove `utils/*` compatibility aliases during unrelated work or move the
  grid-search backtester into `engine.backtest`: the two engines have different contracts.
- Do not bypass tenant/account ownership checks or substitute platform broker keys for a
  caller's required linked account. Preserve the explicit-approval behaviour of the read-only
  advisor surface (`engine/web/ph_advisor.py`).
- Do not enable live trading by changing the `AlpacaAPI(paper=True)` default, remove the
  `AUTONOMY_ENABLED` gate, or launch the worker as a smoke test: scheduled advisor jobs can
  still run when full autonomy is disabled (`engine/autonomy/worker.py`).
- Do not run `run_migration.py`, modify shared database data, or invoke Coolify/notification/
  publishing scripts as verification. Database migrations and operational actions require
  their own explicitly authorised task.
- Do not edit generated/runtime artefacts under `data/`, `backtest-results/`, `reports/`,
  `test-results/` or `eval-results/` as source code; these paths are ignored in `.gitignore`.
- Keep `codex: yes` and `muse: no`; never enable Muse. Keep changes within the authorised
  scope and list unrelated findings as follow-ups.
