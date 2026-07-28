# Autonomous Agent Improvement Plan

Goal: **maximise PnL** of the autonomous paper-trading pipeline, add volatility
and market-regime parameters, and make the agent framework (LangGraph / deepagents /
hermes) switchable on the fly. This doc tracks the plan and what each iteration
shipped. Sourced from a critical review of the orchestrator, autonomy engine,
runtime layer, strategies, and backtester (see "Review findings" at the bottom).

## Iteration log

### Phase 1a — PnL-maximising objective function (DONE)

**What changed**
- New `engine/objective.py`: `ObjectiveWeights` + `score_variation()` +
  `rank_variations()` + `select_best()`. Pure functions, no I/O.
- Score = `annualized_return − λ_drawdown·max_drawdown − λ_vol·downside_vol_penalty`
  with a hard `min_trades` gate (default 20) that disqualifies fluke/overfit
  variations. `error`/`no_price_data` rows are excluded.
- `BacktestAgent.run` (`agents/backtest_agent.py`) now selects best by the
  composite objective instead of `max(results, key=sharpe_ratio)`. The
  `all_results_summary` now includes `annualized_return`, `max_drawdown`, and
  `score` (previously drawdown was computed then dropped from the summary).
- Objective weights are configurable per-run via `request["objective"]`.
- New DB-free tests: `tests/test_objective.py` (8 cases covering the gate,
  drawdown penalty, vol penalty, fallback, and config parsing).

**Why** — the old `max-Sharpe` selector had no drawdown penalty, no min-trade
filter, and dropped drawdown from the summary. A 1-trade fluke could beat a
500-trade robust strategy. This directly enforces the "maximise PnL" goal with
a real risk deterrent.

**Verified** — `python -m pytest tests/test_objective.py tests/test_index_options.py
tests/test_ui_navigation.py -q` → 15 passed.

### Phase 1d — Turn autonomy on in prod (DONE)

