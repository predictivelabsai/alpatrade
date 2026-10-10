---
title: Dan Shapiro · Swing breakout after consolidation (backtest)
description: Daily-bar backtest of the swing breakout after consolidation method Dan Shapiro describes on Chat With Traders (ep. 32). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Dan Shapiro
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/032-dan-shapiro-how-to-handle-a-run-of-losses-grind-through-slumps-while-keeping-your-emotions-intact
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Dan Shapiro · Swing breakout after consolidation (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Dan Shapiro described in a podcast interview. It is **not**
Dan Shapiro's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 32 — [032: Dan Shapiro – How to Handle a Run of Losses & Grind Through Slumps, While Keeping Your Emotions Intact](https://chatwithtraders.com/episode/032-dan-shapiro-how-to-handle-a-run-of-losses-grind-through-slumps-while-keeping-your-emotions-intact) · [YouTube](https://www.youtube.com/watch?v=yOOrqholDMY)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: swing trading; timeframe: multi-day holds. Universe described:
US stocks showing initial moves and consolidations.

### Setup
- stock puts in an initial move, bases out for at least 5 days  
  > "I look for a stock that puts in an initial move, bases out for at least 5 days, and once it gets above that initial move, I buy the stock." — ep. 32 [[00:24:22]]
### Entry
- buy when price gets above the initial move high after 5-day base  
  > "once it gets above that initial move, I buy the stock" — ep. 32 [[00:24:22]]
### Stop
- (not stated)
### Exits
- (not stated)
### Sizing
- (not stated)
### Market Filter
- only in uptrending market with defined ranges  
  > "when there's a uptrending market, I don't even want to day trade... I make my money as a swing trader when there's a trending market, there's defined ranges" — ep. 32 [[00:45:47]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **no numeric values for momentum_min_pct, consolidation_max_range_pct, trail_ma or stops** → assumption: use 5 days as consolidation_days and default other params to null
- **mentions supply zones and 60-min pivots but no exact definition** → assumption: treat as discretionary overlay not codable on daily bars
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.7% | +15.2% |
| Total return | -52.4% | +356.2% |
| Sharpe (daily, N-1) | -0.21 | 0.90 |
| Max drawdown | -72.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -21.8% | |
| CAPM alpha (ann.) / beta | -10.3% / 0.36 | |
| Trades / win rate | 2013 / 28.8% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -9.2% | +17.4% |
| Total return | -43.8% | +161.2% |
| Sharpe (daily, N-1) | -0.41 | 1.00 |
| Max drawdown | -51.6% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -26.5% | |
| CAPM alpha (ann.) / beta | -13.0% / 0.30 | |
| Trades / win rate | 1073 / 29.9% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -3.5% | +12.3% |
| Total return | -15.4% | +73.7% |
| Sharpe (daily, N-1) | -0.02 | 0.76 |
| Max drawdown | -45.6% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -15.8% | |
| CAPM alpha (ann.) / beta | -6.4% / 0.45 | |
| Trades / win rate | 940 / 27.4% | |

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
  "name": "cwt_dan-shapiro-breakout",
  "display_name": "Dan Shapiro · Swing breakout after consolidation (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 63,
    "mom_min": 0.3,
    "cons_days": 5,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.2,
    "max_positions": 10,
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
        "episode": "32",
        "url": "https://chatwithtraders.com/episode/032-dan-shapiro-how-to-handle-a-run-of-losses-grind-through-slumps-while-keeping-your-emotions-intact"
      }
    ]
  }
}
```
