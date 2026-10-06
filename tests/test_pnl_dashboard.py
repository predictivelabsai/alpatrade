from datetime import datetime, timezone

import pytest

from engine.reporting import pnl_dashboard as dashboard

@pytest.fixture(autouse=True)
def _no_live_accounts(monkeypatch):
    """Keep existing paper-only tests free of live-broker DB access."""
    monkeypatch.setattr(dashboard, "_list_live_accounts", lambda _uid: [])




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


def test_unauthorized_keys_get_actionable_guidance(monkeypatch):
    observed = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_account(self):
            observed.append(1)
            return {"error": '{"message": "unauthorized."}\n'}

    monkeypatch.setattr(dashboard, "AlpacaAPI", FakeClient)
    monkeypatch.setattr(dashboard, "get_alpaca_keys", lambda _uid, _aid: ("key", "secret"))

    with pytest.raises(ValueError) as excinfo:
        dashboard._client("user-1", "acct-1")

    message = str(excinfo.value)
    assert "unauthorized" in message
    assert "re-enter them under Settings" in message
    assert '{"message"' not in message  # raw Alpaca JSON never reaches the user


def test_non_unauthorized_alpaca_errors_pass_through(monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_account(self):
            return {"error": "forbidden: IP not whitelisted"}

    monkeypatch.setattr(dashboard, "AlpacaAPI", FakeClient)
    monkeypatch.setattr(dashboard, "get_alpaca_keys", lambda _uid, _aid: ("key", "secret"))

    with pytest.raises(ValueError) as excinfo:
        dashboard._client("user-1", "acct-1")

    assert "IP not whitelisted" in str(excinfo.value)


def test_error_page_offers_the_settings_cta_for_bad_keys():
    from engine.web import ph_pnl

    data = {"errors": [{"account_id": "a1",
                        "message": "Could not read this Alpaca account: "
                                   "Alpaca rejected the stored API keys for this "
                                   "account (unauthorized)."}],
            "period": "daily"}
    rendered = ph_pnl._render(data, None)

    assert "Update your Alpaca keys" in rendered
    assert "href='/settings'" in rendered


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


def test_live_accounts_appear_in_dropdown_catalog(monkeypatch):
    accounts = [_account("paper-1", "Paper One")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_list_live_accounts",
        lambda _uid: [{"account_number": "885504372", "label": "Alpaca live"}],
    )
    monkeypatch.setattr(
        dashboard, "_one_account",
        lambda _uid, account, _period: _portfolio(account, 11_000),
    )
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", None, "daily")

    ids = [a["account_id"] for a in data["accounts"]]
    assert "paper-1" in ids
    assert "live:885504372" in ids
    assert data["has_live"] is True
    live_row = next(a for a in data["accounts"] if a["account_id"].startswith("live:"))
    assert "LIVE" in live_row["account_name"]
    assert "885504372" in live_row["account_name"]


def test_selecting_live_account_loads_readonly_snapshot(monkeypatch):
    accounts = [_account("paper-1", "Paper One")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_list_live_accounts",
        lambda _uid: [{"account_number": "885504372", "label": "Alpaca live"}],
    )

    def fake_live(_uid, account, _period):
        return {
            "account_id": account["account_id"],
            "account_name": account["account_name"],
            "environment": "live",
            "equity": 2810.14,
            "portfolio_value": 2810.14,
            "cash": 2405.47,
            "buying_power": 10_000,
            "period_pnl": 19.58,
            "period_pct": 0.70,
            "unrealized_pnl": 0.42,
            "history": {"timestamps": ["2026-10-05T20:00:00+00:00"],
                        "equity": [2810.14], "pnl": [], "pnl_pct": []},
            "contributors": [],
            "positions": [],
        }

    monkeypatch.setattr(dashboard, "_one_live_account", fake_live)
    monkeypatch.setattr(
        dashboard, "_one_account",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("paper path must not run")),
    )
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "live:885504372", "daily")

    assert data["account_id"] == "live:885504372"
    assert data["environment"] == "live"
    assert data["equity"] == 2810.14
    assert data["paper_rankings"] == []
    assert data["advisor_reports"] == []


def test_all_accounts_aggregates_paper_only(monkeypatch):
    accounts = [_account("one", "One"), _account("two", "Two")]
    monkeypatch.setattr(dashboard, "get_user_accounts", lambda _uid: accounts)
    monkeypatch.setattr(
        dashboard, "_list_live_accounts",
        lambda _uid: [{"account_number": "885504372", "label": "Alpaca live"}],
    )
    loaded = []

    def load_paper(_uid, account, _period):
        loaded.append(("paper", account["account_id"]))
        return _portfolio(account, 10_000)

    def load_live(_uid, account, _period):
        loaded.append(("live", account["account_id"]))
        return {
            **_portfolio(account, 2_800),
            "environment": "live",
        }

    monkeypatch.setattr(dashboard, "_one_account", load_paper)
    monkeypatch.setattr(dashboard, "_one_live_account", load_live)
    monkeypatch.setattr(dashboard.ReportAgent, "top_strategies", lambda *a, **kw: [])

    data = dashboard.dashboard_data("user-1", "all", "weekly")

    assert [kind for kind, _ in loaded] == ["paper", "paper"]
    assert data["account_id"] == "all"
    assert data["equity"] == 20_000


