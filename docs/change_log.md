# Change Log

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
