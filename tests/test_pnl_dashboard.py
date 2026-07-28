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


def test_no_account_returns_onboarding_state(monkeypatch):
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: [])
    assert dashboard.dashboard_data("user-1", None, "daily")["needs_account"] is True
