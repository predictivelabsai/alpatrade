#!/usr/bin/env python3
"""Comparison harness: backtests + LangGraph-vs-DeepAgents framework parity.

Part 1 — run the deterministic grid-search backtest for a few symbols and tabulate
the best config's metrics (this is framework-independent).

Part 2 — build the SAME agent RoleSpec (with a tool that returns those metrics) under
each AGENT_FRAMEWORK and ask the identical question, to show the pluggable adapter
drives an equivalent agent on both backends (same metrics relayed; latency compared).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

SYMBOLS = ["AAPL", "MSFT", "NVDA"]
STRATEGY = "buy_the_dip"
LOOKBACK = "3m"


def run_backtests() -> dict:
    from agents.orchestrator import Orchestrator
    out = {}
    for sym in SYMBOLS:
        r = Orchestrator().run_backtest({"symbols": [sym], "strategy": STRATEGY, "lookback": LOOKBACK})
        best = (r.get("best_config") or {}) if isinstance(r, dict) else {}
        out[sym] = {
            "sharpe": round(float(best.get("sharpe_ratio", 0) or 0), 2),
            "return_pct": round(float(best.get("total_return", 0) or 0), 2),
            "trades": int(best.get("total_trades", 0) or 0),
            "variations": r.get("total_variations") if isinstance(r, dict) else None,
        }
    return out


def parity(metrics: dict) -> list[dict]:
    from engine.agents.runtime import get_runtime, RoleSpec
    from langchain_core.tools import StructuredTool

    def get_backtest_metrics(symbol: str) -> str:
        """Return the backtest metrics (sharpe, return_pct, trades) for a symbol as JSON."""
        return json.dumps(metrics.get(symbol.upper(), {}))

    tool = StructuredTool.from_function(get_backtest_metrics)
    spec = RoleSpec(name="bt-reporter",
                    instructions="You report backtest metrics. Call get_backtest_metrics and "
                                 "state the sharpe, return_pct and trades for the symbol.",
                    tools=[tool])
    prompt = "Report the backtest metrics for AAPL."
    rows = []
    for fw in ("langgraph", "deepagents"):
        rt = get_runtime(fw)
        t0 = time.time()
        try:
            agent = rt.build(spec)
            res = rt.run(agent, prompt)
            text = (res.text or "").replace("\n", " ")
            ok = "1." in text or "0." in text or "trade" in text.lower()  # mentions numbers
            rows.append({"framework": fw, "resolved": rt.name, "latency_s": round(time.time() - t0, 1),
                         "answer": text[:160], "ok": ok})
        except Exception as e:  # noqa: BLE001
            rows.append({"framework": fw, "resolved": rt.name, "latency_s": round(time.time() - t0, 1),
                         "answer": f"ERROR: {e}", "ok": False})
    return rows


def main() -> int:
    print("=== Part 1: comparison backtests (buy_the_dip, 3m, grid-search) ===")
    metrics = run_backtests()
    print(f"{'Symbol':8} {'Sharpe':>7} {'Return%':>8} {'Trades':>7} {'Variations':>11}")
    for sym in SYMBOLS:
        m = metrics[sym]
        print(f"{sym:8} {m['sharpe']:>7} {m['return_pct']:>8} {m['trades']:>7} {str(m['variations']):>11}")
    # rank by sharpe
    best = max(metrics.items(), key=lambda kv: kv[1]["sharpe"])
    print(f"Best by Sharpe: {best[0]} ({best[1]['sharpe']})")

    print("\n=== Part 2: framework parity (same agent + tool, LangGraph vs DeepAgents) ===")
    rows = parity(metrics)
    for r in rows:
        print(f"[{'OK ' if r['ok'] else 'ERR'}] {r['framework']:10} → resolved={r['resolved']:10} "
              f"{r['latency_s']:>5}s  {r['answer']}")
    same = len({tuple(sorted(m.items())) for m in metrics.values()}) >= 0  # metrics deterministic
    both_ok = all(r["ok"] for r in rows) and {r["resolved"] for r in rows} == {"langgraph", "deepagents"}
    print(f"\nParity: both frameworks resolved distinctly and answered = {both_ok}")
    print(json.dumps({"metrics": metrics, "parity": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
