from datetime import datetime, timezone

import pytest

from engine.reporting import pnl_dashboard as dashboard


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("daily", datetime(2026, 7, 28, tzinfo=timezone.utc)),
        ("weekly", datetime(2026, 7, 27, tzinfo=timezone.utc)),
        ("monthly", datetime(2026, 7, 1, tzinfo=timezone.utc)),
    ],
)
def test_calendar_period_bounds(period, expected):
    now = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)
    start, end = dashboard.period_bounds(period, now)
    assert start == expected
    assert end == now


def _account(account_id, name):
    return {"account_id": account_id, "account_name": name}


def _portfolio(account, equity):
    return {
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "environment": "paper",
        "equity": equity,
        "portfolio_value": equity,
        "cash": equity / 2,
        "buying_power": equity,
        "period_pnl": equity / 10,
        "period_pct": 10,
        "unrealized_pnl": equity / 20,
        "history": {"timestamps": ["2026-07-28T00:00:00+00:00"], "equity": [equity],
                    "pnl": [], "pnl_pct": []},
        "contributors": [],
        "positions": [],
    }


def test_default_account_prefers_account_with_largest_usable_portfolio(monkeypatch):
    accounts = [_account("small", "Small"), _account("funded", "Funded")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_one_account",
        lambda _uid, account, _period: _portfolio(
            account, 100 if account["account_id"] == "small" else 25_000),
    )
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", None, "daily")

    assert data["account_id"] == "funded"
    assert data["equity"] == 25_000


def test_all_accounts_aggregates_without_leaking_unowned_account(monkeypatch):
    accounts = [_account("one", "One"), _account("two", "Two")]
    loaded = []
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)

    def load(_uid, account, _period):
        loaded.append(account["account_id"])
        return _portfolio(account, 10_000)

    monkeypatch.setattr(dashboard, "_one_account", load)
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "all", "weekly")

    assert loaded == ["one", "two"]
    assert data["account_id"] == "all"
    assert data["equity"] == 20_000


def test_unknown_account_id_never_selects_foreign_account(monkeypatch):
    accounts = [_account("owned", "Owned")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_one_account",
        lambda _uid, account, _period: _portfolio(account, 8_000),
    )
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "foreign", "monthly")

    assert data["account_id"] == "owned"


def test_dashboard_reads_the_latest_persisted_advisor_for_the_owned_account(monkeypatch):
    accounts = [_account("owned", "Owned")]
    report = {
        "report_id": "report-1",
        "account_id": "owned",
        "session_date": "2026-07-28",
        "status": "completed",
        "severity": "monitor",
        "evidence": {"account": {"account_name": "Owned"}},
        "advisory": {
            "summary": "Persisted advisor summary",
            "why_no_change": "The evidence gates were not reached.",
            "disclaimer": "Paper trading is simulated.",
        },
    }
    observed = {}
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_one_account",
        lambda _uid, account, _period: _portfolio(account, 8_000),
    )
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    def reports(user_id, account_id=None, limit=20):
        observed.update(user_id=user_id, account_id=account_id, limit=limit)
        return [report]

    monkeypatch.setattr("engine.reporting.advisor.list_reports_for_user", reports)

    data = dashboard.dashboard_data("user-1", "owned", "daily")

    assert observed == {"user_id": "user-1", "account_id": "owned", "limit": 20}
    assert data["advisor_report"] is report
    assert data["advisor_report"]["advisory"]["summary"] == "Persisted advisor summary"


def test_no_account_returns_onboarding_state(monkeypatch):
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: [])
    assert dashboard.dashboard_data("user-1", None, "daily")["needs_account"] is True


def test_failing_selected_account_returns_errors_instead_of_crashing(monkeypatch):
    accounts = [_account("broken", "Broken")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)

    def load(_uid, account, _period):
        raise ValueError("Could not read this Alpaca account: unauthorized.")

    monkeypatch.setattr(dashboard, "_one_account", load)
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "broken", "daily")

    assert "equity" not in data
    assert data["errors"] == [
        {"account_id": "broken", "message": "Could not read this Alpaca account: unauthorized."}
    ]


def test_failing_remembered_account_falls_back_to_other_accounts(monkeypatch):
    accounts = [_account("stale", "Stale"), _account("healthy", "Healthy")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)

    def load(_uid, account, _period):
        if account["account_id"] == "stale":
            raise ValueError("unauthorized.")
        return _portfolio(account, 12_000)

    monkeypatch.setattr(dashboard, "_one_account", load)
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "stale", "daily")

    assert data["account_id"] == "healthy"
    assert data["equity"] == 12_000
    assert data["errors"] == [{"account_id": "stale", "message": "unauthorized."}]


def test_failing_selected_account_reports_each_attempt_once(monkeypatch):
    accounts = [_account("broken", "Broken")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    attempts = []

    def load(_uid, account, _period):
        attempts.append(account["account_id"])
        raise ValueError("unauthorized.")

    monkeypatch.setattr(dashboard, "_one_account", load)
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "broken", "daily")

    assert attempts == ["broken", "broken"]  # selected attempt, then fallback
    assert len(data["errors"]) == 1
