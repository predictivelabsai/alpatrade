---
title: Mark Ritchie II · Minervini-style trend template + pivot breakout (backtest)
description: Daily-bar backtest of the minervini-style trend template + pivot breakout method Mark Ritchie II describes on Chat With Traders (ep. 290). Template: trend template. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Mark Ritchie II
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/290-mark-ritchie-ii-price-action-swing-trading-equities-from-the-long-side
tags: trend-template, chat-with-traders, backtest
license: MIT
---

# Mark Ritchie II · Minervini-style trend template + pivot breakout (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Mark Ritchie II described in a podcast interview. It is **not**
Mark Ritchie II's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 290 — [290 · Mark Ritchie II - Price-Action, Swing Trading Equities from the Long Side](https://chatwithtraders.com/episode/290-mark-ritchie-ii-price-action-swing-trading-equities-from-the-long-side) · [YouTube](https://www.youtube.com/watch?v=MtI1PThXoaU)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: price-action swing trading, long side; timeframe: daily, days to weeks. Universe described:
US equities screened daily for earnings/sales growth and relative strength.

### Setup
- Method is Mark Minervini's (SEPA, after William O'Neil)  
  > "90% of it was taught to me by Mark minini" — ep. 290 [[00:19:53]]
- Only stocks in a long-term uptrend (weekly chart / 200-day MA); never bottom fishing  
  > "I want something in a long-term uptrend ... based upon the weekly uh chart and ... maybe something like the 200 day moving average" — ep. 290 [[00:35:01]]
### Entry
- Buy the breakout from the base (discretionary chart read)  
  > "for discretionary breakout type Traders" — ep. 290 [[00:38:37]]
### Stop
- Stop at most 8% (8-10 the max), usually mid single digits; long-term average loss under 5%  
  > "I don't take um individual price stops ... more than eight eight% 8 to 10 being the Max" — ep. 290 [[00:41:11]]
- Tight stops  
  > "be mid single digits my long-term average is under 5%" — ep. 290 [[00:41:44]]
### Exits
- Don't sell a stock that is acting well for less than the average loss; trail it  
  > "as a rule I don't want to sell a stock that's acting well for less than my ave[rage loss]" — ep. 290 [[00:41:44]]
- Protect gains with a back stop or trailing stop  
  > "protection mode you can set some type of a back stop or a trailing stop" — ep. 290 [[00:40:40]]
### Sizing
- Risk 0.5-1% of capital per trade  
  > "I'm not going to risk more than I think it was something like 1% of capital or 50 basis points half a percent" — ep. 290 [[00:12:31]]
### Market Filter
- Hardest periods are corrections / bear markets; growth areas trade poorly first  
  > "coming out of bare markets ... where it's harder to get positioned with sort of a tight stop" — ep. 290 [[00:46:27]]

## How it was backtested
Template **trend_template** — Minervini-style trend template (close > SMA50 > SMA150 > SMA200, SMA200 rising, within 25% of the 52-week high, >= 30% above the low) on the prior close, then a buy-stop at the prior ref_days high (fill max(open, pivot)); stop below the fill (an entry-day low through it counts, conservatively), exit on a close below SMA trail_ma; size = risk_pct / stop distance. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **'long-term uptrend' and the base are discretionary** → assumption: Minervini trend template: close > SMA50 > SMA150 > SMA200, SMA200 rising over 21 sessions, within 25% of the 52-week high, ≥30% above the 52-week low
- **pivot / breakout point is a chart read (VCP)** → assumption: buy-stop at the prior 20-session high: fill max(open, pivot) when the high reaches it
- **stop 'mid single digits', max 8%** → assumption: train-only grid over a 5% or 8% stop below the fill (entry-day low counts, conservative)
- **trailing exit not specified** → assumption: exit on a close below the 50-day SMA (Minervini's usual line)
- **sizing: risk 1% per trade** → assumption: position = 1% of equity / stop distance, capped at 20% of equity, max 10; SPY SMA10 > SMA20 market filter; no earnings/fundamental screen
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +19.6% | +15.2% |
| Total return | +587.1% | +356.2% |
| Sharpe (daily, N-1) | 0.80 | 0.90 |
| Max drawdown | -40.7% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +4.5% | |
| CAPM alpha (ann.) / beta | +11.3% / 0.66 | |
| Trades / win rate | 603 / 34.7% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +12.2% | +17.4% |
| Total return | +99.5% | +161.2% |
| Sharpe (daily, N-1) | 0.67 | 1.00 |
| Max drawdown | -24.1% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -5.2% | |
| CAPM alpha (ann.) / beta | +3.8% / 0.55 | |
| Trades / win rate | 295 / 37.6% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +30.1% | +12.3% |
| Total return | +248.5% | +73.7% |
| Sharpe (daily, N-1) | 0.96 | 0.76 |
| Max drawdown | -35.4% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +17.7% | |
| CAPM alpha (ann.) / beta | +21.5% / 0.79 | |
| Trades / win rate | 308 / 31.8% | |

### Caveats
- **Survivorship bias:** today's S&P 500 members, which flatters long strategies historically.
- Rules were extracted by an LLM from auto-captions / Whisper transcripts; quotes may contain
  transcription errors. Only a small sensitivity grid over the ranges stated in the episode was tried, chosen on the train window only (max Sharpe): stop=0.05 → train Sharpe 0.43; stop=0.08 → train Sharpe 0.67. Chosen: stop=0.08. The test window was never used to choose.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Daily bars, signals from the prior close, cash only; report CAGR, Sharpe, max drawdown,
   alpha vs SPY, trades and win rate over the same period.
3. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "cwt_mark-ritchie-ii-trend_template",
  "display_name": "Mark Ritchie II · Minervini-style trend template + pivot breakout (backtest)",
  "kind": "backtest",
  "template": "trend_template",
  "params": {
    "template": "trend_template",
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
    "risk_pct": 0.01,
    "trend_ma": 0,
    "trail_ma": 50,
    "target": 0.0,
    "stop": 0.08,
    "max_hold": 0,
    "sma5_exit": false,
    "pos_pct": 0.2,
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
        "episode": "290",
        "url": "https://chatwithtraders.com/episode/290-mark-ritchie-ii-price-action-swing-trading-equities-from-the-long-side"
      }
    ]
  }
}
```
