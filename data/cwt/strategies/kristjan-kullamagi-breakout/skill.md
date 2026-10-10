---
title: Kristjan Kullamägi · Momentum breakout swing (backtest)
description: Daily-bar backtest of the momentum breakout swing method Kristjan Kullamägi describes on Chat With Traders (ep. 212). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: Kristjan Kullamägi
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns
tags: breakout, chat-with-traders, backtest
license: MIT
---

# Kristjan Kullamägi · Momentum breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules Kristjan Kullamägi described in a podcast interview. It is **not**
Kristjan Kullamägi's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 212 — [212: Kristjan Kullamägi – Breakouts, Home Runs & Exponential Returns](https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns) · [YouTube](https://www.youtube.com/watch?v=K0F73Sq90j0)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: swing/position trading; timeframe: daily with optional 60min confirmation. Universe described:
US stocks, strongest 2% by 1-18mo momentum, min $150M avg daily volume (was $20M earlier), mid/large caps preferred for liquidity.

### Setup
- Stock has prior leg higher (several weeks/months), then sideways/pullback consolidation with contracting volatility/range  
  > "you have a leg higher and then it usually goes sideways or pull backs pulls back and uh many times what happens is the volatility contracts like it gets tighter" — ep. 212 [[00:18:51]]
- Relative strength: holds up best during market corrections, builds higher lows  
  > "the stocks that held up the most that had big moves previously and held up the most" — ep. 212 [[00:28:43]]
### Entry
- Buy breakout of the consolidation range (daily obvious breakout); can use 1/5/60min opening range high for timing  
  > "our goal is to identify that those stair steps and buy it just as it is about to break out into the next" — ep. 212 [[00:19:53]]
- Buy aggressively at once on breakout  
  > "i buy everything at once uh very aggressively" — ep. 212 [[00:34:30]]
### Stop
- Initial stop = low of the day (or low of the breakout candle on 1/5/60min)  
  > "then i use the low sorry day as my stop" — ep. 212 [[00:36:02]]
- Trail with 10 or 20-day MA after MA catches up; wait for close to exit on violation  
  > "once the moving averages the 10 and the 20 the moving averages it depends on the stock the faster moving stops are you stocks i moved uh i used the 10 day and the slow we're moving once i use the 20 day" — ep. 212 [[00:41:43]]
### Exits
- Partial exit 20-25% into first momentum burst/strength to lock profits  
  > "i always sell some into that first burst uh to lock in a little bit of profits maybe i sell 20 or 25" — ep. 212 [[00:23:32]]
- Remainder trailed with 10/20 MA or sell after 3-5 days for shorter swings  
  > "you can you know hold them for maybe three to five days or and just settle into strength or you can try to hold for bigger moves uh like even try to hold through the next several steps uh and maybe use the moving averages like i do the 10 and 20 day moving averages trailing stops" — ep. 212 [[00:19:53]]
### Sizing
- No fixed risk % or max positions stated; scales up with account, can reach 15-30 positions in strong markets  
  > "i end up with a lot of positions because i take some partial profits and some and then i roll that money into new positions new breakouts and i can end up with you know 20 25 and i've had 30 positions sometimes" — ep. 212 [[00:50:40]]
### Market Filter
- Only trade in uptrending or sideways markets; best after 5-15% market correction when leaders show relative strength; avoid bear markets  
  > "you obviously need uh uh up trending or sideways market to trade this method" — ep. 212 [[00:29:44]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact momentum_lookback_days, momentum_min_pct, consolidation_days and consolidation_max_range_pct not numeric** → assumption: Use 3mo/6mo/12mo lookbacks for momentum scan; consolidation 20-60 days with <10-15% range as typical from stair-step description
- **No explicit risk_per_trade_pct or max_position_pct given** → assumption: Omit or default to standard 1% risk / 10% max pos since not stated
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -1.1% | +15.2% |
| Total return | -10.8% | +356.2% |
| Sharpe (daily, N-1) | -0.52 | 0.90 |
| Max drawdown | -11.3% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -16.2% | |
| CAPM alpha (ann.) / beta | -1.3% / 0.01 | |
| Trades / win rate | 154 / 33.1% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -1.2% | +17.4% |
| Total return | -7.2% | +161.2% |
| Sharpe (daily, N-1) | -0.58 | 1.00 |
| Max drawdown | -7.6% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -18.6% | |
| CAPM alpha (ann.) / beta | -1.5% / 0.02 | |
| Trades / win rate | 102 / 30.4% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -0.8% | +12.3% |
| Total return | -3.9% | +73.7% |
| Sharpe (daily, N-1) | -0.43 | 0.76 |
| Max drawdown | -4.3% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -13.2% | |
| CAPM alpha (ann.) / beta | -1.0% / 0.01 | |
| Trades / win rate | 52 / 38.5% | |

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
  "name": "cwt_kristjan-kullamagi-breakout",
  "display_name": "Kristjan Kullamägi · Momentum breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 90,
    "mom_min": 0.5,
    "cons_days": 30,
    "cons_max_range": 0.12,
    "trail_ma": 20,
    "partial_days": 3,
    "partial_frac": 0.25,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.1,
    "max_positions": 20,
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
        "episode": "212",
        "url": "https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns"
      }
    ]
  }
}
```
