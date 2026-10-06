# Multi-Strategy Walk-Forward Comparisons

AlpaTrade routes comparison requests through the default DeepAgents strategy-lab
specialist. The action creates one durable `deepagent_comparison` job; it never
starts paper or live trading automatically.

Example request:

```text
Compare buy_the_dip, momentum, and vix on AAPL, MSFT, GOOGL, AMZN,
META, TSLA, and NVDA over 3m and 1y. Use $10,000, require a minimum
three-day hold, include costs, run three walk-forward folds, and benchmark SPY.
```

The router stores the normalized specification, then creates chronological folds.
Each fold selects parameters using earlier training data and evaluates them on the
immediately following unseen period. Only stitched out-of-sample (OOS) results are
used for promotion eligibility.

The consolidated result contains:

- training and OOS period returns (never mislabeled as CAGR);
- OOS P&L, trade count, win rate, and profitable-fold count;
- SPY return over identical OOS dates and excess return;
- the search mode (`grid` or `fixed_configuration`);
- insufficient-trade and IS-to-OOS decay warnings;
- train/OOS child run IDs for audit and trade inspection.

`hold_days` is the maximum holding period. `min_hold_days` prevents TP/SL exits
before the requested age and is the correct control for a minimum three-day hold.
Buy-the-Dip receives a true parameter grid. Momentum and VIX currently use their
documented fixed defaults and are labeled accordingly rather than presented as
grid-optimized strategies.

Explicit research jobs are drained by a restricted worker lane even when
`AUTONOMY_ENABLED=false`. That lane can claim only `deepagent_backtest` and
`deepagent_comparison`; it cannot claim paper, full-cycle, or self-fed jobs.

No migration is required. Deploy the web/API/autonomy services from the same
revision so the tool schema and worker job type remain aligned.
