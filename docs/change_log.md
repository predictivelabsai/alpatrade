# Change Log

## Unreleased

### Hermes candidate promotion correctness

- Fixed Hermes paper promotion to pass the exact approved candidate parameters
  into the standalone orchestrator. Previously, the worker stored the candidate
  under `params` but omitted `approved_best_config`, causing YAML defaults to be
  traded and reported instead.
- Forwarded the requested robustness-window count and benchmark symbol through
  the orchestrator, so the three-window Hermes validation contract is actually
  executed rather than only recorded in the queued job.
- Preserved the source backtest lookback when promoting a candidate, keeping the
  paper-run slug and daily-report lineage aligned with the research period.
- Improved Hermes-only command output: running-job queries now exclude history,
  zero-exit sessions report `WAITING` and `N/A` win rate, backtest metrics use
  explicit percentage units, and benchmark underperformance is highlighted.
- Added regression coverage for exact candidate promotion, robustness forwarding,
  running-job filtering, and zero-exit reporting.

### Hermes clarification and suggested follow-ups

- Added persistent, clickable suggested follow-ups beneath every Hermes response;
  clicking fills the composer so the user can review or edit before sending.
- Added a deterministic clarification gate for incomplete backtests, ambiguous
  paper starts, and parameter-change requests. Hermes now states what is missing
  and queues nothing instead of silently choosing defaults.
- Fixed hyphenated natural periods such as `6-month`, which previously bypassed
  the period parser and fell back to three months.

### Consolidated daily agent digest

- Replaced the duplicate Hermes-only daily summary with the account-owned
  AlpaTrade digest. Immediate opt-in Hermes entry/exit alerts remain independent.
- Added Today/MTD/YTD realized agent benchmarks and explicit no-data rows for
  Hermes, DeepAgents, and LangGraph.
- Corrected fractional strategy parameter display (`0.05` now renders as `5%`)
  and added an equity reconciliation notice when Alpaca prior-close P&L differs
  from the last emailed equity snapshot.
- Added a concise agent-status section with safe next commands and clearer
  zero-activity language.
- Fixed deployment recovery for older continuous Hermes jobs whose heartbeat is
  null, and reactivate the canonical run when the worker reclaims the job so
  chat status and daily reporting cannot disagree.

### Guided Hermes workflow

- Added clickable Hermes Backtest, Paper Trade, and Monitor shortcuts to the
  left Agents panel.
- Reworked `/hermes help` into a numbered quick start and explained the
  difference between job, run, and candidate IDs.
- Added no-ID analysis and pause/resume/stop commands that safely resolve the
  latest applicable paper job owned by the authenticated user. Explicit IDs
  remain supported when an account has multiple jobs.
- Tests cover sidebar rendering, deterministic help, ownership-safe job
  selection, and existing ID-based commands.

## 0.23.0 — 2026-08-25

### Attribute autonomous paper runs to a configured owner

- Closes the gap noted in 0.22.0: the paper runs seen piling up were the
  autonomy worker's **scout self-feed** (`worker.loop` → `scout.enqueue_run`),
  which enqueued runs with **no owner** (user_id NULL). Because the 0.22.0 dedup
  guard only acts on attributed runs, those orphans were never de-duplicated.
- The worker now resolves an owner via `worker.scout_owner()`
  (`AUTONOMY_OWNER_USER_ID`/`AUTONOMY_OWNER_ACCOUNT_ID`, falling back to
  `PAPER_USER_ID`/`PAPER_ACCOUNT_ID`) and passes it to the scout, so self-fed
  runs are tenant-scoped sessions and the dedup guard applies to them.
- Both ids must be set together; a half-configured pair resolves to unattributed
  (never a broken key lookup). One env pair now owns both the autonomy self-feed
  and the fixed `paper-strategy` service.
- `docker-compose.yaml`: autonomy service passes `AUTONOMY_OWNER_*` (defaulting
  to `PAPER_*`).

## 0.22.0 — 2026-08-25

### Fix: duplicate live paper runs (replace, session-scoped)

- Paper runs are no longer allowed to pile up: `run_paper_trade` now replaces this
  session's own prior identical live run(s) before starting a new one
  (`stop_duplicate_paper_runs`), marking the old ones `stopped`.
