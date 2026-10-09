---
title: Stan Gluzman · Breakout swing long (backtest)
description: Daily-bar backtest of the breakout swing long method Stan Gluzman describes on Chat With Traders (ep. 211). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Stan Gluzman
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/211-stan-gluzman-one-bias-one-objective-make-money
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Stan Gluzman · Breakout swing long (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Stan Gluzman described in a podcast interview. It is **not**
Stan Gluzman's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 211 — [211: Stan Gluzman – One Bias, One Objective: Make Money](https://chatwithtraders.com/episode/211-stan-gluzman-one-bias-one-objective-make-money) · [YouTube](https://www.youtube.com/watch?v=fwh8Sdu4Ses)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: swing breakout; timeframe: daily with 5-min entry timing. Universe described:
mid caps and large caps, real companies, avoid dilutive small caps.

### Setup
- stocks strong for past couple of months up to six months  
  > "i'll scan for stocks that have been strong strong for past couple of months up to like six months" — ep. 211 [[00:27:18]]
- tight consolidations for a couple weeks or couple days then break out of tight pattern  
  > "i'll find you know tight consolidations where a stock you know went up consolidated for a couple weeks or a couple days couple weeks and then starting to break out of a tight pattern" — ep. 211 [[00:27:18]]
### Entry
- buy the breakout on daily, time on 5-min or at alert if not extended  
  > "i'll just buy the breakouts... i'll put it on like a five minute chart and i'll i'll wait for a dip or or i'll just buy the breakout on the daily" — ep. 211 [[00:28:50]]
### Stop
- stop below low of the day  
  > "i'll see where the low of the day is and i'll put the stop below the low of the day" — ep. 211 [[00:28:50]]
### Exits
- trail core with 10 or 20 EMA on daily, trim into strength  
  > "trail it with moving averages... it's either 10 or 20 ema on a daily chart" — ep. 211 [[00:35:35]]
### Sizing
- risk per trade 1/6 to 1/8 of daily lockout (median green day x2)  
  > "my risk per trade is a fraction of that number so let's say my risk per trade is like 1 8 or 1 6 of my daily lockout" — ep. 211 [[00:15:46]]
### Market Filter
- (not stated)

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **exact momentum_lookback_days and consolidation_days not numeric** → assumption: use 60-120 days momentum, 5-15 days consolidation
- **trail_ma value uncertain between 10/20** → assumption: use 20
- **no explicit momentum_min_pct or consolidation_max_range_pct** → assumption: standard 20% / 10% defaults
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -13.8% | +15.2% |
| Total return | -79.8% | +356.2% |
| Sharpe (daily, N-1) | -0.82 | 0.90 |
| Max drawdown | -82.6% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -29.0% | |
| CAPM alpha (ann.) / beta | -18.9% / 0.35 | |
| Trades / win rate | 2386 / 25.4% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -15.3% | +17.4% |
| Total return | -63.0% | +161.2% |
| Sharpe (daily, N-1) | -1.00 | 1.00 |
| Max drawdown | -64.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -32.6% | |
| CAPM alpha (ann.) / beta | -20.8% / 0.31 | |
| Trades / win rate | 1354 / 24.3% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -11.7% | +12.3% |
| Total return | -44.7% | +73.7% |
| Sharpe (daily, N-1) | -0.62 | 0.76 |
| Max drawdown | -52.6% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -24.0% | |
| CAPM alpha (ann.) / beta | -16.1% / 0.39 | |
| Trades / win rate | 1032 / 26.9% | |

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
  "name": "cwt_stan-gluzman-breakout",
  "display_name": "Stan Gluzman · Breakout swing long (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 90,
    "mom_min": 0.2,
    "cons_days": 10,
    "cons_max_range": 0.1,
    "trail_ma": 20,
    "partial_days": 2,
    "partial_frac": 0.1,
    "max_stop_adr": 1.0,
    "risk_pct": 0.005,
    "max_pos_pct": 0.25,
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
        "episode": "211",
        "url": "https://chatwithtraders.com/episode/211-stan-gluzman-one-bias-one-objective-make-money"
      }
    ]
  }
}
```
