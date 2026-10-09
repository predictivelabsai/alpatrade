---
title: Mag-7 Buy-the-Dip · 3-day hold (live)
description: Buys a Magnificent-7 stock near the close after a 3%+ dip from its 20-day high, exits at +8% / −1.5% or after 3 days. Cash-only, 1/7 of equity per name. Live on Alpaca since 24 Sep 2026.
kind: strategy
author: Julian Kaljuvee
tags: buy-the-dip, mag-7, swing, mean-reversion, alpaca, live
license: MIT
---

# Mag-7 Buy-the-Dip · 3-day hold (live)

*For research and education only. This is not investment advice. It describes a strategy Julian Kaljuvee runs on his own Alpaca live account; anything you trade is your own decision, in your own account.*

A small, cash-only, long-only swing strategy on the seven largest US tech stocks. It buys short, sharp pullbacks from a recent high late in the session and gives each trade three days to bounce, with a tight stop and a wide target. The exact numbers live in the **Parameters** block at the end of this file; if anything in the prose disagrees with that block, the block wins.

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this whole file into a new chat, then ask, for example: "Explain this strategy and its risks", "Backtest it on daily data for 2023–2025 against SPY", "Write pandas code that generates the entry and exit signals", or "Which parameter would you stress-test first?"
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own strategies (private until you publish it). The Parameters block has the same shape as an AlpaTrade `strategy_configs` row (`params` + `execution`); from your copy you can open it in the AlpaTrade chat for a backtest or a paper run.

## The strategy in plain language

### Universe
The Magnificent 7: AAPL, MSFT, GOOGL, AMZN, META, TSLA and NVDA. US regular-hours trading only, long only.

### Entry
- Once a day, between 15 and 5 minutes before the close (15:45–15:55 ET on a normal session), look at each name's latest trade price.
- Reference price = the highest daily high of the last 20 daily bars. Dip = (reference − latest price) / reference.
- Buy when the dip is **3% or more**.
- Skip the name if a position or an open order in it already exists, or if it was already bought today. At most one position per symbol.
- The buy is a market order for a dollar amount (fractional shares), good for the day.

### Position size
- Each new position is **1/7 of current account equity** (pos_frac 0.142857), so a full book is roughly 100% invested across the seven names.
- **Cash only:** a buy is skipped if its size exceeds available cash (no margin, no leverage, no shorting). There is no extra exposure cap beyond that.

### Exits
- **Minimum hold: 3 calendar days.** No exit orders are placed before then, so there are never same-day round trips (PDT-safe for a small account).
- On the morning the minimum hold is reached (around 09:31 ET, just after the open), place broker-side exits: a **take-profit at +8%** and a **stop-loss at −1.5%** from the entry price (one-cancels-other). If the price is already beyond either level at the open, exit at market.
- **Maximum hold: 3 calendar days.** If the position is still open between 15 and 2 minutes before that day's close, cancel the bracket and sell at market.
- **Extended-hours exits are enabled:** if an exit is due while the regular session is closed, sell with an extended-hours limit order at the bid minus 15 bps, reprice it every 5 minutes up to 2 times, and if it still hasn't filled, cancel it and sell at market at the next regular open.

### What makes it work (and what can break it)
- It bets that large, liquid leaders mean-revert after a quick 3%+ pullback; the +8% / −1.5% asymmetry means it can be right well under half the time and still make money.
- Risks: trending sell-offs (repeated stop-outs across correlated names), gaps through the stop overnight, concentration in one sector, and a short live track record.

## Instructions for the assistant
When the user asks you to analyse, backtest or adapt this strategy:
1. Treat the Parameters block as the source of truth and restate the rules before you start.
2. Backtests on daily bars: approximate the late-session entry with the daily close (or a 15:50 ET price if intraday data is available) and say which you used. Compute the 20-day high from the 20 most recent daily highs.
3. Simulate one position per symbol, notional sizing at 1/7 of equity, fractional shares, cash only. Count holding days in calendar days.
4. From the day the minimum hold is reached, apply the +8% take-profit and −1.5% stop intraday; if both could have been hit on the same daily bar, assume the stop hit first (conservative). Exit at that day's close if neither hit (maximum hold).
5. Report against SPY over exactly the same period: total return, annualised return (simple: return × 252 / trading days; compounded as a secondary figure), alpha (strategy return minus SPY return), number of trades, win rate, average win and loss, and maximum drawdown.
6. Include realistic costs and slippage assumptions, and flag look-ahead or survivorship bias (the Mag-7 list is chosen with hindsight).
7. Never place live orders. Suggest paper trading before any real money.

## Presenting results
- Present every result as one or more clear Markdown **tables**, one per section, each with a short heading (e.g. rules, trades, performance vs SPY, metrics).
- Keep prose minimal; put the substance in the tables.
- Offer the user a downloadable **PDF** (formatted) and **CSV** (the underlying trades), and generate them when asked.

## Parameters (machine-readable)
Copied from AlpaTrade's live config (`alpatrade.strategy_configs`, row `buy_the_dip_mag7_minhold_live`, version 2). Units: `dip`, `tp` and `sl` are percent; `min_hold` and `max_hold` are calendar days; `pos_frac` is a fraction of account equity; `max_exposure` 0 means no dollar cap; `entry_window` "15-5" means 15 to 5 minutes before the close and `close_window` "15-2" means 15 to 2 minutes before the close; `ref` "high20" is the 20-day high; `discount_bps` is basis points below the bid; `feed` is the market-data feed.

```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "buy_the_dip_mag7_minhold_live",
  "display_name": "Mag-7 BTD min-hold 3d",
  "config_version": 2,
  "params": {
    "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
    "dip": 3.0,
    "ref": "high20",
    "tp": 8.0,
    "sl": 1.5,
    "min_hold": 3,
    "max_hold": 3,
    "pos_frac": 0.142857,
    "max_exposure": 0.0,
    "entry_window": "15-5",
    "close_window": "15-2",
    "feed": "iex"
  },
  "execution": {
    "regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
    "extended_hours_exit": {
      "enabled": true,
      "order_type": "limit",
      "limit_ref": "bid",
      "discount_bps": 15,
      "reprice_after_min": 5,
      "max_reprices": 2,
      "fallback": "market_day_at_regular_open"
    }
  },
  "live": {
    "broker": "alpaca",
    "account": "live, cash only",
    "started": "2026-09-24",
    "start_equity_usd": 2725.59,
    "benchmark": "SPY"
  }
}
```