- Strictly scoped to the SAME user + account + strategy_slug + symbol-set, and a
  no-op unless the run is attributed (user_id + account_id set) — it can never
  stop another user's runs, a different config, or an unattributed run.
- Note: the runs seen piling up were unattributed system/env paper runs
  (user_id NULL); attaching them to an owner (so this guard applies) requires the
  autonomy/paper-strategy spawner to run with a user/account.

## 0.21.0 — 2026-08-24

### Daily PnL report — critique fixes (1-10)

- Unified stale-orphan run status on `'stale'` (worker sweep + report reconcile
  agreed), leaving `'stopped'` for a deliberate Ctrl+C.
- CLI `--user/--account/--framework` now render the full per-account report
  (MTD/YTD, agent benchmark, live runs), matching the scheduler.
- Hybrid MTD/YTD: seed the baseline from Alpaca portfolio history when snapshots
  don't reach the window start, so returns are correct retroactively; each window
  tags its `source`.
- Labeled baselines: "today (vs prior close)" and "unrealised (since entry)".
- Populate `net_cash_flow` from Alpaca activities so the cash-flow correction is
  real, not a silent no-op.
- Added a SPY buy-and-hold benchmark (with excess return) on MTD/YTD.
- Added cumulative realized P&L, annualized Sharpe, and max drawdown from the
  equity-snapshot curve.
- Back-dated reports show that day's equity/day-change from Alpaca history (only
  positions/cash stay live), with a precise notice.
- Added a "data unavailable" banner distinguishing an outage from "no activity".
- Consolidated recipients: `--to` wins, else the account owner, else the legacy
  `PNL_REPORT_TO` broadcast.
- Tests: analytics + render helpers, email send, run recovery (DB-free).

## 0.20.1 — 2026-08-24

### Fix: daily PnL report email actually sends

- `send_email_to()` had no body after the env check — when Postmark was
  configured it fell through and returned `None`, so the daily PnL report emailed
  nothing and the CLI aggregator crashed on `all_ok &= None`. The worker-owned
  scheduler uses the same helper, so scheduled tenant reports silently never sent.
- Added the missing Postmark POST and a strict bool return; DB-free tests cover
  send/uncleared-env/transport-error/return-type.

## 0.20.0 — 2026-08-24

- Rebuilt the standard daily paper report around per-user, per-account Alpaca
  credentials; removed the hard-coded distribution list and cross-tenant run/trade
  queries.
- Added heartbeat-verified paper-run status, process-safe delivery claims, account
  equity snapshots for honest MTD/YTD returns (superseding the 0.19.0 Alpaca
  portfolio-history period returns), and separate realized-P&L benchmark
  rows for Hermes, DeepAgents, LangGraph, and explicitly labeled legacy runs.
- Bridged the durable Hermes job heartbeat into canonical run liveness and protected
  fresh Hermes jobs during stale-run reconciliation.
- Replace `/app?new=1` with the saved thread URL after the first response so refresh
  restores the new conversation instead of showing a blank composer.
- Added migration `sql/25_tenant_agent_reporting.sql`; it only alters/creates objects
  inside `alpatrade` and does not rewrite existing trades or run statuses.
- Fixed Hermes detailed-backtest result routing so commands containing a job ID
  return the selected result instead of the general jobs list.
- Added three validation robustness windows plus SPY buy-and-hold and excess-return
  evidence to new Hermes backtests; promotion now requires positive results across
  a majority of the robustness windows.
- Added a Hermes-only paper drift guard that waits for 20 closed trades across at
  least five trading days and automatically pauses when daily paper Sharpe falls
  below half the validated Sharpe.
- Added owner-scoped notification delivery tests/history and DB-to-broker position
  reconciliation in Hermes daily reports. Default agents and live trading paths
  remain unchanged.
- Tests: result routing, delivery history, drift thresholds, reconciliation,
  robustness windows, benchmarks, default-agent isolation, tenant report isolation,
  liveness, and framework-separated rendering.

## 0.19.0 — 2026-08-23

### Daily report: period returns

- Added month-to-date, year-to-date, and overall (since-inception) arithmetic
  returns to the daily paper-PnL report, alongside the existing day change.
  Each window's baseline is the first available equity point from Alpaca's
  portfolio history; the return is `equity_now / baseline - 1`.
