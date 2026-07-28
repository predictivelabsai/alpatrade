# AlpaTrade evaluations

The main suite contains 102 cases grouped by agent/tool and domain. Chat cases
have two gates:

1. the observed tool trajectory must include the expected `agent_name`;
2. the Grok/DeepEval judge must score the final answer at or above `0.6`.

Command cases use deterministic structural assertions. Every result is written
as PASS or FAIL with the called tools, routing result, judge score, reason, and
latency. CSV and XLSX reports include per-agent and per-type summaries.

```bash
uv run python evals/run_evals.py
uv run python evals/run_evals.py --agent show_market_map
uv run python evals/run_evals.py --category public_markets
uv run python evals/run_evals.py --only deterministic
uv run python evals/run_evals.py --dry-run
```

Browser rendering is evaluated separately across desktop, tablet, and mobile.
It covers the inline chat market map, dedicated market-map page, and charts
page, and writes compatible PASS/FAIL CSV output plus screenshots.

```bash
uv run --with playwright python evals/run_ui_evals.py
```

Slow backtest and paper-agent cases remain opt-in:

```bash
uv run python evals/run_evals.py --include-slow
```
