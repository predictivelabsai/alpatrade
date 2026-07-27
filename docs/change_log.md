# Change Log

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