- Added an `AlpacaAPI.get_portfolio_history()` wrapper (normalized equity/PnL
  series, null/zero padding dropped) used by the report.
- Deposits/withdrawals are not modelled — for a paper account funded once (the
  norm) this equals the true cumulative return; missing windows render as `n/a`.
- Tests: history normalization, arithmetic-return math, graceful empty history,
  and Performance-table rendering (DB-free).

## 0.18.0 — 2026-08-23

### Stale paper-run cleanup ("zombie" runs)

- Added `heartbeat_at` to `alpatrade.runs` (`sql/24`); a live paper session now
  stamps its heartbeat each cycle so a legitimately long-running session is never
  mistaken for an orphan.
- The autonomy worker sweeps paper runs left `running` by an interrupted or
  redeployed process (heartbeat older than `RUNS_STALE_SECONDS`, default 30 min)
  to `stopped`, and the migration finalizes already-orphaned rows once. This stops
  the daily report from showing "+N older runs with identical configuration still
  marked running".
- Tests: migration hygiene, heartbeat/sweep contracts, per-cycle heartbeat, and
  the worker sweep call.

## 0.17.0 — 2026-08-23

### Daily DeepAgent trading advisor

- Added one persisted, tenant/account-scoped paper advisory after each actual
  Alpaca/NYSE session close plus 15 minutes. Deterministic policy classifies
  reports as `insufficient_data`, `monitor`, `review`, or `urgent` and keeps
  broker-account P&L separate from AlpaTrade-attributed realized P&L.
- Added a locked-down `trading-advisor` DeepAgent specialist. It may rank only
  server-generated candidate IDs; unknown evidence, unsupported claims,
  invented metrics, and altered values are rejected into a deterministic fallback.
- Added authenticated report history/detail APIs, persisted dashboard cards,
  consolidated per-user email rendering, and explicit-intent tools that queue
  a stored advisor grid or start paper trading only from an owned, completed,
  validated backtest. Scheduled reports never change a strategy or place an order.

### Scheduling, persistence, and rollout

- Added migration `sql/23_daily_advisor.sql` for `advisor_reports` and
  deduplicated `advisor_deliveries`, and moved scheduler ownership exclusively
  to the autonomy worker with holiday, early-close, and DST-aware timing. A
  dedicated advisor queue lane keeps post-close reporting responsive while a
  longer paper-trading phase occupies the general autonomy lane.
- Retired web-process, standalone-paper, hardcoded-recipient, and per-session
  daily email paths. The legacy email request field remains accepted but is
  deprecated. `ADVISOR_EMAIL_ENABLED` defaults to `false` for the first-session
  report-only rollout; `ADVISOR_ENABLED` defaults to `true` in Compose.
- Added optional `PAPER_USER_ID`/`PAPER_ACCOUNT_ID` binding for the fixed paper
  service so its runs and trades can be attributed to the matching advisor account.
- Corrected validation-count persistence (`total_trades_checked` → `total_checked`)
  so non-empty validated backtests satisfy the explicit paper-start gate.
- Added DB-free coverage for metrics, thresholds, parameter units, model-output
  filtering, fallbacks, calendar timing, deduplication, consolidation, tenant
  isolation, API contracts, and explicit-intent gates. Bumped package/lockfile
  to 0.17.0.
- Apply `python run_migration.py sql/23_daily_advisor.sql` before deploying the
  worker/API/web services. Inspect at least one generated session before setting
  `ADVISOR_EMAIL_ENABLED=true`; deployment and email activation are not included.

## 0.16.0 — 2026-08-23

### Tenant-safe DeepAgents API

- Added authenticated `POST /v2/deepagents` as the canonical DeepAgents-only
  endpoint with append-only durable threads, stable client message UUIDs,
  replay-safe response idempotency, JSON responses, and SSE streaming.
- Added sanitized tool/subagent lifecycle events and heartbeats. Traces expose
  identity, status, and timing only; arguments, results, credentials, and raw
  exceptions remain private.
- Added five native specialists for market research, caller-owned portfolio
  analysis, strategy work, paper trading, and orchestration. Disabled the
  default general-purpose subagent and blocked filesystem/shell tools.
