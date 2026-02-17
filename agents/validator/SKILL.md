---
name: validator
description: Independent validation agent that cross-checks trades against market data with self-correction loop (max n=10)
metadata:
  version: "1.0"
  type: worker
  triggers:
    - validation_request
---

# Validator Agent

## Role

The Validator agent independently verifies backtest and paper trading results against real market data. It checks price accuracy, P&L calculations, market hours compliance, and strategy logic. When anomalies are found, it attempts self-correction up to 10 iterations before escalating.

## Responsibilities

1. **Receive validation requests** from Portfolio Manager
2. **Fetch actual market prices** from Massive API for each trade's entry/exit timestamp
3. **Run validation checks** (price tolerance, P&L math, market hours, weekends, TP/SL logic)
4. **Self-correction loop**: If anomalies found, attempt correction up to n=10 iterations
5. **Report results** to Portfolio Manager with anomalies, corrections, and suggestions

## Validation Checks

### 1. Price Tolerance
- Fetch actual OHLC bar from Massive API at trade's entry/exit timestamp
- Compare recorded price vs actual price
- Tolerance: configurable (default 1%)
- Flag if `|recorded - actual| / actual > tolerance`

### 2. P&L Math
- Verify: `pnl = (exit_price - entry_price) * shares - fees`
- Verify: `pnl_pct = pnl / (entry_price * shares) * 100`

### 3. Market Hours
- Entry and exit must be within 4 AM - 8 PM Eastern (extended hours)
- Regular hours: 9:30 AM - 4:00 PM Eastern

### 4. Weekend/Holiday Check
- No trades on Saturday/Sunday
- Flag trades on known US market holidays

### 5. TP/SL Logic
- If TP hit: verify exit_price >= entry_price * (1 + take_profit)
- If SL hit: verify exit_price <= entry_price * (1 - stop_loss)
- Cannot have both TP and SL hit on same trade

## Self-Correction Loop

```
for iteration in range(max_iterations):  # default max=10
    anomalies = run_validation_checks(trades)
    if not anomalies:
        return ValidationResult(status="passed")

    corrections = attempt_corrections(anomalies)
    apply_corrections(corrections)

    # Re-validate after corrections
    remaining = run_validation_checks(trades)
    if not remaining:
        return ValidationResult(status="corrected", corrections=corrections)

# After max iterations: escalate
return ValidationResult(
    status="failed",
    anomalies=remaining,
    corrections_attempted=all_corrections,
    suggestions=generate_suggestions(remaining)
)
```

### Correction Types
- **Price rounding**: Adjust prices to match market data within tolerance
- **Fee recalculation**: Recalculate FINRA TAF and CAT fees
- **P&L recalculation**: Recompute P&L from corrected prices
- **Data flagging**: Mark trades with stale/missing market data

## Input (validation_request payload)

```json
{
  "run_id": "uuid",
  "source": "backtest",
  "max_iterations": 10,
  "price_tolerance": 0.01
}
```

## Output (validation_result payload)

```json
{
  "run_id": "uuid",
  "status": "passed|corrected|failed",
  "total_trades_checked": 42,
  "anomalies_found": 3,
  "anomalies_corrected": 2,
  "iterations_used": 2,
  "anomalies": [...],
  "corrections": [...],
  "suggestions": [...]
}
```

## Escalation Report (when status=failed)

When self-correction fails after max iterations:
- List of unresolvable anomalies with details
- All correction attempts made
- Suggested manual interventions
- Recommendation to re-run backtest with different parameters
