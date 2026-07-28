"""Unit tests for the refit closed-loop feedback logic (DB-free)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.autonomy.refit import (
    paper_sharpe, detect_drift, refine_grid, refit_plan,
    DRIFT_RATIO, MIN_PAPER_TRADES,
)


def test_paper_sharpe_returns_none_for_few_trades():
    trades = [{"pnl_pct": 1.0}, {"pnl_pct": -0.5}]
    assert paper_sharpe(trades) is None


def test_paper_sharpe_computes_annualised():
    # 10 trades, all +1% — stdev 0 → Sharpe 0 (no dispersion)
    trades = [{"pnl_pct": 1.0} for _ in range(10)]
    assert paper_sharpe(trades) == 0.0
    # mixed → positive Sharpe
    trades = [{"pnl_pct": 2.0}, {"pnl_pct": 1.0}] * 5
    s = paper_sharpe(trades)
    assert s is not None and s > 0


def test_detect_drift_when_paper_degrades():
    assert detect_drift(backtest_sharpe=2.0, paper_sharpe_val=0.5) is True  # 0.5 < 2.0*0.5
    assert detect_drift(backtest_sharpe=2.0, paper_sharpe_val=1.5) is False  # 1.5 >= 1.0
    # None cases → no drift
    assert detect_drift(None, 1.0) is False
    assert detect_drift(2.0, None) is False
    # Negative backtest: any negative paper is drift
    assert detect_drift(backtest_sharpe=-1.0, paper_sharpe_val=-2.0) is True
    assert detect_drift(backtest_sharpe=-1.0, paper_sharpe_val=0.5) is False


def test_refine_grid_centres_on_top_k():
    variations = [
        {"params": {"dip_threshold": 0.05, "take_profit": 0.01, "hold_days": 2}, "_score": 10},
        {"params": {"dip_threshold": 0.03, "take_profit": 0.015, "hold_days": 1}, "_score": 8},
        {"params": {"dip_threshold": 0.07, "take_profit": 0.01, "hold_days": 3}, "_score": 6},
        {"params": {"dip_threshold": 0.09, "take_profit": 0.02, "hold_days": 5}, "_score": 1},
    ]
    refined = refine_grid(variations, k=3, band=0.2)
    # Top-3 are 0.05, 0.03, 0.07 — 0.09 excluded
    dips = refined["dip_threshold"]
    assert 0.05 in dips and 0.03 in dips and 0.07 in dips and 0.09 not in dips
    # Band neighbours: 0.05*0.8=0.04, 0.05*1.2=0.06
    assert any(abs(v - 0.04) < 1e-6 for v in dips)
    assert any(abs(v - 0.06) < 1e-6 for v in dips)
    # hold_days is integer-perturbed ±1
    holds = refined["hold_days"]
    assert 1 in holds and 2 in holds and 3 in holds


def test_refine_grid_falls_back_to_sharpe_when_no_score():
    variations = [
        {"params": {"dip_threshold": 0.05}, "sharpe_ratio": 2.0},
        {"params": {"dip_threshold": 0.03}, "sharpe_ratio": 1.0},
    ]
    refined = refine_grid(variations, k=2, band=0.2)
    assert 0.05 in refined["dip_threshold"] and 0.03 in refined["dip_threshold"]


def test_refit_plan_no_drift_keeps_default_grid():
    bt = {"best_config": {"sharpe_ratio": 2.0},
          "all_results_summary": [{"params": {"dip_threshold": 0.05}, "_score": 10}]}
    # Paper Sharpe 1.5 >= 1.0 → no drift
    paper = [{"pnl_pct": 1.0}, {"pnl_pct": 0.5}] * 5
    plan = refit_plan(bt, paper)
    assert plan["drift"] is False
    assert plan["refined_grid"] == {}


def test_refit_plan_drift_produces_refined_grid():
    bt = {"best_config": {"sharpe_ratio": 2.0},
          "all_results_summary": [
              {"params": {"dip_threshold": 0.05, "take_profit": 0.01}, "_score": 10},
              {"params": {"dip_threshold": 0.03, "take_profit": 0.015}, "_score": 8},
          ]}
    # Paper Sharpe ~0 (low) → drift
    paper = [{"pnl_pct": 0.1}, {"pnl_pct": -0.1}] * 5
    plan = refit_plan(bt, paper)
    assert plan["drift"] is True
    assert "dip_threshold" in plan["refined_grid"]
    assert 0.05 in plan["refined_grid"]["dip_threshold"]


def test_refit_plan_drift_with_no_refinable_params():
    bt = {"best_config": {"sharpe_ratio": 2.0},
          "all_results_summary": [{"params": {"symbols": ["AAPL"]}, "_score": 10}]}
    paper = [{"pnl_pct": 0.1}, {"pnl_pct": -0.1}] * 5
    plan = refit_plan(bt, paper)
    assert plan["drift"] is True
    assert plan["refined_grid"] == {}  # no refinable params
    assert "no refinable" in plan["reason"]