- Routed the older `/v2/chat` and `/v2/agents/chat/invoke` wire formats through
  the shared service. Anonymous compatibility chat now receives public research
  tools only and never falls back to deployment broker credentials.

### Persistence and paper-action safety

- Added migration `sql/22_deepagent_responses.sql` for durable response,
  sanitized event, action-deduplication, and job-deduplication records.
- Added the official asynchronous PostgreSQL LangGraph checkpointer with a
  shared pool, `alpatrade` search path, idempotent setup, and pickle fallback
  disabled in the MessagePack serializer.
- Generalized the autonomy worker by job kind. Backtests, paper sessions,
  full cycles, and autonomy requests return durable job IDs; full cycles retain
  Backtest → Validate → Paper → Validate → Reconcile → Report checkpoints.
- Enforced explicit imperative intent for mutating tools, caller-owned encrypted
  Alpaca credentials, `paper=True`, deterministic paper `client_order_id`
  values, tenant-scoped cancellation, and no automatic retry after uncertain
  paper-capable worker failures.

### Tests and deployment

- Added DB-free coverage for validation, auth boundaries, replay/concurrency,
  runtime context, specialist/tool registration, trace redaction, token
  normalization, heartbeats, stream failures, and paper-client identity.
- Added `deepagents<0.7`, `langgraph-checkpoint-postgres`, and psycopg 3 pool
  dependencies and bumped the package/lockfile to 0.16.0.
- Apply `python run_migration.py sql/22_deepagent_responses.sql` before deploying
  the API and worker. Deployment itself is not included in this release.

## 0.15.0 — 2026-08-22

- Added Hermes-only conservative backtests with five-basis-point entry/exit
  slippage, regulatory fees, stop-first ambiguous daily bars, close-time entry
  attribution, and portfolio daily-equity Sharpe, Sortino, and drawdown.
- Split Hermes research into 70% training and 30% untouched validation, persist
  both date ranges and validation metrics, and block paper promotion unless the
  validation return, Sharpe, drawdown, trade-count, and stability gates pass.
- Forward the requested objective and methodology flags through the orchestrator,
  attribute research jobs/candidates to the user's linked account when available,
  and release worker claims on terminal states.
- Added explicit methodology and promotion status to saved chat results. Legacy
  candidates without validation evidence can no longer start a Hermes paper job.
- Tests: conservative metric math, objective plumbing, train/validation isolation,
  promotion gates, worker cleanup, default-agent isolation, and full CI suite.
- Fixed combined candidate-start commands containing `notify me both` so they
  queue the validated paper job instead of being mistaken for an update request.

## 0.14.0 — 2026-08-22

- Added Hermes-only performance emails with reconciled signed P&L, grouped
  fills, green/amber/red status, concise reasons, and supported next commands.
- Added detailed entry/exit alerts with quantities, prices, thresholds, P&L,
  rationale, and owned job/run/candidate attribution.
- Added `/hermes analyze paper job <job-id>` for an owner-scoped diagnosis of
  results, repeated fills, duplicate Hermes jobs, and overlapping account runs.
- Finalize stop requests whose paper worker was interrupted during deployment,
  preventing an orphaned job from remaining incorrectly marked as running.
- Accept compact Hermes backtest periods such as `lookback:6m` and
  `lookback=1y` instead of silently applying the three-month default.
- Honor the explicit `objective:sharpe_ratio` contract when selecting the best
  eligible variation, and release worker claims when jobs finish or fail.
- Kept the established AlpaTrade daily email and the DeepAgents/LangGraph
  execution paths unchanged; all Hermes execution remains paper-only.
- Tests: Hermes report calculations, alert rendering, durable trade loading,
  ownership, overlap detection, command routing, and default-template isolation.

## 0.13.0 — 2026-08-21

- Added user-scoped Hermes portfolio recommendations and persisted entry, exit,
  hold, and watch advice in `alpatrade.hermes_advice` (migration 21).
- Added selectable in-app, email, both, or disabled advice delivery per active
  Hermes paper job, with duplicate-alert suppression and daily-email advice.
