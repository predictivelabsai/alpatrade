"""DB-free tests for the daily-report analytics + render helpers (critique 1-10)."""
from types import SimpleNamespace

import pandas as pd

import scripts.daily_pnl_report as report
from engine.brokers.alpaca import AlpacaAPI


# --- Alpaca helpers -------------------------------------------------------

def test_get_portfolio_history_drops_null_padding():
    api = AlpacaAPI.__new__(AlpacaAPI)
    api.trading_client = SimpleNamespace(
        get_portfolio_history=lambda request: {
            "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
            "equity": [None, 0, 10500.0],
            "profit_loss": [None, 0, 500.0],
            "profit_loss_pct": [None, 0, 0.05],
        })
    hist = api.get_portfolio_history(period="1M")
    assert hist["equity"] == [10500.0]


def test_get_cash_flows_sums_net_amount(monkeypatch):
    api = AlpacaAPI.__new__(AlpacaAPI)
    api.api_key, api.secret_key, api.paper = "k", "s", True

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return [{"net_amount": "1000.0"}, {"net_amount": "-250"}]

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    assert abs(api.get_cash_flows("2026-08-24") - 750.0) < 1e-6


def test_get_cash_flows_zero_on_error(monkeypatch):
    api = AlpacaAPI.__new__(AlpacaAPI)
    api.api_key, api.secret_key, api.paper = "k", "s", True
    import requests

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(requests, "get", boom)
    assert api.get_cash_flows("2026-08-24") == 0.0


# --- period / benchmark / historical --------------------------------------

def _api_with_history(equities, timestamps):
    api = AlpacaAPI.__new__(AlpacaAPI)
    api.get_portfolio_history = lambda **k: {"equity": equities, "timestamps": timestamps}
    return api


def test_benchmark_returns_computes_spy_pct(monkeypatch):
    # SPY 100 -> 110 over the year window = +10%
    idx = pd.to_datetime(["2026-01-02", "2026-08-01", "2026-08-24"])
    df = pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=idx)
    import engine.feeds.market_data as md
    monkeypatch.setattr(md, "get_historical_data", lambda *a, **k: df)
    out = report._benchmark_returns(
        "2026-08-24", {"mtd": {"pct": 2.5}, "ytd": {"pct": 25.0}})
    assert round(out["ytd"], 2) == 10.0
    assert out["mtd"] is not None


def test_benchmark_returns_empty_when_no_periods():
    assert report._benchmark_returns("2026-08-24", {}) == {}


def test_historical_equity_picks_day_and_prior():
    api = _api_with_history(
        [100.0, 101.0, 102.0, 103.0],
        ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"])
    eq, prev = report._historical_equity(api, "2026-08-19")
    assert eq == 102.0 and prev == 101.0


# --- render helpers -------------------------------------------------------

def test_render_periods_shows_source_and_benchmark():
    d = {"periods": {"mtd": {"pnl": 300.0, "pct": 2.5, "days": 3, "source": "snapshot"},
                     "ytd": {"pnl": 2500.0, "pct": 25.0, "days": 1, "source": "alpaca"}},
         "benchmark": {"mtd": 1.0, "ytd": 12.0}}
    html = report._render_periods(d)
    assert "Month to date" in html and "Year to date" in html
    assert "vs SPY" in html and "excess" in html
    assert "est. from Alpaca history" in html   # ytd source=alpaca
    assert "snapshot day(s)" in html            # mtd source=snapshot


def test_render_risk_shows_realized_sharpe_drawdown():
    d = {"account_stats": {"realized_pnl": 1234.5, "sharpe": 1.8,
                           "max_drawdown": -6.3, "snapshot_days": 20}}
    html = report._render_risk(d)
    assert "Realized P&amp;L to date" in html
    assert "Sharpe" in html and "1.80" in html
    assert "Max drawdown" in html and "-6.30%" in html


def test_render_risk_empty_without_stats():
    assert report._render_risk({}) == ""


def test_render_health_banner_when_source_down():
    assert "Data unavailable" in report._render_health({"db_ok": False, "account_ok": True})
    assert "Alpaca account" in report._render_health({"db_ok": True, "account_ok": False})
    assert report._render_health({"db_ok": True, "account_ok": True}) == ""
