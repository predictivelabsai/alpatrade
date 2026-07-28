"""Unit tests for the raised promotion bar (Phase 4d). DB-free."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.autonomy.promote import PromotionBar, should_promote


def test_default_bar_raised():
    bar = PromotionBar()
    assert bar.min_sharpe == 1.5  # raised from 1.0
    assert bar.min_trades == 20   # raised from 5
    assert bar.min_sortino == 1.0  # new
    assert bar.min_regime_coverage == 2  # new


def test_meets_raised_bar():
    bar = PromotionBar()
    m = {"sharpe_ratio": 2.0, "sortino_ratio": 2.5, "total_return": 15.0,
         "max_drawdown": 10.0, "total_trades": 50, "regime_coverage": 3}
    ok, reason = should_promote(m, bar)
    assert ok, reason


def test_fails_on_low_sortino():
    bar = PromotionBar()
    m = {"sharpe_ratio": 2.0, "sortino_ratio": 0.5, "total_return": 15.0,
         "max_drawdown": 10.0, "total_trades": 50, "regime_coverage": 3}
    ok, reason = should_promote(m, bar)
    assert not ok and "sortino" in reason


def test_fails_on_low_regime_coverage():
    bar = PromotionBar()
    m = {"sharpe_ratio": 2.0, "sortino_ratio": 2.0, "total_return": 15.0,
         "max_drawdown": 10.0, "total_trades": 50, "regime_coverage": 1}
    ok, reason = should_promote(m, bar)
    assert not ok and "regime" in reason


def test_fails_on_too_few_trades_raised():
    bar = PromotionBar()
    m = {"sharpe_ratio": 2.0, "sortino_ratio": 2.0, "total_return": 15.0,
         "max_drawdown": 10.0, "total_trades": 10, "regime_coverage": 3}
    ok, reason = should_promote(m, bar)
    assert not ok and "trades" in reason


def test_regime_coverage_optional_when_absent():
    """When regime_coverage is not in metrics, the gate is skipped (back-compat)."""
    bar = PromotionBar()
    m = {"sharpe_ratio": 2.0, "sortino_ratio": 2.0, "total_return": 15.0,
         "max_drawdown": 10.0, "total_trades": 50}
    ok, reason = should_promote(m, bar)
    assert ok, reason
