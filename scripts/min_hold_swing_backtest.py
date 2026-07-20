#!/usr/bin/env python3
"""PDT-safe swing buy_the_dip: minimum 3-day hold, then intraday (intrabar) TP/SL exit.

Runs several sensible swing configs through the *methodology-faithful* backtester
(daily bars, next-open fills + 5bps slippage, N-1 Sharpe, no look-ahead) on the Mag-7
basket over 1 year, and compares each to equal-weight buy-and-hold. min_hold_days=3
guarantees no same-day round trip (PDT-safe); once past it, intrabar TP/SL fires.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from engine.backtest.runner import run_backtest  # noqa: E402

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]
START = datetime(2025, 7, 20, tzinfo=timezone.utc)
END = datetime(2026, 7, 20, tzinfo=timezone.utc)
CAP = 10000.0

# min_hold_days=3 on every config (PDT-safe); vary dip depth / target / stop / max hold.
CONFIGS = [
    {"label": "shallow-3d", "dip_threshold": 0.03, "take_profit": 0.03, "stop_loss": 0.05, "hold_days": 10, "min_hold_days": 3},
    {"label": "mid-3d", "dip_threshold": 0.05, "take_profit": 0.05, "stop_loss": 0.08, "hold_days": 15, "min_hold_days": 3},
    {"label": "deep-3d", "dip_threshold": 0.07, "take_profit": 0.06, "stop_loss": 0.10, "hold_days": 20, "min_hold_days": 3},
    {"label": "tight-3d", "dip_threshold": 0.03, "take_profit": 0.015, "stop_loss": 0.03, "hold_days": 10, "min_hold_days": 3},
]


def one(cfg: dict) -> dict:
    params = {k: cfg[k] for k in ("dip_threshold", "take_profit", "stop_loss", "hold_days", "min_hold_days")}
    params["position_size"] = 0.10
    res = run_backtest(symbols=MAG7, start=START, end=END, initial_capital=CAP,
                       strategy_name="buy_the_dip", strategy_params=params,
                       fill_model="next_open", interval="1d", slippage_bps=5.0)
    c = res.summary["reproducible_core"]
    m, b, rt = c["metrics"], c["benchmarks"], c["round_trip"]
    return {
        "label": cfg["label"], "params": params,
        "total_return": m["total_return"], "annualized": m["annualized_return"],
        "sharpe": m["sharpe"], "final": m["final_equity"],
        "trades": rt["trades"], "win_rate": rt["win_rate"], "profit_factor": rt["profit_factor"],
        "bench_return": b["total_return"], "bench_annualized": b["annualized_return"], "bench_sharpe": b["sharpe"],
    }


def main() -> int:
    rows = []
    for cfg in CONFIGS:
        try:
            r = one(cfg)
            rows.append(r)
            print(f"  {r['label']:10} ret {r['total_return']*100:+.2f}%  ann {r['annualized']*100:+.2f}%  "
                  f"SR {r['sharpe']:+.2f}  PF {r['profit_factor']:.2f}  trades {r['trades']}  "
                  f"final ${r['final']:,.0f}   (B&H {r['bench_return']*100:+.2f}%)")
        except Exception as e:  # noqa: BLE001
            print(f"  {cfg['label']} failed: {e}")
    if not rows:
        return 1
    bench = rows[0]["bench_return"]
    best = max(rows, key=lambda r: r["total_return"])
    beats = [r for r in rows if r["total_return"] > bench]
    print(f"\nBuy&hold Mag-7: {bench*100:+.2f}% ({rows[0]['bench_annualized']*100:+.2f}% ann, SR {rows[0]['bench_sharpe']:.2f})")
    print(f"Best swing config: {best['label']} at {best['total_return']*100:+.2f}%")
    print(f"Configs beating buy&hold: {len(beats)}/{len(rows)}")
    print(json.dumps({"rows": rows, "bench_return": bench}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
