---
title: Nick Radge · Absolute trend following breakout (backtest)
description: Daily-bar backtest of the absolute trend following breakout method Nick Radge describes on Chat With Traders (ep. 178). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Nick Radge
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/178-nick-radge-the-blueprint-create-a-simple-trend-following-system
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Nick Radge · Absolute trend following breakout (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Nick Radge described in a podcast interview. It is **not**
Nick Radge's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 178 — [178: Nick Radge – The Blueprint: Create a Simple Trend Following System](https://chatwithtraders.com/episode/178-nick-radge-the-blueprint-create-a-simple-trend-following-system) · [YouTube](https://www.youtube.com/watch?v=EUUd2kq1Mh4)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: systematic trend following; timeframe: weekly signals on daily bars. Universe described:
S&P 500 or Russell 1000 constituents.

### Setup
- 20-week high breakout  
  > "you've just got to close above the highest high of the past 20 weeks" — ep. 178 [[00:19:27]]
- ROC over 20 weeks > 30%  
  > "rate of change over those 20 weeks is above a certain level ... above 30" — ep. 178 [[00:21:04]]
### Entry
- buy on 20-week breakout with ROC>30% when regime filter true  
  > "20 week breakout if the rate of change is above 30 then bang we've got a buy signal" — ep. 178 [[00:22:08]]
### Stop
- 20% trailing stop from recent high, ratchet to 10% when regime turns down  
  > "trailing stop somewhere in the vicinity ... 20% behind the position ... ratchet that up to 10 percent" — ep. 178 [[00:29:37]]
### Exits
- exit next open if close below trailing stop  
  > "has to close below that ... execute the exit on the open the next day" — ep. 178 [[00:17:59]]
### Sizing
- 5% fixed equity per position, max 20 positions  
  > "allocate 5% of our capital to each one of those positions ... 20 positions" — ep. 178 [[00:30:09]]
### Market Filter
- only buy when S&P 500 above its 200-day MA  
  > "only gonna take buy signals if the S&P 500 is above its 200 day moving average" — ep. 178 [[00:28:02]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **system described as weekly but engine is daily** → assumption: approximate 20-week high and Friday close logic on daily bars
- **exact trail stop calculation not fully specified** → assumption: standard ATR-independent percentage trailing stop from highest close
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -8.5% | +15.2% |
| Total return | -61.6% | +356.2% |
| Sharpe (daily, N-1) | -0.77 | 0.90 |
| Max drawdown | -64.0% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -23.7% | |
| CAPM alpha (ann.) / beta | -11.9% / 0.23 | |
| Trades / win rate | 5110 / 28.4% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.6% | +17.4% |
| Total return | -33.6% | +161.2% |
| Sharpe (daily, N-1) | -0.62 | 1.00 |
| Max drawdown | -35.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -24.0% | |
| CAPM alpha (ann.) / beta | -10.0% / 0.21 | |
| Trades / win rate | 2724 / 29.0% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -10.7% | +12.3% |
| Total return | -41.5% | +73.7% |
| Sharpe (daily, N-1) | -0.93 | 0.76 |
| Max drawdown | -44.4% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -23.0% | |
| CAPM alpha (ann.) / beta | -14.0% / 0.26 | |
| Trades / win rate | 2386 / 27.8% | |

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
  "name": "cwt_nick-radge-breakout",
  "display_name": "Nick Radge · Absolute trend following breakout (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 140,
    "mom_min": 0.3,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.006,
    "max_pos_pct": 0.05,
    "max_positions": 20,
    "min_price": 5.0,
    "market_filter": true,
    "slippage_bps": 10.0,
    "include_taf_fees": true,
    "include_cat_fees": true,
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
        "episode": "178",
        "url": "https://chatwithtraders.com/episode/178-nick-radge-the-blueprint-create-a-simple-trend-following-system"
      }
    ]
  }
}
```
