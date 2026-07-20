#!/usr/bin/env python3
"""Multi-horizon strategy comparison on the Mag-7 basket → shareable markdown report.

Runs each strategy's grid-search over several look-back windows (1m/3m/6m/1y) so we can
see whether an edge is *consistent* across horizons (robust) or only shows up on one
window (over-fit). Writes docs/backtest_summary_<ts>.md. All backtests persist to the
DB (alpatrade.runs / backtest_summaries / trades) as usual.

Usage: python scripts/multi_horizon_report.py
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

from scripts.strategy_backtest_compare import MAG7, STRATEGIES, run  # noqa: E402

HORIZONS = ["1m", "3m", "6m", "1y"]
CAPITAL = 10000.0


def _cell(m: dict) -> str:
    if not m or "error" in m:
        return "—"
    return f"{m['return_pct']:+.2f}% / {m['sharpe']:.2f} / {m['trades']}"


def main() -> int:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    data = {h: run(h, CAPITAL) for h in HORIZONS}  # {horizon: {strategy: metrics}}

    lines = []
    w = lines.append
    w(f"# AlpaTrade — Mag-7 strategy backtest summary\n")
    w(f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
      f"basket: {', '.join(MAG7)} · starting capital ${CAPITAL:,.0f}_\n")
    w("Each cell is the **best grid-search variation** for that strategy over that look-back "
      "window, shown as **Return% / Sharpe / Trades**. Comparing across horizons is the "
      "anti-over-fit check: an edge that only appears on one window is likely fitted to it.\n")

    # matrix
    w("## Performance across horizons\n")
    w("| Strategy | " + " | ".join(HORIZONS) + " |")
    w("|---|" + "|".join(["---"] * len(HORIZONS)) + "|")
    for strat in STRATEGIES:
        w(f"| `{strat}` | " + " | ".join(_cell(data[h].get(strat, {})) for h in HORIZONS) + " |")
    w("")

    # PnL table
    w("## PnL ($) by horizon\n")
    w("| Strategy | " + " | ".join(HORIZONS) + " |")
    w("|---|" + "|".join(["---"] * len(HORIZONS)) + "|")
    for strat in STRATEGIES:
        cells = []
        for h in HORIZONS:
            m = data[h].get(strat, {})
            cells.append("—" if not m or "error" in m else f"${m['pnl']:,.0f}")
        w(f"| `{strat}` | " + " | ".join(cells) + " |")
    w("")

    # calibration
    w("## Calibration / over-fit read\n")
    for strat in STRATEGIES:
        rets = [data[h].get(strat, {}).get("return_pct") for h in HORIZONS]
        rets = [r for r in rets if r is not None]
        traded = [h for h in HORIZONS if data[h].get(strat, {}).get("trades")]
        if not traded:
            w(f"- **`{strat}`** — produced **no trades** on any horizon (default grid didn't "
              f"trigger on this basket); not comparable without parameter tuning.")
            continue
        pos = sum(1 for r in rets if r > 0)
        sharpes = [data[h].get(strat, {}).get("sharpe", 0) for h in traded]
        note = ("consistent across horizons — more trustworthy"
                if pos == len(rets) and rets else
                "profitable only on some horizons — treat with caution (possible over-fit)")
        w(f"- **`{strat}`** — traded on {', '.join(traded)}; positive on {pos}/{len(rets)} "
          f"horizons; Sharpe range {min(sharpes):.1f}–{max(sharpes):.1f}. {note}.")
    w("")
    # recommended (calibrate to the longest window that traded)
    best_strat, best_h, best_m = None, None, None
    for strat in STRATEGIES:
        for h in reversed(HORIZONS):  # prefer the longest window (most out-of-sample-like)
            m = data[h].get(strat, {})
            if m.get("trades") and m.get("return_pct", 0) > (best_m or {}).get("return_pct", -1e9):
                best_strat, best_h, best_m = strat, h, m
    if best_m:
        w("## Calibrated recommendation\n")
        w(f"On the **longest window that actually traded**, the best strategy is **`{best_strat}`** "
          f"over **{best_h}**: {best_m['return_pct']:+.2f}% return, ${best_m['pnl']:,.0f} PnL, "
          f"Sharpe {best_m['sharpe']:.2f}, {best_m['trades']} trades, {best_m['max_dd']:.2f}% max drawdown.")
        w(f"\nWinning parameters: `{json.dumps(best_m.get('params'))}`\n")

    w("## Caveats\n")
    w("- **Best-of-grid is optimistic.** Each cell picks the best of ~18 variations on that exact "
      "window; a very high Sharpe on a short window usually means over-fit, not edge. Longer windows "
      "are more trustworthy. For a true test, run walk-forward (train on one window, test on the next).")
    w("- Momentum / VIX may need parameter tuning to trade on this basket; `box_wedge` isn't wired "
      "into the grid-search backtester.")
    w("- Hypothetical results; not financial advice. Past performance does not predict future returns.\n")

    w("## Storage & reproduce\n")
    w("- Every grid variation is persisted to the DB: `alpatrade.runs` (mode=backtest), "
      "`alpatrade.backtest_summaries`, `alpatrade.trades` (trade_type=backtest).")
    w("- Reproduce: `python scripts/multi_horizon_report.py` (or `scripts/strategy_backtest_compare.py "
      "<lookback>` for a single window).\n")

    out = ROOT / "docs" / f"backtest_summary_{ts}.md"
    out.write_text("\n".join(lines))
    (ROOT / "docs" / "_last_backtest_summary_path.txt").write_text(str(out))
    print("WROTE", out)
    print(json.dumps(data, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
