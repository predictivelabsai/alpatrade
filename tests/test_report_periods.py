"""DB-free tests for MTD / YTD / overall arithmetic returns in the daily report."""
from datetime import datetime, timezone
from types import SimpleNamespace

import scripts.daily_pnl_report as report
from engine.brokers.alpaca import AlpacaAPI


class _FakeTradingClient:
    """Returns a canned portfolio-history payload; records requested windows."""

    def __init__(self, equity):
        self._equity = equity
        self.requests = []

    def get_portfolio_history(self, request):
        self.requests.append(request)
        n = len(self._equity)
        return {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(n)],
            "equity": list(self._equity),
            "profit_loss": [0.0] * n,
            "profit_loss_pct": [0.0] * n,
        }


def _api(equity):
    api = AlpacaAPI.__new__(AlpacaAPI)  # bypass __init__ (no real keys/network)
    api.trading_client = _FakeTradingClient(equity)
    return api


def test_get_portfolio_history_normalizes_and_drops_null_padding():
    api = AlpacaAPI.__new__(AlpacaAPI)
    api.trading_client = SimpleNamespace(
        get_portfolio_history=lambda request: {
            "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
            "equity": [None, 0, 10500.0],  # Alpaca pads pre-inception with null/0
            "profit_loss": [None, 0, 500.0],
            "profit_loss_pct": [None, 0, 0.05],
        }
    )
    hist = api.get_portfolio_history(period="1M")
    assert hist["equity"] == [10500.0]  # null/zero dropped
    assert len(hist["timestamps"]) == 1


def test_get_portfolio_history_returns_error_dict_on_failure():
    api = AlpacaAPI.__new__(AlpacaAPI)

    def _boom(request):
        raise RuntimeError("api down")

    api.trading_client = SimpleNamespace(get_portfolio_history=_boom)
    out = api.get_portfolio_history(period="1M")
    assert "error" in out


def test_period_returns_computes_arithmetic_return_from_baseline():
    # baseline (first equity point) = 10000; current equity = 12500 -> +25%
    api = _api([10000.0, 11000.0, 12000.0])
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    out = report._period_returns(api, 12500.0, now=now)

    for key in ("mtd", "ytd", "overall"):
        assert out[key] is not None
        assert out[key]["baseline"] == 10000.0
        assert abs(out[key]["abs"] - 2500.0) < 1e-6
        assert abs(out[key]["pct"] - 25.0) < 1e-6


def test_period_returns_handles_missing_history_gracefully():
    api = _api([])  # no equity points
    out = report._period_returns(api, 12500.0, now=datetime(2026, 8, 23, tzinfo=timezone.utc))
    assert out == {"mtd": None, "ytd": None, "overall": None}


def test_render_performance_shows_all_windows_including_overall():
    d = {
        "day_pnl": 92.74, "day_pct": 0.76, "last_equity": 12181.12,
        "periods": {
            "mtd": {"abs": 300.0, "pct": 2.5, "baseline": 12000.0},
            "ytd": {"abs": 2500.0, "pct": 25.0, "baseline": 10000.0},
            "overall": {"abs": 2273.86, "pct": 22.7, "baseline": 10000.0},
        },
    }
    html = report._render_performance(d)
    assert "Performance" in html
    assert "Month to date" in html
    assert "Year to date" in html
    assert "Overall (since inception)" in html
    assert "+25.00%" in html          # YTD arithmetic return
    assert "+22.70%" in html          # overall arithmetic return


def test_render_performance_marks_missing_windows_na():
    d = {"day_pnl": 10.0, "day_pct": 0.1, "last_equity": 10000.0,
         "periods": {"mtd": None, "ytd": None, "overall": None}}
    html = report._render_performance(d)
    assert "n/a" in html
    assert "Overall (since inception)" in html
