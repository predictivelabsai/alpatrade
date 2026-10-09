---
title: Marsten Parker · Volume breakout swing (backtest)
description: Daily-bar backtest of the volume breakout swing method Marsten Parker describes on Chat With Traders (ep. 281). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Marsten Parker
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/281-marsten-parker-the-purely-systematic-wizard-trader
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Marsten Parker · Volume breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Marsten Parker described in a podcast interview. It is **not**
Marsten Parker's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 281 — [281: Marsten Parker - The Purely Systematic Wizard Trader](https://chatwithtraders.com/episode/281-marsten-parker-the-purely-systematic-wizard-trader) · [YouTube](https://www.youtube.com/watch?v=vhx3yeFBlNA)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: systematic; timeframe: swing (few days hold). Universe described:
all common US stocks meeting liquidity and price filters.

### Setup
- unusual volume at least two or three times average, significant move up several percent in one day, prior flat congestion not overbought  
  > "unusual volume, like at least two times average or three times average volume, a significant move, you know, not like up 5 cents on two times average volume, but, you know, up several percent uh in one day. And then the pre prior to that, it should not have already been overbought. So, you know, ideally it's it's like a flat congestion area and then a breakout from there." — ep. 281 [[00:24:54]]
### Entry
- buy breakout at next open market  
  > "place an order to buy or short at the open at market with an attached bracket" — ep. 281 [[00:27:31]]
### Stop
- 7% adverse stop  
  > "5% favorable or 7% adverse" — ep. 281 [[00:27:31]]
### Exits
- 5% target or 7% stop or time stop  
  > "there was also a time stop, so there's basically three three components to the exit" — ep. 281 [[00:22:49]]
- average hold 3-4 days  
  > "most mostly, it was within a few days... average holding period, maybe three, four days" — ep. 281 [[00:28:02]]
### Sizing
- (not stated)
### Market Filter
- (not stated)

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **consolidation_days and consolidation_max_range_pct not specified numerically** → assumption: flat congestion implies prior consolidation but no exact days or range given
- **momentum_lookback_days, trail_ma, partial params, risk_per_trade_pct, max_position_pct, max_positions not specified** → assumption: use 1-day momentum lookback and no trailing/partial as bracket target/stop used instead
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -15.8% | +15.2% |
| Total return | -84.2% | +356.2% |
| Sharpe (daily, N-1) | -1.34 | 0.90 |
| Max drawdown | -84.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -31.0% | |
| CAPM alpha (ann.) / beta | -20.5% / 0.26 | |
| Trades / win rate | 2358 / 26.3% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -16.8% | +17.4% |
| Total return | -66.8% | +161.2% |
| Sharpe (daily, N-1) | -1.45 | 1.00 |
| Max drawdown | -69.1% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -34.2% | |
| CAPM alpha (ann.) / beta | -22.2% / 0.26 | |
| Trades / win rate | 1398 / 25.0% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -14.0% | +12.3% |
| Total return | -51.3% | +73.7% |
| Sharpe (daily, N-1) | -1.17 | 0.76 |
| Max drawdown | -52.3% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -26.4% | |
| CAPM alpha (ann.) / beta | -17.9% / 0.27 | |
| Trades / win rate | 960 / 28.3% | |

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
  "name": "cwt_marsten-parker-breakout",
  "display_name": "Marsten Parker · Volume breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 40,
    "mom_min": 0.1,
    "cons_days": 20,
    "cons_max_range": 0.1,
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
        "episode": "281",
        "url": "https://chatwithtraders.com/episode/281-marsten-parker-the-purely-systematic-wizard-trader"
      }
    ]
  }
}
```