- Added deterministic `/hermes help`, portfolio construction, advice history,
  and notification commands. Advice is paper-only and never places extra orders.
- Kept DeepAgents, LangGraph compatibility routing, and default chat behavior
  unchanged.
- Tests: focused Hermes contracts, CI-default DB-free suite, compile/import,
  migration transaction, secret scan, and regression suite.

## 0.12.0 — 2026-08-21

### Hermes paper operations and voice

- Added deterministic, account-owned `/hermes` commands to start a saved
  candidate in paper mode and pause, resume, or stop its durable job.
- Added daily report opt-in stored on the owned paper job; recipients resolve
  from the authenticated user's login email instead of the global `TO_EMAIL`.
- Added durable controls and responsive worker polling. Explicitly continuous
  paper jobs requeue after worker restarts; finite jobs retain fail-safe recovery.
- Added an authenticated Hermes command tool to voice mode and changed voice
  position lookup to use the logged-in user's linked Alpaca paper account.
- Live-order routes remain unavailable.

### Tests and deployment

- Added command-intent, ownership, paper-control, report, worker-recovery, and
  voice-tool contracts.
- Apply `sql/20_hermes_paper_controls.sql`, then redeploy the full Compose
  resource so both `agui` and `hermes-jobs` use version 0.12.0.

## 0.11.0 — 2026-08-20

### Durable asynchronous Hermes jobs

- Changed scoped Hermes backtests and paper sessions from blocking HTTP calls
  to PostgreSQL-backed jobs that immediately return `job_id` and `run_id`.
- Added a deterministic `/hermes ... backtest` dispatcher in the AlpaTrade web
  tier, so queue creation occurs before remote model planning or terminal tools.
- Added an isolated AlpaTrade `hermes-jobs` worker, owned job status endpoints,
  candidate creation on successful backtests, and completion/failure messages
  written into the originating saved chat.
- Added five-second chat synchronization so results appear while a chat remains
  open; users may navigate away, close the browser, or inspect jobs later.
- Interrupted backtests are safely requeued. Interrupted paper sessions are
  failed rather than replayed, preventing duplicate paper orders.
- Removed every documented fallback to general backtest, paper, authentication,
  or generated test-user routes. Live trading remains unavailable.

### Tests and deployment

- Added DB-free contracts for delegated ownership, queue submission, worker
  attribution, candidate output, recovery policy, and service isolation.
- Apply `sql/19_hermes_jobs.sql` before redeploying the complete Compose resource.

## 0.10.0 — 2026-08-20

### Hermes Agent integration — Phase 2

- Added a dedicated Hermes broker with short-lived, per-user delegation and no
  database, Alpaca, JWT, or general service credentials in the Hermes service.
- Added user-owned backtest execution, best-parameter candidate persistence,
  run inspection, and candidate-to-paper promotion under `/v2/hermes/*`.
- Added `agent_name` and `agent_framework` attribution plus the
  `alpatrade.strategy_candidates` store. Live execution remains unavailable.
- Persisted `/app` conversations per account with sidebar resume/delete, and
  added visible elapsed-time/tool progress for long Hermes operations.
- Removed duplicated browser history from persistent Hermes sessions, extended
  per-message delegation to 30 minutes, and disabled non-renderable gateway
  approval prompts inside the credential-isolated Hermes container.

### Tests and deployment

- Added security-contract coverage for delegation signing, key separation,
  Compose credential isolation, schema-qualified migration objects, owned chat
  history, and long-running progress behavior.
- Apply `sql/18_hermes_agent_attribution.sql` before redeploying, then enable
  only **Terminal & Processes** with `hermes setup tools` for the mounted skill.

## 0.9.0 — 2026-08-20

### Hermes Agent integration — Phase 1

- Replaced the Hermes-as-LangGraph placeholder with an authenticated client for
  Nous Hermes Agent's OpenAI-compatible gateway, including SSE streaming and
  stable per-user and per-thread memory scopes.
- Added one-message `/hermes`, `/deepagents`, and `/langgraph` chat overrides;
  unprefixed messages continue using the user's saved framework.
- Added a private, persistent Hermes service to the Coolify Compose topology and
  retained DeepAgents as the automatic fallback when Hermes is unavailable.

### Tests and deployment

