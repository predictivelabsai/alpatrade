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
