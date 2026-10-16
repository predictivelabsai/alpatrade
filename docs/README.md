# AlpaTrade docs index

Superseded plans, one-off reports and old designs are in [archive/](archive/).

## Changelog
- [change_log.md](change_log.md): release notes, newest first (update with every release).

## Operations and runbooks
- [user_live_runner_deploy.md](user_live_runner_deploy.md): deploying the per-user live/paper runner supervisors.
- [live_btd_minhold.md](live_btd_minhold.md): the standalone live Mag-7 buy-the-dip runner.
- [strategy_methodology.md](strategy_methodology.md): live BTD rules, scheduler and operations (ET).
- [hermes.md](hermes.md): Hermes Agent setup, deployment, verification and recovery.
- [finespresso-news-worker.md](finespresso-news-worker.md): the separate news ingestion worker.
- [cwt_pipeline.md](cwt_pipeline.md): Chat With Traders → backtested Leaderboard strategies pipeline.

## Architecture
- [agent_architecture.md](agent_architecture.md): the implemented agent surface and catalog.
- [deepagent_flow.md](deepagent_flow.md): DeepAgent end-to-end flow (API, routing, safety, jobs).
- [autonomous-agent-team-plan.md](autonomous-agent-team-plan.md): autonomous paper-trading agent team (status needs refresh).
- [activity_logging.md](activity_logging.md): tenant-scoped activity histories in Postgres.
- [agent-tracing.md](agent-tracing.md): agent tracing and LLM cost visibility.
- [agent-benchmark-reporting.md](agent-benchmark-reporting.md): consolidated daily paper/agent digest.
- [streaming-chat.md](streaming-chat.md): streaming chat trace in the web UI and API.

## Features and APIs
- [mobile-api.md](mobile-api.md): contract for the Flutter mobile client.
- [swagger.json](swagger.json): OpenAPI snapshot (used by the mobile API contract test).
- [index_options.md](index_options.md): index options paper trading.
- [hedge_funds_13f_plan.md](hedge_funds_13f_plan.md): 13F filters and implied performance (linked from the app).
- [auth_readme.md](auth_readme.md): authentication and per-user Alpaca keys.
- [multi_account_guide.md](multi_account_guide.md): multiple Alpaca accounts per user.
- [product_todo.md](product_todo.md): product backlog.

## Current evidence reports (read by code)
- `walk_forward_btd_semi7_*.json/.md`: Semi-7 walk-forward; `engine/leaderboard/semi7.py` loads the latest from docs/.
- `btd_live_rules_wf_*.json/.md`: exact-live-rules backtests used by `scripts/seed_semi7_backtest.py`.