- Added DB-free tests for Hermes request construction, authentication, remote
  invocation, and runtime-prefix routing, and included them in CI.
- No database migration is required. Coolify requires `HERMES_API_SERVER_KEY`,
  one supported Hermes model-provider credential (including XAI/Grok), and
  one-time profile setup.

## 0.8.3 — 2026-08-15

### Developer and agent documentation

- Replaced raw-JSON-first links on the Developers page with an inline catalogue
  of all callable agents, including their skills, endpoint, execution model,
  access requirement, and paper/read-only safety boundary.
- Added browser-aware navigation so direct visits to the agent catalogue and
  OpenAPI JSON open the formatted ReDoc reference, while API clients continue
  to receive the canonical machine-readable JSON contracts.
- Enriched OpenAPI operations with agent skills and vendor metadata, grouped
  ReDoc navigation, deep links, and an interactive Swagger configuration suited
  to service integrations.

### Tests and deployment

- Added DB-free coverage for agent skill metadata, ReDoc grouping, browser/API
  content negotiation, and developer-page catalogue content.
- No database migration or configuration change is required.

## 0.8.2 — 2026-08-15

### New Chat news pane

- Opened the News pane by default on New Chat and restored it whenever the New
  Chat action resets an existing conversation.
- Replaced the close icon with directional controls: `>` minimizes the open
  News pane and `< News` maximizes it again.
- Added accessible control labels and synchronized expanded state.

### Tests and deployment

- Added DB-free coverage for the default-open state, New Chat reset behavior,
  directional controls, and their accessibility attributes.
- No database migration or configuration change is required.

## 0.8.1 — 2026-08-15

### Web layout

- Added a shared, constrained scrolling viewport to every application route so
  long tool, research, monitoring, and public-market pages remain scrollable on
  desktop and mobile while the sidebar and chat composer stay fixed.
- Kept wide tables and data views horizontally accessible on narrow screens
  without introducing document-level overflow.
- Preserved the chat and guide views' internal scrolling within the new shared
  center-column container.

### Tests and deployment

- Added DB-free regression coverage for the shared page viewport and verified
  route scrolling locally in Chromium at desktop and mobile viewport sizes.
- No database migration or configuration change is required.

## 0.8.0 — 2026-08-15

### External API and agent access

- Added a public agent catalog plus typed JSON invocation endpoints for the primary
  LangChain DeepAgent, Premarket Agent, Growth and Value research agents, their
  combined view, and the paper-only autonomy scout.
- Documented the existing Backtest, Validation, Paper Trade, Reconciliation,
  Report, and Orchestrator endpoints as canonical external agent interfaces.
- Added API discovery at `/`, production server metadata, explicit Swagger UI,
  ReDoc, and OpenAPI routes, stable package-version metadata, and request IDs.

### Security and developer experience

- Replaced spoofable standalone `X-User-Id` trust with JWT, configured service API
  keys, or a short-lived signed internal identity; tenant data and actions now
  require a concrete user identity.
- Restricted browser CORS to configured AlpaTrade origins and made direct order
  placement use only the authenticated user's linked Alpaca paper account.
- Added a public `/developers` page and homepage/footer navigation to Swagger,
  ReDoc, the live OpenAPI JSON contract, and the machine-readable agent catalog.

### Tests and deployment

- Added DB-free API discovery, authentication-boundary, request-ID, agent-catalog,
  and developer-navigation regression coverage.
- No database migration is required. Configure `API_SERVICE_KEY` or
  `API_SERVICE_KEYS` before onboarding trusted service clients.

## 0.7.0 — 2026-08-15

### DeepAgents and autonomy

- Made LangChain DeepAgents the primary chat and reasoning harness while retaining
  the existing LangGraph-compatible streaming interface and compatibility alias.
- Added a safe runtime fallback chain from DeepAgents to LangGraph and Hermes.
- Added best-effort LLM annotations to autonomy scouting, backtest selection, and
  refit decisions without changing deterministic paper-trading risk gates.

### Interface

- Improved authentication form accessibility with associated labels, browser
  autofill metadata, and announced success/error notices.
- Updated the Settings framework selector and architecture documentation to show
  DeepAgents as the default.

### Tests and deployment

