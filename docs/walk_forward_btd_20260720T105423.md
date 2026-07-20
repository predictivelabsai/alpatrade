# AlpaTrade — buy_the_dip walk-forward (Mag-7, PnL objective)

_Generated 2026-07-20 10:54 UTC · basket AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA · $10,000/fold · train 60d → test 30d, rolling · 8 folds_

Each fold: optimise the grid on the **train** window by **PnL**, then trade that exact config on the next, unseen **test** window. **OOS PnL** is the honest number — money the just-optimised config made on data it never saw. Naive = a fixed default config, untouched.

## Fold-by-fold (out-of-sample)

| Test window | Chosen dip/TP/hold | In-sample PnL | **OOS PnL** | OOS trades | Naive PnL |
|---|---|---:|---:|---:|---:|
| 2025-11-22→2025-12-22 | 0.03/0.015/3 | $4,457 | **$3,256** | 88 | $1,896 |
| 2025-12-22→2026-01-21 | 0.03/0.015/1 | $3,594 | **$3,882** | 80 | $3,882 |
| 2026-01-21→2026-02-20 | 0.03/0.015/1 | $4,538 | **$4,148** | 107 | $3,677 |
| 2026-02-20→2026-03-22 | 0.03/0.015/2 | $4,280 | **$4,030** | 118 | $3,665 |
| 2026-03-22→2026-04-21 | 0.03/0.01/1 | $4,291 | **$1,846** | 86 | $211 |
| 2026-04-21→2026-05-21 | 0.03/0.015/1 | $2,049 | **$2,850** | 68 | $1,546 |
| 2026-05-21→2026-06-20 | 0.03/0.015/1 | $3,149 | **$4,319** | 106 | $4,340 |
| 2026-06-20→2026-07-20 | 0.03/0.015/2 | $4,566 | **$3,219** | 93 | $945 |
| **Total** | | $30,924 | **$27,550** | | $20,162 |

## Verdict (PnL)

- **Out-of-sample PnL: $27,550** across 8 folds ($10,000/fold), profitable in **8/8** folds.
- In-sample PnL was $30,924. The **IS→OOS drop of $3,374** (11% of in-sample) is the over-fit tax — how much the grid-optimised number overstates reality.
- vs a fixed naive config ($20,162 OOS): optimising per fold BEAT the fixed naive config out-of-sample — the tuning adds real PnL.
- Bottom line: **$27,550 of realistic (out-of-sample) PnL** is the number to trust, not the $30,924 in-sample figure.

## Caveats

- Still uses the backtester's fill/fee model; OOS removes *window* over-fit but not idealised execution. Real fills/slippage would reduce this further.
- Each fold is a fresh $10k (not compounded). Hypothetical; not financial advice.

## Storage & reproduce

- All train + test runs persist to `alpatrade.runs`/`backtest_summaries`/`trades`.
- Reproduce: `python scripts/walk_forward_btd.py`.
