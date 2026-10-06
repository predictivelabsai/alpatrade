"""Durable multi-strategy walk-forward comparison orchestration.

The grid backtester remains the execution engine.  This module only plans
chronological train/test folds, pins the selected training parameters for the
following unseen window, and aggregates out-of-sample evidence.  It deliberately
does not promote or start paper trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import reduce
from typing import Any, Callable, Iterable


SUPPORTED_STRATEGIES = ("buy_the_dip", "momentum", "vix")
SUPPORTED_HORIZONS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA")
DEFAULT_BTD_GRID = {
    "dip_threshold": [0.03, 0.05, 0.07],
    "take_profit": [0.01, 0.015],
    "stop_loss": [0.005],
    "hold_days": [1, 2, 3],
    "min_hold_days": [3],
    "position_size": [0.10],
}
DEFAULT_FIXED_PARAMS = {
    "momentum": {
        "lookback_period": 20,
        "momentum_threshold": 0.05,
        "hold_days": 5,
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.05,
        "position_size_pct": 0.10,
    },
    "vix": {"vix_threshold": 20.0, "hold_overnight": True, "position_size": 0.10},
}


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "fold": self.index,
            "train_start": self.train_start.date().isoformat(),
            "train_end": self.train_end.date().isoformat(),
            "test_start": self.test_start.date().isoformat(),
            "test_end": self.test_end.date().isoformat(),
        }


def normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a tenant-supplied comparison specification."""
    strategies = list(dict.fromkeys(
        str(item).strip().lower() for item in raw.get("strategies", SUPPORTED_STRATEGIES)
    ))
    unknown = sorted(set(strategies) - set(SUPPORTED_STRATEGIES))
    if unknown:
        raise ValueError(f"unsupported strategies: {', '.join(unknown)}")
    horizons = list(dict.fromkeys(
        str(item).strip().lower() for item in raw.get("horizons", ("3m", "1y"))
    ))
    invalid_horizons = sorted(set(horizons) - set(SUPPORTED_HORIZONS))
    if invalid_horizons:
        raise ValueError(f"unsupported horizons: {', '.join(invalid_horizons)}")
    requested_symbols = raw.get("symbols") or DEFAULT_SYMBOLS
    symbols = list(dict.fromkeys(
        str(item).strip().upper() for item in requested_symbols
        if str(item).strip()
    ))
    if not symbols or len(symbols) > 25:
        raise ValueError("symbols must contain between 1 and 25 tickers")
    capital = float(raw.get("initial_capital", 10_000.0))
    if capital <= 0:
        raise ValueError("initial_capital must be positive")
    folds = int(raw.get("folds", 3))
    if folds < 2 or folds > 10:
        raise ValueError("folds must be between 2 and 10")
    min_hold_days = max(0, int(raw.get("min_hold_days", 3)))
    minimum_trades = max(1, int(raw.get("minimum_oos_trades", 20)))
    return {
        "strategies": strategies,
        "horizons": horizons,
        "symbols": symbols,
        "initial_capital": capital,
        "folds": folds,
        "min_hold_days": min_hold_days,
        "minimum_oos_trades": minimum_trades,
        "benchmark_symbol": str(raw.get("benchmark_symbol") or "SPY").upper(),
        "objective": {"maximize": str(raw.get("objective") or "sharpe_ratio")},
        "include_taf_fees": bool(raw.get("include_taf_fees", True)),
        "include_cat_fees": bool(raw.get("include_cat_fees", True)),
        "slippage_bps": max(0.0, float(raw.get("slippage_bps", 5.0))),
        "conservative_execution": bool(raw.get("conservative_execution", True)),
        "end_date": raw.get("end_date"),
    }


