---
title: Semi-7 Buy-the-Dip · 3-day hold (backtest)
description: Buys one of the 7 largest US-listed semiconductor stocks outside the Mag-7 (TSM, AVGO, MU, AMD, ASML, INTC, AMAT) near the close after a 3%+ dip from its 20-day high; exits at +8% / −1.5% or after 3 days. Cash only. Walk-forward backtest; switches to live figures once the live sleeve starts trading.
kind: strategy
author: Predictive Labs Ltd
tags: buy-the-dip, semiconductors, semi-7, swing, mean-reversion, alpaca, backtest
license: MIT
---

# Semi-7 Buy-the-Dip · 3-day hold (backtest)

*For research and education only. This is not investment advice. The figures shown are a hypothetical walk-forward backtest with idealised fills; the strategy has only just been allocated a small live sleeve on Predictive Labs Ltd's own Alpaca account.*

The Mag-7 buy-the-dip rules applied to semiconductors. The exact numbers live in the **Parameters** block at the end of this file; if anything in the prose disagrees with that block, the block wins.

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this whole file into a new chat and ask, e.g., "Explain this strategy and its risks", "Backtest it on daily data for 2023–2025 against SPY and SOXX", or "Write pandas code for the entry and exit signals".
- **AlpaTrade:** "Clone into AlpaTrade" copies it into your own strategies (private until you publish it). The Parameters block has the shape of an AlpaTrade `strategy_configs` row.

## The strategy in plain language

### Universe
"Semi 7": the seven largest US-listed semiconductor stocks by market cap that are not in the Magnificent 7 (NVDA excluded). As of 9 Oct 2026 (yfinance): TSM, AVGO, MU, AMD, ASML, INTC, AMAT. Long only, US regular hours.

### Entry
- Once a day, 15–5 minutes before the close, compare each name's latest price with its highest daily high of the last 20 bars.
- Buy when the dip is **3% or more**; one position per symbol, never twice on the same day.
- Market order for a dollar amount = 1/7 of the strategy's cash allocation (its sleeve), cash only.

### Exit
- From the third calendar day after the buy: take profit at **+8%**, stop at **−1.5%** (broker-side orders).
- Otherwise sell at the close once the position is 3 days old.

## Backtest (walk-forward)
`scripts/walk_forward_btd.py --basket semi7`: 8 rolling folds, each optimises the backtester's buy-the-dip grid on 60 days and trades the chosen config on the next, unseen 30 days (2026-02-11 → 2026-10-09). Out-of-sample fold returns are chained into the equity curve. Each fold re-picks the backtester's dip / take-profit / hold grid (fold 1, for example, chose a 3% dip, +1.5% take-profit and a 1-day hold), so this measures the buy-the-dip approach on these names, not the exact live parameters below, and it compounds the full $10k each fold. Fills are idealised (no slippage or fees), so treat the figures as an optimistic upper bound.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "buy_the_dip_semi7_minhold_live",
  "kind": "backtest",
  "params": {"symbols": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"],
             "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
             "pos_frac": 0.142857, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
             "entry_window": "15-5", "close_window": "15-2"},
  "execution": {"regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
                "sizing": "pos_frac x strategy cash allocation, cash only"}
}
```