- Added DB-free runtime-default, subagent construction, scout, backtest, refit,
  and authentication accessibility coverage to the CI unit suite.
- Verified syntax compilation, 101 DB-free tests, and the secret scan. No database
  migration is required for this release.

## 0.6.0 — 2026-08-06

### Alpha Research

- Added a collapsed Alpha Research sidebar section with editable Growth Agent
  and Value Agent commands, plus a compact Combined View.
- Ported the concise Growth and Value methodology themes from Alpha Agents into
  an in-process, read-only AlpaTrade runner using existing company, financial,
  valuation, analyst, news, and per-user model providers.
- Added `alpha:runs` for user-scoped saved-report history and deterministic
  evidence fallback when model synthesis is unavailable.
- Added `alpha:compare` to collect evidence once, run compact Growth and Value
  synthesis concurrently, and save both perspectives as ordinary research runs.
- Added `alpha:show run-id:<uuid>` and a Saved Reports sidebar group so users
  can reopen user-scoped stored reports without new data or model calls.

### Persistence and deployment

- Added idempotent migration `sql/17_alpha_research_runs.sql` for user-scoped
  completed, partial, and failed research reports.
- Apply `python run_migration.py sql/17_alpha_research_runs.sql` before deployment.
  Reports still return with a visible not-saved warning when persistence is not
  configured or the migration has not been applied.

### Tests

- Added DB-free coverage for sidebar commands, routing, ticker validation,
  methodology prompts, evidence fallback, persistence lifecycle, and user-scoped
  recent-run queries.

## 0.5.2 — 2026-07-29

### Authentication navigation

- Restored `/` as the public landing page regardless of existing session state.
- Successful password, registration, and Google login flows now redirect directly
  to `/dashboard`; ordinary visits to the root no longer do so.
- Added a visible sign-out action to the dashboard header and styled the existing
  authenticated-sidebar sign-out link.

## 0.5.1 — 2026-07-28

### Market data providers

- Removed the retired Polygon/Massive implementation, credentials, endpoints,
  configuration choices, news fallback, documentation, and legacy imports.
- Yahoo Finance is now the default market-data provider and requires no key.
- Alpaca market data is an optional provider using the existing Alpaca account
  credentials; stale or unknown provider values fall back safely to Yahoo.
- Updated validation, paper trading, backtesting, research, regime detection,
  CLI completion, and Docker Compose services to use the shared provider adapter.

### Tests

- Added provider default/fallback coverage and updated the market-data feed tests.
- Twenty focused tests and syntax compilation passed. The broad regression retains
  its four environment `pytz` errors and two pre-existing autonomy threshold failures.

## 0.5.0 — 2026-07-28

### Portfolio dashboard

- Made an authenticated, account-scoped Portfolio P&L dashboard the default
  post-login home page.
- Added current calendar day, week, and month views using Alpaca portfolio
  history, with equity, return, cash, buying power, unrealized P&L, and Plotly
  equity/contributor charts.
- Added paper and backtest strategy leaderboards and cached, fact-grounded AI
  commentary routed through each user's configured model provider.
- Added an all-accounts view, automatic selection of a funded account, support
  for read-only paper and live Alpaca credentials, and connect-account onboarding.
- Corrected backtest account scoping to join through its owning run, retaining
  compatibility with databases where `backtest_summaries` has no `account_id`.

### Tests

- Added DB-free tests for calendar bounds, account isolation, funded-account
  selection, aggregation, and onboarding.
- Expanded Playwright coverage to assert real dashboard Plotly charts at
  desktop, tablet, and mobile widths.

## 0.4.1 — 2026-07-28

### Fixed

- Fixed streamed Plotly charts being removed when the final SSE `done` event
  rewrote the already-rendered chat bubble.
- Added an authenticated local Playwright regression that submits “Show me a
  market map” and requires real Plotly and treemap SVG nodes with no page errors.

## 0.4.0 — 2026-07-28

### Research workspace

- Migrated Finespresso research into five FastHTML submenu pages: Premarket,
  Model Analytics, News Intelligence, News Timing, and Historical Research.
- Reads the existing database through explicitly schema-qualified `public.*`
  relations; scheduler-owned premarket refreshes remain outside AlpaTrade.
