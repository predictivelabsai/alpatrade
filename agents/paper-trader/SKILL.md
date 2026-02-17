---
name: paper-trader
description: Continuous paper trading agent using real Alpaca paper API with position tracking and P&L reporting
metadata:
  version: "1.0"
  type: worker
  triggers:
    - paper_trade_start
---

# Paper Trader Agent

## Role

The Paper Trader agent executes real paper trades via the Alpaca paper trading API. It runs continuously for a configurable duration, applying validated strategy parameters from the Backtester.

## Responsibilities

1. **Receive trading parameters** from Portfolio Manager (validated by Backtester/Validator)
2. **Execute trades** via Alpaca paper API (real orders, real fills, market hours)
3. **Track positions** and monitor for exit signals (TP, SL, hold period)
4. **Log trades** to the `trades` DB table
5. **Report** daily P&L and position updates to Portfolio Manager

## Trading Logic

Uses the same buy-the-dip logic as `tasks/cli_trader.py`:

1. **Entry**: Buy when stock dips `dip_threshold%` from recent 20-period high
2. **Exit conditions** (checked each poll):
   - Take profit: unrealized P&L >= `take_profit_threshold%`
   - Stop loss: unrealized P&L <= `-stop_loss_threshold%`
   - Hold period expired: days held >= `hold_days`
3. **PDT protection**: Mandatory overnight hold if account equity < $25k
4. **Position sizing**: `capital_per_trade` capped at 5% of buying power

## Input (paper_trade_start payload)

```json
{
  "strategy": "buy_the_dip",
  "symbols": ["AAPL", "MSFT", "NVDA"],
  "params": {
    "dip_threshold": 5.0,
    "take_profit_threshold": 1.5,
    "stop_loss_threshold": 0.5,
    "hold_days": 2,
    "capital_per_trade": 1000.0
  },
  "duration_seconds": 604800,
  "poll_interval_seconds": 300
}
```

## Output (paper_trade_result payload)

```json
{
  "session_id": "uuid",
  "duration_actual": "6d 23h 45m",
  "total_trades": 12,
  "winning_trades": 8,
  "losing_trades": 4,
  "total_pnl": 245.50,
  "daily_pnl": [...],
  "final_positions": [...]
}
```

## Trade Updates (sent periodically)

```json
{
  "type": "trade_update",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 5,
  "price": 185.50,
  "timestamp": "2025-01-15T10:30:00Z"
}
```

## Safety

- Only market orders (no limit/stop orders to avoid stale orders)
- Position size capped at 5% of buying power
- PDT protection enforced for accounts under $25k
- All orders logged to DB and local JSONL fallback
