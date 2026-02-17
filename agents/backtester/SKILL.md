---
name: backtester
description: Runs parameterized backtests with systematic variation of portfolios, intervals, and strategy parameters
metadata:
  version: "1.0"
  type: worker
  triggers:
    - backtest_request
---

# Backtester Agent

## Role

The Backtester agent runs parameterized backtests using existing strategy implementations. It systematically varies portfolio composition, time intervals, and strategy parameters to find optimal configurations.

## Responsibilities

1. **Receive backtest requests** from Portfolio Manager via message bus
2. **Generate parameter grid** for systematic variation
3. **Execute backtests** using `utils/backtester_util.py` strategy functions
4. **Store results** in DB via `utils/backtest_db_util.py`
5. **Report best configuration** back to Portfolio Manager

## Parameter Variations

### Portfolio Composition
- Individual Mag7 stocks: AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA
- Subsets: Top 3 by market cap, FAANG, all Mag7
- Custom symbol lists from request

### Time Intervals
- Lookback periods: 1 month, 3 months, 6 months, 1 year
- Data intervals: 1d (daily), 60m (hourly)

### Strategy Parameters (Buy the Dip)
- `dip_threshold`: 3%, 4%, 5%, 6%, 7%
- `take_profit`: 0.5%, 1.0%, 1.5%, 2.0%
- `hold_days`: 1, 2, 3, 5
- `stop_loss`: 0.3%, 0.5%, 1.0%
- `position_size`: 5%, 10%, 15%

## Input (backtest_request payload)

```json
{
  "strategy": "buy_the_dip",
  "symbols": ["AAPL", "MSFT", "NVDA"],
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "initial_capital": 10000,
  "variations": {
    "dip_threshold": [0.03, 0.05, 0.07],
    "take_profit": [0.01, 0.015],
    "hold_days": [1, 2, 3]
  }
}
```

## Output (backtest_result payload)

```json
{
  "run_id": "uuid",
  "total_variations": 18,
  "best_config": {
    "dip_threshold": 0.05,
    "take_profit": 0.015,
    "hold_days": 2,
    "sharpe_ratio": 1.42,
    "total_return": 12.5,
    "win_rate": 65.0
  },
  "all_results_summary": [...]
}
```

## Strategies Supported

- `buy_the_dip` -> `utils/backtester_util.backtest_buy_the_dip()`
- `momentum` -> `utils/backtester_util.backtest_momentum_strategy()`
- `vix` -> `utils/backtester_util.backtest_vix_strategy()`
