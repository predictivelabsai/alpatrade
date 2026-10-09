---
title: Jon Boorman · Long-only trend following breakout (backtest)
description: Daily-bar backtest of the long-only trend following breakout method Jon Boorman describes on Chat With Traders (ep. 43). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Jon Boorman
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/043-jon-boorman-buying-stocks-in-uptrends-managing-risk-and-tips-for-long-term-survival
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Jon Boorman · Long-only trend following breakout (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Jon Boorman described in a podcast interview. It is **not**
Jon Boorman's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 43 — [043: Jon Boorman – Buying Stocks in Uptrends, Managing Risk, and Tips for Long Term Survival](https://chatwithtraders.com/episode/043-jon-boorman-buying-stocks-in-uptrends-managing-risk-and-tips-for-long-term-survival) · [YouTube](https://www.youtube.com/watch?v=iOlSqwz5-Fw)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: trend following; timeframe: daily to weekly. Universe described:
US stocks.

### Setup
- Buy stocks in uptrends using new highs screens  
  > "I buy stocks in uptrends and manage risk." — ep. 43 [[00:43:37]]
- New highs on daily or weekly: all-time highs, 52-week highs or 50-day highs  
  > "simple stuff, they're really simple screens, all time highs, 52 week highs, they could be 50 day highs, they just need to be new highs and whatever timeframe best suits you" — ep. 43 [[00:46:42]]
### Entry
- Take signal on new high; act immediately on signal  
  > "when you get your signal, just take it, just instantly acting on it" — ep. 43 [[00:16:28]]
### Stop
- Exit when trend invalidated by price  
  > "exit trends when they're invalidated" — ep. 43 [[00:44:52]]
### Exits
- Exit on trend invalidation by price alone  
  > "if the trend invalidates by price alone, then I'm out" — ep. 43 [[00:50:47]]
### Sizing
- Risk 0.5% of capital per trade  
  > "it's always half a percent" — ep. 43 [[01:05:49]]
### Market Filter
- (not stated)

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact exit rule (e.g. 25-day low) and consolidation filter not stated for stocks** → assumption: Similar to futures example of new 50-day high entry / 25-day low exit
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -5.5% | +15.2% |
| Total return | -45.3% | +356.2% |
| Sharpe (daily, N-1) | -0.35 | 0.90 |
| Max drawdown | -57.6% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -20.6% | |
| CAPM alpha (ann.) / beta | -8.0% / 0.21 | |
| Trades / win rate | 1439 / 28.0% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -6.5% | +17.4% |
| Total return | -33.3% | +161.2% |
| Sharpe (daily, N-1) | -0.47 | 1.00 |
| Max drawdown | -35.1% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -23.9% | |
| CAPM alpha (ann.) / beta | -9.3% / 0.19 | |
| Trades / win rate | 783 / 28.1% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -4.3% | +12.3% |
| Total return | -18.6% | +73.7% |
| Sharpe (daily, N-1) | -0.23 | 0.76 |
| Max drawdown | -35.7% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -16.6% | |
| CAPM alpha (ann.) / beta | -6.4% / 0.23 | |
| Trades / win rate | 656 / 27.9% | |

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
  "name": "cwt_jon-boorman-breakout",
  "display_name": "Jon Boorman · Long-only trend following breakout (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 50,
    "mom_min": 0.3,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.005,
    "max_pos_pct": 0.2,
    "max_positions": 15,
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
        "episode": "43",
        "url": "https://chatwithtraders.com/episode/043-jon-boorman-buying-stocks-in-uptrends-managing-risk-and-tips-for-long-term-survival"
      }
    ]
  }
}
```
