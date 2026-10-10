# buy_the_dip on the live rules after the v0.33.6 backtester fixes

_Generated 2026-10-10T03:29 UTC · rules: dip 3% vs 20-day high, TP 8%, SL 1.5%, min = max hold 3 calendar days, 1/7 of equity per position, cash only · daily bars (yfinance, adjusted), entry at the signal close + 10 bps, stop before target when both are touched, stop fills at the open when gapped through, 10 bps per side._

Annualised = simple total × 252 / trading days (CAGR alongside). Sharpe from daily equity, rf 0.

| Basket | Run | Period | Total | Simple ann. | CAGR | Sharpe | Max DD | Trades | Win | SPY total | SPY simple | SPY Sharpe | SPY max DD | Alpha (simple) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| semi7 | pre-fix code (reported total) | 2026-02-11 → 2026-10-09 (167d) | +73.5% | +79.6% | +89.6% | 2.72 | -6.8% | 334 | 45% | +13.4% | +20.2% | 1.51 | -8.6% | +59.4% |
| semi7 | fixed | 2026-02-11 → 2026-10-09 (167d) | +6.7% | +10.1% | +10.3% | 0.53 | -11.4% | 330 | 43% | +13.4% | +20.2% | 1.51 | -8.6% | -10.1% |
| semi7 | fixed | 2016-01-04 → 2026-10-09 (2794d) | +41.2% | +3.7% | +3.2% | 0.27 | -38.4% | 5610 | 47% | +360.6% | +32.5% | 0.89 | -33.7% | -28.8% |

semi7 30-day folds (fresh $10k, fixed): -7.4%, +4.1%, +11.5%, -2.6%, +5.2%, -3.7%, +1.0%, -0.5% — sum +7.6%
semi7 folds, pre-fix code as reported: +42.6%, +56.0%, +62.0%, +49.9%, +56.2%, +50.5%, +60.0%, +13.5%

| mag7 | pre-fix code (reported total) | 2026-02-11 → 2026-10-09 (167d) | +63.6% | +30.2% | +31.7% | 2.67 | -5.4% | 377 | 44% | +13.4% | +20.2% | 1.51 | -8.6% | +10.0% |
| mag7 | fixed | 2026-02-11 → 2026-10-09 (167d) | -2.2% | -3.3% | -3.3% | -0.26 | -8.6% | 377 | 42% | +13.4% | +20.2% | 1.51 | -8.6% | -23.5% |
| mag7 | fixed | 2016-01-04 → 2026-10-09 (2794d) | +28.6% | +2.6% | +2.3% | 0.23 | -34.9% | 4952 | 48% | +360.6% | +32.5% | 0.89 | -33.7% | -29.9% |

mag7 30-day folds (fresh $10k, fixed): -4.3%, +0.8%, +1.7%, -3.3%, +1.2%, +0.3%, -0.3%, +2.6% — sum -1.3%
mag7 folds, pre-fix code as reported: +51.2%, +2.9%, +15.3%, +48.2%, +42.7%, +4.6%, +40.9%, +38.6%

Caveat: the baskets are today's largest names (survivorship / selection bias flatters any long-only rule over 2016–2026). Hypothetical; not financial advice.