def build_folds(horizon: str, count: int, *, end: datetime | None = None) -> list[Fold]:
    """Create expanding-train, non-overlapping OOS folds inside one horizon."""
    total_days = SUPPORTED_HORIZONS[horizon]
    end = end or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    test_days = max(7, total_days // (count + 2))
    train_days = total_days - test_days * count
    # A one-month comparison with two folds leaves a 16-calendar-day initial
    # training window.  Keep that advertised combination usable while still
    # rejecting folds whose training slice is too small to be meaningful.
    if train_days < 14:
        raise ValueError("horizon is too short for the requested fold count")
    origin = end - timedelta(days=total_days)
    folds = []
    for index in range(count):
        test_start = origin + timedelta(days=train_days + index * test_days)
        test_end = end if index == count - 1 else test_start + timedelta(days=test_days)
        folds.append(Fold(index + 1, origin, test_start, test_start, test_end))
    return folds


def _return(row: dict[str, Any]) -> float:
    return float(row.get("total_return", 0.0) or 0.0)


def _compound(values: Iterable[float]) -> float:
    return (reduce(lambda acc, value: acc * (1.0 + value / 100.0), values, 1.0) - 1.0) * 100.0


def _test_request(base: dict[str, Any], strategy: str, best: dict[str, Any]) -> dict[str, Any]:
    request = dict(base)
    params = dict(best.get("params") or {})
    params.pop("symbols", None)
    if strategy == "buy_the_dip":
        keys = ("dip_threshold", "take_profit", "hold_days", "min_hold_days", "stop_loss", "position_size")
        request["variations"] = {key: [params[key]] for key in keys if key in params}
    elif strategy == "momentum":
        request["params"] = {
            "lookback_period": params.get("lookback_period", 20),
            "momentum_threshold": params.get("momentum_threshold", 0.05),
            "hold_days": params.get("hold_days", 5),
            "take_profit_pct": params.get("take_profit", 0.10),
            "stop_loss_pct": params.get("stop_loss", 0.05),
            "position_size_pct": params.get("position_size_pct", 0.10),
        }
    else:
        request["params"] = {
            "vix_threshold": params.get("vix_threshold", 20.0),
            "hold_overnight": params.get("hold_type", "on") == "on",
            "position_size": params.get("position_size", 0.10),
        }
    return request


def _aggregate(strategy: str, horizon: str, rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    train_return = _compound(row["train_return"] for row in rows)
    oos_return = _compound(row["oos_return"] for row in rows)
    benchmark_return = _compound(row["benchmark_return"] for row in rows)
    trades = sum(row["oos_trades"] for row in rows)
    wins = sum(row["oos_win_rate"] * row["oos_trades"] / 100.0 for row in rows)
    profitable_folds = sum(row["oos_return"] > 0 for row in rows)
    max_drawdown = max((row["oos_max_drawdown"] for row in rows), default=0.0)
    status = "valid" if trades >= spec["minimum_oos_trades"] else "insufficient_trades"
    warnings = []
    if status != "valid":
        warnings.append(f"only {trades} OOS trades; minimum is {spec['minimum_oos_trades']}")
    if train_return > 0 and oos_return < train_return * 0.5:
        warnings.append("OOS return is less than half the in-sample return")
    if profitable_folds <= len(rows) // 2:
        warnings.append("half or fewer OOS folds were profitable")
    return {
        "strategy": strategy,
        "horizon": horizon,
        "search_mode": "grid" if strategy == "buy_the_dip" else "fixed_configuration",
        "train_return": train_return,
        "oos_return": oos_return,
        "oos_pnl": spec["initial_capital"] * oos_return / 100.0,
        "benchmark": spec["benchmark_symbol"],
        "benchmark_return": benchmark_return,
        "oos_excess_return": oos_return - benchmark_return,
        "oos_trades": trades,
        "oos_win_rate": (wins / trades * 100.0) if trades else None,
        "oos_max_drawdown": max_drawdown,
        "profitable_folds": profitable_folds,
        "fold_count": len(rows),
        "status": status,
        "warnings": warnings,
        "folds": rows,
    }


def run_comparison(
    raw_spec: dict[str, Any],
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    benchmarker: Callable[[str, datetime, datetime, str], float | None],
) -> dict[str, Any]:
    """Run and aggregate a multi-strategy walk-forward comparison."""
    spec = normalize_spec(raw_spec)
    end = datetime.fromisoformat(spec["end_date"]) if spec.get("end_date") else None
    results = []
    for horizon in spec["horizons"]:
        rows_by_strategy = {strategy: [] for strategy in spec["strategies"]}
        for fold in build_folds(horizon, spec["folds"], end=end):
            for strategy in spec["strategies"]:
                common = {
                    "strategy": strategy,
                    "symbols": spec["symbols"],
                    "initial_capital": spec["initial_capital"],
                    "objective": spec["objective"],
                    "include_taf_fees": spec["include_taf_fees"],
                    "include_cat_fees": spec["include_cat_fees"],
                    "slippage_bps": spec["slippage_bps"],
                    "conservative_execution": spec["conservative_execution"],
                }
                train_request = {
                    **common,
                    "start_date": fold.train_start.isoformat(),
                    "end_date": fold.train_end.isoformat(),
                }
                if strategy == "buy_the_dip":
                    grid = {key: list(values) for key, values in DEFAULT_BTD_GRID.items()}
                    grid["min_hold_days"] = [spec["min_hold_days"]]
                    grid["hold_days"] = sorted({
                        max(spec["min_hold_days"], day) for day in grid["hold_days"]
                    })
                    train_request["variations"] = grid
                else:
                    train_request["params"] = dict(DEFAULT_FIXED_PARAMS[strategy])
                trained = runner(train_request)
                best = dict(trained.get("best_config") or {})
                if not best:
                    raise RuntimeError(f"{strategy} training produced no usable configuration")
                test_request = _test_request({
                    **common,
                    "start_date": fold.test_start.isoformat(),
                    "end_date": fold.test_end.isoformat(),
                }, strategy, best)
                tested = runner(test_request)
                oos = dict(tested.get("best_config") or {})
                benchmark = benchmarker(
                    spec["benchmark_symbol"], fold.test_start, fold.test_end, "yfinance"
                )
                row = {
                    **fold.as_dict(),
                    "train_run_id": trained.get("run_id"),
                    "oos_run_id": tested.get("run_id"),
                    "selected_params": best.get("params") or {},
                    "train_return": _return(best),
                    "oos_return": _return(oos),
                    "benchmark_return": float(benchmark or 0.0),
                    "oos_trades": int(oos.get("total_trades", 0) or 0),
                    "oos_win_rate": float(oos.get("win_rate", 0.0) or 0.0),
                    "oos_max_drawdown": float(oos.get("max_drawdown", 0.0) or 0.0),
                }
                rows_by_strategy[strategy].append(row)
        for strategy, rows in rows_by_strategy.items():
            results.append(_aggregate(strategy, horizon, rows, spec))
    eligible = [
        row for row in results
        if row["status"] == "valid" and row["oos_return"] > 0
        and row["profitable_folds"] > row["fold_count"] / 2
    ]
    winner = max(eligible, key=lambda row: row["oos_return"], default=None)
    return {
        "status": "completed",
        "methodology": "rolling_walk_forward",
        "spec": spec,
        "results": results,
        "winner": winner,
        "promotion": {
            "eligible": bool(winner),
            "automatic": False,
            "reason": (
                "A candidate passed the minimum OOS evidence gates; explicit approval is still required."
                if winner else "No candidate passed the minimum OOS evidence gates."
            ),
        },
        "disclaimer": "Hypothetical paper research; past performance does not predict future returns.",
    }
