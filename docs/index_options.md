# Index Options Paper Trading

AlpaTrade can discover and submit paper orders for Alpaca's initial Cboe index
options: `SPX`, `SPXW`, `VIX`, `VIXW`, `DJX`, and `XSP`. They are cash-settled
and European-style, so expiration produces a cash credit/debit and there is no
early assignment. Alpaca does not currently provide underlying index market
data; contract discovery and execution work, but strategy signals require a
separate licensed data source.

## Tools

- `list_index_option_contracts` filters active European-style contracts by
  underlying, call/put, and expiration window.
- `place_index_option_paper_order` submits a whole-contract DAY market or limit
  order. It is intentionally restricted to paper trading.

## Strategies to Evaluate

These are research templates, not recommendations:

- **Defined-risk directional spread:** buy one call/put and sell a farther OTM
  contract with the same expiry. Cap size at the net debit.
- **XSP protective put:** test smaller-notional S&P 500 downside hedges and
  compare hedge cost with portfolio drawdown reduction.
- **SPXW iron condor:** test defined-risk short premium only after modeling both
  wings, fees, slippage, and a loss-based exit. Avoid naked shorts.
- **VIX call spread:** test convex volatility protection with a fixed premium
  budget; VIX options do not track spot VIX one-for-one.
- **0DTE SPXW debit spread:** paper-test entry/exit and PM settlement with one
  spread; assume live fills will differ materially.

AM-settled series can stop accepting orders before expiration and settle from
an opening reference value. PM-settled weeklies, including SPXW 0DTE, have
different timing. The agent must identify settlement style before holding
through expiry.

## Example Conversations

> Show active XSP puts expiring 20–45 days from now.

> Design a one-contract XSP put spread with a maximum loss under $300. List
> contracts first; do not place orders.

> Paper buy one discovered SPXW call contract at a $2.10 limit.

> Compare an SPXW iron condor and debit spread for a 0DTE paper experiment,
> including maximum loss, exit rules, settlement risk, and data required.

See Alpaca's [index-options announcement](https://alpaca.markets/blog/alpaca-introduces-index-options-paper-trading/)
and [options API walkthrough](https://alpaca.markets/learn/how-to-trade-options-with-alpaca).
