# Autonomy agent-team — evidence benchmark (2026-07-20)

Supersedes `autonomy_benchmark_2026-07-18.md`. That doc honestly scored Backtest / Paper /
Reconcile at **1** (wired but not yet run end-to-end via the runner). This run promotes them
to **2** on verified evidence: a full `default_pipeline` execution reached a terminal `done`
state with a real paper session.

**Scope:** local, paper-only. The system places no live orders; "promotion" is a
recommendation. A stage counts only with a verified artifact (DB run row, checkpoint step,
paper session id + trades, reconciliation record).

## Verified end-to-end run

`engine.autonomy.graph.run_once({"symbols":["TSLA","NVDA"],"lookback":"3m","paper_duration_seconds":12})`

| Artifact | Value |
|---|---|
| Autonomy run | `b32073d8-acd2-406e-93f8-465aba6906e2` — status **done**, all 7 steps `done` |
| Backtest run | `b58dca72-4e68-4aeb-b9db-281f1908ff2c` (best_config produced) |
| Validate | `6be2ceeb-…` — status **passed**, 0 anomalies |
| Paper session | `5ff7157e-b090-4da8-962c-6958d06dab53` — **5 trades executed** on the paper account |
| Reconcile | `e2f311c8-…` — status **mismatched**, 6 issues flagged (reconciler working as designed) |
| Promote | 0 candidates this cycle (none cleared the bar) |

Checkpoints (`alpatrade.autonomy_run_steps`): scout · backtest · policy_gate · validate_backtest ·
paper_trade · reconcile · promote — all `done`.

## Stage matrix — 0 / 1 / 2

| Stage | Score | Evidence |
|---|---|---|
| Scout | **2** | Ranked paper candidates (ISRG…) + live portfolio state; agent-evals scout 2/2. |
| Risk gate | **2** | `policy.evaluate` pure + replayed 9/9; admitted candidates threaded into the paper order. |
| Backtest | **2** | Ran against real bars; produced run `b58dca72` + best_config. |
| Validate | **2** | `passed`, 0 anomalies. |
| Paper trade | **2** | **Executed 5 paper trades** (session `5ff7157e`); size from the risk gate (`build_paper_config`). |
| Reconcile | **2** | Ran (`e2f311c8`), flagged 6 DB-vs-broker issues — the reconciler doing its job. |
| Promote | **2** | Pure gate ran; 0 candidates cleared the bar this cycle; agent-evals promotion 6/6. |
| Live promotion | **0** | Out of scope by design (human-only). |

**Total (excl. live): 14 / 14.**

## Bug found + fixed this run

- **`utils/pdt_tracker.py` `check_account_pdt_status`** crashed with `int(None)` when Alpaca
  returned `daytrade_count` present-but-`None`. Fixed to coerce (`… or 0`) for equity /
  pattern_day_trader / trading_blocked / daytrade_count. This was the sole blocker preventing the
  paper phase from executing. Regression: `TestPDTTracker.test_account_status_handles_none_fields`.

## Design decisions verified

- **Honest halt:** pipeline nodes raise on a phase `{"error": …}` result (run → `failed`, retried),
  rather than checkpointing a misleading `done`.
- **Graceful skip:** when the backtest yields no viable strategy, `paper_trade`/`validate` skip
  cleanly ("nothing to paper-trade") instead of crashing — correct autonomy behavior.
- **Risk-sized orders:** `build_paper_config` threads the gate's `sized_notional` → `capital_per_trade`
  and restricts symbols to admitted; session duration bounded (not the Orchestrator's 7-day default).

## Phase E — self-fed worker cycle (local, verified)

Ran the actual worker path (`AUTONOMY_ENABLED=true`, `AUTONOMY_PAPER_SECONDS=12`), not just
`run_once`:

- **Self-feed proven:** `scout.enqueue_run` created run `89892bb9-…`; `worker.run_one` **claimed
  it** (attempt 1, `claimed_by=local-worker`) and drove all 7 nodes to `done` → event `run complete`.
  **Paper phase executed 9 trades.**
- **Honest-halt + auto-requeue proven:** the first attempt hit a real bug (below); the `backtest`
  node **raised**, the run went `failed → requeued` (status back to `queued`, `claimed_by` cleared) —
  the retry mechanics work.
- **Bug found + fixed:** `scout.enqueue_run` put the strategy **slug** `btd` into the backtest config,
  but the grid-search wants the full name → "Unknown strategy: btd". Added `scout.strategy_name`
  (slug→name map: btd→buy_the_dip, mom→momentum, …). Test: `TestScoutStrategyName`.
- **Promotion digest:** 0 candidates cleared the bar this cycle (no email sent). The digest HTML the
  notifier emits is captured at `media/marketing/promotion_digest.html` (Postmark-sent to `TO_EMAIL`
  automatically when a candidate clears the bar).

Updated stage matrix is unchanged at **14/14 excl. live** — now also verified via the *worker*, not
only the synchronous entrypoint.

## First reliable blocker (next)

1. **Run via the `autonomy` worker/compose service** (not just `run_once`) with `AUTONOMY_ENABLED=true`
   on a non-prod host, and capture a full self-fed cycle incl. a promotion digest email.
2. **Reconcile "mismatched" (6 issues)** — investigate the DB-vs-broker drift the reconciler flagged
   (likely from repeated test paper trades); confirm it's benign or fix the drift source.
3. **Framework parity** — prove the pipeline is identical under `AGENT_FRAMEWORK=deepagents` once the
   lib is installed (currently falls back to langgraph).

## Reproduce

```
python -c "from engine.autonomy.graph import run_once; print(run_once({'symbols':['TSLA','NVDA'],'lookback':'3m','paper_duration_seconds':12}))"
python evals/run_agent_evals.py      # risk_policy + promotion + scout  → 17/17
python tests/regression_suite.py     # 98/98 incl. TestAutonomy*/Promotion/PaperSizing/AgentRuntime
```

## Retractions

_None._ (07-18 provisional 1s were honest "not-yet-run" scores, now superseded by verified 2s — not
false positives.)