- Added real Plotly sector breadth, prediction scatter, event-by-industry
  correlation heatmap, publication timing, and stored classifier/regressor metrics.
- Added `analyze_prediction_correlation` to streaming chat. The active user's
  configured AlpaTrade model interprets deterministic research results.
- Preserved historical Finespresso event aliases in a shared normalization module.

### Tests and deployment

- Added Research data, navigation, chart-transport and schema-boundary tests.
- Added Research-agent routing and LLM-judge eval cases.
- Playwright-smoked every Research route at desktop and mobile widths.
- No database migration is required. The Finespresso scheduler remains responsible
  for updating the shared public premarket tables.

## 0.3.0 — 2026-07-28

### Added

- A complete FastHTML port of the Finespresso premarket screener: 165 sector
  memberships across 11 US sectors, prior-close versus premarket OHLC moves,
  ranked gainers/fallers, sector breadth, mover detail, catalysts, and sources.
- The read-only Premarket Agent and `get_premarket_movers` chat tool, with
  persisted-scan and explicit fresh-scan modes.
- PostgreSQL migration `16_premarket_scans.sql`, with compatible local JSON
  fallback for environments where the migration has not yet been applied.
- Categorized premarket catalysts in the shared right-hand news pane.
- Agent-routing and LLM-judge eval coverage for premarket requests, plus
  desktop/mobile Playwright smoke coverage and DB-free regression tests.

### Changed

- Premarket market-data acquisition is batched rather than issuing sequential
  requests for every symbol.
- Expanded the agent eval corpus to 102 cases with tool-trajectory validation,
  per-category filtering, PASS/FAIL routing results, and UI eval reporting.
- Fixed inline chart tools such as `show_market_map` by preserving chart
  markers returned from tool events through the FastHTML SSE stream.

### Tests

- 59 DB-free CI tests passed.
- Premarket Playwright smoke passed on desktop and mobile, including catalyst
  detail and categorized-news rendering with no browser console errors.
- The broad regression suite passed 99 tests; two pre-existing autonomy
  promotion-threshold assertions remain failing and are unrelated to this port.
- Syntax compilation and secret scanning passed.

### Deploy Notes

- Apply `python run_migration.py sql/16_premarket_scans.sql` before deployment
  to enable PostgreSQL scan history. Without it, the feature safely uses JSON
  reports in `PREMARKET_REPORTS_DIR` (default `data/premarket`).
- A fresh scan is read-only and never places orders.

## 0.2.1 — 2026-07-27

### Added

- Alpaca paper-trading tools for discovering and ordering Cboe index options
  on SPX, SPXW, VIX, VIXW, DJX, and XSP.
- Paper-only execution validation, whole-contract sizing, European-style and
  cash-settlement guidance, and expiration-risk controls.
- A dedicated **Public Markets → Index Options** hub with supported products,
  strategy templates, contract-discovery prompts, and safe chat handoffs.
- An index-options agent skill, focused broker tests, strategy documentation,
  and example conversations.
- Repository contributor guidance in `AGENTS.md`.

### Changed

- Corrected legacy AssetHero package metadata, URLs, installer copy, API naming,
  and console entry points to the canonical AlpaTrade identity.
- Rebuilt IPO Map and IPO Pipeline to follow LiquidRound more closely,
  including filters, KPIs, treemap and performance charts, performer tables,
  valuation bars, private-company cards, and upcoming/completed IPO tables.
- Added a dedicated Public Markets sidebar section.
- Made top-level sidebar sections collapsed by default with `>` expand and
  `<` collapse controls.
- Fixed sidebar command navigation from `/guide` by preserving the selected
  prompt and routing it into `/app`.

### CI/CD

- CI now installs all application extras and explicitly installs pytest.
- Added unconditional index-options and UI-navigation tests.
- Fixed credential-free application import smoke tests with a non-secret
  placeholder model key.
- Verified seven focused tests, syntax compilation, import smoke tests, secret
  scanning, GitHub Actions CI, and the Coolify deployment trigger.

### Release Notes

- All trading paths added in this release are restricted to Alpaca paper
  accounts.
- Alpaca does not yet provide underlying index market data; external licensed
  data is still required for index levels, signals, quotes, and Greeks.
