"""Unit tests for live account vs SPY performance helpers."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from engine.reporting import live_perf as lp


class HistClient:
    def get_portfolio_history(self, start, end, timeframe="1D"):
        return {
            "timestamp": [
                int(datetime(2026, 9, 24, 20, tzinfo=timezone.utc).timestamp()),
                int(datetime(2026, 9, 25, 20, tzinfo=timezone.utc).timestamp()),
            ],
            "equity": [10000.0, 10150.0],
        }


def test_performance_since_start_vs_spy():
    run = {
        "run_id": "r1",
        "config": {"start_equity": 10000.0, "start_spy": 600.0, "started": "2026-09-24"},
        "results": {"latest": {"realized_pnl": 10.0, "closed_trades": 1}},
    }
    p = lp.performance_since_start(
        10150.0, run, day=date(2026, 9, 25), spy=612.0,
        runner_open=[{"upl": 5.0}],
    )
    assert p["account_return_pct"] == pytest.approx(1.5)
    assert p["spy_return_pct"] == pytest.approx(2.0)
    assert p["excess_pct"] == pytest.approx(-0.5)
    assert p["strategy_pnl"] == 15.0


def test_equity_curves_index_and_svg(monkeypatch):
    def fake_hist(symbol, start, end, timeframe="day"):
        import pandas as pd
        idx = pd.to_datetime(["2026-09-24", "2026-09-25"])
        return pd.DataFrame({"Close": [600.0, 612.0]}, index=idx)

    monkeypatch.setattr("engine.feeds.market_data.get_historical_data", fake_hist)
    run = {
        "run_id": "r1",
        "config": {"start_equity": 10000.0, "start_spy": 600.0, "started": "2026-09-24"},
    }
    curves = lp.equity_curves(HistClient(), run, end=date(2026, 9, 25))
    assert curves["dates"] == ["2026-09-24", "2026-09-25"]
    assert curves["account"][1] == 10150.0
    assert curves["account_idx"][0] == 100.0
    assert curves["spy_idx"][1] == pytest.approx(102.0)
    svg = lp.svg_equity_chart(curves)
    assert "svg" in svg and "Account" in svg and "SPY" in svg
    png = lp.png_equity_chart(curves)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 200


def test_empty_without_run():
    assert lp.performance_since_start(100, {}, spy=1) == {}
    assert lp.equity_curves(HistClient(), {}) == {}
    assert lp.svg_equity_chart({}) == ""
    assert lp.png_equity_chart({}) == b""


def test_png_equity_chart_has_dates_and_hires():
    """Email PNG must be sharp (hi-res default) and include axis date ticks."""
    from io import BytesIO
    from PIL import Image
    curves = {
        "dates": ["2026-09-01", "2026-09-15", "2026-09-30", "2026-10-06"],
        "account_idx": [100.0, 102.0, 101.0, 104.0],
        "spy_idx": [100.0, 101.0, 100.5, 102.0],
    }
    png = lp.png_equity_chart(curves)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    im = Image.open(BytesIO(png))
    # Default display size is larger than the old 560x200 email chart.
    assert im.size[0] >= 800 and im.size[1] >= 300
    # Hi-res path still works when scale=1
    small = lp.png_equity_chart(curves, width=400, height=160, scale=1)
    assert small[:8] == b"\x89PNG\r\n\x1a\n"
