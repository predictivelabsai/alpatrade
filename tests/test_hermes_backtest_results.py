from datetime import datetime, timezone


def _result():
    return {
        "job_id": "job-1",
        "run_id": "run-1",
        "trades": [
            {
                "symbol": "AAPL", "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "exit_time": datetime(2026, 1, 3, tzinfo=timezone.utc),
                "entry_price": 100, "exit_price": 110, "shares": 2,
                "pnl": 20, "pnl_pct": 10,
            },
            {
                "symbol": "MSFT", "entry_time": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "exit_time": datetime(2026, 1, 3, tzinfo=timezone.utc),
                "entry_price": 100, "exit_price": 95, "shares": 2,
                "pnl": -10, "pnl_pct": -5,
            },
        ],
    }


def test_trade_table_focuses_on_pnl_and_return():
    from engine.agents.hermes_backtest_results import render_trade_analysis

    output = render_trade_analysis(_result(), "all")
    assert "| # | Symbol | Entry | Exit | P&L | Return |" in output
    assert "| 1 | AAPL | 2026-01-01 | 2026-01-03 | +$20.00 | +10.00% |" in output
    assert "| 2 | MSFT | 2026-01-02 | 2026-01-03 | -$10.00 | -5.00% |" in output
    assert "| 2 | +$10.00 | +2.50% | 50.0% | 1.5 days |" in output
    assert "Sharpe" not in output
    assert "validation" not in output.lower()


def test_best_and_worst_trade_are_selected_by_realized_pnl():
    from engine.agents.hermes_backtest_results import render_trade_analysis

    best = render_trade_analysis(_result(), "best")
    worst = render_trade_analysis(_result(), "worst")
    assert "AAPL" in best and "MSFT" not in best
    assert "MSFT" in worst and "AAPL" not in worst


def test_holding_period_returns_one_compact_summary_table():
    from engine.agents.hermes_backtest_results import render_trade_analysis

    output = render_trade_analysis(_result(), "holding")
    assert "Average hold" in output
    assert "1.5 days" in output
    assert "| # | Symbol" not in output


def test_owned_query_is_bound_to_user_run_and_backtest_type():
    import inspect
    from engine.agents import hermes_backtest_results

    source = inspect.getsource(hermes_backtest_results.load_owned_backtest_trades)
    assert "user_id = CAST(:user_id AS UUID)" in source
    assert "kind = 'backtest'" in source
    assert "status = 'completed'" in source
    assert "trade_type = 'backtest'" in source
    assert "alpatrade.hermes_jobs" in source
    assert "alpatrade.trades" in source

