"""Pure regression tests for PostgreSQL float8 NaN handling."""
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import MagicMock

import pandas as pd


def test_hedge_fund_numeric_values_are_finite_and_sortable(monkeypatch):
    import engine.publicmarkets.hedge_funds as hedge_funds

    assert hedge_funds._f(float("nan")) is None
    assert hedge_funds._f(float("inf")) is None
    assert hedge_funds._f("not a number") == 0.0

    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [
        ("Finite Fund", 10.0, 3, "2026-Q1"),
        ("NaN Fund", float("nan"), 4, "2026-Q1"),
    ]
    pool = MagicMock()
    pool.return_value.get_session.return_value.__enter__.return_value = session
    monkeypatch.setattr(hedge_funds, "DatabasePool", pool)

    funds = hedge_funds.top_funds()

    assert [fund["name"] for fund in funds] == ["Finite Fund", "NaN Fund"]
    assert funds[-1]["value"] is None


def test_sector_returns_skips_nonfinite_close_groups(monkeypatch):
    import engine.publicmarkets.market_intel as market_intel

    monkeypatch.setattr(market_intel, "SECTOR_ETFS", {"Bad": "BAD", "Good": "GOOD"})
    bad = pd.DataFrame(
        {"Close": [10.0, 11.0, float("nan"), 13.0]},
        index=pd.to_datetime(["2024-01-01", "2024-12-31", "2025-01-01", "2025-12-31"]),
    )
    good = pd.DataFrame(
        {"Close": [20.0, 22.0, 30.0, 33.0]},
        index=pd.to_datetime(["2024-01-01", "2024-12-31", "2025-01-01", "2025-12-31"]),
    )

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, **_kwargs):
            return bad if self.ticker == "BAD" else good

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    result = market_intel.sector_returns()

    assert result == {"sectors": ["Bad", "Good"], "years": [2024, 2025],
                      "matrix": [[10.0, None], [10.0, 10.0]]}


def test_news_scheduler_none_move_renders_em_dash_without_float_conversion(monkeypatch):
    auth = ModuleType("engine.web.ph_auth")
    auth.current_user = lambda _session: None
    layout = ModuleType("engine.web.ph_layout")
    layout.page = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "engine.web.ph_auth", auth)
    monkeypatch.setitem(sys.modules, "engine.web.ph_layout", layout)
    from engine.web.ph_news_scheduler import _format_predicted_move

    assert _format_predicted_move(None) == "—"
    assert _format_predicted_move(1.25) == "+1.25%"
