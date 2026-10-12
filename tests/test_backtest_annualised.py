"""Backtest leaderboard rows (v0.42.0): headline annualised = CAGR (≥60 days, bounded),
alpha = CAGR − SPY CAGR over the same days."""
import pytest

from engine.leaderboard import perf
from engine.leaderboard import semi7


def _row(tot, spy, days, start="2026-02-11", end="2026-10-09", cagr=9999.0):
    return {"kind": "backtest", "backtest_metrics": {
        "period_start": start, "period_end": end, "trading_days": days,
        "total_return_pct": tot, "spy_return_pct": spy,
        "annualised_pct": cagr, "spy_annualised_pct": cagr, "alpha_annualised_pct": cagr}}


def test_short_window_cagr_out_of_bounds_shows_total():
    # Semi 7 shape: +550.8% over 167 sessions -> CAGR ~+1,600%/yr exceeds the 1000% bound
    m = perf.backtest_metrics(_row(550.8, 13.4, 167))
    assert m["annualised_pct"] is None and m["annualised_out_of_bounds"]
    assert m["annualised_cagr_pct"] > 1500
    assert perf.ann_display(m) == "n/a (>1000%/yr)"
    assert "sanity bound" in perf.annualised_tip(m)


def test_stored_cagr_ignored():
    m = perf.backtest_metrics(_row(10.0, 5.0, 126))
    assert m["annualised_pct"] == pytest.approx((1.10 ** 2 - 1) * 100)
    assert m["alpha_pct"] == pytest.approx((1.10 ** 2 - 1.05 ** 2) * 100)


def test_long_window_and_negative():
    m = perf.backtest_metrics(_row(555.7, 356.2, 2708, "2016-01-04"))
    assert m["annualised_pct"] == pytest.approx((6.557 ** (252 / 2708) - 1) * 100)
    assert 13 <= m["spy_annualised_pct"] <= 16       # SPY-like CAGR, not simple ~33%
    neg = perf.backtest_metrics(_row(-79.1, 356.2, 2708, "2016-01-04"))
    assert neg["annualised_pct"] == pytest.approx((0.209 ** (252 / 2708) - 1) * 100)
    assert neg["annualised_pct"] < 0


def test_days_from_dates_when_missing():
    m = perf.backtest_metrics(_row(10.0, 5.0, None, "2026-01-02", "2026-03-31"))
    assert m["trading_days"] > 55
    assert m["annualised_pct"] == pytest.approx((1.10 ** (252 / m["trading_days"]) - 1) * 100)


def test_no_total_no_data():
    assert not perf.backtest_metrics(_row(None, 5.0, 100))["has_data"]


def test_tooltips_and_labels():
    from engine.web import ph_leaderboard as lb
    m = perf.backtest_metrics(_row(55.0, 13.4, 167))
    tip = perf.annualised_tip(m)
    assert "CAGR" in tip and "167 trading days" in tip
    assert "CAGR" in perf.alpha_tip(m)
    assert "CAGR ·" in lb._alpha_cell(m) and "simple" not in lb._alpha_cell(m)
    assert "CAGR" in lb._annualised_cell(m)


def test_simple_from_cagr_roundtrip():
    # 20% CAGR over exactly one 252-session window -> simple 20%
    v = perf.simple_from_cagr(20.0, "2025-01-02", "2025-12-31")
    assert v == pytest.approx(20.0, rel=0.02)


def test_semi7_build_metrics_simple():
    wf = {"rows": [{"test_period": "2026-02-11→2026-03-13", "oos_ret": 0.10, "oos_pnl": 1000},
                   {"test_period": "2026-03-13→2026-04-12", "oos_ret": 0.10, "oos_pnl": 1000}],
          "metrics": {}}
    bm = semi7.build_metrics(wf, {"2026-02-10": 100.0, "2026-04-10": 102.0})
    d = bm["trading_days"]
    assert bm["total_return_pct"] == pytest.approx(21.0)
    assert bm["annualised_pct"] == pytest.approx(21.0 * 252 / d)
    assert bm["alpha_annualised_pct"] == pytest.approx((21.0 - 2.0) * 252 / d)
    assert bm["annualised_cagr_pct"] > bm["annualised_pct"]
