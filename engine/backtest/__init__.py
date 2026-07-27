"""Methodology-faithful backtesting per the Alpaca `alpaca-trading-backtest` skill.

The skill (vendored under `engine/backtest/skills/`) prescribes a deterministic,
reproducible research workflow:

    strategy idea -> formalized rules -> CLI data fetch -> local script -> artifacts -> report

This package implements that contract for AlpaTrade:

- `data`        — fetch Alpaca bars (via the official alpaca-py SDK), save raw + normalized,
                  compute the per-symbol data fingerprint.
- `fills`       — named fill models (next_open / time_based / same_bar) + sizing + friction.
- `metrics`     — the skill's metric formulas (Sharpe N-1 from daily equity, max drawdown,
                  profit factor, …) + the Teaching Five.
- `strategies`  — pluggable signal/exit logic (Phase 0 ships buy_the_dip).
- `runner`      — orchestrates a run and writes the full dated artifact folder.
- `artifacts`   — the run-folder writer (notes.md, summary.json, report.md, run.py, …)
                  including the mandatory hypothetical-results disclosure.

Guardrails enforced in code: no future data in signals (next_open is the default fill;
`same_bar` forces a look-ahead warning into the report), Sharpe uses sample stddev (N-1),
and every run writes the disclosure block.

Import the entry points directly, e.g. `from engine.backtest.runner import run_backtest`.
"""
