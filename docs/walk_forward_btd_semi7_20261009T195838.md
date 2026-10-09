# AlpaTrade — buy_the_dip walk-forward (Semi-7, PnL objective)

_Generated 2026-10-09 19:58 UTC · basket TSM, AVGO, MU, AMD, ASML, INTC, AMAT · $10,000/fold · train 60d → test 30d, rolling · 8 folds_

Each fold: optimise the grid on the **train** window by **PnL**, then trade that exact config on the next, unseen **test** window. **OOS PnL** is the honest number — money the just-optimised config made on data it never saw. Naive = a fixed default config, untouched.

## Fold-by-fold (out-of-sample)

| Test window | Chosen dip/TP/hold | In-sample PnL | **OOS PnL** | OOS trades | Naive PnL |
|---|---|---:|---:|---:|---:|
| 2026-02-11→2026-03-13 | 0.03/0.015/1 | $4,647 | **$4,094** | 108 | $3,617 |
| 2026-03-13→2026-04-12 | 0.03/0.015/1 | $4,987 | **$385** | 88 | $285 |
| 2026-04-12→2026-05-12 | 0.05/0.015/1 | $810 | **$2,686** | 21 | $2,653 |
| 2026-05-12→2026-06-11 | 0.05/0.015/1 | $3,071 | **$3,265** | 55 | $3,181 |
| 2026-06-11→2026-07-11 | 0.03/0.015/1 | $4,754 | **$3,426** | 73 | $2,459 |
| 2026-07-11→2026-08-10 | 0.03/0.015/1 | $3,875 | **$3,530** | 104 | $2,505 |
| 2026-08-10→2026-09-09 | 0.03/0.015/1 | $3,994 | **$983** | 92 | $940 |
| 2026-09-09→2026-10-09 | 0.03/0.015/1 | $2,680 | **$3,243** | 60 | $3,168 |
| **Total** | | $28,818 | **$21,612** | | $18,808 |

## Verdict (PnL)

- **Out-of-sample PnL: $21,612** across 8 folds ($10,000/fold), profitable in **8/8** folds.
- In-sample PnL was $28,818. The **IS→OOS drop of $7,206** (25% of in-sample) is the over-fit tax — how much the grid-optimised number overstates reality.
- vs a fixed naive config ($18,808 OOS): optimising per fold BEAT the fixed naive config out-of-sample — the tuning adds real PnL.
- Bottom line: **$21,612 of realistic (out-of-sample) PnL** is the number to trust, not the $28,818 in-sample figure.

## Annualised return & periods covered

- **Periods (out-of-sample):** 2026-02-11 → 2026-10-09 (8 × 30d = 240d ≈ 8 months); training data reaches ~60d earlier.
- **Avg per-fold (30d) OOS return:** +27.0%.
- **Annualised OOS return:** ~329% simple / ~1626% compounded (×6.5 over 240d).
- A return this large is a **warning about idealised fills**, not a headline — realistic execution (slippage + fees) would cut it to a fraction.

## Risk metrics vs buy-and-hold (out-of-sample windows)

Fold returns are chained (compounded) across the consecutive test windows. Buy-and-hold = equal-weight basket bought at the first close of each test window and held to its last close (yfinance adjusted closes). Sharpe = mean/stdev of fold returns × sqrt(folds per year), rf = 0.

| Metric | BTD (walk-forward OOS) | Buy & hold (same windows) |
|---|---:|---:|
| CAGR | 1626.3% | 152.8% |
| Sharpe (fold-based) | 7.67 | 2.26 |
| Max drawdown (fold equity) | 0.0% | 4.6% |
| Profitable folds | 8/8 | 6/8 |
| Avg trade win rate (OOS) | 60.6% | — |
| Folds BTD beat B&H | 6/8 | |

## Caveats

- Still uses the backtester's fill/fee model; OOS removes *window* over-fit but not idealised execution. Real fills/slippage would reduce this further.
- Each fold is a fresh $10k (not compounded). Hypothetical; not financial advice.

## Storage & reproduce

- All train + test runs persist to `alpatrade.runs`/`backtest_summaries`/`trades`.
- Reproduce: `python scripts/walk_forward_btd.py --basket semi7`.
