---
title: Tom Basso · Asymmetric MA trend following (backtest)
description: Daily-bar backtest of the asymmetric ma trend following method Tom Basso describes on Chat With Traders (ep. 271). Template: trend ma. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Tom Basso
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/271-tom-basso-the-sweet-balance-between-risk-and-reward
tags: trend-ma, chat-with-traders, backtest
license: MIT
---

# Tom Basso · Asymmetric MA trend following (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Tom Basso described in a podcast interview. It is **not**
Tom Basso's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 271 — [271: Tom Basso - The Sweet Balance Between Risk and Reward](https://chatwithtraders.com/episode/271-tom-basso-the-sweet-balance-between-risk-and-reward) · [YouTube](https://www.youtube.com/watch?v=g5gNiDO-CSc)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: trend following with hedge overlay; timeframe: long-term position. Universe described:
30 sector ETFs covering most of the S&P 500.

### Setup
- Trade 30 sector ETFs with upward bias via asymmetric MAs  
  > "when I'm trading my 30 sector ETFs which range across almost all the sectors and the markets the reason I do that is using 21 for the upside and 50 for the downside puts a slant towards the upside" — ep. 271 [[00:27:15]]
### Entry
- Go long ETFs on 21-day MA upside signal  
  > "using 21 for the upside and 50 for the downside" — ep. 271 [[00:27:15]]
### Stop
- Exit long ETFs or initiate hedge on 50-day MA downside cross  
  > "50-day to initiate a hedge ... I do the same thing the other way with my long ETF" — ep. 271 [[00:26:13]]
### Exits
- Exit to cash or hedge when 50-day MA signals downtrend  
  > "50-day to initiate a hedge" — ep. 271 [[00:26:13]]
### Sizing
- Volatility-based position sizing across strategies to balance risk  
  > "I set my risk uh in volatility control schemes on my position sizing" — ep. 271 [[00:42:21]]
### Market Filter
- Hedge with single S&P futures when equity exposure needs protection  
  > "if I use an S&P futures hedge" — ep. 271 [[00:09:55]]

## How it was backtested
Template **trend_ma** — trend following: buy the next open after the fast SMA crosses above the slow SMA, exit on a close below the exit SMA or an ATR stop. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact MA crossover direction and confirmation not verbatim** → assumption: Standard MA cross up on 21-day for entry, cross down on 50-day for exit/hedge
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +8.5% | +15.2% |
| Total return | +139.5% | +356.2% |
| Sharpe (daily, N-1) | 0.69 | 0.90 |
| Max drawdown | -20.0% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -6.7% | |
| CAPM alpha (ann.) / beta | +2.1% / 0.44 | |
| Trades / win rate | 2025 / 34.6% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +7.8% | +17.4% |
| Total return | +57.1% | +161.2% |
| Sharpe (daily, N-1) | 0.73 | 1.00 |
| Max drawdown | -20.0% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -9.5% | |
| CAPM alpha (ann.) / beta | +1.1% / 0.40 | |
| Trades / win rate | 1068 / 34.6% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +9.4% | +12.3% |
| Total return | +53.0% | +73.7% |
| Sharpe (daily, N-1) | 0.68 | 0.76 |
| Max drawdown | -16.6% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -3.0% | |
| CAPM alpha (ann.) / beta | +3.7% / 0.48 | |
| Trades / win rate | 957 / 34.5% | |

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
  "name": "cwt_tom-basso-trend_ma",
  "display_name": "Tom Basso · Asymmetric MA trend following (backtest)",
  "kind": "backtest",
  "template": "trend_ma",
  "params": {
    "template": "trend_ma",
    "dip": 0.05,
    "ref_days": 20,
    "rsi_max": 0.0,
    "fast": 21,
    "slow": 50,
    "exit_ma": 50,
    "atr_stop": 0.0,
    "gap_min": 0.04,
    "lookback": 126,
    "top_n": 10,
    "rebalance_days": 21,
    "hold_buffer": 2.0,
    "trend_ma": 200,
    "trail_ma": 0,
    "target": 0.0,
    "stop": 0.0,
    "max_hold": 0,
    "sma5_exit": false,
    "pos_pct": 0.03,
    "max_positions": 30,
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
        "episode": "271",
        "url": "https://chatwithtraders.com/episode/271-tom-basso-the-sweet-balance-between-risk-and-reward"
      }
    ]
  }
}
```
