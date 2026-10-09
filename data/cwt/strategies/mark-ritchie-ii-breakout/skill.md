---
title: Mark Ritchie II · Minervini-style momentum breakout (backtest)
description: Daily-bar backtest of the minervini-style momentum breakout method Mark Ritchie II describes on Chat With Traders (ep. 290). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Mark Ritchie II
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/290-mark-ritchie-ii-price-action-swing-trading-equities-from-the-long-side
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Mark Ritchie II · Minervini-style momentum breakout (backtest)

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
Style: discretionary swing trading; timeframe: swing (days to weeks). Universe described:
US equities screened daily for earnings/sales growth and relative strength.

### Setup
- Long-term uptrend on weekly chart or 200-day MA  
  > "I want something in a long-term uptrend and then I'm looking at defining that based upon the weekly chart and or maybe something like the 200 day moving average" — ep. 290 [[00:35:01]]
- Tight consolidation or pivot point after uptrend  
  > "I'm looking for really the best way again to in very short form is a tight consolidation or pivot point where I can know in relatively short order if I'm right or wrong" — ep. 290 [[00:35:31]]
### Entry
- Technical confirmation of breakout from consolidation in uptrend  
  > "the actual timing and execution of Trades it's always going to be because of the technicals or I'm looking for technical confirmation" — ep. 290 [[00:35:01]]
### Stop
- Max individual stop 8-10%, long-term average under 5%  
  > "I don't take individual price stops or stop risk on a percentage basis of more than eight eight% 8 to 10 being the Max and usually I want to be mid single digits my long-term average is under 5%" — ep. 290 [[00:41:11]]
### Exits
- Partial profits at multiple of risk when stalling; trail on strength  
  > "if I'm already at a multiple of my risk and the stock has run and now it starts to stall well that's usually where I'm thinking I can take partial profits" — ep. 290 [[00:37:35]]
### Sizing
- Risk per trade mid-single digits percent of capital  
  > "my long-term average is under 5%" — ep. 290 [[00:41:11]]
### Market Filter
- Raise cash on signs of poor relative strength in growth areas ahead of bear markets  
  > "aggressive long longside Trader at times but have not been caught in any of these major bare markets and declines we've had over the last 15 16 years it's because the stocks give you a lead on all that stuff" — ep. 290 [[00:20:55]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact momentum_lookback_days, consolidation_days, trail_ma, partial_frac, max_positions not numerically specified** → assumption: Use 200-day MA for trend, 20-day MA trail, 2-5 positions typical for swing
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -13.6% | +15.2% |
| Total return | -79.1% | +356.2% |
| Sharpe (daily, N-1) | -0.82 | 0.90 |
| Max drawdown | -85.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -28.7% | |
| CAPM alpha (ann.) / beta | -17.9% / 0.30 | |
| Trades / win rate | 1596 / 28.6% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -17.6% | +17.4% |
| Total return | -68.7% | +161.2% |
| Sharpe (daily, N-1) | -1.33 | 1.00 |
| Max drawdown | -70.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -35.0% | |
| CAPM alpha (ann.) / beta | -23.0% / 0.26 | |
| Trades / win rate | 885 / 27.3% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -8.1% | +12.3% |
| Total return | -33.1% | +73.7% |
| Sharpe (daily, N-1) | -0.36 | 0.76 |
| Max drawdown | -52.2% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -20.4% | |
| CAPM alpha (ann.) / beta | -11.3% / 0.35 | |
| Trades / win rate | 711 / 30.2% | |

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
  "name": "cwt_mark-ritchie-ii-breakout",
  "display_name": "Mark Ritchie II · Minervini-style momentum breakout (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 200,
    "mom_min": 0.3,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.5,
    "max_stop_adr": 1.0,
    "risk_pct": 0.02,
    "max_pos_pct": 0.2,
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
        "episode": "290",
        "url": "https://chatwithtraders.com/episode/290-mark-ritchie-ii-price-action-swing-trading-equities-from-the-long-side"
      }
    ]
  }
}
```
