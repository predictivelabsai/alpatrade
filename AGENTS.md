# Repository Guidelines

## Project Structure & Module Organization

Core infrastructure lives in `engine/`: market feeds are under `engine/feeds/`, database access under `engine/db/`, web components under `engine/web/`, and agent runtimes under `engine/agents/runtime/`. Asset-specific routes belong in `verticals/`; current equities code is in `verticals/equities/`. Workflow agents live in `agents/`. Use `scripts/` for operational utilities and `tasks/` for trading jobs. Tests are in `tests/`, evaluation harnesses in `evals/`, and UI assets in `static/` and `screenshots/`.

## Build, Test, and Development Commands

- `uv sync --all-extras` creates the environment from `pyproject.toml` and `uv.lock`.
- `uv run python main.py` starts the interactive application entry point.
- `uv run python web_app.py` runs the FastHTML web UI.
- `uv run uvicorn api_app:app --host 0.0.0.0 --port 5001 --reload` starts the REST API with reload.
- `uv run python -m pytest tests/regression_suite.py -q` runs the CI regression suite.
- `uv run python -m compileall -q app.py api.py engine verticals agents` performs a fast syntax check.

## Coding Style & Naming Conventions

Use Python 3.11+ syntax, four-space indentation, and PEP 8 naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_CASE` for constants. Add type hints to public interfaces and docstrings where behavior is not obvious. Keep provider-neutral logic in `engine/` and asset-specific behavior in `verticals/`. No repository-wide formatter is configured, so follow nearby code and group imports as standard library, third-party, then local.

## Testing Guidelines

Pytest is the primary runner, although several suites use `unittest` classes. Name new files `test_<feature>.py` and test methods `test_<behavior>`. Mock brokerage, model, email, and market-data calls in unit tests. Tests requiring API keys or PostgreSQL must skip cleanly when configuration is absent. Run the focused test first, then the regression suite before opening a PR; no numeric coverage threshold is currently enforced.

CI/CD must remain configured and active. Add every new feature's focused tests to `.github/workflows/ci.yml`, and do not merge while required checks fail.

For every major feature or release push, bump the project version in both `pyproject.toml` and `uv.lock`. Update `docs/change_log.md` in the same commit with the date, version, user-visible changes, tests, and deployment notes.

## Commits & Pull Requests

Recent history follows Conventional Commit-style subjects such as `feat(backtest): ...`, `fix(auth): ...`, and `docs: ...`. Keep commits imperative, focused, and scoped when useful. PRs should explain the user-visible impact, list verification commands, link relevant issues, and include screenshots for changes under `engine/web/` or `static/`. Call out migrations, new environment variables, and any paper-trading behavior explicitly.

## Security & Configuration

Store credentials only in `.env`; never commit keys, tokens, account data, or database URLs. Run `scripts/verify_no_secrets.sh` before pushing configuration changes. Default all trading changes to paper mode and clearly flag any path capable of live orders.
