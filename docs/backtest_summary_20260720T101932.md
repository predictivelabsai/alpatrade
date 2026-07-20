# AlpaTrade — Mag-7 strategy backtest summary

_Generated 2026-07-20 10:24 UTC · basket: AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA · starting capital $10,000_

Each cell is the **best grid-search variation** for that strategy over that look-back window, shown as **Return% / Sharpe / Trades**. Comparing across horizons is the anti-over-fit check: an edge that only appears on one window is likely fitted to it.

## Performance across horizons

| Strategy | 1m | 3m | 6m | 1y |
|---|---|---|---|---|
| `buy_the_dip` | +2.14% / 10.99 / 59 | +4.95% / 9.07 / 170 | +10.41% / 8.09 / 386 | +18.31% / 8.22 / 613 |
| `momentum` | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 |
| `vix` | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 | +0.00% / 0.00 / 0 |

## PnL ($) by horizon

| Strategy | 1m | 3m | 6m | 1y |
|---|---|---|---|---|
| `buy_the_dip` | $214 | $495 | $1,041 | $1,831 |
| `momentum` | $0 | $0 | $0 | $0 |
| `vix` | $0 | $0 | $0 | $0 |

## Calibration / over-fit read

- **`buy_the_dip`** — traded on 1m, 3m, 6m, 1y; positive on 4/4 horizons; Sharpe range 8.1–11.0. consistent across horizons — more trustworthy.
- **`momentum`** — produced **no trades** on any horizon (default grid didn't trigger on this basket); not comparable without parameter tuning.
- **`vix`** — produced **no trades** on any horizon (default grid didn't trigger on this basket); not comparable without parameter tuning.

## Calibrated recommendation

On the **longest window that actually traded**, the best strategy is **`buy_the_dip`** over **1y**: +18.31% return, $1,831 PnL, Sharpe 8.22, 613 trades, 0.37% max drawdown.

Winning parameters: `{"dip_threshold": 0.07, "take_profit": 0.01, "hold_days": 1, "stop_loss": 0.005, "position_size": 0.1, "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]}`

## Caveats

- **Best-of-grid is optimistic.** Each cell picks the best of ~18 variations on that exact window; a very high Sharpe on a short window usually means over-fit, not edge. Longer windows are more trustworthy. For a true test, run walk-forward (train on one window, test on the next).
- Momentum / VIX may need parameter tuning to trade on this basket; `box_wedge` isn't wired into the grid-search backtester.
- Hypothetical results; not financial advice. Past performance does not predict future returns.

## Storage & reproduce

- Every grid variation is persisted to the DB: `alpatrade.runs` (mode=backtest), `alpatrade.backtest_summaries`, `alpatrade.trades` (trade_type=backtest).
- Reproduce: `python scripts/multi_horizon_report.py` (or `scripts/strategy_backtest_compare.py <lookback>` for a single window).
