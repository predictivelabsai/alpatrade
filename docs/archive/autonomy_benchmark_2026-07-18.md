# Autonomy agent-team — evidence benchmark (2026-07-18)

**Scope:** local only, paper-only. The system never places live orders; "promotion" is a
recommendation. A stage counts as reached **only with a verified artifact** (a DB run row,
a checkpoint step, a backtest-results folder, a paper fill, a reconciliation match) — not
because an agent said so. Absence of any one artifact is not success.

This doc is the honest end-to-end record. Update it (new dated file) each time the pipeline
is run against real data; **retract false positives explicitly** rather than editing them away.

## Stage matrix — 0 / 1 / 2

`2` = reliably autonomous with verified evidence · `1` = partial / needs attention · `0` = not
reached. Live promotion is **deliberately 0** (out of scope; human-only).

| Stage | Score | Evidence / first blocker |
|---|---|---|
| Scout (scan → candidates + portfolio state) | **2** | `scout.scan` returns ranked paper candidates; `portfolio_state` reads the live paper account (equity/open/gross). Agent-evals `scout` 2/2. |
| Risk gate (policy admit/size, paper-only wall) | **2** | `policy.evaluate` pure + replayed; agent-evals `risk_policy` 9/9; no-live-path test enforced. |
| Backtest (grid-search, stored run) | **1** | Pipeline node wired to `Orchestrator.run_backtest`; not yet exercised end-to-end **through the autonomy runner** in this benchmark (only via the existing `agent:backtest` path). First step to prove next. |
| Paper trade (execute admitted on paper) | **1** | Node wired to `Orchestrator.run_paper_trade` (paper account). Candidate→order sizing from the gate is not yet threaded into the order (uses the strategy's own config). |
| Reconcile (DB vs broker) | **1** | Node wired to `Orchestrator.run_reconciliation`; not yet run inside an autonomy run here. |
| Promote (paper→live candidate report) | **2** | `should_promote` pure + gated; agent-evals `promotion` 6/6; digest via Postmark/Hermes. Records candidates only — never trades. |
| Live promotion (execute) | **0** | Out of scope by design. Human action outside the system. |

**Total (excl. live): 9 / 12.**

## What is verified (artifacts exist)

- **Durable engine:** `autonomy_runs` / `autonomy_run_steps` (checkpoints) / `autonomy_events` /
  `autonomy_promotions` tables (`sql/15`). Queue claim/heartbeat/`requeue_unfinished` and
  checkpoint-resume proven by `TestAutonomyEngine` (a failed run resumes and skips completed nodes).
- **Risk policy:** 9 replayed states, all correct (sizing cap, gross-exposure headroom, max-positions,
  kill-switch, paper-only wall, non-positive/no-equity guards).
- **Promotion gate:** 6 cases (pass / at-bar / fail-trades / fail-sharpe / fail-return / fail-drawdown).
- **No-live wall:** source-scan test asserts nothing in `engine/autonomy/` touches a live broker.
- **Scout:** produces ≥1 paper candidate per strategy with correct sizing; dips for `btd`, gainers for `momentum`.

## First reliable blocker (what to prove next — Phase C→D)

1. **Run `default_pipeline` end-to-end against real data via the worker** and record the run_id +
   the `autonomy_run_steps` rows for each node — promote the Backtest/Paper/Reconcile rows from `1`→`2`.
2. **Thread the gate's `sized_notional` into the paper order** so the executed size is the risk-policy
   size, not the strategy default.
3. **Enable the `autonomy` compose service** (paper, `AUTONOMY_ENABLED=true`) on a non-prod host and
   capture a full self-fed cycle (scout → … → promote digest email).

## Reproduce

```
python evals/run_agent_evals.py          # risk_policy + promotion + scout   → agent-evals-*.csv
python tests/regression_suite.py         # incl. TestAutonomy* / TestPromotion / TestAgentRuntime
python -m engine.autonomy.worker         # AUTONOMY_ENABLED=true to actually run (paper)
```

## Retractions

_None yet._ (When a stage is later found to have been over-scored, record the superseded result here
with its date rather than deleting it.)
