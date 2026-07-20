# AlpaTrade — buy_the_dip on Mag-7: consolidated backtest summary

_Basket: AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA · $10,000 · winning config `dip 3% / take-profit 1.5% / stop 0.5% / hold 1 day / 10% size`._

## Verdict (read this first)

**buy_the_dip has no real edge on the Mag-7 basket.** The eye-popping backtest numbers were an artifact of **idealised intraday fills**. Under realistic execution (daily bars, next-open fills, slippage), the strategy is a **net loser** and is beaten decisively by simply **buying and holding** the basket. Do **not** deploy this config as-is.

## Three lenses on the same strategy, same config

### A. Same period — walk-forward window (2025-11-22 → 2026-07-20, ~8 months)

| Engine | Fills / assumptions | Total return | Annualised | Final $ | Verdict |
|---|---|---:|---:|---:|---|
| Grid-search **walk-forward** (OOS) | intraday, **idealised fills** | **+275%** ($27,550 over 8 folds) | ~419% simple / ~3,486% comp. | — | window-honest but fill-fantasy |
| **Methodology-faithful** | daily, **next-open fill + 5bps slippage**, N-1 Sharpe | **−2.91%** | **−4.52%** | $9,709 | **realistic: loses money** |
| Benchmark (buy & hold) | equal-weight, hold | **+4.26%** | +6.75% | $10,426 | just holding wins |

### B. One year (2025-07-20 → 2026-07-20)

| Engine | Fills / assumptions | Total return | Annualised | Sharpe | Trades / Win% / PF | Final $ |
|---|---|---:|---:|---:|---|---:|
| Grid-search (best single window) | intraday, idealised | **+18.31%** | ~18% | 8.22 | 613 / — / — | $11,831 |
| **Methodology-faithful** | daily, next-open + 5bps | **−2.56%** | **−2.58%** | **−0.47** | 578 / 37.2% / **0.93** | $9,744 |
| Benchmark (buy & hold) | equal-weight, hold | **+21.31%** | +21.50% | 1.02 | — | $12,131 |

## Why the numbers collapse

- The grid-search / walk-forward engine used **intraday (5-min) bars with same-/intraday-bar exits** — it books tiny, reliable moves that a real broker fill never gives you. That is where the +18% / +275% / Sharpe-8 came from.
- The methodology-faithful engine (`engine.backtest`) enforces **next-open fills (signal at close t, fill at open t+1 → no look-ahead)**, adds **5bps slippage**, uses **daily bars**, and computes **Sharpe with sample stddev (N-1)**. On that basis the same rules **lose money** (profit factor < 1, negative Sharpe) and trail buy-and-hold by ~20 percentage points over the year.
- **Consistency check passed, edge check failed.** The walk-forward correctly showed the config isn't *window*-overfit (8/8 folds, 11% IS→OOS drop) — but that only means the intraday-fill result is *repeatable*, not *real*. Realistic execution is the test it fails.

## What this proves about the platform

This is the methodology-faithful backtester doing exactly its job: catching a strategy that looks great on optimistic fills and would have lost money live. All runs (grid-search + walk-forward + methodology) persist to `alpatrade.runs` / `backtest_summaries` / `trades`, and the methodology runs also write dated artifact folders to `backtest-results/` (summary.json, report.md, data fingerprints).

## Recommendation

1. **Don't trade this config.** On realistic execution it underperforms buy-and-hold.
2. If pursuing buy_the_dip, **re-optimise against the methodology-faithful engine** (next-open + fees), not the intraday grid — optimise for realistic PnL, and only accept a config that beats buy-and-hold out-of-sample after friction.
3. Or let the **paper-trading autonomy loop** adjudicate: it fills on the real paper account, so its PnL already reflects execution — a much better arbiter than any idealised backtest.

_Hypothetical results; not financial advice. Past performance does not predict future returns. Regulatory fees excluded (execution friction only) in the methodology runs._
