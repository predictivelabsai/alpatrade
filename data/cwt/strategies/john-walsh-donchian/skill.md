---
title: John Walsh · 52-week-high trend following with a Donchian trailing stop (backtest)
description: Daily-bar backtest of the 52-week-high trend following with a donchian trailing stop method John Walsh describes on Chat With Traders (ep. 74). Template: donchian. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: John Walsh
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/074-john-walsh-pocketing-100k-from-a-trading-comp-and-making-simplicity-a-priority-w-the-black-cabbie-trader
tags: donchian, chat-with-traders, backtest
license: MIT
---

# John Walsh · 52-week-high trend following with a Donchian trailing stop (backtest)

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
Style: position / trend following (long side here); timeframe: daily, holds for months. Universe described:
US stocks scanned on finviz.com.

### Setup
- Long stocks at 52-week highs (Turtle-style: buy new highs, short new lows)  
  > "I long 52 week highs, I short 52 week lows" — ep. 74 [[00:26:51]]
- Smooth uptrend: price higher on the right of a 1-2 year daily chart than the left  
  > "I look over a year or two years daily chart, and I really just want to see a smooth-ish line where it's higher in the right hand side" — ep. 74 [[00:29:55]]
### Entry
- Enter at the market open; entry precision does not matter for a trend trader  
  > "I open at the market open. So, I don't even know where I'm going to get in" — ep. 74 [[00:32:26]]
### Stop
- Trailing stop from a Donchian channel (lowest low of the last 20-40 days), checked after every close and only ever raised  
  > "Donchin channels are, they're essentially just the highest high or the [lowest low]" — ep. 74 [[00:37:24]]
- Channel length  
  > "I found 20, the 20 days pretty good. I've looked at 40, but yeah, between 20 and 40 days" — ep. 74 [[00:38:22]]
- Raise the stop daily  
  > "every day when the market closes, I look if the stop needs to be raised" — ep. 74 [[00:36:58]]
### Exits
- Exit only on the trailing stop: 'I literally get stopped out on every trade'  
  > "I literally get stopped out on every trade" — ep. 74 [[00:36:58]]
### Sizing
- Risk 2-4% of the account per trade, size from the stop distance  
  > "How do you decide on your risk and position size for each trade? You mentioned they're 2 to 4%" — ep. 74 [[00:33:24]]
### Market Filter
- (not stated)

## How it was backtested
Template **donchian** — 52-week-high trend following: after a closing high_days high in a stock above its close a year earlier, buy the next open; stop = lowest low of the prior donchian_days sessions, raised (never lowered) every session; size = risk_pct of equity / stop distance, capped at pos_pct. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **'smooth-ish' trend is visual** → assumption: close above its close 252 sessions earlier
- **channel length 20-40 days and risk 2-4%** → assumption: train-only grid over {20, 40} days × {2%, 4%} risk; position capped at 20% of equity, max 10
- **short side (52-week lows) and earnings filter** → assumption: omitted: long-only, cash-only, no fundamentals
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +20.0% | +15.2% |
| Total return | +608.3% | +356.2% |
| Sharpe (daily, N-1) | 0.81 | 0.90 |
| Max drawdown | -35.5% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +4.8% | |
| CAPM alpha (ann.) / beta | +10.8% / 0.71 | |
| Trades / win rate | 549 / 41.0% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +18.7% | +17.4% |
| Total return | +179.3% | +161.2% |
| Sharpe (daily, N-1) | 0.88 | 1.00 |
| Max drawdown | -35.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +1.3% | |
| CAPM alpha (ann.) / beta | +8.9% / 0.61 | |
| Trades / win rate | 246 / 41.9% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +21.5% | +12.3% |
| Total return | +151.9% | +73.7% |
| Sharpe (daily, N-1) | 0.77 | 0.76 |
| Max drawdown | -35.5% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +9.2% | |
| CAPM alpha (ann.) / beta | +13.7% / 0.83 | |
| Trades / win rate | 303 / 40.3% | |

### Caveats
- **Survivorship bias:** today's S&P 500 members, which flatters long strategies historically.
- Rules were extracted by an LLM from auto-captions / Whisper transcripts; quotes may contain
  transcription errors. Only a small sensitivity grid over the ranges stated in the episode was tried, chosen on the train window only (max Sharpe): donchian_days=20, risk_pct=0.02 → train Sharpe 0.81; donchian_days=20, risk_pct=0.04 → train Sharpe 0.88; donchian_days=40, risk_pct=0.02 → train Sharpe 0.85; donchian_days=40, risk_pct=0.04 → train Sharpe 0.76. Chosen: donchian_days=20, risk_pct=0.04. The test window was never used to choose.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Daily bars, signals from the prior close, cash only; report CAGR, Sharpe, max drawdown,
   alpha vs SPY, trades and win rate over the same period.
3. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "cwt_john-walsh-donchian",
  "display_name": "John Walsh · 52-week-high trend following with a Donchian trailing stop (backtest)",
  "kind": "backtest",
  "template": "donchian",
  "params": {
    "template": "donchian",
    "dip": 0.05,
    "ref_days": 20,
    "rsi_max": 0.0,
    "fast": 20,
    "slow": 50,
    "exit_ma": 50,
    "atr_stop": 3.0,
    "gap_min": 0.04,
    "lookback": 126,
    "top_n": 10,
    "rebalance_days": 21,
    "hold_buffer": 2.0,
    "ret_min": 0.04,
    "vol_mult": 2.0,
    "cons_days": 20,
    "cons_max": 0.25,
    "high_days": 252,
    "donchian_days": 20,
    "risk_pct": 0.04,
    "trend_ma": 0,
    "trail_ma": 0,
    "target": 0.0,
    "stop": 0.0,
    "max_hold": 0,
    "sma5_exit": false,
    "pos_pct": 0.2,
    "max_positions": 10,
    "min_price": 5.0,
    "market_filter": false,
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
        "episode": "74",
        "url": "https://chatwithtraders.com/episode/074-john-walsh-pocketing-100k-from-a-trading-comp-and-making-simplicity-a-priority-w-the-black-cabbie-trader"
      }
    ]
  }
}
```
