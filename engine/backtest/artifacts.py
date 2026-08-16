"""Run-folder artifact writer — the skill's artifact contract.

Writes the dated run folder with every required file and the mandatory
hypothetical-results disclosure. Raw/normalized data are written by `data.py`
directly into this folder's raw/ and normalized/ subdirs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

DISCLOSURE = (
    "**Important disclosure**\n\n"
    "This backtest is a hypothetical historical simulation and does not represent actual "
    "trading performance. Backtested results do not guarantee future results. Results depend "
    "on market-data quality, data feed selection, corporate-action handling, fees, slippage, "
    "liquidity, taxes, execution assumptions, and implementation details. This material is for "
    "research and educational purposes only and is not investment advice, a recommendation, an "
    "offer, or a solicitation to buy or sell securities, options, cryptocurrencies, or any other "
    "financial product. All investments involve risk and may lose value. Review Alpaca's "
    "disclosures and agreements at https://alpaca.markets/disclosures."
)

LOOK_AHEAD_WARNING = (
    "**LOOK-AHEAD WARNING** — this run uses the `same_bar` fill model: signals and fills occur "
    "on the same bar, which can use information not available at decision time. Treat results as "
    "optimistic. Prefer `next_open` for realistic execution."
)


def _w(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_run(folder: Path, ctx: Dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)

    # --- strategy_spec.json -------------------------------------------------
    _w(folder / "strategy_spec.json", json.dumps(ctx["strategy_spec"], indent=2))

    # --- config.json --------------------------------------------------------
    _w(folder / "config.json", json.dumps(ctx["config"], indent=2, default=str))

    # --- data_fingerprint.json ---------------------------------------------
    _w(folder / "data_fingerprint.json", json.dumps(ctx["data_fingerprint"], indent=2))

    # --- fee_source.json ----------------------------------------------------
    _w(folder / "fee_source.json", json.dumps(ctx["fee_source"], indent=2))

    # --- warnings.json ------------------------------------------------------
    _w(folder / "warnings.json", json.dumps(ctx["warnings"], indent=2))

    # --- trades / round_trips / equity / benchmark CSVs --------------------
    pd.DataFrame(ctx["fills"]).to_csv(folder / "trades.csv", index=False)
    pd.DataFrame(ctx["round_trips"]).to_csv(folder / "round_trips.csv", index=False)
    ctx["equity"].rename("equity").to_csv(folder / "equity.csv", header=True)
    ctx["benchmark_equity"].rename("benchmark_equity").to_csv(folder / "benchmark_equity.csv", header=True)

    # --- summary.json (carries the deterministic reproducible_core) --------
    _w(folder / "summary.json", json.dumps(ctx["summary"], indent=2, default=str))

    # --- notes.md -----------------------------------------------------------
    _w(folder / "notes.md", _notes_md(ctx))

    # --- report.md ----------------------------------------------------------
    _w(folder / "report.md", _report_md(ctx))

    # --- run.py (reproducibility re-run) -----------------------------------
    _w(folder / "run.py", _run_py())


def _notes_md(ctx: Dict) -> str:
    c = ctx["config"]
    s = ctx["strategy_spec"]
    lines = [
        f"# Backtest notes — {s['name']}",
        "",
        "## Request",
        ctx.get("request", "Run a buy-the-dip backtest on the configured universe."),
        "",
        "## Confirmed interpretation",
        f"- Symbols: {', '.join(c['symbols'])}",
        f"- Timeframe: {c['timeframe']}",
        f"- Data: Alpaca via alpaca-py, feed={c['feed']}, adjustment={c['adjustment']}",
        f"- Strategy params: {json.dumps(s['params'])}",
        f"- Signal timing: completed bar close; Fill timing/model: {c['fill_model']}",
        f"- Sizing: {s['params']['position_size']:.0%} of available cash, whole shares",
        f"- Execution friction: spread {c['friction']['spread_bps']} bps + slippage "
        f"{c['friction']['slippage_bps']} bps",
        f"- Benchmark: equal-weight buy-and-hold of the same universe",
        f"- Seed: {c['seed']}",
        "",
        "## Fees",
        "Regulatory/pass-through trading-activity fees (SEC, FINRA TAF/CAT, ORF, OCC) are "
        "**excluded** in this run; only execution friction is modeled. See fee_source.json.",
        "",
    ]
    if ctx["warnings"]:
        lines += ["## Warnings", *[f"- {w}" for w in ctx["warnings"]], ""]
    lines += ["## Disclosure", "", DISCLOSURE, ""]
    return "\n".join(lines)


def _report_md(ctx: Dict) -> str:
    m = ctx["summary"]["reproducible_core"]["metrics"]
    b = ctx["summary"]["reproducible_core"]["benchmarks"]
    rt = ctx["summary"]["reproducible_core"]["round_trip"]
    t5 = ctx["summary"]["reproducible_core"]["teaching_five"]
    first = ctx["round_trips"][0] if ctx["round_trips"] else None
    last = ctx["round_trips"][-1] if ctx["round_trips"] else None

    def pct(x):
        return f"{x * 100:.2f}%"

    out = [f"# Backtest report — {ctx['strategy_spec']['name']}", ""]
    if ctx.get("look_ahead"):
        out += [LOOK_AHEAD_WARNING, ""]
    out += [
        "## Performance vs Benchmarks",
        "",
        "| | Total Return | Ann. Return | Max Drawdown | Sharpe | Final Equity |",
        "|---|---:|---:|---:|---:|---:|",
        f"| **Strategy** | {pct(m['total_return'])} | {pct(m['annualized_return'])} | "
        f"{pct(m['max_drawdown'])} | {m['sharpe']:.2f} | ${m['final_equity']:,.2f} |",
        f"| Benchmark (EW buy&hold) | {pct(b['total_return'])} | {pct(b['annualized_return'])} | "
        f"{pct(b['max_drawdown'])} | {b['sharpe']:.2f} | ${b['final_equity']:,.2f} |",
        "",
        "## Teaching Five",
        f"1. Total return: **{pct(t5['total_return'])}** vs benchmark {pct(t5['benchmark_total_return'])}",
        f"2. Max drawdown: **{pct(t5['max_drawdown'])}**",
        f"3. Trades (round trips): **{t5['trades']}**",
        f"4. Win rate: **{pct(t5['win_rate'])}**",
        f"5. Sharpe: **{t5['sharpe']:.2f}** vs benchmark {t5['benchmark_sharpe']:.2f}",
        "",
        "## Detail",
        f"- Profit factor: {rt['profit_factor']}",
        f"- Wins / losses: {rt['wins']} / {rt['losses']}",
        f"- Fees paid (modeled): ${rt['fees_paid']:.2f}",
        f"- First trade: {first['symbol']} {first['entry_time']} → {first['exit_time']} "
        f"(pnl {first['pnl']:.2f})" if first else "- First trade: none",
        f"- Last trade: {last['symbol']} {last['entry_time']} → {last['exit_time']} "
        f"(pnl {last['pnl']:.2f})" if last else "- Last trade: none",
        "",
        "## Data fingerprint",
        "```json",
        json.dumps(ctx["data_fingerprint"], indent=2),
        "```",
        "",
        "## Disclosure",
        "",
        DISCLOSURE,
        "",
    ]
    return "\n".join(out)


def _run_py() -> str:
    return (
        '#!/usr/bin/env python3\n'
        '"""Reproduce this run from its saved normalized data and assert determinism.\n\n'
        'Re-runs the simulation from normalized/ + config.json + strategy_spec.json and\n'
        'compares the recomputed reproducible_core to the stored summary.json. Exits 0 on\n'
        'an exact match, 1 otherwise.\n'
        '"""\n'
        'import json, sys\n'
        'from pathlib import Path\n\n'
        '# Make the AlpaTrade `engine` package importable whether or not it is installed:\n'
        '# walk up from this run folder until we find a dir containing engine/backtest.\n'
        'try:\n'
        '    from engine.backtest.runner import reproduce\n'
        'except ModuleNotFoundError:\n'
        '    here = Path(__file__).resolve()\n'
        '    for parent in here.parents:\n'
        '        if (parent / "engine" / "backtest" / "runner.py").exists():\n'
        '            sys.path.insert(0, str(parent))\n'
        '            break\n'
        '    from engine.backtest.runner import reproduce\n\n'
        'folder = Path(__file__).resolve().parent\n'
        'stored = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["reproducible_core"]\n'
        'recomputed = reproduce(folder)\n'
        'match = json.dumps(stored, sort_keys=True) == json.dumps(recomputed, sort_keys=True)\n'
        'print("REPRODUCIBLE: PASS" if match else "REPRODUCIBLE: FAIL")\n'
        'sys.exit(0 if match else 1)\n'
    )

