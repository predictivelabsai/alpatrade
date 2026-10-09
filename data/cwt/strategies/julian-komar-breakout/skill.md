---
title: Julian Komar · Momentum breakout swing (backtest)
description: Daily-bar backtest of the momentum breakout swing method Julian Komar describes on Chat With Traders (ep. 305). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Julian Komar
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/305-when-story-fundamentals-and-technicals-align-w-julian-komar
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Julian Komar · Momentum breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Julian Komar described in a podcast interview. It is **not**
Julian Komar's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 305 — [305 · Julian Komar - When Story, Fundamentals, and Technicals Align](https://chatwithtraders.com/episode/305-when-story-fundamentals-and-technicals-align-w-julian-komar) · [YouTube](https://www.youtube.com/watch?v=hWx_d6gAhPQ)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: breakout from flags/tight consolidations after 50-70% move; timeframe: daily. Universe described:
US stocks with institutional quality volume (5-100M+ daily dollar volume depending on theme maturity), RS rating >=90.

### Setup
- High relative strength and accumulation on volume  
  > "relative strength so how performs a stock in comparison with the indices ... how is the the accumulation of a stock uh when you watch the volume" — ep. 305 [[00:10:33]]
- Big prior move then tight consolidation around EMA8/21  
  > "when when a stock makes a big move like 50 or 70% in a short period of time and then it get gets very tight and starts to consolidate around the exponential moving average 8 or exponential moving average 21" — ep. 305 [[00:42:12]]
### Entry
- Breakout from flag, cup-handle or tight consolidation on volume  
  > "90% of my trades are breakouts from uh classical chart patterns" — ep. 305 [[00:43:46]]
### Stop
- Tight stop implied by pattern; risk 0.5-1.5% per trade  
  > "instead of risking let's say 0.5 to to 1% of my trading capital I risk a little bit more like you know one to one and a half%" — ep. 305 [[00:57:55]]
### Exits
- Partial or full exit on breakdown or profit target (unspecified)  
  > "I have some some rules when to take profits, when to enter a stock" — ep. 305 [[00:57:25]]
### Sizing
- 10-15% per position in good markets, 5-10% sideways, up to 20-25% high-conviction liquid names  
  > "in good market periods, I invest 10 to 15% in one position ... I can also go up to 20 20% position size. So Tesla as an example or Nvidia, I had last year I had a 25% position in Nvidia" — ep. 305 [[00:51:03]]
### Market Filter
- Market trend model on MAs green + new highs + stocks above MA200  
  > "I'm I'm running my own market trend model ... based on moving averages. And when I see a good trend in the stock market, so when my market trend model switches to green, when I see that there are a lot of stocks reaching new highs and we have a higher number of stocks above the MA200" — ep. 305 [[00:41:09]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **No exact values for momentum_lookback_days, consolidation_days, consolidation_max_range_pct, trail_ma, partial_after_days, partial_frac, max_positions** → assumption: Use standard breakout template defaults where unspecified; focus on quoted 50-70% prior move and EMA8/21 consolidation
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -1.2% | +15.2% |
| Total return | -12.5% | +356.2% |
| Sharpe (daily, N-1) | -0.10 | 0.90 |
| Max drawdown | -24.6% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -16.4% | |
| CAPM alpha (ann.) / beta | -2.1% / 0.08 | |
| Trades / win rate | 500 / 26.6% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +0.7% | +17.4% |
| Total return | +4.2% | +161.2% |
| Sharpe (daily, N-1) | 0.13 | 1.00 |
| Max drawdown | -11.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -16.7% | |
| CAPM alpha (ann.) / beta | -0.3% / 0.07 | |
| Trades / win rate | 259 / 27.0% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -3.6% | +12.3% |
| Total return | -16.0% | +73.7% |
| Sharpe (daily, N-1) | -0.35 | 0.76 |
| Max drawdown | -20.1% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -15.9% | |
| CAPM alpha (ann.) / beta | -4.3% / 0.08 | |
| Trades / win rate | 241 / 26.1% | |

### Caveats
- **Survivorship bias:** today's S&P 500 members, which flatters long strategies historically.
- Rules were extracted by an LLM from auto-captions / Whisper transcripts; quotes may contain
  transcription errors. Parameters were not optimised.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Daily bars, signals from the prior close, cash only; report CAGR, Sharpe, max drawdown,
   alpha vs SPY, trades and win rate over the same period.
3. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "cwt_julian-komar-breakout",
  "display_name": "Julian Komar · Momentum breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 63,
    "mom_min": 0.5,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.15,
    "max_positions": 10,
    "min_price": 5.0,
    "market_filter": true,
    "slippage_bps": 10.0,
    "universe": "sp500_current",
    "timeframe": "1d"
  },
  "execution": {
    "cash_only": true,
    "slippage_bps_per_side": 10.0
  },
  "backtest": {
    "engine": "engine.backtest.breakout",
    "data": "Alpaca SIP daily bars, adjustment=all (splits+dividends)",
    "universe": "S&P 500 current members (503 with data)",
    "train": [
      "2016-01-04",
      "2021-12-31"
    ],
    "test": [
      "2022-01-03",
      "2026-10-09"
    ],
    "benchmark": "SPY"
  },
  "source": {
    "site": "chatwithtraders.com",
    "episodes": [
      {
        "episode": "305",
        "url": "https://chatwithtraders.com/episode/305-when-story-fundamentals-and-technicals-align-w-julian-komar"
      }
    ]
  }
}
```
