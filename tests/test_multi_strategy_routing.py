from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engine.backtest.comparison import build_folds, normalize_spec, run_comparison


def test_normalize_spec_uses_safe_research_defaults():
    spec = normalize_spec({"symbols": [], "strategies": ["buy_the_dip"]})
    assert spec["symbols"][:2] == ["AAPL", "MSFT"]
    assert spec["horizons"] == ["3m", "1y"]
    assert spec["min_hold_days"] == 3
    assert spec["include_taf_fees"] is True
    assert spec["slippage_bps"] == 5.0


@pytest.mark.parametrize("bad", ["2m", "5y", "all"])
def test_normalize_spec_rejects_ambiguous_horizons(bad):
    with pytest.raises(ValueError, match="unsupported horizons"):
        normalize_spec({"horizons": [bad]})


def test_build_folds_are_chronological_and_oos_does_not_overlap():
    folds = build_folds("3m", 3, end=datetime(2026, 9, 29, tzinfo=timezone.utc))
    assert len(folds) == 3
    assert all(fold.train_end == fold.test_start for fold in folds)
    assert folds[0].test_end == folds[1].test_start
    assert folds[1].test_end == folds[2].test_start
    assert all(fold.train_start < fold.train_end < fold.test_end for fold in folds)


def test_one_month_two_fold_comparison_is_supported():
    folds = build_folds("1m", 2, end=datetime(2026, 9, 29, tzinfo=timezone.utc))
    assert len(folds) == 2
    assert folds[0].train_end == folds[0].test_start
    assert folds[0].test_end == folds[1].test_start


def test_walk_forward_pins_training_params_and_reports_oos_only():
    calls = []

    def runner(request):
        calls.append(request)
        is_test = "variations" in request and all(
            len(values) == 1 for values in request["variations"].values()
        )
        params = {
            "dip_threshold": 0.03, "take_profit": 0.015,
            "stop_loss": 0.005, "hold_days": 3,
            "min_hold_days": request["variations"]["min_hold_days"][0],
            "position_size": 0.1,
        }
        return {
            "run_id": f"run-{len(calls)}",
            "best_config": {
                "params": params, "total_return": 2.0 if is_test else 8.0,
                "total_trades": 10, "win_rate": 60.0, "max_drawdown": 1.0,
            },
        }

    report = run_comparison(
        {"strategies": ["buy_the_dip"], "horizons": ["3m"],
         "symbols": ["AAPL"], "folds": 2, "min_hold_days": 3,
         "minimum_oos_trades": 20, "end_date": "2026-09-29T00:00:00+00:00"},
        runner=runner, benchmarker=lambda *_args: 1.0,
    )
    row = report["results"][0]
    assert row["search_mode"] == "grid"
    assert row["status"] == "valid"
    assert row["oos_trades"] == 20
    assert row["oos_return"] == pytest.approx(4.04)
    assert row["benchmark_return"] == pytest.approx(2.01)
    assert row["oos_excess_return"] == pytest.approx(2.03)
    assert report["promotion"]["automatic"] is False
    assert all(request["variations"]["min_hold_days"] == [3]
               for request in calls if "variations" in request)


def test_fixed_strategy_with_zero_trades_is_not_a_zero_return_winner():
    def runner(_request):
        return {"run_id": "fixed-run", "best_config": {
            "params": {"strategy": "momentum", "lookback_period": 20},
            "total_return": 0.0, "total_trades": 0, "win_rate": 0.0,
        }}

    report = run_comparison(
        {"strategies": ["momentum"], "horizons": ["3m"],
         "symbols": ["AAPL"], "folds": 2,
         "end_date": "2026-09-29T00:00:00+00:00"},
        runner=runner, benchmarker=lambda *_args: 2.0,
    )
    row = report["results"][0]
    assert row["search_mode"] == "fixed_configuration"
    assert row["status"] == "insufficient_trades"
    assert row["oos_win_rate"] is None
    assert report["winner"] is None
    assert report["promotion"]["eligible"] is False


