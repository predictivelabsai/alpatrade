"""Orchestrate a methodology-faithful backtest and write the dated artifact folder.

Public API:
    run_backtest(...)  -> BacktestResult   # fetch Alpaca data, simulate, write artifacts
    reproduce(folder)  -> dict             # recompute the deterministic core from normalized data

CLI:
    python -m engine.backtest.runner --symbols AAPL,MSFT --start 2024-01-01 --end 2024-06-30
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from engine.backtest import artifacts, data, metrics
from engine.backtest.engine import equal_weight_buy_hold, simulate
from engine.backtest.fills import DEFAULT_FILL_MODEL, FILL_MODELS, Friction
from engine.backtest.strategies import build_strategy

ARTIFACT_ROOT = Path("backtest-results")


@dataclass
class BacktestResult:
    folder: Path
    summary: Dict

    @property
    def teaching_five(self) -> Dict:
        return self.summary["reproducible_core"]["teaching_five"]


def _core_fingerprint(normalized_path: Path) -> Dict:
    """Deterministic per-symbol fingerprint recomputable from the normalized CSV alone."""
    df = pd.read_csv(normalized_path)
    close_sum = round(float(df["c"].sum()), 6) if len(df) else 0.0
    return {
        "bars": int(len(df)),
        "close_sum": close_sum,
        "normalized_file_hash": hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
    }


def _compute_core(symbol_bars: Dict[str, pd.DataFrame], strategy, config: Dict,
                  normalized_dir: Path) -> Dict:
    """The deterministic heart of a run — identical for a live run and a reproduce()."""
    friction = Friction(**config["friction"])
    round_trips, equity, fills = simulate(
        symbol_bars, strategy, config["initial_capital"],
        fill_model=config["fill_model"], friction=friction, fractional=config["fractional"],
    )
    bench_equity = equal_weight_buy_hold(symbol_bars, config["initial_capital"])

    strat_m = metrics.equity_metrics(equity)
    bench_m = metrics.equity_metrics(bench_equity)
    rt_m = metrics.round_trip_metrics(round_trips)
    t5 = metrics.teaching_five(strat_m, bench_m, rt_m)

    core_fp = {sym: _core_fingerprint(normalized_dir / f"bars_{sym}.csv")
               for sym in symbol_bars}

    core = {
        "metrics": strat_m,
        "benchmarks": bench_m,
        "round_trip": rt_m,
        "teaching_five": t5,
        "core_fingerprint": core_fp,
    }
    return core, round_trips, equity, bench_equity, fills


def run_backtest(
    symbols: List[str],
    start: datetime,
    end: datetime,
    initial_capital: float = 10000.0,
    strategy_name: str = "buy_the_dip",
    strategy_params: Dict | None = None,
    fill_model: str = DEFAULT_FILL_MODEL,
    interval: str = "1d",
    feed: str = data.DEFAULT_FEED,
    adjustment: str = data.DEFAULT_ADJUSTMENT,
    spread_bps: float = 0.0,
    slippage_bps: float = 5.0,
    vol_scale: float = 0.0,
    fractional: bool = False,
    seed: int = 42,
    artifact_root: Path = ARTIFACT_ROOT,
    request: str = "",
) -> BacktestResult:
    if fill_model not in FILL_MODELS:
        raise ValueError(f"fill_model must be one of {FILL_MODELS}")

    strategy = build_strategy(strategy_name, **(strategy_params or {}))
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")
    slug = f"{stamp}_{'-'.join(symbols)[:24]}_{strategy_name}_{interval}"
    folder = artifact_root / slug
    raw_dir, normalized_dir = folder / "raw", folder / "normalized"

    # 1. Fetch Alpaca data → raw + normalized + rich fingerprint
    symbol_data = {}
    warnings: List[str] = []
    for sym in symbols:
        sd = data.fetch_symbol(sym, start, end, raw_dir, normalized_dir, interval, feed, adjustment)
        symbol_data[sym] = sd
        if sd.bars.empty:
            warnings.append(f"No bars returned for {sym} ({feed}/{interval}) — excluded.")
    symbol_bars = {s: sd.bars for s, sd in symbol_data.items() if not sd.bars.empty}
    if not symbol_bars:
        raise RuntimeError("No market data fetched for any symbol; cannot backtest.")

    config = {
        "symbols": list(symbol_bars.keys()),
        "timeframe": interval,
        "feed": feed,
        "adjustment": adjustment,
        "initial_capital": initial_capital,
        "fill_model": fill_model,
        "friction": {"spread_bps": spread_bps, "slippage_bps": slippage_bps,
                     "vol_scale": vol_scale},
        "fractional": fractional,
        "seed": seed,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

    # 2. Deterministic core
    core, round_trips, equity, bench_equity, fills = _compute_core(
        symbol_bars, strategy, config, normalized_dir)

    if fill_model == "same_bar":
        warnings.append("same_bar fill model used — look-ahead risk; see report.")

    summary = {
        "strategy_name": strategy_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols": list(symbol_bars.keys()),
        "timeframe": interval,
        "initial_cash": initial_capital,
        "generated_at": now.isoformat(),
        "reproducible_core": core,
        "first_trade": round_trips[0] if round_trips else {},
        "last_trade": round_trips[-1] if round_trips else {},
        "assumptions": [
            f"fill_model={fill_model}", f"feed={feed}", f"adjustment={adjustment}",
            "regulatory fees excluded (execution friction only)",
        ],
        "warnings": warnings,
    }

    fee_source = {
        "url": "https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf",
        "revision_date": None,
        "extracted_at": None,
        "modeled_categories": [],
        "excluded_categories": ["SEC", "FINRA_TAF", "FINRA_CAT", "ORF", "OCC"],
    }

    ctx = {
        "config": config,
        "strategy_spec": {"name": strategy_name, "params": strategy.params, "version": "0.1"},
        "data_fingerprint": {s: sd.fingerprint for s, sd in symbol_data.items()},
        "fee_source": fee_source,
        "warnings": warnings,
        "fills": fills,
        "round_trips": round_trips,
        "equity": equity,
        "benchmark_equity": bench_equity,
        "summary": summary,
        "request": request,
        "look_ahead": fill_model == "same_bar",
    }
    artifacts.write_run(folder, ctx)
    return BacktestResult(folder, summary)


def reproduce(folder: Path) -> Dict:
    """Recompute the deterministic reproducible_core from the run's normalized data."""
    folder = Path(folder)
    config = json.loads((folder / "config.json").read_text())
    spec = json.loads((folder / "strategy_spec.json").read_text())
    normalized_dir = folder / "normalized"
    strategy = build_strategy(spec["name"], **spec["params"])
    symbol_bars = {sym: data.load_normalized(normalized_dir, sym) for sym in config["symbols"]}
    core, *_ = _compute_core(symbol_bars, strategy, config, normalized_dir)
    return core


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="AlpaTrade methodology backtest (Alpaca data)")
    p.add_argument("--symbols", default="AAPL", help="comma-separated symbols")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-06-30")
    p.add_argument("--capital", type=float, default=10000.0)
    p.add_argument("--strategy", default="buy_the_dip")
    p.add_argument("--fill-model", default=DEFAULT_FILL_MODEL, choices=FILL_MODELS)
    p.add_argument("--interval", default="1d")
    p.add_argument("--feed", default=data.DEFAULT_FEED)
    p.add_argument("--dip-threshold", type=float, default=0.02)
    p.add_argument("--take-profit", type=float, default=0.03)
    p.add_argument("--stop-loss", type=float, default=0.02)
    p.add_argument("--hold-days", type=int, default=5)
    p.add_argument("--vol-scale", type=float, default=0.0,
                   help="Vol-dependent slippage scaling (0=off, ~0.5=moderate)")
    return p.parse_args(argv)


