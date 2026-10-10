---
title: Marsten Parker · Unusual-volume momentum with a 5%/7% bracket (backtest)
description: Daily-bar backtest of the unusual-volume momentum with a 5%/7% bracket method Marsten Parker describes on Chat With Traders (ep. 281). Template: volume spike. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Marsten Parker
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/281-marsten-parker-the-purely-systematic-wizard-trader
tags: volume-spike, chat-with-traders, backtest
license: MIT
---

# Marsten Parker · Unusual-volume momentum with a 5%/7% bracket (backtest)

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
Style: systematic short-term swing (long side); timeframe: daily scan after the close, hold ~3-4 days. Universe described:
all common US stocks meeting liquidity and price filters.

### Setup
- Scan all liquid US common stocks after the close for unusual volume (≥2-3× average) and a significant up move (several percent in one day)  
  > "unusual volume, like at least two times average or three times average volume, a significant move ... up several percent uh in one day" — ep. 281 [[00:24:54]]
- Not already overbought: ideally a flat congestion area, then the breakout  
  > "prior to that, it should not have already been overbought ... ideally it's it's like a flat congestion area and then a br[eakout]" — ep. 281 [[00:25:25]]
### Entry
- Buy at the next open at market  
  > "place an order to buy or short at the open at market with an attached bracket of a target and a stop" — ep. 281 [[00:26:59]]
### Stop
- Stop 7% below the entry (bracket, one-cancels-other)  
  > "calculated in advance as ... 5% favorable or 7% adverse ... 5% up and 7% down" — ep. 281 [[00:27:31]]
### Exits
- Target +5% above the entry  
  > "I think we were using like a 5% uh target and a 7% stop initially" — ep. 281 [[00:21:47]]
- Time stop: average hold 3-4 days  
  > "there was also a time stop, so there's basically three three components to the exit" — ep. 281 [[00:21:47]]
- Holding period  
  > "a few days was the average holding period, maybe three, four days" — ep. 281 [[00:28:02]]
### Sizing
- ~10% of the account per position  
  > "each position was 10% of my a[ccount] ... on average around that size. 10 to 15" — ep. 281 [[00:40:32]]
### Market Filter
- (not stated)

## How it was backtested
Template **volume_spike** — unusual-volume momentum: after a close-to-close gain of at least ret_min on volume of at least vol_mult x its prior 50-day average, out of a non-extended base (prior cons_days range <= cons_max), buy the next open with a +target / -stop bracket (stop checked first on a day that touches both) and exit at the close of session max_hold. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **'several percent' and '2-3× average volume' are not exact** → assumption: small train-only grid: gain ≥ 3% or 5%, volume ≥ 2× or 3× its 50-day average
- **'not overbought / flat congestion' is discretionary** → assumption: range (max high / min low) of the 20 sessions before the signal day ≤ 25%
- **time-stop length not stated, only the 3-4 day average hold** → assumption: exit at the close of session 3 or 4 (train-only grid)
- **short side (breakdowns on heavier volume) and the later mean-reversion systems** → assumption: omitted: long-only, cash-only engine; this is his original 1998-2015 long side
- **10% sizing was for the later mean-reversion book** → assumption: 10% of equity per position, max 10 positions; no market filter (none stated)
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +1.5% | +15.2% |
| Total return | +17.7% | +356.2% |
| Sharpe (daily, N-1) | 0.28 | 0.90 |
| Max drawdown | -15.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -13.6% | |
| CAPM alpha (ann.) / beta | +0.1% / 0.11 | |
| Trades / win rate | 1710 / 51.2% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +2.4% | +17.4% |
| Total return | +15.1% | +161.2% |
| Sharpe (daily, N-1) | 0.44 | 1.00 |
| Max drawdown | -11.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -15.0% | |
| CAPM alpha (ann.) / beta | +0.8% / 0.10 | |
| Trades / win rate | 953 / 51.8% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +0.4% | +12.3% |
| Total return | +2.1% | +73.7% |
| Sharpe (daily, N-1) | 0.10 | 0.76 |
| Max drawdown | -15.9% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -11.9% | |
| CAPM alpha (ann.) / beta | -0.9% / 0.12 | |
| Trades / win rate | 757 / 50.3% | |

### Caveats
- **Survivorship bias:** today's S&P 500 members, which flatters long strategies historically.
- Rules were extracted by an LLM from auto-captions / Whisper transcripts; quotes may contain
  transcription errors. Only a small sensitivity grid over the ranges stated in the episode was tried, chosen on the train window only (max Sharpe): ret_min=0.03, vol_mult=2.0, max_hold=3 → train Sharpe 0.07; ret_min=0.03, vol_mult=2.0, max_hold=4 → train Sharpe 0.25; ret_min=0.03, vol_mult=3.0, max_hold=3 → train Sharpe 0.28; ret_min=0.03, vol_mult=3.0, max_hold=4 → train Sharpe 0.28; ret_min=0.05, vol_mult=2.0, max_hold=3 → train Sharpe 0.25; ret_min=0.05, vol_mult=2.0, max_hold=4 → train Sharpe 0.34; ret_min=0.05, vol_mult=3.0, max_hold=3 → train Sharpe 0.44; ret_min=0.05, vol_mult=3.0, max_hold=4 → train Sharpe 0.44. Chosen: ret_min=0.05, vol_mult=3.0, max_hold=3. The test window was never used to choose.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Daily bars, signals from the prior close, cash only; report CAGR, Sharpe, max drawdown,
   alpha vs SPY, trades and win rate over the same period.
3. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "cwt_marsten-parker-volume_spike",
  "display_name": "Marsten Parker · Unusual-volume momentum with a 5%/7% bracket (backtest)",
  "kind": "backtest",
  "template": "volume_spike",
  "params": {
    "template": "volume_spike",
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
    "ret_min": 0.05,
    "vol_mult": 3.0,
    "cons_days": 20,
    "cons_max": 0.25,
    "high_days": 252,
    "donchian_days": 20,
    "risk_pct": 0.0,
    "trend_ma": 0,
    "trail_ma": 0,
    "target": 0.05,
    "stop": 0.07,
    "max_hold": 3,
    "sma5_exit": false,
    "pos_pct": 0.1,
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
        "episode": "281",
        "url": "https://chatwithtraders.com/episode/281-marsten-parker-the-purely-systematic-wizard-trader"
      }
    ]
  }
}
```
