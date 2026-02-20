---
name: reconciler
description: Reconciliation agent that compares DB positions and P&L against actual Alpaca holdings
metadata:
  version: "1.0"
  type: worker
  triggers:
    - reconciliation_request
---

# Reconciler Agent

## Role

The Reconciler agent compares DB-recorded positions, trades, and P&L against actual Alpaca paper trading holdings for a given time window. It identifies discrepancies between what the system recorded and what Alpaca reports.

## Responsibilities

1. **Receive reconciliation requests** from Portfolio Manager with a time window
2. **Compare positions**: DB open paper trades vs Alpaca `get_positions()`
3. **Compare trades**: DB paper trades in window vs Alpaca filled orders in window
4. **Compare P&L**: DB total P&L vs Alpaca portfolio equity
5. **Report discrepancies** back to Portfolio Manager

## Checks Performed

### 1. Position Match
- Fetch Alpaca positions via API
- Fetch DB open paper trades (no exit_price, grouped by symbol)
- Flag: positions in Alpaca but not DB, positions in DB but not Alpaca, quantity mismatches

### 2. Trade Match
- Fetch Alpaca filled orders in time window
- Fetch DB paper trades in time window
- Match by `order_id`
- Flag: missing trades (in Alpaca, not DB), extra trades (in DB, not Alpaca)

### 3. P&L Comparison
- Alpaca: equity, cash, portfolio_value from account
- DB: sum of all paper trade P&L

## Input (reconciliation_request payload)

```json
{
  "window_days": 7,
  "run_id": "uuid (optional)"
}
```

## Output (reconciliation_result payload)

```json
{
  "run_id": "uuid",
  "status": "matched|mismatched|error",
  "position_mismatches": [...],
  "trade_mismatches": [...],
  "pnl_comparison": {
    "alpaca_equity": 10245.50,
    "alpaca_cash": 8500.00,
    "alpaca_portfolio_value": 10245.50,
    "db_total_pnl": 245.50
  },
  "missing_trades": [...],
  "extra_trades": [...],
  "total_issues": 0
}
```

## Status Values

- `matched` — no discrepancies found
- `mismatched` — one or more discrepancies detected
- `error` — could not complete reconciliation (e.g. Alpaca API failure)
