---
title: Kenny Glick · Consolidation range breakout swing (backtest)
description: Daily-bar backtest of the consolidation range breakout swing method Kenny Glick describes on Chat With Traders (ep. 94). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Kenny Glick
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/094-kenny-glick-shady-tales-from-a-real-life-boiler-room-and-things-profitable-traders-do
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Kenny Glick · Consolidation range breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Kenny Glick described in a podcast interview. It is **not**
Kenny Glick's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 94 — [094: Kenny Glick – Shady Tales From a Real-Life Boiler Room, and Things Profitable Traders Do](https://chatwithtraders.com/episode/094-kenny-glick-shady-tales-from-a-real-life-boiler-room-and-things-profitable-traders-do) · [YouTube](https://www.youtube.com/watch?v=G5UMKkOg1xg)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: momentum breakout after consolidation; timeframe: daily to multi-month swing. Universe described:
US stocks coming out of long consolidation or beaten-down ranges.

### Setup
- stock consolidating in range after being beaten down, sellers dried up  
  > "finding stocks that are coming out of a malaise or coming out of a depression or or just or just coming out of just sitting around and consolidating and once I see them reversing and breaking some previous you know not just a day but going back you know a month sometimes two months sometimes a year" — ep. 94 [[00:45:54]]
### Entry
- breakout above consolidation range high or VWAP  
  > "once they break out of that channel or that that range that they're sitting in" — ep. 94 [[00:45:54]]
- use 9-month or yearly VWAP as guide for breakout confirmation  
  > "once these stocks reverse and they break the vwap the trades have been working about 90% of the time" — ep. 94 [[00:48:00]]
### Stop
- exit if fails to hold breakout or re-enters range  
  > "if it pulls back and you know goes right back down to 385 no harm no foul" — ep. 94 [[01:02:21]]
### Exits
- scale out at prior breakdown highs or next range targets; use VWAP for profit taking  
  > "I'm using the vwap as a guide to where I might be looking to take some profit and if it does break over these yearly vaps you're getting another 10 15 20% on some of these stocks" — ep. 94 [[00:49:34]]
### Sizing
- start small, scale out most on initial move, hold remainder as swing  
  > "stock spurts 40 cents guess what I'm doing I'm selling 800 shares of it taking the money off the table and I'm holding 200 shares as a swing trade" — ep. 94 [[00:55:54]]
### Market Filter
- prefer bull market environment for long breakouts  
  > "once the shorts get nervous the stock goes and has a monster move and I just go from stock to stock" — ep. 94 [[00:46:57]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **no exact numerical thresholds for range length, breakout pct, or stops given** → assumption: use standard daily-bar breakout params with consolidation_days=20-60, momentum_min_pct=5-10
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.3% | +15.2% |
| Total return | -50.0% | +356.2% |
| Sharpe (daily, N-1) | -1.38 | 0.90 |
| Max drawdown | -50.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -21.4% | |
| CAPM alpha (ann.) / beta | -7.6% / 0.08 | |
| Trades / win rate | 1458 / 29.7% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.3% | +17.4% |
| Total return | -32.1% | +161.2% |
| Sharpe (daily, N-1) | -1.35 | 1.00 |
| Max drawdown | -33.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -23.6% | |
| CAPM alpha (ann.) / beta | -7.9% / 0.09 | |
| Trades / win rate | 884 / 28.7% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.0% | +12.3% |
| Total return | -25.5% | +73.7% |
| Sharpe (daily, N-1) | -1.38 | 0.76 |
| Max drawdown | -25.6% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -18.3% | |
| CAPM alpha (ann.) / beta | -7.1% / 0.07 | |
| Trades / win rate | 574 / 31.2% | |

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
  "name": "cwt_kenny-glick-breakout",
  "display_name": "Kenny Glick · Consolidation range breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 50,
    "mom_min": 0.1,
    "cons_days": 30,
    "cons_max_range": 0.1,
    "trail_ma": 20,
    "partial_days": 3,
    "partial_frac": 0.5,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.1,
    "max_positions": 5,
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
        "episode": "94",
        "url": "https://chatwithtraders.com/episode/094-kenny-glick-shady-tales-from-a-real-life-boiler-room-and-things-profitable-traders-do"
      }
    ]
  }
}
```
