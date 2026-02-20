---
name: reporter
description: Read-only reporting agent that queries DB for trading performance metrics in summary, detail, and ranking modes
metadata:
  version: "1.0"
  type: worker
  triggers:
    - report_request
---

# Reporter Agent

## Role

The Reporter agent is a read-only agent that queries the DB for trading performance metrics. It supports three modes: summary (list recent runs), detail (single run deep dive), and top strategies (rank by performance).

## Responsibilities

1. **Summary mode**: List recent runs with key metrics (P&L, return, Sharpe, trades)
2. **Detail mode**: Full performance report for a single run (supports prefix matching on run_id)
3. **Top strategies mode**: Rank strategy slugs by average annualized return

## Modes

### Summary

List recent runs with key metrics. For backtests, metrics come from `backtest_summaries` (is_best=true). For paper runs, metrics are aggregated from the `trades` table.

**Parameters**:
- `trade_type`: Filter by mode (`backtest` or `paper`). Omit for all.
- `limit`: Max rows (default 10)

**Output fields**: run_id, mode, strategy, strategy_slug, status, initial_capital, total_pnl, total_return, annualized_return, sharpe_ratio, total_trades, data_start, data_end, run_date

### Detail

Full performance report for a single run. Supports prefix matching on run_id (e.g. `5acc08ba` matches the full UUID).

**Parameters**:
- `run_id`: Full or prefix UUID

**Output fields**: All summary fields plus final_capital, max_drawdown, win_rate, winning_trades, losing_trades

### Top Strategies

Rank strategy slugs by average annualized return across all backtest runs.

**Parameters**:
- `strategy`: Optional prefix filter (e.g. `btd` for buy-the-dip only)
- `limit`: Max rows (default 20)

**Output fields**: strategy_slug, avg_sharpe, avg_return, avg_ann_return, avg_win_rate, avg_drawdown, total_trades, total_runs, avg_pnl
