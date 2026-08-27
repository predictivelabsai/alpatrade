"""Hermes-only conservative backtest and promotion contracts."""
from datetime import datetime, timezone
import inspect
import math

import pandas as pd


def _row(sharpe, total_return=5.0, drawdown=2.0, trades=50, params=None):
    return {
        "params": params or {
            "dip_threshold": 0.03, "take_profit": 0.01,
            "hold_days": 2, "stop_loss": 0.005,
            "position_size": 0.1, "symbols": ["AAPL"],
        },
        "sharpe_ratio": sharpe, "sortino_ratio": sharpe,
        "calmar_ratio": 2.0, "total_return": total_return,
        "annualized_return": total_return * 2, "max_drawdown": drawdown,
        "win_rate": 55.0, "total_trades": trades,
        "total_pnl": total_return * 100, "trades": [],
    }


def test_portfolio_metrics_use_daily_equity_and_are_finite():
    from utils.backtester_util import calculate_portfolio_metrics

    equity = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC"),
        "equity": [100.0, 101.0, 100.0, 102.0],
    })
    metrics = calculate_portfolio_metrics(
        equity, 100.0,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    assert metrics["total_return"] == 2.0
    assert 0.98 < metrics["max_drawdown"] < 1.0
    assert metrics["equity_days"] == 4
    assert math.isfinite(metrics["sharpe_ratio"])
    assert math.isfinite(metrics["sortino_ratio"])


def test_hermes_command_enables_conservative_methodology():
    from engine.web.ph_chat import _hermes_backtest_config

    config = _hermes_backtest_config(
        "backtest lookback:6m symbols:AAPL objective:sharpe_ratio"
    )
    assert config["objective"] == {"maximize": "sharpe_ratio"}
    assert config["conservative_metrics"] is True
    assert config["conservative_execution"] is True
    assert config["slippage_bps"] == 5.0
    assert config["validation_fraction"] == 0.30
    assert config["robustness_windows"] == 3
    assert config["benchmark_symbol"] == "SPY"


def test_orchestrator_forwards_objective_and_quality_flags():
    from agents.orchestrator import Orchestrator

    source = inspect.getsource(Orchestrator.run_backtest)
    for field in (
        "objective", "conservative_metrics", "conservative_execution",
        "include_taf_fees", "include_cat_fees", "slippage_bps",
        "validation_fraction", "robustness_windows", "benchmark_symbol",
    ):
        assert f'"{field}"' in source


def test_result_rows_preserve_equity_day_count():
    from agents.backtest_agent import BacktestAgent

    source = inspect.getsource(BacktestAgent._run_buy_the_dip_grid)
    assert '"equity_days": metrics.get("equity_days")' in source


def test_sharpe_selection_is_validated_out_of_sample(monkeypatch):
    from agents.backtest_agent import BacktestAgent

    agent = BacktestAgent()
    calls = []

    def fake_grid(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return [_row(1.0), _row(2.5), _row(1.8)]
        return [_row(0.9, total_return=1.5, drawdown=3.0, trades=24)]

    monkeypatch.setattr(agent, "_run_buy_the_dip_grid", fake_grid)
    monkeypatch.setattr(agent, "_store_results", lambda *args, **kwargs: None)
    result = agent.run({
        "strategy": "buy_the_dip", "symbols": ["AAPL"], "lookback": "6m",
        "objective": {"maximize": "sharpe_ratio"},
        "validation_fraction": 0.30, "conservative_metrics": True,
        "conservative_execution": True, "slippage_bps": 5.0,
    })
    best = result["best_config"]
    assert best["sharpe_ratio"] == 2.5
    assert best["validation_metrics"]["sharpe_ratio"] == 0.9
    assert best["promotion_eligible"] is True
    assert len(calls) == 2
    assert calls[0]["end_date"] < calls[1]["start_date"]


def test_failed_validation_blocks_promotion(monkeypatch):
    from agents.backtest_agent import BacktestAgent

    agent = BacktestAgent()
    calls = []

    def fake_grid(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return [_row(2.0), _row(1.8), _row(1.5)]
        return [_row(-0.4, total_return=-2.0, drawdown=12.0, trades=8)]

    monkeypatch.setattr(agent, "_run_buy_the_dip_grid", fake_grid)
    monkeypatch.setattr(agent, "_store_results", lambda *args, **kwargs: None)
    best = agent.run({
        "strategy": "buy_the_dip", "symbols": ["AAPL"], "lookback": "6m",
        "objective": {"maximize": "sharpe_ratio"},
        "validation_fraction": 0.30,
    })["best_config"]
    assert best["promotion_eligible"] is False
    assert len(best["promotion_reasons"]) >= 4


def test_hermes_robustness_windows_and_benchmark_are_persisted(monkeypatch):
    from agents import backtest_agent as module
    from agents.backtest_agent import BacktestAgent

    agent = BacktestAgent()
    calls = []

    def fake_grid(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return [_row(2.0), _row(1.8), _row(1.6)]
        return [_row(1.0, total_return=1.0, drawdown=1.0, trades=25)]

    monkeypatch.setattr(agent, "_run_buy_the_dip_grid", fake_grid)
    monkeypatch.setattr(agent, "_store_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_benchmark_return", lambda *args, **kwargs: 0.4)
    best = agent.run({
        "strategy": "buy_the_dip", "symbols": ["SPY"], "lookback": "1y",
        "objective": {"maximize": "sharpe_ratio"}, "validation_fraction": 0.30,
        "robustness_windows": 3, "benchmark_symbol": "SPY",
    })["best_config"]
    assert len(calls) == 5
    assert len(best["robustness_windows"]) == 3
    assert best["benchmark"]["total_return"] == 0.4
    assert best["benchmark"]["excess_return"] == 0.6
    assert best["promotion_eligible"] is True


def test_paper_promotion_enforces_saved_validation_gate():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs.enqueue_candidate_paper)
    assert 'metrics.get("promotion_eligible") is not True' in source
    assert "Candidate is not eligible for paper promotion" in source
    assert "requested_robustness" in source
    assert "completed_robustness < requested_robustness" in source


def test_backtest_worker_attributes_default_owned_account():
    from engine.agents import hermes_jobs

    source = inspect.getsource(hermes_jobs._backtest)
    assert "get_user_accounts" in source
    assert "SET account_id = CAST(:aid AS UUID)" in source


def test_conservative_daily_bar_prefers_stop_and_applies_slippage():
    from utils import buy_the_dip

    source = inspect.getsource(buy_the_dip.backtest_buy_the_dip)
    assert "conservative_execution and hit_tp and hit_sl" in source
    assert "slippage_bps" in source
    assert "calculate_portfolio_metrics" in source
