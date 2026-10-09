---
title: Vincent Bruzzese · Relative strength daily swing (backtest)
description: Daily-bar backtest of the relative strength daily swing method Vincent Bruzzese describes on Chat With Traders (ep. 312). Template: relative strength. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Vincent Bruzzese
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/312-vincent-bruzzese-aka-hari-seldon
tags: relative-strength, chat-with-traders, backtest
license: MIT
---

# Vincent Bruzzese · Relative strength daily swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Vincent Bruzzese described in a podcast interview. It is **not**
Vincent Bruzzese's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 312 — [312 · Vincent Bruzzese - Battling Irrational Markets - and the Battle Within](https://chatwithtraders.com/episode/312-vincent-bruzzese-aka-hari-seldon)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: relative strength with SMA confirmation; timeframe: daily. Universe described:
US stocks with relative strength to SPY.

### Setup
- Market (SPY) first; avoid low probability environments  
  > "the market comes first, right? So everything revolves around the market. 75% of all stocks... will go with SPI." — ep. 312 [[00:38:00]]
- Stock must show relative strength to SPY  
  > "second is, is a stock relatively strong or relatively weak to the market?... if you look today at Google... still green... institutions are buying that stock" — ep. 312 [[00:38:44]]
### Entry
- Daily chart not extended, above all SMAs, above technical indicators, near all-time high  
  > "I took this trade because on the daily chart, it's not extended. It's above all of its SMAs. It's above its technical indicators. It's strong, relatively strong against the market." — ep. 312 [[00:00:50]]
### Stop
- Mental stop if SPY breaks 50 SMA; no hard stops for longer holds  
  > "I'm looking at the SMA 50 on spy as my line... Spy needs to break that line for me to no longer want to take bullish links." — ep. 312 [[00:41:21]]
### Exits
- Hold winners; avoid quick profit taking due to skepticism  
  > "traders in general do not come from a rich mentality... The moment you get a dollar profit, they run away with the money" — ep. 312 [[00:12:16]]
### Sizing
- Position size based on business plan for consistent monthly returns  
  > "if you say, I need to make $10,000 a month, you want that to be within $8,000 to $12,000." — ep. 312 [[00:09:43]]
### Market Filter
- Only trade in direction supported by SPY trend; SPY above 50 SMA for longs  
  > "Spy needs to break that line for me to no longer want to take bullish links." — ep. 312 [[00:41:29]]

## How it was backtested
Template **relative_strength** — relative-strength rotation: every N sessions (at most weekly) hold the strongest names by trailing return (above their trend SMA), equal weight, a holding is kept while it still ranks in the top 2N (hysteresis against churn), cash when SPY < SMA200. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **No exact lookback, top_n or rebalance_days specified for relative strength scan** → assumption: Use standard 20-60 session lookback and daily rebalance as implied by daily chart focus
- **Mentions options and futures but core rules are for stock direction** → assumption: Focus on long equity rules only per engine constraints
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +19.1% | +15.2% |
| Total return | +555.7% | +356.2% |
| Sharpe (daily, N-1) | 0.80 | 0.90 |
| Max drawdown | -40.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +4.0% | |
| CAPM alpha (ann.) / beta | +11.7% / 0.59 | |
| Trades / win rate | 1703 / 48.0% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +6.2% | +17.4% |
| Total return | +43.8% | +161.2% |
| Sharpe (daily, N-1) | 0.39 | 1.00 |
| Max drawdown | -40.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -11.1% | |
| CAPM alpha (ann.) / beta | -0.6% / 0.51 | |
| Trades / win rate | 972 / 49.1% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +37.5% | +12.3% |
| Total return | +354.1% | +73.7% |
| Sharpe (daily, N-1) | 1.17 | 0.76 |
| Max drawdown | -32.3% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +25.2% | |
| CAPM alpha (ann.) / beta | +27.7% / 0.70 | |
| Trades / win rate | 731 / 46.5% | |

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
  "name": "cwt_vincent-bruzzese-relative_strength",
  "display_name": "Vincent Bruzzese · Relative strength daily swing (backtest)",
  "kind": "backtest",
  "template": "relative_strength",
  "params": {
    "template": "relative_strength",
    "dip": 0.05,
    "ref_days": 20,
    "rsi_max": 0.0,
    "fast": 20,
    "slow": 50,
    "exit_ma": 50,
    "atr_stop": 3.0,
    "gap_min": 0.04,
    "lookback": 20,
    "top_n": 10,
    "rebalance_days": 5,
    "hold_buffer": 2.0,
    "trend_ma": 50,
    "trail_ma": 0,
    "target": 0.0,
    "stop": 0.0,
    "max_hold": 0,
    "sma5_exit": false,
    "pos_pct": 0.1,
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
    "engine": "engine.backtest.templates",
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
        "episode": "312",
        "url": "https://chatwithtraders.com/episode/312-vincent-bruzzese-aka-hari-seldon"
      }
    ]
  }
}
```
