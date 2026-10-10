# buy_the_dip on the live rules after the v0.33.6 backtester fixes

_Generated 2026-10-10T03:59 UTC · rules: dip 3% vs 20-day high, TP 8%, SL 1.5%, min = max hold 3 calendar days, 1/7 of equity per position, cash only · daily bars (yfinance, adjusted), entry at the signal close + 10 bps, stop before target when both are touched, stop fills at the open when gapped through, 10 bps per side, FINRA TAF + CAT fees on · engine 0.34.1 (d64f6bfd0eb9)._

Annualised = simple total × 252 / trading days (CAGR alongside). Sharpe from daily equity, rf 0.

| Basket | Run | Period | Total | Simple ann. | CAGR | Sharpe | Max DD | Trades | Win | SPY total | SPY simple | SPY Sharpe | SPY max DD | Alpha (simple) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| semi7 | fixed | 2026-02-11 → 2026-10-09 (167d) | +6.7% | +10.2% | +10.3% | 0.53 | -11.0% | 330 | 43% | +13.4% | +20.2% | 1.51 | -8.6% | -10.1% |
| semi7 | fixed | 2016-01-04 → 2026-10-09 (2794d) | +39.6% | +3.6% | +3.1% | 0.26 | -38.8% | 5609 | 47% | +360.6% | +32.5% | 0.89 | -33.7% | -28.9% |

semi7 30-day folds (fresh $10k, fixed): -7.4%, +4.1%, +11.5%, -2.6%, +5.2%, -3.7%, +0.9%, -0.5% — sum +7.6%

| mag7 | fixed | 2026-02-11 → 2026-10-09 (167d) | -2.2% | -3.4% | -3.3% | -0.27 | -8.6% | 377 | 42% | +13.4% | +20.2% | 1.51 | -8.6% | -23.6% |
| mag7 | fixed | 2016-01-04 → 2026-10-09 (2794d) | +27.7% | +2.5% | +2.2% | 0.23 | -35.0% | 4952 | 48% | +360.6% | +32.5% | 0.89 | -33.7% | -30.0% |

mag7 30-day folds (fresh $10k, fixed): -4.3%, +0.8%, +1.7%, -3.3%, +1.2%, +0.3%, -0.3%, +2.6% — sum -1.4%

Caveat: the baskets are today's largest names (survivorship / selection bias flatters any long-only rule over 2016–2026). Hypothetical; not financial advice.
