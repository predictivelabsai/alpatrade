---
title: Ivaylo Ivanhoff · Momentum breakout swing (backtest)
description: Daily-bar backtest of the momentum breakout swing method Ivaylo Ivanhoff describes on Chat With Traders (ep. 24). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Ivaylo Ivanhoff
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/024-ivaylo-ivanhoff-riding-industry-momentum-using-high-probability-swing-setups-to-capitalize-on-short-term-gainers
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Ivaylo Ivanhoff · Momentum breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Ivaylo Ivanhoff described in a podcast interview. It is **not**
Ivaylo Ivanhoff's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 24 — [024: Ivaylo Ivanhoff – Riding Industry Momentum & Using High Probability Swing Setups to Capitalize on Short-Term Gainers](https://chatwithtraders.com/episode/024-ivaylo-ivanhoff-riding-industry-momentum-using-high-probability-swing-setups-to-capitalize-on-short-term-gainers) · [YouTube](https://www.youtube.com/watch?v=pIw84hDLZWw)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: swing trading on strength; timeframe: daily. Universe described:
US equities, prioritize recent IPOs and stocks in industries showing momentum (e.g. biotech, semiconductors, cybersecurity).

### Setup
- 5-day MA above 20-day MA with consolidation or slight pullback  
  > "I'm looking for for the five day moving average daily trading above the 20 day moving average and i'm looking for something i call someone just looking for a people clavo guests to be taken out" — ep. 24 [[00:16:40]]
- stock belongs to industry with momentum and/or recent IPO  
  > "the first you know my perspective the best way to figure out which industry Cir is just a few screeners... and of course I'll give priority to recent IPOs" — ep. 24 [[00:14:30]]
### Entry
- breakout of at least 7-9.2% to new 20-day high  
  > "looking for a certain size seven more 49.2% breakout to new 20 TH I you know in order to enter" — ep. 24 [[00:17:14]]
### Stop
- (not stated)
### Exits
- hold 3-10 trading days then reallocate on better opportunity  
  > "I buy own strengths and i said im strength... hold anywhere between three to 10 trading days" — ep. 24 [[00:08:41]]
### Sizing
- risk 0.25% to 2% of capital per trade depending on setup and market environment  
  > "Series anywhere between 25 basis points in 200 basis points capital border trade depending on the on the set up in the market environment" — ep. 24 [[00:08:02]]
### Market Filter
- only trade when market environment supports the setup; step aside in corrections if needed  
  > "there is no trading abroad for not changing set up so you really have to take into account the right market environment" — ep. 24 [[00:06:51]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **exact stop-loss rule not stated** → assumption: none coded
- **partial profit rule not detailed for swing trades** → assumption: none coded
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -7.2% | +15.2% |
| Total return | -55.0% | +356.2% |
| Sharpe (daily, N-1) | -0.21 | 0.90 |
| Max drawdown | -79.7% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -22.3% | |
| CAPM alpha (ann.) / beta | -12.2% / 0.47 | |
| Trades / win rate | 2640 / 27.1% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -17.0% | +17.4% |
| Total return | -67.4% | +161.2% |
| Sharpe (daily, N-1) | -0.84 | 1.00 |
| Max drawdown | -67.9% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -34.4% | |
| CAPM alpha (ann.) / beta | -23.6% / 0.39 | |
| Trades / win rate | 1589 / 26.2% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | +7.0% | +12.3% |
| Total return | +37.8% | +73.7% |
| Sharpe (daily, N-1) | 0.39 | 0.76 |
| Max drawdown | -37.9% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -5.3% | |
| CAPM alpha (ann.) / beta | +2.6% / 0.58 | |
| Trades / win rate | 1051 / 28.4% | |

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
  "name": "cwt_ivaylo-ivanhoff-breakout",
  "display_name": "Ivaylo Ivanhoff · Momentum breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 25,
    "mom_min": 0.1,
    "cons_days": 5,
    "cons_max_range": 0.15,
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
        "episode": "24",
        "url": "https://chatwithtraders.com/episode/024-ivaylo-ivanhoff-riding-industry-momentum-using-high-probability-swing-setups-to-capitalize-on-short-term-gainers"
      }
    ]
  }
}
```
