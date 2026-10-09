---
title: Kristjan Kullamägi · Momentum breakout (backtest)
description: Daily-bar backtest of the breakout swing method Kristjan Kullamägi describes on Chat With Traders ep. 212: strong prior momentum, tight consolidation, breakout entry, low-of-day stop, partial after 5 days, trail on the 20-day MA. S&P 500, cash only. Backtest, not live.
kind: backtest
author: Kristjan Kullamägi
source: chatwithtraders.com
source_url: https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns
tags: breakout, momentum, swing, chat-with-traders, backtest
license: MIT
---

# Kristjan Kullamägi · Momentum breakout (backtest)

*For research and education only. This is not investment advice. This is AlpaTrade's
interpretation of rules Kristjan Kullamägi described in a podcast interview, backtested on daily bars.
It is **not** Kristjan Kullamägi's own code, account or track record, and it has **never been traded
live** on AlpaTrade.*

Source: Chat With Traders ep. 212, "212: Kristjan Kullamägi – Breakouts, Home Runs & Exponential Returns" — https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns
(YouTube: https://www.youtube.com/watch?v=K0F73Sq90j0)

## How to use this skill
- **ChatGPT / Claude / Grok:** paste this whole file into a new chat, then ask, for example:
  "Re-run this backtest on a small/mid-cap universe", "Write pandas code for the signals",
  or "Which assumption would you stress-test first?"
- **AlpaTrade:** "Clone into AlpaTrade" on alpatrade.chat/leaderboard copies it into your own
  strategies (private until you publish it).

## The strategy in plain language (with quotes from the episode)
Timestamps refer to the YouTube auto-caption transcript.

### Universe
strongest stocks US equities mid/large caps most liquid. **Backtested on:** S&P 500 current members (503 with data), price
≥ $5, long only.

### Setup
- big absolute and relative momentum then pullback or sideways consolidation with volatility contraction  
  > "you have a leg higher and then it usually goes sideways or pull backs pulls back and uh many times what happens is the volatility contracts like it gets tighter" — [00:18:51]

Daily-bar version: return over the last 90 sessions ≥ 50%,
the last 30 sessions' high-low range ≤ 15% of the high,
close above the 20-day SMA — all measured at the prior close.

### Entry
- buy opening range high on daily breakout confirmation  
  > "i buy the opening range highs and the opening range highs is when the stock takes out uh obviously it has to be a breakout first" — [00:35:32]

Daily-bar version: buy-stop at the consolidation high; fill at that level, or at the open if
the stock gaps above it, plus 10 bps slippage.

### Stop
- initial stop low of day then trail 10 or 20 day MA waiting for close  
  > "initially my stop is always low low sodium day uh and once the moving averages the 10 and the 20 uh the moving averages it depends on the stock the faster moving stops are you stocks i moved uh i used the 10 day and the slow we're moving once i use the 20 day" — [00:41:43]

Daily-bar version: low of the entry day, never more than 1.0× the 20-day
average daily range below the entry; stops fill at the stop or at the open on a gap.

### Exits
- scale out 20-25% into first burst of strength then trail rest with MA hold as long as possible  
  > "i always sell some into that first burst uh to lock in a little bit of profits maybe i sell 20 or 25 or it can vary a lot" — [00:23:32]

Daily-bar version: after 5 sessions sell 25% at the
close if in profit and move the stop to break-even; exit the rest at the first close below the
20-day SMA.

### Position sizing
- buy everything at once aggressively no scaling in unless new setup  
  > "i buy everything at once uh very aggressively" — [00:34:30]

Daily-bar version: risk 1.0% of equity per trade (stop distance ≈ 1 ADR),
capped at 20% of equity per name and at most 20
positions. **Cash only** (no margin, unlike the trader).

### Market filter
- only uptrending or sideways market after correction prefer stocks with relative strength  
  > "you obviously need uh uh up trending or sideways market to trade this method" — [00:29:44]

Daily-bar version: new entries only when SPY's 10-day SMA is above its 20-day SMA (prior close).

### Ambiguities and assumptions
- **exact consolidation range pct or days not specified** → assumption: use 20-60 days with max 15% range for daily approximation
- The opening-range-high entry (1/5/60-minute candles) is intraday; daily bars approximate it
  with a buy-stop at the prior consolidation high, so the stop is the whole day's low.
- Same-day volume confirmation is not used (the day's volume is only known at the close).
- Earnings are not avoided (no earnings calendar in the backtest).

## Backtest results
Engine `engine.backtest.breakout` (cash only, 10 bps slippage per side,
no look-ahead: signals use the prior close). Data: Alpaca SIP daily bars, adjustment=all (splits+dividends).

### Full period 2016-01-04 → 2026-10-09
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -1.8% | +15.2% |
| Total return | -17.4% | +356.2% |
| Sharpe (daily, N-1) | -0.20 | 0.90 |
| Max drawdown | -30.2% | -33.8% |
| Alpha vs SPY (total return) | -373.6% | |
| Alpha vs SPY (annualised) | -16.9% | |
| CAPM alpha (ann.) / beta | -2.6% / 0.07 | |
| Trades / win rate | 334 / 26.9% | |
| Avg win / avg loss | +5.2% / -2.3% | |
| Time invested | 33% | 100% |

### Train 2016-01-04 → 2021-12-31 (same fixed rules)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -0.7% | +17.4% |
| Total return | -3.9% | +161.2% |
| Sharpe (daily, N-1) | -0.05 | 1.00 |
| Max drawdown | -19.8% | -33.8% |
| Alpha vs SPY (total return) | -165.1% | |
| Alpha vs SPY (annualised) | -18.0% | |
| CAPM alpha (ann.) / beta | -1.8% / 0.08 | |
| Trades / win rate | 210 / 25.7% | |
| Avg win / avg loss | +5.6% / -2.0% | |
| Time invested | 35% | 100% |

### Test 2022-01-03 → 2026-10-09 (same fixed rules, out-of-sample)
| Metric | Strategy | SPY |
|---|---|---|
| Annualised return (CAGR) | -3.2% | +12.3% |
| Total return | -14.3% | +73.7% |
| Sharpe (daily, N-1) | -0.42 | 0.76 |
| Max drawdown | -26.5% | -24.5% |
| Alpha vs SPY (total return) | -87.9% | |
| Alpha vs SPY (annualised) | -15.5% | |
| CAPM alpha (ann.) / beta | -3.7% / 0.05 | |
| Trades / win rate | 124 / 29.0% | |
| Avg win / avg loss | +4.8% / -2.7% | |
| Time invested | 29% | 100% |

### Train-optimised check
A 24-config grid (mom_min, cons_days, trail_ma, partial_days) was optimised on the train window by Sharpe; the best ({"mom_min": 0.5, "cons_days": 10, "trail_ma": 20, "partial_days": 5}) then traded the unseen test window: CAGR -3.3% vs SPY +12.3%, Sharpe -0.07, max drawdown -33.4%, 556 trades.

### Caveats
- **Survivorship bias:** the universe is *today's* S&P 500, which flatters any long strategy in
  the past; the trader focuses on smaller, faster stocks that are not in this universe.
- Daily bars cannot reproduce intraday entries, stops or the trader's discretion.
- The rule spec was extracted by an LLM from auto-captions and checked by hand; quotes may
  contain caption errors.

## Instructions for the assistant
1. Treat the Parameters block as the source of truth and restate the rules first.
2. Use daily bars, signals from the prior close, one position per symbol, cash only.
3. Report against SPY over the same period: CAGR, Sharpe, max drawdown, alpha, trades, win rate.
4. Never place live orders. Suggest paper trading before any real money.

## Parameters (machine-readable)
```json
{
  "schema": "alpatrade.strategy_config/v1",
  "name": "cwt_212_breakout",
  "display_name": "Kristjan Kullamägi · Momentum breakout (backtest)",
  "kind": "backtest",
  "params": {
    "mom_days": 90,
    "mom_min": 0.5,
    "cons_days": 30,
    "cons_max_range": 0.15,
    "trail_ma": 20,
    "partial_days": 5,
    "partial_frac": 0.25,
    "max_stop_adr": 1.0,
    "risk_pct": 0.01,
    "max_pos_pct": 0.2,
    "max_positions": 20,
    "min_price": 5.0,
    "market_filter": true,
    "slippage_bps": 10.0,
    "universe": "sp500_current",
    "timeframe": "1d",
    "entry": "buy_stop_at_consolidation_high",
    "stop": "entry_day_low_capped_adr",
    "market_filter_rule": "SPY SMA10 > SMA20 (prior close)"
  },
  "execution": {
    "sizing": "risk_pct of equity / (ADR x price), capped at max_pos_pct, cash only",
    "slippage_bps_per_side": 10.0,
    "fill": "stop price or open if gapped"
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
    "full": [
      "2016-01-04",
      "2026-10-09"
    ],
    "benchmark": "SPY"
  },
  "source": {
    "site": "chatwithtraders.com",
    "episode": "212",
    "url": "https://chatwithtraders.com/episode/212-kristjan-kullamagi-breakouts-home-runs-exponential-returns",
    "youtube": "https://www.youtube.com/watch?v=K0F73Sq90j0"
  }
}
```