def test_render_all_label_mentions_paper_when_live_linked():
    from engine.web import ph_pnl
    data = {
        "account_id": "paper-1",
        "account_name": "Paper One",
        "accounts": [
            {"account_id": "paper-1", "account_name": "Paper One"},
            {"account_id": "live:885504372", "account_name": "Alpaca live · 885504372 (LIVE)"},
        ],
        "has_live": True,
        "period": "daily",
        "equity": 100.0,
        "period_pnl": 1.0,
        "period_pct": 1.0,
        "unrealized_pnl": 0.0,
        "cash": 50.0,
        "buying_power": 50.0,
        "environment": "paper",
        "as_of": "2026-10-06T12:00:00+00:00",
        "contributors": [],
        "paper_rankings": [],
        "backtest_rankings": [],
        "advisor_reports": [],
        "advisor_history": [],
        "history": {"timestamps": [], "equity": []},
    }
    html = ph_pnl._render(data, "paper-1")
    assert "All paper accounts" in html
    assert "live:885504372" in html
    assert "LIVE" in html


def test_paper_view_does_not_stack_live_panel():
    """Selecting paper must not keep the Live vs SPY block on the same page."""
    from engine.web import ph_pnl
    data = {
        "account_id": "paper-1",
        "account_name": "Paper One",
        "accounts": [
            {"account_id": "paper-1", "account_name": "Paper One"},
            {"account_id": "live:885504372", "account_name": "Alpaca live · 885504372 (LIVE)"},
        ],
        "has_live": True,
        "period": "daily",
        "equity": 100.0,
        "period_pnl": 1.0,
        "period_pct": 1.0,
        "unrealized_pnl": 0.0,
        "cash": 50.0,
        "buying_power": 50.0,
        "environment": "paper",
        "as_of": "2026-10-06T12:00:00+00:00",
        "contributors": [],
        "paper_rankings": [],
        "backtest_rankings": [],
        "advisor_reports": [],
        "advisor_history": [],
        "paper_runs": [
            {"strategy_slug": "buy_the_dip", "status": "running",
             "total_pnl": 12.5, "total_trades": 3, "started_at": "2026-10-01T14:00:00"},
        ],
        "positions": [],
        "history": {"timestamps": [], "equity": []},
        "live": {  # even if mistakenly present, paper render must ignore it
            "linked": True,
            "account_number": "885504372",
            "perf": {"account_pnl": 1},
            "curves": {"dates": ["2026-10-01"], "account_idx": [100], "spy_idx": [100]},
        },
    }
    html = ph_pnl._render(data, "paper-1")
    assert "Live account vs SPY" not in html
    assert "PAPER" in html
    assert 'name="account_id"' in html
    assert "live:885504372" in html
    assert "Paper strategy activity" in html
    assert "buy_the_dip" in html


def test_live_view_shows_spy_curve_and_dropdown():
    from engine.web import ph_pnl
    data = {
        "account_id": "live:885504372",
        "account_name": "Alpaca live · 885504372 (LIVE)",
        "accounts": [
            {"account_id": "paper-1", "account_name": "Paper One"},
            {"account_id": "live:885504372", "account_name": "Alpaca live · 885504372 (LIVE)"},
        ],
        "has_live": True,
        "period": "daily",
        "equity": 2800.0,
        "period_pnl": -0.3,
        "period_pct": -0.01,
        "unrealized_pnl": 10.0,
        "cash": 500.0,
        "buying_power": 9800.0,
        "environment": "live",
        "as_of": "2026-10-06T12:00:00+00:00",
        "contributors": [],
        "positions": [{"symbol": "AAPL", "qty": 1, "avg_entry_price": 100,
                      "current_price": 105, "market_value": 105,
                      "unrealized_pl": 5, "unrealized_plpc": 0.05}],
        "history": {"timestamps": [], "equity": []},
        "live": {
            "linked": True,
            "account_number": "885504372",
            "had_bnbx": True,
            "orders": [],
            "perf": {
                "started": "2026-09-01",
                "start_equity": 2500,
                "account_pnl": 300,
                "account_return_pct": 12.0,
                "spy_return_pct": 5.0,
                "spy_start": 400,
                "spy": 420,
                "excess_pct": 7.0,
            },
            "curves": {"dates": ["2026-09-01", "2026-10-01"],
                       "account_idx": [100, 112], "spy_idx": [100, 105]},
        },
    }
    html = ph_pnl._render(data, "live:885504372")
    assert "Live account vs SPY" in html
    assert "dash-live-equity-chart" in html
    assert 'name="account_id"' in html
    assert "paper-1" in html
    assert 'mode-badge">PAPER' not in html
    assert "Open positions" in html
    assert "AAPL" in html
    assert "BNBX" in html  # footnote only
    assert "Daily trading advisor" not in html  # paper-only panel


def test_error_page_keeps_account_dropdown_when_catalog_present():
    from engine.web import ph_pnl
    data = {
        "errors": [{"account_id": "paper-1", "message": "unauthorized"}],
        "period": "daily",
        "accounts": [
            {"account_id": "paper-1", "account_name": "Paper One"},
            {"account_id": "live:885504372", "account_name": "Alpaca live · 885504372 (LIVE)"},
        ],
        "has_live": True,
        "environment": "paper",
    }
    html = ph_pnl._render(data, "paper-1")
    assert 'name="account_id"' in html
    assert "live:885504372" in html
    assert "Live account vs SPY" not in html
