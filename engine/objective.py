"""PnL-maximising objective function for backtest variation ranking.

Replaces the prior `max(results, key=sharpe_ratio)` selection (which had no
drawdown penalty, no min-trade guard, and no volatility awareness) with a
composite score tuned to the project goal of **maximising PnL** while
controlling risk.

Score is:
    score = annualized_return
            - λ_drawdown * max_drawdown_pct
            - λ_vol * downside_vol_penalty
            - λ_size * size_penalty   (under min_trades)

subject to a hard `min_trades` gate (variations below the threshold are
disqualified, not just penalised) and an `error`/`no_price_data` guard.

All λ weights and the min-trades floor are configurable; defaults reflect a
PnL-first posture with a meaningful drawdown deterrent. Pure function — no
side effects, no I/O — so it is trivially unit-testable and reusable by the
autonomy refit node (Phase 1b) and the regime-conditional grid (Phase 2c).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ObjectiveWeights:
    """Weights for the composite ranking score.

    Defaults: PnL-first (annualised return dominates), with a real
    drawdown deterrent, a downside-vol penalty, and a Sortino bonus.
    `min_trades` is a hard gate, not a soft penalty — variations below
    it are filtered out. The Calmar ratio (ann_ret / max_dd) is already
    captured implicitly via the drawdown penalty; the Sortino bonus
    directly rewards downside-aware risk-adjusted returns.
    """
    lambda_drawdown: float = 1.0
    lambda_vol: float = 0.3
    lambda_size: float = 0.0
    lambda_sortino: float = 0.2
    min_trades: int = 20

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None) -> "ObjectiveWeights":
        if not cfg:
            return cls()
        return cls(
            lambda_drawdown=float(cfg.get("lambda_drawdown", cls().lambda_drawdown)),
            lambda_vol=float(cfg.get("lambda_vol", cls().lambda_vol)),
            lambda_size=float(cfg.get("lambda_size", cls().lambda_size)),
            lambda_sortino=float(cfg.get("lambda_sortino", cls().lambda_sortino)),
            min_trades=int(cfg.get("min_trades", cls().min_trades)),
        )


def score_variation(result: Dict[str, Any], w: ObjectiveWeights) -> Optional[float]:
    """Score a single backtest variation. Return None if disqualified.

    Disqualification happens when:
      - the variation errored or had no price data (`error` key present)
      - `total_trades` < `w.min_trades` (fluke / overfit guard)
    """
    if result.get("error"):
        return None
    total_trades = int(result.get("total_trades", 0) or 0)
    if total_trades < w.min_trades:
        return None

    ann_ret = float(result.get("annualized_return", 0.0) or 0.0)
    max_dd = float(result.get("max_drawdown", 0.0) or 0.0)
    # downside-vol proxy: use Sharpe denominator when available; fall back to 0.
    # We penalise low Sharpe (high vol relative to return) but don't reward
    # infinite Sharpe from a single trade — the min_trades gate handles that.
    sharpe = float(result.get("sharpe_ratio", 0.0) or 0.0)
    # Convert Sharpe into a soft vol penalty: negative Sharpe hurts, near-zero
    # mildly hurts; capped so it can't dominate the return term.
    vol_penalty = max(0.0, 5.0 - sharpe) if sharpe < 5.0 else 0.0
    # Sortino bonus (Phase 4a): reward downside-aware risk-adjusted returns.
    sortino = float(result.get("sortino_ratio", 0.0) or 0.0)
    sortino_bonus = w.lambda_sortino * min(sortino, 10.0)  # cap to avoid domination

    score = (
        ann_ret
        - w.lambda_drawdown * max_dd
        - w.lambda_vol * vol_penalty
        + sortino_bonus
    )

    # Optional size penalty (off by default — min_trades gate is the main guard)
    if w.lambda_size > 0:
        score -= w.lambda_size * max(0.0, w.min_trades - total_trades)

    return score


def rank_variations(results: List[Dict[str, Any]],
                    weights: Optional[ObjectiveWeights] = None) -> List[Dict[str, Any]]:
    """Return results sorted by score descending; disqualified ones excluded.

    Each result gets a `_score` field injected for transparency. Pure: does
    not mutate the input list (returns a new list of shallow-copied dicts).
    """
    w = weights or ObjectiveWeights()
    scored: List[Dict[str, Any]] = []
    for r in results:
        s = score_variation(r, w)
        if s is None:
            continue
        rc = dict(r)
        rc["_score"] = s
        scored.append(rc)
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def select_best(results: List[Dict[str, Any]],
                weights: Optional[ObjectiveWeights] = None) -> Dict[str, Any]:
    """Select the best variation by the composite objective.

    Falls back to the old max-Sharpe behaviour only if every variation is
    disqualified (e.g. all errored) AND the caller still needs *something* —
    in that case returns the highest-Sharpe non-error row, or `{}` if none.
    """
    ranked = rank_variations(results, weights)
    if ranked:
        return ranked[0]
    # Last-resort fallback: highest Sharpe among non-error rows, no min-trade gate
    non_error = [r for r in results if not r.get("error")]
    if not non_error:
        return {}
    return max(non_error, key=lambda r: r.get("sharpe_ratio", 0))
