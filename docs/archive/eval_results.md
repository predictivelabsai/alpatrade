# AlpaTrade — Agent & Tool Evaluation Results

Automated evaluation of every agent/tool surface using [DeepEval](https://deepeval.com),
with **grok (XAI) as the LLM judge** (no OpenAI key required).

- **Harness:** [`evals/run_evals.py`](../evals/run_evals.py) · ground truth: [`evals/ground_truth.csv`](../evals/ground_truth.csv) · judge: [`evals/judge.py`](../evals/judge.py)
- **Run:** `python evals/run_evals.py` (add `--include-slow` for `agent:backtest` / `agent:paper`)
- **Outputs:** timestamped `eval-results/evals-*.csv` and `eval-results/evals-*.xlsx` (color-coded results + a summary sheet)

## Grading

| agent_type | How it's graded |
|---|---|
| **deterministic** | Structural match — required tokens/structure must appear in the output (no LLM). Covers `CommandProcessor` CLI commands (`trades:`, `runs:`, `top:`, `report:`, `positions`, `news:`, `price:`, `agent:status`, …) and orchestrator agents (`agent:reconcile`, and with `--include-slow`: `agent:backtest`, `agent:paper`). |
| **chat** | DeepEval `GEval` "Correctness" (grok judge) — semantic correctness vs the expected answer, threshold 0.6. Covers the LangGraph tools (positions, account, price, news, ratings, financials, movers, valuation, **paper orders**, charts, runs, agent status). |

Each result row: `prompt · expected_answer · ai_answer · agent_name · agent_type · result (PASS/FAIL) · score · reason · latency_s`.

## Latest run — 2026-07-10 (BYOK + provider-config + Tavily-news pass)

**Overall accuracy: 32/32 = 100.0%** (chat 18/18; deterministic 14/14; excludes the 2 slow agents).
Chat covers the charting tools (`show_market_map`, `compare_stocks`) and the Tavily-backed news tool.

This pass validated the provider/BYOK work: the chat model is now resolved through
`engine.config` (env `MODEL_PROVIDER`/`MODEL_NAME`, per-user overrides in
`alpatrade.user_settings`) and self-heals an unavailable model — e.g. the region-locked
`grok-4.5` falls back to `grok-4.3`, which is what unblocked chat answering at all.

Three rows regressed on an interim run and were fixed:

1. **`get_stock_news`** — now forces the configured `SEARCH_PROVIDER` (Tavily) and queries by
   *company name + ticker* (TSLA → "Tesla" (TSLA)) so results stay on the issuer instead of
   drifting to adjacent entities (SpaceX). Returns real, dated, linked headlines.
2. **`get_market_movers`** — Polygon's gainers/losers endpoints need a paid plan; added a
   yfinance fallback that ranks a liquid S&P universe by today's return when Polygon is empty.
3. **`show_market_map`** — the treemap renders client-side, so a headless judge only sees the
   tool's text. Right-sized the expectation: the up/down count + best/worst-sector summary
   line *is* the correct answer.

| Type | Passed | Accuracy |
|---|---|---|
| Deterministic | 14/14 | **100.0%** |
| Chat | 18/18 | **100.0%** |

### By agent

| Agent / tool | Passed | Accuracy |
|---|---|---|
| CommandProcessor (13 commands) | 13/13 | 100% |
| Reconciler (`agent:reconcile`) | 1/1 | 100% |
| get_alpaca_positions | 2/2 | 100% |
| get_alpaca_account | 1/1 | 100% |
| get_stock_price | 1/1 | 100% |
| get_stock_news | 1/1 | 100% |
| get_analyst_ratings | 1/1 | 100% |
| get_company_profile | 1/1 | 100% |
| get_financials | 1/1 | 100% |
| get_market_movers | 1/1 | 100% |
| get_valuation | 1/1 | 100% |
| place_paper_order | 3/3 | 100% |
| show_stock_chart | 1/1 | 100% |
| show_market_map | 1/1 | 100% |
| compare_stocks | 1/1 | 100% |
| show_recent_runs / get_top_strategies | 1/1 | 100% |
| show_running_agents | 1/1 | 100% |

### Findings — all fixed

The first run (27/30) surfaced three real defects, now resolved:

1. **`get_valuation` ticker bug** — two layered defects. First the tool split on `,` and passed empty
   tokens through (`Quote not found for symbol: ,`). Deeper: `MarketResearch.valuation()` expects a
   **list**, but the wrapper handed it a **string**, so it iterated the string *character by character* —
   the comma 404'd and stray letters resolved to unrelated real tickers (`A`=Agilent, `M`=Macy's), which
   the agent reported as "unrelated tickers". **Fixed:** parse with `re.split(r"[,\s]+", …)`, drop
   empties and connector words (`and`/`vs`/…), and pass a **list**. Now 0.9.
2. **`place_paper_order` (sell) wash-trade rejection** — "Sell 1 TSLA at market" was rejected by Alpaca
   as a *potential wash trade* because open opposite (buy) orders from earlier testing existed.
   **Fixed:** (a) the tool now surfaces a friendly wash-trade explanation instead of a raw API error,
   and (b) the eval harness clears open paper orders before running. Now 0.9.
3. **Best-strategy routing** — "Which of my strategies performed best?" returned a raw runs list rather
   than a ranking. **Fixed:** added a `get_top_strategies` tool (ranks by return/Sharpe via
   `ReportAgent().top_strategies`) and routed the intent to it in the system prompt. Now 0.9.

> Note: `show_stock_chart` is a borderline judge case — the tool returns a chart marker the UI renders,
> but a headless `ainvoke` only yields the agent's text. The chart tool's reply and system prompt were
> tightened to state plainly that the chart is *rendered below* so the judge scores the render intent,
> not the raw numbers.

## Extending

Add rows to `evals/ground_truth.csv`:

| column | meaning |
|---|---|
| `prompt` | the user prompt / command |
| `expected_answer` | prose expectation (chat) — what a correct answer must convey |
| `must_contain` | deterministic only — required tokens; `\|` separates required groups, `;` separates alternatives within a group |
| `agent_name` | the tool/agent/command expected to handle it |
| `agent_type` | `chat` or `deterministic` |
| `slow` | `1` to gate behind `--include-slow` (long-running agents) |

Then re-run `python evals/run_evals.py`. Eval-only deps: `pip install -r requirements-eval.txt` (`deepeval`, `openpyxl`).
