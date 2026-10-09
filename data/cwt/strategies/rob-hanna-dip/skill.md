---
title: Rob Hanna · Quant edge mean-reversion swing (backtest)
description: Daily-bar backtest of the quant edge mean-reversion swing method Rob Hanna describes on Chat With Traders (ep. 269). Template: dip. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Rob Hanna
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/269-rob-hanna-reducing-anxiety-and-drawdowns-through-quantifiable-edges
tags: dip, chat-with-traders, backtest
license: MIT
---

# Rob Hanna · Quant edge mean-reversion swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Rob Hanna described in a podcast interview. It is **not**
Rob Hanna's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 269 — [269: Rob Hanna - Reducing Anxiety and Drawdowns through Quantifiable Edges](https://chatwithtraders.com/episode/269-rob-hanna-reducing-anxiety-and-drawdowns-through-quantifiable-edges) · [YouTube](https://www.youtube.com/watch?v=CiXWgFkSwF8)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: quantitative swing mean-reversion with filters; timeframe: daily. Universe described:
S&P 500 stocks and broad indices.

### Setup
- three down days close at 10-day low above 200-day MA  
  > "what happens if we have uh three down days and we close at a 10day low and we're above the 200 day moving average" — ep. 269 [[00:20:28]]
### Entry
- (not stated)
### Stop
- (not stated)
### Exits
- (not stated)
### Sizing
- (not stated)
### Market Filter
- Fed day after selloff  
  > "when you have the market doing poorly heading into a Fed day it's been an even stronger bullish Edge" — ep. 269 [[00:48:19]]

## How it was backtested
Template **dip** — mean reversion: buy the next open after the close is a set % below its recent high (optional RSI(2) and long-term trend filter), exit on target / stop / close above the 5-day SMA / time. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **No exact numeric parameters, position sizing or full rule set provided for any single system** → assumption: Closest template is dip based on described price-stretch rebounds and 3-down-day example
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +16.3% | +15.2% |
| Total return | +408.8% | +356.2% |
| Sharpe (daily, N-1) | 0.67 | 0.90 |
| Max drawdown | -41.7% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +1.2% | |
| CAPM alpha (ann.) / beta | +7.3% / 0.77 | |
| Trades / win rate | 4310 / 52.8% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +13.6% | +17.4% |
| Total return | +115.0% | +161.2% |
| Sharpe (daily, N-1) | 0.64 | 1.00 |
| Max drawdown | -37.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -3.7% | |
| CAPM alpha (ann.) / beta | +3.4% / 0.71 | |
| Trades / win rate | 2380 / 53.4% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +19.5% | +12.3% |
| Total return | +132.8% | +73.7% |
| Sharpe (daily, N-1) | 0.70 | 0.76 |
| Max drawdown | -32.1% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | +7.1% | |
| CAPM alpha (ann.) / beta | +12.2% / 0.84 | |
| Trades / win rate | 1930 / 52.0% | |

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
  "name": "cwt_rob-hanna-dip",
  "display_name": "Rob Hanna · Quant edge mean-reversion swing (backtest)",
  "kind": "backtest",
  "template": "dip",
  "params": {
    "template": "dip",
    "dip": 0.03,
    "ref_days": 10,
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
    "trend_ma": 200,
    "trail_ma": 0,
    "target": 0.0,
    "stop": 0.0,
    "max_hold": 5,
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
        "episode": "269",
        "url": "https://chatwithtraders.com/episode/269-rob-hanna-reducing-anxiety-and-drawdowns-through-quantifiable-edges"
      }
    ]
  }
}
```