def main(argv=None):
    a = _parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    res = run_backtest(
        symbols=[s.strip().upper() for s in a.symbols.split(",") if s.strip()],
        start=datetime.fromisoformat(a.start),
        end=datetime.fromisoformat(a.end),
        initial_capital=a.capital,
        strategy_name=a.strategy,
        strategy_params={
            "dip_threshold": a.dip_threshold,
            "take_profit": a.take_profit,
            "stop_loss": a.stop_loss,
            "hold_days": a.hold_days,
        },
        fill_model=a.fill_model,
        interval=a.interval,
        feed=a.feed,
        vol_scale=a.vol_scale,
        request=f"CLI backtest {a.strategy} on {a.symbols}",
    )
    t5 = res.teaching_five
    print(f"\nArtifacts: {res.folder}")
    print("Teaching Five:")
    print(f"  total return:  {t5['total_return']*100:.2f}%  (benchmark {t5['benchmark_total_return']*100:.2f}%)")
    print(f"  max drawdown:  {t5['max_drawdown']*100:.2f}%")
    print(f"  trades:        {t5['trades']}")
    print(f"  win rate:      {t5['win_rate']*100:.2f}%")
    print(f"  sharpe:        {t5['sharpe']:.2f}  (benchmark {t5['benchmark_sharpe']:.2f})")


if __name__ == "__main__":
    main()
