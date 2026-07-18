"""Paper→live promotion — decide which paper strategies are *candidates* for live.

The system never trades live; a "promotion" is an evidence-backed recommendation a
human acts on. ``should_promote`` is a pure, testable gate over a strategy's metrics;
``run_promotions`` records the ones that clear the bar as candidates (with evidence).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PromotionBar:
    min_sharpe: float = 1.0
    min_return_pct: float = 0.0
    max_drawdown_pct: float = 20.0   # maximum allowed drawdown (positive %)
    min_trades: int = 5


def _num(metrics: dict, *keys) -> float:
    for k in keys:
        if metrics.get(k) is not None:
            try:
                return float(metrics[k])
            except (TypeError, ValueError):
                continue
    return 0.0


def should_promote(metrics: dict, bar: PromotionBar = PromotionBar()) -> tuple[bool, str]:
    """Pure gate: does this strategy's paper record clear the promotion bar?"""
    trades = int(_num(metrics, "total_trades", "trades", "num_trades"))
    sharpe = _num(metrics, "sharpe", "sharpe_ratio")
    ret = _num(metrics, "total_return", "return_pct", "total_return_pct")
    dd = abs(_num(metrics, "max_drawdown", "max_drawdown_pct", "maxdd"))
    if trades < bar.min_trades:
        return False, f"too few trades ({trades} < {bar.min_trades})"
    if sharpe < bar.min_sharpe:
        return False, f"sharpe {sharpe:.2f} < {bar.min_sharpe}"
    if ret < bar.min_return_pct:
        return False, f"return {ret:.2f}% < {bar.min_return_pct}%"
    if dd > bar.max_drawdown_pct:
        return False, f"drawdown {dd:.2f}% > {bar.max_drawdown_pct}%"
    return True, "meets promotion bar"


def run_promotions(strategies: list[dict], run_id: Optional[str] = None,
                   bar: PromotionBar = PromotionBar()) -> list[dict]:
    """Evaluate strategy metric dicts; record + return the promotion candidates."""
    from engine.autonomy import store
    promoted = []
    for m in strategies or []:
        ok, reason = should_promote(m, bar)
        if not ok:
            continue
        slug = m.get("strategy_slug") or m.get("slug") or m.get("strategy") or "?"
        symbol = m.get("symbol") or m.get("symbols") or ""
        evidence = {"sharpe": _num(m, "sharpe", "sharpe_ratio"),
                    "return_pct": _num(m, "total_return", "return_pct"),
                    "max_drawdown_pct": abs(_num(m, "max_drawdown", "max_drawdown_pct")),
                    "trades": int(_num(m, "total_trades", "trades")), "reason": reason}
        try:
            store.record_promotion(run_id, str(slug), str(symbol), evidence)
        except Exception:  # noqa: BLE001 — recording is best-effort
            pass
        promoted.append({"strategy_slug": slug, "symbol": symbol, "evidence": evidence})
    return promoted
