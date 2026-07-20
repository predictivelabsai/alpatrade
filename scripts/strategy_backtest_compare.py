#!/usr/bin/env python3
"""Compare strategies on the Mag-7 / large-tech basket and rank by performance.

For each strategy, run the grid-search backtester over the basket and report the best
variation's PnL / return / Sharpe / win-rate / drawdown, then rank to find the best.

Usage: python scripts/strategy_backtest_compare.py [lookback] [capital]
       lookback ∈ {1m,3m,6m,1y} (default 3m); capital default 10000.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
# The grid-search backtester registers exactly these three strategies.
STRATEGIES = ["buy_the_dip", "momentum", "vix"]


def _num(d: dict, *keys, default=0.0):
    for k in keys:
        if d.get(k) is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return default


def run(lookback: str, capital: float) -> dict:
    from agents.orchestrator import Orchestrator
    results = {}
    for strat in STRATEGIES:
        try:
            r = Orchestrator().run_backtest({
                "symbols": MAG7, "strategy": strat, "lookback": lookback,
                "initial_capital": capital,
            })
            if isinstance(r, dict) and r.get("error"):
                results[strat] = {"error": r["error"]}
                continue
            best = (r.get("best_config") or {}) if isinstance(r, dict) else {}
            ret = _num(best, "total_return")
            results[strat] = {
                "sharpe": round(_num(best, "sharpe_ratio"), 2),
                "return_pct": round(ret, 2),
                "pnl": round(_num(best, "total_pnl", default=capital * ret / 100.0), 2),
                "win_rate": round(_num(best, "win_rate"), 1),
                "trades": int(_num(best, "total_trades")),
                "max_dd": round(_num(best, "max_drawdown"), 2),
                "variations": r.get("total_variations") if isinstance(r, dict) else None,
                "params": best.get("params"),
            }
        except Exception as e:  # noqa: BLE001
            results[strat] = {"error": str(e)[:120]}
    return results


def main() -> int:
    lookback = sys.argv[1] if len(sys.argv) > 1 else "3m"
    capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10000.0
    print(f"Mag-7 basket: {', '.join(MAG7)}")
    print(f"Window: {lookback} · starting capital ${capital:,.0f} · grid-search best variation per strategy\n")

    results = run(lookback, capital)
    hdr = f"{'Strategy':14} {'Sharpe':>7} {'Return%':>8} {'PnL$':>10} {'Win%':>6} {'Trades':>7} {'MaxDD%':>7}"
    print(hdr); print("-" * len(hdr))
    ranked = []
    for strat in STRATEGIES:
        m = results[strat]
        if "error" in m:
            print(f"{strat:14} {'— ' + m['error'][:50]:>50}")
            continue
        print(f"{strat:14} {m['sharpe']:>7} {m['return_pct']:>8} {m['pnl']:>10,.0f} "
              f"{m['win_rate']:>6} {m['trades']:>7} {m['max_dd']:>7}")
        ranked.append((strat, m))

    if ranked:
        by_ret = sorted(ranked, key=lambda kv: kv[1]["return_pct"], reverse=True)
        by_sharpe = sorted(ranked, key=lambda kv: kv[1]["sharpe"], reverse=True)
        print(f"\nBest by return: {by_ret[0][0]} ({by_ret[0][1]['return_pct']}%, "
              f"${by_ret[0][1]['pnl']:,.0f})")
        print(f"Best by Sharpe: {by_sharpe[0][0]} ({by_sharpe[0][1]['sharpe']})")
        print(f"Winning params: {json.dumps(by_ret[0][1].get('params'))}")
    print("\n" + json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
