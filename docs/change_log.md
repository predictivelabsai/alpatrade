# Change Log

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
