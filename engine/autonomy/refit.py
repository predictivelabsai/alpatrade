"""Refit node — closed-loop feedback from paper-trade outcomes to the next grid.

The pipeline was open-loop: each autonomy tick re-ran the *identical* static
grid regardless of how the previous paper session performed. This module turns
it into a controller: after each paper-trade session, compare realised paper
performance to the backtest's expectation and narrow the next search around the
top-K variations (with a perturbation band) when there is evidence of regime
drift.

Pure functions only — no I/O, no broker calls — so the logic is trivially
unit-testable. The ``refit_node`` in ``engine/autonomy/graph.py`` wraps these
and persists the refined grid centre into the run context / next scout tick.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

log = logging.getLogger("autonomy.refit")

# Drift signal: if paper Sharpe < backtest Sharpe * DRIFT_RATIO, treat the
# regime as having shifted and narrow the grid. Above this ratio, keep the
# full grid (the model is tracking).
DRIFT_RATIO = 0.5

# How many top-K backtest variations to seed the refined grid around.
TOP_K = 3

# Perturbation band around each seeded param: ± this fraction of the value.
# e.g. dip_threshold=0.05 → [0.04, 0.05, 0.06] at BAND=0.2.
PERTURBATION_BAND = 0.2

# Minimum number of paper trades to trust the drift signal (avoid noise).
MIN_PAPER_TRADES = 5

# Params eligible for refinement (continuous, in fraction units).
_REFINABLE = {"dip_threshold", "take_profit", "stop_loss", "position_size"}
# Integer params (hold_days) — perturb by ±1 instead of a fraction.
_INT_PARAMS = {"hold_days"}


def _safe_float(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (TypeError, ValueError):
        return d


def paper_sharpe(paper_trades: List[Dict[str, Any]]) -> Optional[float]:
    """Annualised Sharpe from a list of paper-trade dicts (each with `pnl_pct`).

    Returns None if there are too few trades to be meaningful.
    """
    rets = [_safe_float(t.get("pnl_pct")) for t in paper_trades if t.get("pnl_pct") is not None]
    if len(rets) < MIN_PAPER_TRADES:
        return None
    import statistics
    mean = statistics.mean(rets)
    stdev = statistics.stdev(rets)
    if stdev <= 0:
        return 0.0
    return (mean / stdev) * math.sqrt(252)


def detect_drift(backtest_sharpe: Optional[float],
                 paper_sharpe_val: Optional[float],
                 ratio: float = DRIFT_RATIO) -> bool:
    """True when paper performance has degraded relative to the backtest expectation."""
    if backtest_sharpe is None or paper_sharpe_val is None:
        return False
    if backtest_sharpe <= 0:
        # Backtest expected no edge; any negative paper is drift, any positive is a bonus.
        return paper_sharpe_val < 0
    return paper_sharpe_val < backtest_sharpe * ratio


def refine_grid(top_variations: List[Dict[str, Any]],
                k: int = TOP_K,
                band: float = PERTURBATION_BAND) -> Dict[str, list]:
    """Build a narrowed grid centred on the top-K variations' params.

    For each refinable continuous param, collects the top-K values and adds
    ±band% neighbours. For integer params (hold_days), adds ±1. Dedupes and
    sorts. Returns a variations dict suitable for ``BacktestAgent``.

    If no variations have refinable params, returns {} (caller keeps the default grid).
    """
    # Extract param dicts, sorted by score (highest first) then take top-K
    scored = [v for v in top_variations if v.get("_score") is not None]
    scored.sort(key=lambda v: v.get("_score", 0), reverse=True)
    if not scored:
        # Fall back to sharpe if scores aren't present
        scored = sorted(top_variations, key=lambda v: v.get("sharpe_ratio", 0), reverse=True)
    seed = scored[:k]

    refined: Dict[str, set] = {}
    for v in seed:
        params = v.get("params") or {}
        for p, val in params.items():
            if p not in _REFINABLE and p not in _INT_PARAMS:
                continue
            if p in _INT_PARAMS:
                iv = int(round(_safe_float(val, 1)))
                for nv in (max(1, iv - 1), iv, iv + 1):
                    refined.setdefault(p, set()).add(nv)
            else:
                fv = _safe_float(val)
                if fv <= 0:
                    continue
                lo = round(max(0.001, fv * (1 - band)), 4)
                hi = round(fv * (1 + band), 4)
                for nv in (lo, round(fv, 4), hi):
                    refined.setdefault(p, set()).add(nv)

    return {p: sorted(v) for p, v in refined.items()}


def refit_plan(backtest_result: Dict[str, Any],
               paper_trades: List[Dict[str, Any]],
               ratio: float = DRIFT_RATIO,
               k: int = TOP_K,
               band: float = PERTURBATION_BAND) -> Dict[str, Any]:
    """Decide whether to refine the grid and return the plan.

    Returns:
        {"drift": bool, "refined_grid": dict, "paper_sharpe": float|None,
         "backtest_sharpe": float|None, "reason": str}
    The caller writes ``refined_grid`` into the next run's config when drift is True.
    """
    bt_sharpe = None
    best = (backtest_result or {}).get("best_config") or {}
    if best:
        bt_sharpe = _safe_float(best.get("sharpe_ratio")) or None

    p_sharpe = paper_sharpe(paper_trades)
    drift = detect_drift(bt_sharpe, p_sharpe, ratio=ratio)

    if not drift:
        return {"drift": False, "refined_grid": {},
                "paper_sharpe": p_sharpe, "backtest_sharpe": bt_sharpe,
                "reason": "paper tracks backtest (no drift)"}

    all_results = (backtest_result or {}).get("all_results_summary") or []
    refined = refine_grid(all_results, k=k, band=band)
    if not refined:
        return {"drift": True, "refined_grid": {},
                "paper_sharpe": p_sharpe, "backtest_sharpe": bt_sharpe,
                "reason": "drift detected but no refinable params in top variations"}
    return {"drift": True, "refined_grid": refined,
            "paper_sharpe": p_sharpe, "backtest_sharpe": bt_sharpe,
            "reason": f"drift: paper Sharpe {p_sharpe:.2f} < backtest {bt_sharpe:.2f}×{ratio}"}
