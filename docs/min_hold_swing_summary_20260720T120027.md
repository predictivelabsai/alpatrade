# AlpaTrade — PDT-safe min-hold swing (buy_the_dip, Mag-7)

_Realistic engine (`engine.backtest`: daily bars, next-open fills + 5bps slippage, N-1 Sharpe, no look-ahead) · basket AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA · $10,000 · 2025-07-20 → 2026-07-20._

**Rule:** buy the dip, hold a **minimum of 3 trading days** (never a same-day round trip → PDT-safe), then exit **intraday** once take-profit or stop is hit (intrabar), with a max hold. Implemented as a new `min_hold_days` gate on the methodology strategy/engine.

## Results (realistic fills)

| Config (all min-hold 3d) | Dip / TP / SL / max-hold | Return | Annualised | Sharpe | Profit factor | Trades |
|---|---|---:|---:|---:|---:|---:|
| tight-3d | 3% / 1.5% / 3% / 10d | +0.99% | +1.00% | 0.19 | 1.04 | 268 |
| shallow-3d | 3% / 3% / 5% / 10d | +1.74% | +1.75% | 0.29 | 1.07 | 210 |
| mid-3d | 5% / 5% / 8% / 15d | +4.28% | +4.32% | 0.68 | 1.29 | 110 |
| **deep-3d** | **7% / 6% / 10% / 20d** | **+5.25%** | **+5.29%** | **0.88** | **1.45** | 69 |
| — 1-day scalp (prior) | 3% / 1.5% / 0.5% / 1d | −2.56% | −2.58% | −0.47 | 0.93 | 578 |
| **Buy & hold Mag-7** | — | **+21.31%** | +21.50% | 1.02 | — | — |

## What this shows

- **The min-hold swing turns a loser into a real, positive-edge strategy.** Every 3-day-min config is profitable with **profit factor > 1 and positive Sharpe**, whereas the 1-day scalp (min-hold 0) *lost* money (PF 0.93, Sharpe −0.47). Holding through the first few days — and only exiting intraday once the move actually materialises — is a genuine edge; scalping tiny same-week moves was just noise the costs ate.
- **Deeper dips + patience win.** `deep-3d` (buy 7% dips, 6% target, hold up to 20 days) is best — **PF 1.45, Sharpe 0.88, just 69 trades**. Fewer, higher-conviction trades beat frequent shallow ones.
- **But it still trails buy-and-hold (+21.3%) in this bull year.** With the Mag-7 trending up, sitting in cash between dips costs you the trend. The swing's advantage is *low exposure and low drawdown*, not out-gunning a raging bull.

## Honest read

- This is now a **realistic** result (next-open fills, slippage, no intraday-scalp fantasy). A ~5% annual return with PF 1.45 is a modest but real edge — plausible, unlike the earlier +18%/+419% artifacts.
- In a **flat or choppy** market (where buy-and-hold stalls), a positive-PF dip-swing that's mostly in cash is exactly the kind of thing that adds value; in a **strong uptrend** it under-earns. Regime matters.
- Next: (a) test these configs in **down/sideways** windows to see where the swing beats buy-and-hold; (b) or promote `deep-3d` into the **paper-trading autonomy loop** and let real paper fills adjudicate.

_Hypothetical; not financial advice. Regulatory fees excluded (execution friction only). All runs persist to the DB and to dated artifact folders under `backtest-results/`._
