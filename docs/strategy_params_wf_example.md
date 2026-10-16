# Walk-forward example (v0.51.0)

Semi-7 (TSM, AVGO, MU, AMD, ASML, INTC, AMAT), $10k per window, parity backtester (same rules as paper/live), fees + 10 bps slippage.

* **Live v1**: dip 3%, TP 8%, SL 1.5% (pct), min/max hold 3/3, pos 14.3%.
* **Candidate v2**: same, plus `stop_mode=atr`, `stop_k=2`, `tp_mult=3`, `regime_filter=SPY,SMH` (5-day low).

**Walk-forward of v2** on the parity backtester (data to 2026-10-15, $10k per window).

| Window | Return | Sharpe | Max DD | Live version | SPY |
|---|---|---|---|---|---|
| 2016-2022 | -6.7% | 0.07 | -44.6% | -11.5% / 0.02 | +115.8% / 0.67 |
| 2023+ | +140.0% | 0.98 | -31.3% | +130.9% / 0.96 | +112.5% / 1.42 |
| OOS test years chained | +114.9% | 0.42 | -48.6% | +83.8% / 0.36 | +353.5% / 0.88 |

Rolling 3y fit → 1y test (test-year return, candidate / live / SPY): 2016 +20%/+32%/+14%, 2017 +3%/+5%/+21%, 2018 -33%/-34%/-5%, 2019 +35%/+26%/+31%, 2020 -24%/-5%/+17%, 2021 +16%/+27%/+31%, 2022 -13%/-40%/-19%, 2023 +22%/+34%/+27%, 2024 +7%/+9%/+26%, 2025 +37%/+21%/+18%, 2026 +38%/+23%/+14%

Fit windows (in-sample, 3y) for decay: 2013-2015 +12%, 2014-2016 +16%, 2015-2017 +27%, 2016-2018 -13%, 2017-2019 -7%, 2018-2020 -28%, 2019-2021 +17%, 2020-2022 -24%, 2021-2023 +28%, 2022-2024 +16%, 2023-2025 +71%

Hypothetical backtest, not investment advice.
