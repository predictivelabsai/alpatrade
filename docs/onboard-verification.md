# Onboarding verification

Reviewed on 12 October 2026 from the repository root using PowerShell.
Only `AGENTS.md` and this report were changed for onboarding.

## Executed checks

| Check | Result |
|---|---|
| `git status --short` / `git status --porcelain=v1` | Initially clean on `task/onboard-enrich`. |
| `python --version` | Python 3.14.6 available; CI declares 3.13 and the package requires >=3.11. |
| `uv --version` | uv 0.12.10 available; no synchronisation or installation performed. |
| Standard-library `ast.parse` on source bytes | Passed for 177 files: entry points, migration/deploy script sources and all Python files under engine/verticals/tui/utils/agents. No repository imports or bytecode writes. |
| CI target existence and AST checks | Passed: 47 main Unit tests targets, two separate unit-test targets and the regression suite. `TestStrategySlug` is declared in the regression suite. |

AST checks establish syntax and target existence only. They do not establish dependency
availability, import success, functional correctness, database connectivity or provider access.
The source review found stale command coverage and missing concrete conventions; architecture
and existing project policies were retained.

Additional documentation checks passed: existing policy/custom sections preserved, all three
CI unit commands match, Muse remains disabled, and no new copy contains em dashes.
A scoped scan of only the two authorised documentation files using the ten patterns and
placeholder exclusions from `scripts/verify_no_secrets.sh` found no potential secrets.
This standard-library scan did not execute the Bash script or scan credentials/runtime files.
`git diff --check` passed for tracked changes. A direct whitespace check of both documentation
files also passed; staging was blocked by filesystem permissions.

## Command review

All paths and module invocations below assume the repository root as the working directory.
Container entry points run from `/app`, declared by both Dockerfiles. Commands marked
source-reviewed were not executed.

| Command or group | Declared source | Verification and correction |
|---|---|---|
| `uv sync --all-extras` | `pyproject.toml`, `uv.lock` | Source-reviewed. web/agents/agui/e2e/all extras exist; all includes web/agents/agui, not e2e. Installation skipped. |
| `uv run python cli.py`, `alpatrade` | `cli.py`, `[project.scripts]` in `pyproject.toml` | Source-reviewed: console script resolves to `cli:main`, which invokes authentication and the interactive CLI. Skipped because it loads local environment configuration and can contact services. |
| `uv run python app.py`, `python main.py` | `app.py`, `main.py`, `Dockerfile.agui` | Source-reviewed: both serve the merged app at local default 5001; Docker overrides `ASSETHERO_WEB_PORT` to 5003. No server started. |
| `python api_app.py`, `python api.py` | `api_app.py`, `api.py`, `Dockerfile.api` | Source-reviewed: production API uses 5001, namespaced shell defaults to 5002 via `ASSETHERO_API_PORT`. No server started. |
| `uvicorn agui_app:app --port 5003 --reload` | `agui_app.py`, web dependencies in `pyproject.toml` | Source-reviewed: module declares the ASGI app. Uvicorn CLI sets port/reload; not started. |
| `python -m compileall -q app.py api.py engine verticals tui utils agents` | CI Byte-compile step | Exact match retained. Not executed because it writes bytecode; used in-memory AST parsing instead. |
| `python -m pytest tests/regression_suite.py -vv --durations=20` | CI Regression suite step | Updated flags to match CI. Target exists and parses; execution skipped because it imports application modules and can reach DB/providers. CI gates it on DATABASE_URL. |
| `python -m pytest tests/regression_suite.py::TestStrategySlug -v` | `tests/regression_suite.py` | Class confirmed statically. Not executed: collecting a single class still imports the module. |
| Three CI unit-test commands | CI LLM usage unit tests, News worker unit tests, Unit tests steps | Replaced the stale 17-file list with the current 47-file list and added the two separate steps. All targets exist and parse. Added pytest-asyncio to the documented CI dependencies. No pytest collection or execution. |
| `python -m engine.autonomy.worker` | `engine/autonomy/worker.py` | Source-reviewed: module invokes a persistent loop. AUTONOMY_ENABLED gates full autonomy, but advisor scheduling still operates. Not started. |
| `python -m engine.backtest.runner --symbols AAPL --start 2024-01-01 --end 2024-06-30` | `engine/backtest/runner.py` argument parser and main | Source-reviewed: all flags declared. Loads .env, fetches market data and writes dated artefacts. Not executed. |
| `python run_migration.py sql/23_daily_advisor.sql` | `run_migration.py`, `sql/23_daily_advisor.sql` | Replaced the non-existent NN_name.sql placeholder with an existing example. Runner accepts the first positional path relative to cwd and commits SQL through DatabasePool. Not executed; idempotence does not make migration execution a harmless check. |
| `python scripts/coolify_deploy.py deploy --name agui` | `scripts/coolify_deploy.py` parser | Source-reviewed: deploy subcommand and --name exist. Not executed, including --help, because the module loads environment configuration. |
| `scripts/verify_no_secrets.sh` | Script shebang and usage comments | Source-reviewed: scans staged files by default; requires Bash, grep and process substitution. Corrected the implication that the bare path is a PowerShell command. Existing pre-push policy preserved. Script not executed. |

## Scope and follow-ups

No dependencies installed, repository modules imported, local environment files read, servers
started, database operations run, deployments triggered or pushes performed. Builder settings
remain `codex: yes` and `muse: no`. Existing policies and custom text remain in place.

`CLAUDE.md` has broader historical command/architecture notes that could be reconciled in a
separate task; it is outside the authorised edit scope. A native PowerShell secret-check entry
point would also require a separate task. Runtime commands remain unverified in this restricted
onboarding pass. No user decision is needed to finish the requested documentation changes.

The final action creates an empty `.dispatch-done`; `.gitignore` already excludes it.

## Commit outcome

The requested commit could not be created. `git add -- AGENTS.md
docs/onboard-verification.md` failed because the sandbox denied creation of `index.lock`
in the worktree metadata under `C:/Users/Joosep/alpatrade/.git/worktrees/`.
No commit or push was performed and no permission restriction was bypassed.
The documentation changes remain uncommitted, so the worktree is not clean.
The remaining action outside this sandbox is to stage these two files and commit with
`ops: enrich repository onboarding`.
