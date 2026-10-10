"""Backtest leaderboard rows: headline annualised = SIMPLE total × 252 / trading days,
alpha = simple strategy − simple SPY over the same days, CAGR only in the tooltip."""
import pytest

from engine.leaderboard import perf
from engine.leaderboard import semi7


def _row(tot, spy, days, start="2026-02-11", end="2026-10-09", cagr=9999.0):
    return {"kind": "backtest", "backtest_metrics": {
        "period_start": start, "period_end": end, "trading_days": days,
        "total_return_pct": tot, "spy_return_pct": spy,
        "annualised_pct": cagr, "spy_annualised_pct": cagr, "alpha_annualised_pct": cagr}}


def test_short_window_uses_simple_not_cagr():
    # Semi 7 shape: +550.8% over 167 sessions; CAGR would be ~+1,600%
    m = perf.backtest_metrics(_row(550.8, 13.4, 167))
    assert m["annualised_pct"] == pytest.approx(550.8 * 252 / 167)          # ~831%
    assert m["spy_annualised_pct"] == pytest.approx(13.4 * 252 / 167)
    assert m["alpha_pct"] == pytest.approx((550.8 - 13.4) * 252 / 167)
    assert m["annualised_cagr_pct"] > 1500                                   # tooltip only
    assert m["annualised_pct"] < m["annualised_cagr_pct"]


def test_stored_cagr_ignored():
    m = perf.backtest_metrics(_row(10.0, 5.0, 126))
    assert m["annualised_pct"] == pytest.approx(20.0)
    assert m["alpha_pct"] == pytest.approx(10.0)


def test_long_window_and_negative():
    m = perf.backtest_metrics(_row(555.7, 356.2, 2708, "2016-01-04"))
    assert m["annualised_pct"] == pytest.approx(555.7 * 252 / 2708)
    assert m["annualised_cagr_pct"] == pytest.approx((6.557 ** (252 / 2708) - 1) * 100)
    neg = perf.backtest_metrics(_row(-79.1, 356.2, 2708, "2016-01-04"))
    assert neg["annualised_pct"] == pytest.approx(-79.1 * 252 / 2708)


def test_days_from_dates_when_missing():
    m = perf.backtest_metrics(_row(10.0, 5.0, None, "2026-01-02", "2026-03-31"))
    assert m["trading_days"] > 55 and m["annualised_pct"] == pytest.approx(10.0 * 252 / m["trading_days"])


def test_no_total_no_data():
    assert not perf.backtest_metrics(_row(None, 5.0, 100))["has_data"]


def test_tooltips_and_labels():
    from engine.web import ph_leaderboard as lb
    m = perf.backtest_metrics(_row(550.8, 13.4, 167))
    tip = perf.annualised_tip(m)
    assert "× 252 / 167" in tip and "CAGR" in tip
    assert "simple" in perf.alpha_tip(m)
    cell = lb._alpha_cell(m)
    assert "simple, ×252/trading days" in cell and "CAGR" not in cell.split("data-tip")[0]
    assert "simple, ×252/trading days" in lb._annualised_cell(m)


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
