from contextlib import contextmanager

from scripts import daily_pnl_report as report


class _Result:
    def __init__(self, rows=(), columns=()):
        self._rows = list(rows)
        self._columns = list(columns)
        self.rowcount = len(self._rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def keys(self):
        return self._columns


class _Session:
    def __init__(self, result=None):
        self.result = result or _Result()
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.result


class _Pool:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def get_session(self):
        yield self.session


def test_no_hardcoded_distribution_list(monkeypatch):
    monkeypatch.delenv("PNL_REPORT_TO", raising=False)
    monkeypatch.delenv("TO_EMAIL", raising=False)
    assert report.recipients() == []


def test_active_runs_requires_tenant_and_fresh_heartbeat(monkeypatch):
    assert report.active_runs() == []
    session = _Session(_Result())
    monkeypatch.setattr("engine.db.pool.DatabasePool", lambda: _Pool(session))

    report.active_runs(user_id="user-1", account_id="account-1",
                       framework="hermes")

    sql, params = session.calls[0]
    assert "r.user_id = :user_id" in sql
    assert "r.account_id = :account_id" in sql
    assert "r.heartbeat_at >= NOW() - INTERVAL '10 minutes'" in sql
    assert "FROM alpatrade.hermes_jobs h" in sql
    assert "mode IN ('paper', 'full')" in sql
    assert "agent_framework" in sql
    assert params["framework"] == "hermes"


def test_trade_query_is_tenant_and_framework_scoped(monkeypatch):
    session = _Session(_Result())
    monkeypatch.setattr("engine.db.pool.DatabasePool", lambda: _Pool(session))

    report.gather_trades("2026-08-23", user_id="user-1",
                         account_id="account-1", framework="deepagents")

    sql, params = session.calls[0]
    assert "t.user_id = :user_id" in sql
    assert "t.account_id = :account_id" in sql
    assert "JOIN alpatrade.runs r" in sql
    assert params["framework"] == "deepagents"


def test_stale_reconciliation_is_tenant_scoped(monkeypatch):
    session = _Session(_Result([("changed",)]))
    monkeypatch.setattr("engine.db.pool.DatabasePool", lambda: _Pool(session))

    assert report.reconcile_stale_runs("user-1", "account-1") == 1
    sql, params = session.calls[0]
    assert "status = 'stale'" in sql
    assert "heartbeat_at IS NULL" in sql
    assert "NOT EXISTS" in sql and "alpatrade.hermes_jobs" in sql
    assert params == {"uid": "user-1", "aid": "account-1"}


def test_render_separates_framework_benchmark_and_periods():
    data = {
        "day": "2026-08-23", "day_pnl": 25.0, "day_pct": 0.25,
        "equity": 10025.0, "cash": 5000.0, "buying_power": 10000.0,
        "unrealized_pl": 5.0, "daytrade_count": 0, "positions": [],
        "trades": [], "runs": {}, "active_runs": [],
        "periods": {
            "mtd": {"pnl": 120.0, "pct": 1.2, "days": 4},
            "ytd": {"pnl": -50.0, "pct": -0.5, "days": 8},
        },
        "agent_performance": [
            {"framework": "hermes", "agent_name": "Hermes", "mtd_exits": 3,
             "mtd_pnl": 75, "ytd_exits": 5, "ytd_pnl": 100,
             "win_rate": 60, "run_count": 1},
            {"framework": "deepagents", "agent_name": "DeepAgents", "mtd_exits": 2,
             "mtd_pnl": -10, "ytd_exits": 2, "ytd_pnl": -10,
             "win_rate": 50, "run_count": 1},
            {"framework": "langgraph", "agent_name": "LangGraph", "mtd_exits": 0,
             "mtd_pnl": 0, "ytd_exits": 1, "ytd_pnl": 5,
             "win_rate": 100, "run_count": 1},
        ],
    }

    html = report.render(data)
    assert "Month to date" in html and "Year to date" in html
    assert "Hermes" in html and "DeepAgents" in html and "LangGraph" in html
    assert "realized paper trades only" in html


def test_migration_is_confined_to_alpatrade_schema():
    source = open("sql/25_tenant_agent_reporting.sql", encoding="utf-8").read()
    assert "alpatrade.account_equity_snapshots" in source
    assert "alpatrade.report_deliveries" in source
    assert "public." not in source


def test_deepagent_mutating_jobs_are_explicitly_attributed():
    source = open("engine/ai/deepagent_tools.py", encoding="utf-8").read()
    assert source.count('"agent_framework": "deepagents"') >= 4
    assert '"agent_name": "DeepAgents"' in source
