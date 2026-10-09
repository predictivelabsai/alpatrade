---
title: George, @RollyTrader · Momentum VCP breakout swing (backtest)
description: Daily-bar backtest of the momentum vcp breakout swing method George, @RollyTrader describes on Chat With Traders (ep. 110). Template: breakout. S&P 500, cash only, 10 bps slippage. Backtest, not live.
kind: backtest
author: George, @RollyTrader
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/110-george-rollytrader-learning-to-trade-momentum-setups-and-becoming-a-venture-capitalist
tags: breakout, chat-with-traders, backtest
license: MIT
---

# George, @RollyTrader · Momentum VCP breakout swing (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
daily-bar interpretation of rules George, @RollyTrader described in a podcast interview. It is **not**
George, @RollyTrader's own code, account or track record, and it has **never been traded live**.*

## Sources (Chat With Traders)
- Ep. 110 — [110: George, @RollyTrader – Learning to Trade, Momentum Setups, and Becoming a Venture Capitalist](https://chatwithtraders.com/episode/110-george-rollytrader-learning-to-trade-momentum-setups-and-becoming-a-venture-capitalist) · [YouTube](https://www.youtube.com/watch?v=xn0-isz8vQA)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this file into a new chat and ask, e.g. "Explain this
  strategy and its risks" or "Re-run the backtest on a different universe".
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (quotes from the episode)
Style: momentum swing; timeframe: daily. Universe described:
Australian equities primary; also US stocks.

### Setup
- Volatility contraction pattern (VCP) breakout  
  > "I have the volatility contraction pattern which is from Mark Manini. ... that's effectively a breakout trade." — ep. 110 [[00:33:56]]
- Pocket pivot entry  
  > "I use a pocket pivot which comes from Gil Morales ... the stock needs to come from below the 10day moving average to close above it on that volume." — ep. 110 [[00:37:03]]
- Pullback buy on uptrend  
  > "a pullback buy method where the stock is already trending. ... buying off the first pullback to the moving average when it's obeyed on the uptick." — ep. 110 [[00:34:26]]
### Entry
- Buy above pivot after contraction; no chase >4%  
  > "I'll just set my alert above that little pivot point. And when that goes through there, I'm buying. ... if it goes 4% past there, that's it's off the table." — ep. 110 [[00:42:50]]
- Wait for higher close on pullback  
  > "I'm waiting for the next day for the close or for the intraday to be above that previous day's high." — ep. 110 [[00:46:31]]
### Stop
- Initial stop below base; move to breakeven at +10%  
  > "Ideally, I want to move my stop to break even as soon as possible. So, if I'm up 10% in a trade, I'll just try to reduce my risk immediately." — ep. 110 [[00:54:26]]
### Exits
- Partial sell at +20% gain; trail 20-day EMA  
  > "if I'm risking 1 in and which might be 5% and all of a sudden I make 20% I'll definitely be selling partial into that ... to get out, I'll use a moving average. ... holding the 20-day" — ep. 110 [[00:52:21]]
### Sizing
- Initial position <=8%, max 20% concentrated; risk ~1% per trade  
  > "I don't like to trade more than 8% in a position. ... I will go up to 20% into one stock. ... if you're taking a 10% position size, your risk with a 10% stop is 1% of your total capital." — ep. 110 [[00:47:32]]
### Market Filter
- Follow leadership; go to cash on distribution in leaders  
  > "my system works very much on following leadership. ... If the market comes under distribution ... I went back to cash." — ep. 110 [[00:31:50]]

## How it was backtested
Template **breakout** — momentum breakout: strong prior run-up, tight consolidation, buy-stop at the consolidation high, low-of-day stop (≤ 1 ADR), partial after N days, trail on the 10/20-day SMA. Parameters (from the most recent episode's rules, LLM
mapped and clamped to sane ranges) are in the block below.

### Ambiguities and assumptions
- **Exact momentum_lookback_days, consolidation_days, consolidation_max_range_pct not stated numerically** → assumption: VCP implies multi-week contraction with tightening ranges per Minervini description
- **partial_after_days and partial_frac not exact** → assumption: partial sell after ~20% gain, fraction unspecified
- Daily bars only: intraday entries, stops and discretion are approximated or dropped.
- Long only, cash only (no margin or shorting), one position per symbol.
- No earnings calendar, news or fundamentals; no same-day volume confirmation.

## Backtest results
Universe S&P 500 current members (503 with data); Alpaca SIP daily bars, adjustment=all (splits+dividends); 10 bps slippage per side; signals from the prior
close (gap entries use the day's open). Train / test are slices of the full-period run.

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -5.7% | +15.2% |
| Total return | -47.0% | +356.2% |
| Sharpe (daily, N-1) | -0.62 | 0.90 |
| Max drawdown | -51.5% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -20.9% | |
| CAPM alpha (ann.) / beta | -7.8% / 0.15 | |
| Trades / win rate | 1959 / 28.6% | |

### Train 2016-01-04 → 2021-12-31
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -2.7% | +17.4% |
| Total return | -15.3% | +161.2% |
| Sharpe (daily, N-1) | -0.28 | 1.00 |
| Max drawdown | -24.5% | -33.8% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -20.1% | |
| CAPM alpha (ann.) / beta | -4.8% / 0.14 | |
| Trades / win rate | 1017 / 30.3% | |

### Test 2022-01-03 → 2026-10-09 (out-of-sample, same rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -9.3% | +12.3% |
| Total return | -37.3% | +73.7% |
| Sharpe (daily, N-1) | -1.00 | 0.76 |
| Max drawdown | -38.9% | -24.5% |
| Alpha vs SPY (annualised, CAGR − SPY CAGR) | -21.7% | |
| CAPM alpha (ann.) / beta | -11.5% / 0.16 | |
| Trades / win rate | 942 / 26.8% | |

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
  "name": "cwt_george-rollytrader-breakout",
  "display_name": "George, @RollyTrader · Momentum VCP breakout swing (backtest)",
  "kind": "backtest",
  "template": "breakout",
  "params": {
    "mom_days": 63,
    "mom_min": 0.3,
    "cons_days": 15,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 4,
    "partial_frac": 0.33,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.08,
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
        "episode": "110",
        "url": "https://chatwithtraders.com/episode/110-george-rollytrader-learning-to-trade-momentum-setups-and-becoming-a-venture-capitalist"
      }
    ]
  }
}
```