**What changed**
- `docker-compose.yaml`: removed `profiles: ["autonomy"]` from the `autonomy`
  service and flipped `AUTONOMY_ENABLED` default to `true`. The worker now
  starts with `docker compose up` (and therefore with Coolify's default deploy).
- `engine/autonomy/worker.py` docstring updated to reflect the new default.

**Why** — the autonomy loop (self-feeding scout → backtest → policy gate →
validate → paper trade → reconcile → promote) was dormant in prod. Only the
nightly PnL email thread was running. Turning it on unblocks the feedback loop
(Phase 1b) and lets the pipeline actually trade while backtests run.

**Safety** — still paper-only. `engine/autonomy/policy.py` hard-rejects any
`is_live=True` candidate (`RiskLimits.allow_live=False`). To stop: set
`AUTONOMY_ENABLED=false` or scale the service to 0 in Coolify.

### Phase 1b — Closed-loop feedback (refit node) (DONE)

**What changed**
- New `engine/autonomy/refit.py`: pure functions — `paper_sharpe()`,
  `detect_drift()`, `refine_grid()`, `refit_plan()`. No I/O, fully unit-tested.
- Drift signal: if `paper_sharpe < backtest_sharpe × 0.5`, the regime has
  shifted → narrow the next grid around the top-K backtest variations ± a 20%
  perturbation band. Integer params (hold_days) perturb ±1. Min 5 paper trades
  to trust the signal (avoid noise).
- New `refit` node added to `default_pipeline()` in `engine/autonomy/graph.py`,
  after `reconcile` and before `promote`. It reads paper trades via
  `gather_trades()` (reused from the daily report), runs `refit_plan()`, and
  threads the refined grid into `ctx["refined_grid"]`.
- The `backtest` node now merges `ctx["refined_grid"]` into the variations
  passed to `BacktestAgent`, so the next scout tick uses the narrowed search.
- 8 new DB-free tests in `tests/test_refit.py`.

**Why** — the pipeline was open-loop: each autonomy tick re-ran the identical
static 18-row grid regardless of paper outcomes. Now paper losses refit the
search around what worked in backtest, turning the controller into a closed
loop. This is the highest system-level leverage for adapting to regime drift.

**Verified** — `python -m pytest tests/test_refit.py tests/test_objective.py
tests/test_index_options.py tests/test_ui_navigation.py -q` → 23 passed.

### Phase 1c — Fix `run_full` + configurable validation gate (DONE)

**What changed**
- `Orchestrator.run_full` (`agents/orchestrator.py`) now runs the full
  BT → Validate → PT → Validate → **Reconcile → Report** sequence
  (previously skipped reconcile + report, contradicting AGENTS.md).
- Added a `report` phase that calls `ReportAgent().summary()` and surfaces
  recent runs in the result (non-fatal on error).
- Validation failures are now configurable via `config["validation_gate"]`:
  - `"warn"` (default, back-compat): log and continue.
  - `"strict"`: halt the run on a failed validation so a broken backtest or
    paper session never flows to the next phase.

**Why** — `run_full` was incomplete (missing reconcile + report) and validation
was advisory-only. A broken backtest would silently flow to paper trading.
Strict mode gives the autonomy pipeline a real quality gate.

**Verified** — compile + 23 tests pass.

### Phase 2a — Regime classifier (DONE)

**What changed**
- New `engine/regime.py` (provider-neutral, per AGENTS.md convention):
  `classify_regime(date) -> RegimeLabel` with a 3-state label
  `{low_vol, normal, high_vol}` × trend `{bull, chop, bear}`.
- Three signals: realised vol (21d annualised, percentile vs 63d window),
  VIX level (yfinance `^VIX`), SMA200 trend. Rule-based — no HMM dep;
  an HMM can later replace internals behind the same interface.
- Per-process LRU cache (`classify_regime_cached` / `current_regime`).
- `REGIME_PARAMS` preset grids per regime for `buy_the_dip` — wider dip
  thresholds, bigger TPs, smaller position sizes in high_vol; tighter in
  low_vol. `regime_variations(strategy, state)` returns the grid.
- Graceful degradation: on any data failure returns `normal/chop` so
  callers never crash.
- 11 DB-free tests in `tests/test_regime.py` (vol percentile, trend,
  presets, label string).

**Why** — the repo had zero regime classification. The only "regime" function
was `is_bullish_regime = close > SMA200` in a strategy not wired into the
orchestrator. This gives every downstream phase (2b grid, 2d sizing, Phase 4
walk-forward/promotion) a single classification entry point.

**Verified** — `python -m pytest tests/test_regime.py -q` → 11 passed.

### Phase 2b + 2c — Regime-conditional grid + adaptive search (DONE)

**What changed**
- `BacktestAgent.run` now resolves variations with the precedence:
  explicit `request["variations"]` → `request["regime"]` preset from
  `engine.regime.regime_variations()` → static `DEFAULT_VARIATIONS`.
  So when the autonomy pipeline sets `regime="high_vol"`, the agent
  sweeps wider dip thresholds / bigger TPs / smaller sizes automatically.
- New `_run_adaptive_buy_the_dip()` method: random-search + elite
  refinement against the Phase-1 composite objective. Samples from the
  ranges implied by the seed (or regime) variations, scores each with
  `score_variation()`, then refines around the top-K elite. No new deps
  (stdlib `random`, seeded for determinism). Activated via
  `request["adaptive"]=True` + optional `adaptive_iterations` (default 40).
- The autonomy `backtest` node (`engine/autonomy/graph.py`) now calls
  `current_regime()` and threads the regime state into the backtest
  request — so the pipeline automatically uses regime-aware grids.
- Falls back to the static grid if the adaptive path errors.

**Why** — the grid was static (18 rows) regardless of market conditions,
and there was no adaptive refinement. Now the search space is
regime-conditional (tighter in calm markets, wider + more conservative
sizing in high-vol) and the adaptive path scales to the larger
regime-conditional parameter space without running 1000s of variations.

**Verified** — compile + 34 tests pass.

### Phase 2d — Vol-scaled sizing + ATR exits (DONE)

**What changed**
- `utils/buy_the_dip.py`: two new optional params on
  `backtest_buy_the_dip()`:
  - `vol_target` (annualised, e.g. 0.12): scales position size ∝
    `vol_target / realised_vol` (capped at `position_size`). Replaces
    fixed-fraction sizing when set. None = back-compat fixed fraction.
  - `atr_exit_mult` (e.g. 1.5 or 2.0): computes TP/SL as ATR multiples
    (`entry ± atr_exit_mult × ATR`) instead of fixed percentages. Falls
    back to fixed-% when ATR is unavailable. None = back-compat fixed %.
- New helpers `_atr()` and `_realised_vol_annualised()` in
  `buy_the_dip.py` (revives the ATR concept that was dead code in
  `box_wedge.py:40-46`).
- `BacktestAgent` threads `vol_target` / `atr_exit_mult` from the request
  or regime preset into both the static grid and adaptive search paths.
- The `high_vol` regime preset now sets `vol_target=0.12` and
  `atr_exit_mult=2.0` — so high-vol regimes automatically vol-scale
  sizing and use ATR-based exits.
- 7 DB-free tests in `tests/test_vol_sizing.py` (ATR, realised vol,
  regime preset wiring).

**Why** — position sizing was fixed-fraction everywhere and TP/SL were
fixed percentages, regardless of volatility. Now in high-vol regimes the
system sizes inversely to realised vol (smaller positions when vol spikes)
and sets exits relative to actual range (ATR), which is the standard
risk-aware approach. This directly implements the "volatility dimensions
as parameters" the user asked for.

**Verified** — `python -m pytest tests/test_vol_sizing.py tests/test_regime.py
tests/test_objective.py tests/test_refit.py tests/test_index_options.py
tests/test_ui_navigation.py -q` → 41 passed. Adaptive backtest with
`regime=normal` ran 12 variations and selected best by composite score
(ann_ret 9.8%, max_dd 0.22%, 62 trades).

### Phase 3a — Route autonomy nodes through the runtime layer (DONE)

**What changed**
- New `engine/autonomy/reason.py`: `reason(prompt)` builds a one-shot
  agent from the configured runtime (LangGraph / deepagents / hermes /
  pydantic-ai) via `get_runtime()` and returns the text. Best-effort:
  returns `""` on any failure so nodes fall back to the deterministic path.
- Module-level cache rebuilds when `agent_framework` changes, so a
  settings swap is picked up on the next call (no restart).
- The `promote` node in `default_pipeline()` now calls `reason()` to get
  an LLM-annotated recommendation on which strategies are most robust,
  while the deterministic `PromotionBar` (`promote.py`) stays as the hard
  gate — the LLM never decides alone; `allow_live=False` is never bypassed.

**Why** — the pipeline nodes called the legacy `Orchestrator`/`ReportAgent`
directly, bypassing the runtime abstraction. Now deepagents' planning +
subagents can drive the promotion reasoning, and the framework swap is
real (not just for the chat agent).

### Phase 3b — Hot-swap framework without restart (DONE)

**What changed**
- `agui_app.py`: the per-user agent cache key now includes
  `agent_framework` (was `(provider, model)` only). `get_runtime()` is
  called per cache miss instead of reusing the import-time `chat_runtime`,
  so changing `agent_framework` in the UI takes effect on the next message.
- New `clear_agent_cache()` in `agui_app.py` and `clear_reasoning_cache()`
  in `engine/autonomy/reason.py`.
- `ph_settings.py` POST `/settings/preferences` now calls both cache
  evictions on save, so a framework/model change is live immediately —
  no process restart.
- Settings UI labels updated: hermes → "hermes (LangGraph + notifier)",
  deepagents → "deepagents (planning + subagents)" (was "coming soon").

**Why** — changing `agent_framework` previously required a process restart
because `chat_runtime` was bound at import and the cache key excluded the
framework. Now the user's choice is live on the next message/reasoning call.

**Verified** — compile + 41 tests pass.

### Phase 3c — CLI per-command framework/model (DONE)

**What changed**
- `tui/command_processor.py`: parses `framework:` and `model:` from CLI
  input (e.g. `show me AAPL analysis framework:deepagents model:grok-4-fast`).
  The override is stripped from the prompt and applied via a temporary env
  override (`_env_override` context manager) for that call only — no
  permanent .env change, no restart. Falls back to the configured default
  when not specified.
- New `_extract_framework_model()` helper + `_env_override()` context
  manager (both unit-tested inline).

**Why** — the CLI was fixed to `.env`/defaults with no per-command switch.
Now a user can test deepagents vs LangGraph or a different model on a single
query without restarting or editing `.env`.

### Phase 3d — Hermes documented honestly (DONE)

**What changed**
- `engine/agents/runtime/hermes_rt.py` docstring updated: clearly states
  it's "LangGraph reasoning + Hermes channel notifier", not a separate
  pipeline engine. Documents that selecting `AGENT_FRAMEWORK=hermes` gives
  identical reasoning to `langgraph` plus the `notify()` side-channel, and
  that `reason()` and the `promote` node use it when configured.
- Settings UI labels already fixed in Phase 3b ("hermes (LangGraph +
  notifier)", "deepagents (planning + subagents)").

**Why** — hermes was labelled "coming soon" but it actually works (as a
LangGraph pass-through + notifier). The honest framing prevents confusion.

### Phase 3e — REST settings endpoint (DONE)

**What changed**
- New `GET /api/v1/settings` and `PATCH /api/v1/settings` in `api.py`
  (the unified REST entry). GET returns the caller's effective settings
  (per-user merged over env). PATCH writes per-user overrides for any of
  `model_provider`, `model_name`, `market_data_provider`, `search_provider`,
  `agent_framework` (only non-null fields are written). Both require JWT
  auth via `api_app.get_current_user`.
- PATCH evicts the agent + reasoning caches (same as the web UI's
  `/settings/preferences`), so the change is live for the next request —
  no restart.

**Why** — previously only the FastHTML web UI could change settings; the
REST API had no settings endpoint. Now programmatic/CLI consumers can
switch framework/model on the fly via `PATCH /api/v1/settings`.

**Verified** — compile + 41 tests pass.

---

## Remaining plan

### Phase 1b — Feedback loop (next)

Add a `refit` node to `engine/autonomy/graph.py` after `paper_trade`:
- reads paper-trade PnL from `alpatrade.trades` (reuses `gather_trades()`),
- if paper Sharpe < backtest Sharpe × 0.5 (regime drift), narrows the next
  grid around the top-K backtest variations ± a perturbation band,
- writes the refined grid centre to `autonomy_runs.config` so the next scout
  tick uses it.
Turns the open-loop into a closed-loop controller. No new table needed.

### Phase 1c — Fix `run_full` + gate on validation

- Add `run_reconciliation` + report to `Orchestrator.run_full` (currently
  BT→Val→PT→Val, skipping reconcile/report).
- Make validation failures configurable (hard-stop vs warn) so a broken
  backtest doesn't flow to paper.

### Phase 2a — Regime classifier

New `engine/regime.py` (provider-neutral): realised-vol percentile (21d/63d)
+ VIX level + SMA200 trend → 3-state label `{low_vol, normal, high_vol}`.
Rule-based first (no HMM dep); HMM can come later behind the same interface.
Single entry: `classify_regime(date) -> RegimeLabel`, cached per-day.

### Phase 2b + 2c — Regime-conditional params + adaptive grid

- Extend the grid to sweep per-regime params (wider dip thresholds and TP in
  high-vol, tighter in low-vol; `vol_scale_position: true` for vol-targeting;
  `atr_exit` multiples as an alternative to fixed-% TP/SL).
- Replace `itertools.product` with Bayesian optimisation (optuna, optional
  dep) against the Phase-1 objective, with regime as a categorical dimension.
  Falls back to the static grid if optuna is absent.

### Phase 2d — Vol-scaled sizing + ATR exits

- In `buy_the_dip.py` / `paper_trade_agent.py`: `size ∝ vol_target /
  realised_vol` (capped at the existing 5%-of-buying-power PDT guard).
- Wire the ATR already computed in `box_wedge.py:40-46` (currently dead code)
  into TP/SL as `atr_mult` multiples. Revives dead code + vol-aware exits.

### Phase 3a — Route autonomy nodes through the runtime layer

`graph.py` calls the legacy `Orchestrator` directly. Introduce a
`ReasoningNode` that takes a `RoleSpec` and calls `get_runtime().build()` /
`.run()` so the backtest-selection reasoning can use deepagents' planning +
subagents. Keep `policy.py` as a pure-function guard after reasoning — never
let the LLM bypass `allow_live=False`.

### Phase 3b — Hot-swap framework without restart

- Include `agent_framework` in the agui_app agent cache key (`agui_app.py:867`).
- Call `get_runtime()` per cache miss instead of reusing the import-time
  `chat_runtime`.
- Add cache eviction on `/settings/preferences` save.
- Then langgraph→deepagents in the UI takes effect on the next message.

### Phase 3c — CLI per-command framework

Add `framework:` / `model:` parsing to `command_processor.py` (mirrors the
existing `provider:` news param). Resolves via `get_settings()` with an inline
override.

### Phase 3d — Define hermes honestly

Document hermes as "LangGraph + notifier" and remove the "coming soon" framing
(it already works as a pass-through), OR build a true `HermesPipelineRuntime`
if there's a real Hermes endpoint. Recommend the former now.

### Phase 3e — REST settings endpoint

Add `PATCH /api/v1/settings` to `api.py` calling `store_user_settings` —
currently only the web UI can change framework/model.

### Phase 4 — Optimisation dimensions & guardrails (ongoing)

- Sortino + Calmar in `backtester_util.py:51` alongside Sharpe; expose all
  three in the objective λ-mix.
- Walk-forward by regime, not just calendar (`scripts/walk_forward_btd.py`).
- Vol-dependent friction in `engine/backtest/runner.py:126` (slippage ∝ vol).
- Raise `PromotionBar.min_sharpe` to match the Phase-1 objective; add
  `min_regime_coverage` so a bull-only strategy can't promote.
- Wire `box_wedge` into `backtest_agent.py:103-134` (its R-based scale-out +
  ATR are the most vol-aware logic in the repo and are unreachable).

---

## Review findings (what the critical review found, summarised)

**No PnL objective.** Only `max(sharpe_ratio)` over a static 18-row grid
(`backtest_agent.py:139`). No drawdown penalty, no min-trade filter, no
Sortino/Calmar. Drawdown was computed then dropped from the summary.

**Open-loop.** `best_config` flows one-way (backtest → paper), never refit
from paper outcomes. Each autonomy tick re-runs the identical static grid.

**Zero vol/regime awareness in the control path.** No regime classifier. ATR
computed in `box_wedge.py:40-46` but never read. The only regime function
(`is_bullish_regime = close > SMA200`) is in a strategy not wired into the
orchestrator dispatch. Position sizing is fixed-fraction everywhere.

**Framework switching half-built.** `agent_framework` is per-user in
`user_settings` and UI-selectable, but: agui_app caches at import (framework
excluded from the cache key → needs restart); CLI is .env-only; REST API has
no settings endpoint; the autonomy worker doesn't read `agent_framework` at
all. Hermes is a LangGraph pass-through + notifier, not a pipeline engine.

**Autonomy off in prod.** `docker-compose.yaml` put the worker behind
`profiles:["autonomy"]` with `AUTONOMY_ENABLED=false`. Only the nightly email
ran.

**Static, tiny grid.** 18 combinations for buy_the_dip; momentum/vix run a
single config each; box_wedge runs zero via the agent. No adaptive refinement.

**`run_full` incomplete.** BT→Val→PT→Val, skipping reconcile + report,
contradicting AGENTS.md. Validation failures advisory only.
