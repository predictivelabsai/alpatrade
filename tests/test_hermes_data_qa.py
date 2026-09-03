from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import inspect


def _result():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "run_id": "run-1",
        "trades": [
            {"symbol": "AAPL", "entry_time": start,
             "exit_time": start + timedelta(days=2), "entry_price": 100,
             "exit_price": 110, "shares": 2, "pnl": 20, "pnl_pct": 10,
             "reason": "TAKE_PROFIT"},
            {"symbol": "MSFT", "entry_time": start,
             "exit_time": start + timedelta(days=1), "entry_price": 200,
             "exit_price": 195, "shares": 1, "pnl": -5, "pnl_pct": -2.5,
             "reason": "STOP_LOSS"},
        ],
    }


def test_natural_language_summary_and_symbol_breakdown():
    from engine.agents.hermes_data_qa import render_trade_question

    summary = render_trade_question(
        _result(), "what is pnl and average return for my paper run", "paper"
    )
    assert "+$15.00" in summary
    assert "+3.75%" in summary
    assert "1.5 days" in summary
    by_symbol = render_trade_question(
        _result(), "show paper pnl and return by symbol", "paper"
    )
    assert "| AAPL | 1 | +$20.00 | +10.00% |" in by_symbol
    assert "| MSFT | 1 | -$5.00 | -2.50% |" in by_symbol


def test_natural_language_best_trade():
    from engine.agents.hermes_data_qa import render_trade_question

    answer = render_trade_question(
        _result(), "most profitable paper trade", "paper"
    )
    assert "AAPL" in answer
    assert "TAKE_PROFIT" in answer


def test_open_only_paper_data_does_not_claim_zero_realized_performance():
    from engine.agents.hermes_data_qa import render_trade_question

    answer = render_trade_question({
        "run_id": "run-open",
        "trades": [{"symbol": "AAPL", "entry_price": 100, "shares": 2,
                    "entry_time": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
    }, "show pnl for my paper run", "paper")
    assert "| N/A | N/A | N/A | n/a |" in answer
    assert "No completed exits" in answer


def test_sql_is_fixed_owned_and_alpatrade_only():
    from engine.agents import hermes_data_qa

    source = inspect.getsource(hermes_data_qa._load_owned_run_trades)
    assert "alpatrade.hermes_jobs" in source
    assert "alpatrade.trades" in source
    assert "user_id = CAST(:user_id AS UUID)" in source
    assert ":run_id" in source
    assert "information_schema" not in source


def test_idle_running_job_recommends_review_without_auto_change(monkeypatch):
    from engine.agents import hermes_advice

    class Result:
        def __init__(self, rows=None, scalar=0):
            self.rows, self.scalar = rows or [], scalar
        def mappings(self): return self
        def first(self): return self.rows[0] if self.rows else None
        def all(self): return self.rows
        def scalar_one(self): return self.scalar

    class Session:
        calls = 0
        def execute(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return Result([{
                    "job_id": "job-1", "run_id": "run-1",
                    "candidate_id": "candidate-1", "account_id": "account-1",
                    "status": "running", "config": {}, "error": None,
                    "created_at": datetime.now(timezone.utc) - timedelta(days=2),
                    "heartbeat_at": datetime.now(timezone.utc),
                }])
            if self.calls == 2:
                return Result([])
            return Result(scalar=0)

    session = Session()

    class Pool:
        @contextmanager
        def get_session(self):
            yield session

    monkeypatch.setattr(hermes_advice, "_pool", lambda: Pool())
    monkeypatch.setattr(hermes_advice, "list_owned", lambda *_args, **_kwargs: [])
    report = hermes_advice.analyze_owned_paper_job("job-1", "user-1")
    assert report["status"] == "REVIEW"
    assert report["idle_hours"] >= 47
    assert any("6 months" in command for command in report["commands"])
    assert "automatically" not in report["decision"].lower()
