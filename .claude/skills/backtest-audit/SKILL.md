---
name: backtest-audit
description: Run the AlpaTrade backtest audit before reporting, publishing or acting on any backtest figure (return, CAGR, Sharpe, drawdown, win rate). Quote the audit status with the numbers; never publish a failing audit.
---

# Backtest audit

Any agent that reports backtest numbers must audit them first and quote the result.

## Run it

```bash
python scripts/audit_backtest.py --strategy-id <leaderboard id>        # published entry
python scripts/audit_backtest.py --run-id <alpatrade.runs run_id>       # a stored backtest run
python scripts/audit_backtest.py --btd-live <strategy_configs name> \
    --start 2025-10-01 --end 2026-10-09 --slippage-bps 10               # fresh BTD run, live params
# --json for machine-readable output; --save stores the result on the leaderboard row
```

Exit code: `0` pass, `1` warn, `2` fail, `3` error.

## What it checks (utils/backtest_audit.py)

| check | fails when |
|---|---|
| engine_version | no engine/version stamp, or buy_the_dip older than b47e6de (v0.33.6) |
| reconciliation | sum of trade P&L != final equity - initial capital, or reported return != that |
| same_bar_exits | capital_after != initial + realised P&L when flat (same-bar double count) |
| cash | replayed cash < 0 without allowed margin |
| tp_sl_same_bar | a bar touching both target and stop booked as take-profit, or a target-first engine |
| costs | slippage or fees 0 / not recorded |
| params | labelled live but tested params != active strategy_configs (else label it research) |
| lookahead | signal after fill, exit before entry, fill on the signal bar under next-open |
| universe | (warn) universe chosen after the backtest start: survivorship bias |
| plausibility | annualised > 1000% or Sharpe > 8 (warn above 200% / 4 / zero DD with > 20 trades); an override needs a note |
| min_trades | < 10 trades (warn < 30) |
| oos_degradation | (warn) OOS keeps < 50% of the in-sample return |

## How to report

- **fail:** do not quote the figures as results. Say "backtest audit FAILED" and list the failing checks; fix the backtest or label it research.
- **warn:** quote the figures with "Audit: warnings" and the reasons.
- **pass:** quote the figures and say the audit passed.

Publishing paths (`scripts/cwt_pipeline.py publish`, `scripts/seed_semi7_backtest.py`) call `engine.leaderboard.audit_gate.gate()` and refuse failing audits automatically.
