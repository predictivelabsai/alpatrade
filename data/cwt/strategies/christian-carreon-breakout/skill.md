---
title: Christian Carreon · Box breakout trend following (backtest)
description: Daily-bar backtest of the box breakout trend following method Christian Carreon describes on Chat With Traders (ep. 254). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Christian Carreon
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/254-christian-carreon
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Christian Carreon · Box breakout trend following (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Christian Carreon described in a podcast interview. It is **not**
Christian Carreon's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 254 — [254: Christian Carreon - Kidney Disease, Poverty, and Jail Time to Going All In On the Markets](https://chatwithtraders.com/episode/254-christian-carreon) · [YouTube](https://www.youtube.com/watch?v=5cyJWommOqE)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: rules-based trend-following breakout from consolidation; timeframe: daily swing (also 5-min day trade). Universe described:
US stocks mainly technology sector; also E-mini futures.

### Setup
- Identify rectangular consolidation zone (box) of 1 month or longer around flat 50-day MA  
  > "a month-long consolidation, which is one of the requirements for time... 50 MA box, which is a box that's surrounded by the 50-day moving average" — ep. 254 [[00:32:21]]
- Use TTM squeeze red for 3-4 week contraction confirming box  
  > "When you have these contractions take place, the TTM squeeze changes colors... Red being the most aggressive contraction... 30 days of a squeeze in price, you have a red squeeze indicator" — ep. 254 [[00:33:58]]
### Entry
- Enter long on breakout above the box consolidation in direction of rising 50MA  
  > "it looks to enter at the break of that consolidation period. And it looks to participate in the trend... price will most likely move up out of it and continue higher" — ep. 254 [[00:27:08]]
### Stop
- Stop below the box low or lower zone (e.g. 3920 in example)  
  > "it broke below it around 3920... you get short on a break of 3920... understanding of where our stops should be" — ep. 254 [[00:32:54]]
### Exits
- Exit at next higher zone or target resistance  
  > "exit at the next zone above it... move from 4,100... to 4,300" — ep. 254 [[00:26:37]]
### Sizing
- Risk ~5% per trade on all-in A+ setups; can size up to all-in when conditions met  
  > "risk per trade is close to 4%... all-in trades set out to risk about 5% of his account value" — ep. 254 [[00:49:08]]
### Market Filter
- Above key zone (e.g. 3900) participate in uptrends only; below stay cash or short  
  > "if the market gets above 3,900, I want to participate in uptrends. If the market gets below 3,900, I want to participate in downtrends or just stay in cash" — ep. 254 [[00:26:04]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact momentum_lookback_days, consolidation_max_range_pct, trail_ma not specified numerically** → assumption: Use 20-30 trading days for month-long box and 50MA as trend filter per quotes
- **Short-side rules mentioned but engine is long-only** → assumption: Focus only on long breakout rules
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -5.4% | +15.2% |
| Total return | -44.8% | +356.2% |
| Sharpe (daily, N-1) | -0.53 | 0.90 |
| Max drawdown | -54.2% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -20.5% | |
| CAPM alpha (ann.) / beta | -6.9% / 0.12 | |
| Trades / win rate | 460 / 24.3% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -5.9% | +17.4% |
| Total return | -30.6% | +161.2% |
| Sharpe (daily, N-1) | -0.59 | 1.00 |
| Max drawdown | -39.4% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -23.3% | |
| CAPM alpha (ann.) / beta | -7.4% / 0.10 | |
| Trades / win rate | 255 / 22.0% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -4.9% | +12.3% |
| Total return | -21.2% | +73.7% |
| Sharpe (daily, N-1) | -0.46 | 0.76 |
| Max drawdown | -29.8% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -17.2% | |
| CAPM alpha (ann.) / beta | -6.3% / 0.14 | |
| Trades / win rate | 205 / 27.3% | |

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
  "name": "cwt_christian-carreon-breakout",
  "display_name": "Christian Carreon · Box breakout trend following (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 40,
    "mom_min": 0.3,
    "cons_days": 20,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.02,
    "max_pos_pct": 0.25,
    "max_positions": 3,
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
        "episode": "254",
        "url": "https://chatwithtraders.com/episode/254-christian-carreon"
      }
    ]
  }
}
```