def test_deepagent_pipeline_routes_comparison_to_one_checkpoint():
    from engine.autonomy.graph import deepagent_job_pipeline

    pipeline = deepagent_job_pipeline(
        "deepagent_comparison", "00000000-0000-0000-0000-000000000001", None
    )
    assert [node for node, _handler in pipeline.nodes] == ["strategy_comparison"]


def test_strategy_specialist_exposes_comparison_tool():
    from engine.ai.deepagent_tools import STRATEGY_TOOLS

    assert "queue_multi_strategy_comparison" in {
        getattr(tool, "name", "") for tool in STRATEGY_TOOLS
    }


def test_monitoring_renders_comparison_oos_table_and_actual_phase():
    from engine.web.ph_monitoring import _render

    output = {"result": {"results": [{
        "strategy": "buy_the_dip", "horizon": "3m", "oos_return": 4.2,
        "benchmark_return": 1.1, "oos_trades": 24, "oos_win_rate": 54.2,
        "status": "valid",
    }]}}
    rendered = _render({
        "counts": {"queued": 0, "running": 0, "done": 1, "failed": 0},
        "configured": False, "fresh_heartbeat": False, "accounts": [],
        "runs": [{
            "run_id": "12345678-0000-0000-0000-000000000000",
            "kind": "deepagent_comparison", "status": "done", "attempt": 1,
            "claimed_by": "research-worker", "heartbeat_at": None, "error": None,
            "steps": {"strategy_comparison": "done"},
            "outputs": {"strategy_comparison": output},
        }],
    })
    assert "deepagent comparison" in rendered
    assert "strategy comparison" in rendered
    assert "OOS return" in rendered
    assert "buy_the_dip" in rendered
    assert "+4.20%" in rendered
    assert "policy gate" not in rendered


def test_research_lane_can_only_claim_research_jobs(monkeypatch):
    from engine.autonomy import worker

    monkeypatch.setattr(worker.queue, "claim", lambda worker_id, **kwargs: None)
    assert worker.run_one("research-1", research_only=True) is False


def test_failed_comparison_is_retryable_not_treated_as_uncertain_paper(monkeypatch):
    from unittest.mock import MagicMock
    from engine.autonomy import worker

    claimed = {
        "run_id": "comparison-1", "kind": "deepagent_comparison", "attempt": 1,
        "config": {}, "user_id": "user-1", "account_id": None,
    }
    pipeline = MagicMock()
    pipeline.run.side_effect = RuntimeError("research failed")
    monkeypatch.setattr(worker.queue, "claim", lambda *_args, **_kwargs: claimed)
    fail = MagicMock(return_value="queued")
    monkeypatch.setattr(worker.queue, "fail", fail)
    monkeypatch.setattr(worker.store, "append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "deepagent_job_pipeline", lambda *_args, **_kwargs: pipeline)

    assert worker.run_one("research-1", research_only=True) is True
    assert fail.call_args.kwargs["max_attempts"] == worker.MAX_ATTEMPTS


def test_buy_the_dip_grid_forwards_minimum_hold(monkeypatch):
    import pandas as pd
    from agents.backtest_agent import BacktestAgent

    seen = []

    def fake_backtest(**kwargs):
        seen.append(kwargs)
        return pd.DataFrame(), {"total_return": 0, "total_trades": 0}, pd.DataFrame()

    monkeypatch.setattr("agents.backtest_agent.backtest_buy_the_dip", fake_backtest)
    rows = BacktestAgent()._run_buy_the_dip_grid(
        symbols=["AAPL"], start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 4, 1), initial_capital=10_000,
        data_source="yfinance", variations={
            "dip_threshold": [0.03], "take_profit": [0.015], "hold_days": [5],
            "min_hold_days": [3], "stop_loss": [0.005], "position_size": [0.1],
        }, run_id="test-run",
    )
    assert seen[0]["min_hold_days"] == 3
    assert rows[0]["params"]["min_hold_days"] == 3
