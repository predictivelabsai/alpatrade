---
title: John Walsh · 52-week high breakout trend (backtest)
description: Daily-bar backtest of the 52-week high breakout trend method John Walsh describes on Chat With Traders (ep. 74). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: John Walsh
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/074-john-walsh-pocketing-100k-from-a-trading-comp-and-making-simplicity-a-priority-w-the-black-cabbie-trader
tags: breakout, chat-with-traders, backtest
license: MIT
---

# John Walsh · 52-week high breakout trend (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules John Walsh described in a podcast interview. It is **not**
John Walsh's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 74 — [074: John Walsh – Pocketing $100k From a Trading Comp, and Making Simplicity a Priority w/ the Black Cabbie Trader](https://chatwithtraders.com/episode/074-john-walsh-pocketing-100k-from-a-trading-comp-and-making-simplicity-a-priority-w-the-black-cabbie-trader)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: trend following position trading; timeframe: daily. Universe described:
US stocks scanned on finviz.com.

### Setup
- 52-week high with decent volume and EPS increase  
  > "I long 52 week highs, I short 52 week lows with a few added parameters, nothing major like, they've got to have a decent volume and an increase in earnings per share" — ep. 74 [[00:26:59]]
- smooth chart higher on right than left over 1-2 years  
  > "I'm looking for smooth charts. I look over a year or two years daily chart, and I really just want to see a smooth-ish line where it's higher in the right hand side than it is on the left hand side" — ep. 74 [[00:29:55]]
### Entry
- buy at next day market open after scan confirmation  
  > "the following day, at the market open to for a UK time, I just open the trade with the trade size at the stop" — ep. 74 [[00:33:10]]
### Stop
- Donchian channel low (20-40 days)  
  > "I use Donchin channels. And I follow certain Donchin channel time frames. ... I found 20, the 20 days pretty good. I've looked at 40" — ep. 74 [[00:36:58]]
### Exits
- Donchian channel exit on close  
  > "every day when the market closes, I look if the stop needs to be raised ... I literally get stopped out on every trade" — ep. 74 [[00:36:58]]
### Sizing
- risk 2-4% per trade, max 8 positions  
  > "I risk between 2% and 4% per trade. ... I like maybe eight positions at the max" — ep. 74 [[00:32:19]]
### Market Filter
- (not stated)

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **short side mentioned but engine is long-only** → assumption: use long-side rules only
- **exact Donchian period and momentum min pct not numeric** → assumption: use 20-day Donchian and 0 for min pct
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -15.6% | +15.2% |
| Total return | -83.9% | +356.2% |
| Sharpe (daily, N-1) | -0.85 | 0.90 |
| Max drawdown | -88.7% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -30.8% | |
| CAPM alpha (ann.) / beta | -21.3% / 0.38 | |
| Trades / win rate | 2225 / 28.5% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -14.6% | +17.4% |
| Total return | -61.2% | +161.2% |
| Sharpe (daily, N-1) | -0.88 | 1.00 |
| Max drawdown | -68.0% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -32.0% | |
| CAPM alpha (ann.) / beta | -20.2% / 0.33 | |
| Trades / win rate | 1164 / 28.8% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -16.8% | +12.3% |
| Total return | -58.2% | +73.7% |
| Sharpe (daily, N-1) | -0.82 | 0.76 |
| Max drawdown | -66.2% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -29.1% | |
| CAPM alpha (ann.) / beta | -22.4% / 0.46 | |
| Trades / win rate | 1061 / 28.3% | |

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
  "name": "cwt_john-walsh-breakout",
  "display_name": "John Walsh · 52-week high breakout trend (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 252,
    "mom_min": 0.3,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.02,
    "max_pos_pct": 0.2,
    "max_positions": 8,
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
        "episode": "74",
        "url": "https://chatwithtraders.com/episode/074-john-walsh-pocketing-100k-from-a-trading-comp-and-making-simplicity-a-priority-w-the-black-cabbie-trader"
      }
    ]
  }
}
```
