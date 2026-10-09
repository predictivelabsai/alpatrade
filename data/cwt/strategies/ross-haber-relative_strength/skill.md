---
title: Ross Haber · CAN SLIM relative strength breakout (backtest)
description: Daily-bar backtest of the can slim relative strength breakout method Ross Haber describes on Chat With Traders (ep. 294). Template: relative strength. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Ross Haber
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/294-ross-haber-stock-leaders-and-timeless-strategies-still-effective-today
tags: relative-strength, chat-with-traders, backtest
license: MIT
---

# Ross Haber · CAN SLIM relative strength breakout (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Ross Haber described in a podcast interview. It is **not**
Ross Haber's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 294 — [294 · Ross Haber - Stock Leaders and Timeless Strategies Still Effective Today](https://chatwithtraders.com/episode/294-ross-haber-stock-leaders-and-timeless-strategies-still-effective-today) · [YouTube](https://www.youtube.com/watch?v=28LOSLtoJdA)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: growth momentum; timeframe: swing to position. Universe described:
US stocks, top 200 leaders from ~12000.

### Setup
- Current quarterly earnings 25%+ yoy growth, preferably triple digit accelerating  
  > "you want to see at least 25% growth for the last for the most current three quarters you know and you learn that's a bare minimum um I require triple digit growth preferably um accelerating triple digit growth" — ep. 294 [[00:22:06]]
- Annual earnings growth ~20%+ for three years  
  > "on an annual basis you got a little e it's a little easier on the Restriction you're at about 20% for three years obviously more is better triple digit is better" — ep. 294 [[00:23:11]]
- New product, service or management  
  > "n um is either a new product new service or New Management" — ep. 294 [[00:25:46]]
- Relative strength new highs ahead of price  
  > "relative strength new highs ahead of price understanding exactly what that is and when to use that that works as good today as it did in 1890" — ep. 294 [[00:13:12]]
### Entry
- Buy at consolidation pivot or early stage base breakout on volume  
  > "I've sprinkled in some Stan Weinstein right so I've got my early buy points what I call consolidation pivots instead of Base pivots which are much earlier up the right side and if I can combine that with my relative strength new highs or relative strength line leading price" — ep. 294 [[00:18:29]]
### Stop
- Sell stop 7-8% below buy point  
  > "that 7 to eight% that you hear all of fin twit talk about as their Max sell stop and a lot of it comes from how to make money in stocks" — ep. 294 [[00:46:04]]
### Exits
- Scale out on break of 21-day SMA or 10-day; personality based  
  > "I have a very specific Line in the Sand relative to my performance in the account in that stock and where it that stock is overall in its run versus where I would expect from it" — ep. 294 [[00:42:54]]
- Use 21 day simple moving average as line in the sand  
  > "I use the 21 days simple moving average as a line in the sand for me" — ep. 294 [[00:42:22]]
### Sizing
- Scale in progressively, risk management with stops  
  > "the way that I bought them I'm actually managing risk and have much better control of my risk" — ep. 294 [[00:55:58]]
### Market Filter
- Market direction via follow through day on NASDAQ or S&P; watch leaders for breadth and rotation  
  > "getting the direction of the market right is 50 at least half the ball game" — ep. 294 [[00:37:44]]
- Follow through day 1.75% up on higher volume days 4-7 after first up day in downtrend  
  > "the market needs to be up at least 1.75% on more volume than the prior day volume doesn't have to be more than average it doesn't even have to be big it just has to be bigger than the prior day so an ideal follow through day I say happens on days four through seven" — ep. 294 [[00:39:49]]

## How it was backtested
Template **relative_strength** — relative-strength rotation: every N sessions (at most weekly) hold the strongest names by trailing return (above their trend SMA), equal weight, a holding is kept while it still ranks in the top 2N (hysteresis against churn), cash when SPY < SMA200. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Qualitative stock personality, leader action and exact scaling rules** → assumption: Approximated via relative strength top stocks, 21/50 MA exits and 7-8% stops
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +19.2% | +15.2% |
| Total return | +562.4% | +356.2% |
| Sharpe (daily, N-1) | 1.04 | 0.90 |
| Max drawdown | -22.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +4.1% | |
| CAPM alpha (ann.) / beta | +11.2% / 0.52 | |
| Trades / win rate | 3088 / 43.2% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +11.6% | +17.4% |
| Total return | +93.4% | +161.2% |
| Sharpe (daily, N-1) | 0.77 | 1.00 |
| Max drawdown | -22.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -5.7% | |
| CAPM alpha (ann.) / beta | +3.9% / 0.48 | |
| Trades / win rate | 1554 / 43.1% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +29.8% | +12.3% |
| Total return | +245.8% | +73.7% |
| Sharpe (daily, N-1) | 1.33 | 0.76 |
| Max drawdown | -17.4% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +17.5% | |
| CAPM alpha (ann.) / beta | +20.9% / 0.57 | |
| Trades / win rate | 1534 / 43.4% | |

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
  "name": "cwt_ross-haber-relative_strength",
  "display_name": "Ross Haber · CAN SLIM relative strength breakout (backtest)",
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
    "lookback": 252,
    "top_n": 50,
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
        "episode": "294",
        "url": "https://chatwithtraders.com/episode/294-ross-haber-stock-leaders-and-timeless-strategies-still-effective-today"
      }
    ]
  }
}
```
