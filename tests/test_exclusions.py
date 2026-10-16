"""Excluded ('junk') securities: one rule set, same figures everywhere, no P&L jump."""
from datetime import datetime, timezone

import pytest

from engine.reporting import exclusions as ex
from engine.reporting.cash_flows import adjusted_pnl

RULES = [
    {"id": 1, "symbol": "BNBX", "scope": "global", "account_ref": None, "reason": "dust", "auto": False},
    {"id": 2, "symbol": "CDTX", "scope": "account", "account_ref": "PA3QUCXV3HJJ",
     "reason": "not tradable", "auto": False},
]
POS = [
    {"symbol": "AAPL", "qty": "10", "market_value": "2000", "unrealized_pl": "100",
     "unrealized_plpc": "0.05", "avg_entry_price": "190", "current_price": "200"},
    {"symbol": "CDTX", "qty": "100", "market_value": "300", "unrealized_pl": "-700",
     "unrealized_plpc": "-0.7", "avg_entry_price": "10", "current_price": "3"},
    {"symbol": "bnbx", "qty": "15", "market_value": "1.5", "unrealized_pl": "-57",
     "unrealized_plpc": "-0.97", "avg_entry_price": "3.94", "current_price": "0.1"},
]
ACCT = {"account_number": "PA3QUCXV3HJJ", "equity": "10301.5", "last_equity": "10201.5",
        "portfolio_value": "10301.5", "cash": "8000", "buying_power": "16000"}


@pytest.fixture(autouse=True)
def _rules():
    ex.set_rules_for_tests([dict(r) for r in RULES])


def test_scopes_global_and_account():
    kept, gone = ex.split_positions(POS, ("PA3QUCXV3HJJ",))
    assert [p["symbol"] for p in kept] == ["AAPL"]
    assert sorted(p["symbol"] for p in gone) == ["CDTX", "bnbx"]
    kept, gone = ex.split_positions(POS, ("OTHERACCT",))  # CDTX only excluded for Kairi
    assert sorted(p["symbol"] for p in kept) == ["AAPL", "CDTX"]
    assert ex.excluded_value(gone) == pytest.approx(1.5)


def test_auto_rule_inactive_or_untradable(monkeypatch):
    monkeypatch.setenv("EXCLUSION_AUTO_ASSET_STATUS", "1")
    ex.set_rules_for_tests([])
    look = {"AAPL": {"status": "active", "tradable": True},
            "CDTX": {"status": "inactive", "tradable": False},
            "BNBX": {"status": "active", "tradable": False}}
    kept, gone = ex.split_positions(POS, (), lookup=lambda s: look.get(s))
    assert [p["symbol"] for p in kept] == ["AAPL"]
    assert all(p["exclusion_reason"].startswith("auto") for p in gone)


def test_dust_threshold_optional(monkeypatch):
    ex.set_rules_for_tests([])
    assert len(ex.split_positions(POS)[0]) == 3  # off by default
    monkeypatch.setenv("EXCLUSION_DUST_USD", "5")
    kept, gone = ex.split_positions(POS)
    assert [p["symbol"] for p in gone] == ["bnbx"]


def test_adding_exclusion_creates_no_pnl_jump():
    """Shifting equity and baseline by the same excluded MV leaves period P&L unchanged."""
    hist = [10000.0, 10150.0, 10301.5]
    raw = adjusted_pnl(hist[-1], hist[0], 50.0)[0]
    _, gone = ex.split_positions(POS, ("PA3QUCXV3HJJ",))
    adj = ex.adjust_history(hist, ex.excluded_value(gone))
    assert adjusted_pnl(adj[-1], adj[0], 50.0)[0] == pytest.approx(raw)
    assert adj[-1] == pytest.approx(10301.5 - 301.5)


class FakeClient:
    def __init__(self):
        self._dashboard_account = dict(ACCT)

    def get_account(self):
        return dict(ACCT)

    def get_positions(self):
        return [dict(p) for p in POS]

    def get_portfolio_history(self, *a, **k):
        return {}

    def get_cash_flows(self, *a, **k):
        return 0.0


def _dashboard(monkeypatch):
    from engine.reporting import pnl_dashboard as dash
    monkeypatch.setattr(dash, "_client", lambda u, a: (FakeClient(), "paper"))
    monkeypatch.setattr(dash, "_history", lambda c, s, e: {
        "timestamps": [datetime(2026, 10, 9, 20, tzinfo=timezone.utc).isoformat()],
        "equity": [10201.5], "pnl": [], "pnl_pct": []})
    monkeypatch.setattr(dash, "_period_deposits", lambda *a, **k: (0.0, True, []))
    return dash._one_account("u", {"account_id": "acct-kairi", "account_name": "Kairi"}, "1D")


def test_dashboard_excludes_mv_and_unrealised(monkeypatch):
    d = _dashboard(monkeypatch)
    assert [p["symbol"] for p in d["positions"]] == ["AAPL"]
    assert d["equity"] == pytest.approx(10000.0)
    assert d["unrealized_pnl"] == pytest.approx(100.0)
    assert d["period_pnl"] == pytest.approx(100.0)  # same as raw 10301.5 - 10201.5
    assert d["excluded_value"] == pytest.approx(301.5)


def test_paper_email_matches_dashboard(monkeypatch):
    from scripts import daily_pnl_report as rep
    import engine.brokers.alpaca as alp
    monkeypatch.setattr(alp, "AlpacaAPI", lambda *a, **k: FakeClient())
    monkeypatch.setattr(rep, "gather_trades", lambda *a, **k: [])
    monkeypatch.setattr(rep, "gather_runs", lambda *a, **k: {})
    monkeypatch.setattr(rep, "active_runs", lambda *a, **k: [])
    monkeypatch.setattr(rep, "latest_hermes_paper_job", lambda *a, **k: None)
    monkeypatch.setattr(rep, "agent_performance", lambda *a, **k: {})
    monkeypatch.setattr(rep, "_db_ok", lambda: True)
    monkeypatch.setattr(rep, "_benchmark_returns", lambda *a, **k: {})
    d = rep.gather(keys=("k", "s"))
    dash = _dashboard(monkeypatch)
    assert d["equity"] == pytest.approx(dash["equity"])
    assert d["unrealized_pl"] == pytest.approx(dash["unrealized_pnl"])
    assert d["day_pnl"] == pytest.approx(100.0)
    assert [p["symbol"] for p in d["positions"]] == ["AAPL"]
    html = rep.render(d)
    assert "CDTX" in html and "excluded from P&amp;L" in html
    assert "<td>CDTX</td>" not in html


def test_admin_panel_lists_rules():
    from engine.web.ph_admin import render_exclusions
    html = render_exclusions(RULES)
    assert "BNBX" in html and "PA3QUCXV3HJJ" in html and "/admin/exclusions/add" in html
    assert "/admin/exclusions/delete" in html
