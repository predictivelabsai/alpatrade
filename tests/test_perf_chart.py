"""Shared performance chart (dashboard live/paper, /live/account, strategy pages)."""
from datetime import date

from engine.reporting.cash_flows import flow_rows
from engine.reporting.perf_chart import chart_html, performance_series, period_returns

# Real shape of account 885504372: runner start 2026-09-24 @ 2725.59, $2,000 CSD on 2026-10-09.
DATES = ["2026-09-24", "2026-09-25", "2026-09-30", "2026-10-08", "2026-10-09"]
EQ = [2726.61, 2727.91, 2745.36, 2808.58, 4819.61]
SPY = [767.29, 768.71, 764.90, 774.30, 778.57]
FLOWS = flow_rows([{"activity_type": "CSD", "date": "2026-10-09", "net_amount": "2000"}])


def _series():
    return performance_series(DATES, EQ, SPY, FLOWS, 2725.59, 767.29, start_date="2026-09-24")


def test_deposit_day_has_no_jump():
    s = _series()
    jump = s["index"][-1] / s["index"][-2] - 1
    assert abs(jump - ((4819.61 - 2000) / 2808.58 - 1)) < 1e-6 and jump < 0.01
    assert abs(s["index"][-1] - 2819.61 / 2725.59 * 100) < 1e-3   # +3.45% since inception
    raw = performance_series(DATES, EQ, SPY, None, 2725.59, 767.29, start_date="2026-09-24")
    assert raw["index"][-1] > 170  # without flows the deposit would be a +71% jump


def test_mtd_ytd_inception_rows():
    pr = period_returns(_series(), date(2026, 10, 11))
    assert abs(pr["inception"]["account_pct"] - 3.4495) < 1e-3
    mtd = pr["mtd"]
    assert mtd["base_date"] == "2026-09-30" and not mtd["clipped"]
    assert abs(mtd["account_pct"] - ((2808.58 / 2745.36) * (2819.61 / 2808.58) - 1) * 100) < 1e-3
    assert abs(mtd["spy_pct"] - (778.57 / 764.90 - 1) * 100) < 1e-3
    assert abs(mtd["excess_pct"] - (mtd["account_pct"] - mtd["spy_pct"])) < 1e-9
    assert pr["ytd"]["clipped"] and pr["ytd"]["account_pct"] == pr["inception"]["account_pct"]


def test_chart_html_is_strategy_page_chart():
    h = chart_html("x1", _series(), highlight=("2026-10-01", "2026-10-11"))
    assert "xaxis:{type:'date'}" in h and "#1F5D43" in h and "Plotly.newPlot('x1'" in h
    assert '"hl": ["2026-10-01", "2026-10-09"]' in h
    assert chart_html("x2", {}) == ""
    ytd = chart_html("x3", _series(), highlight=("2026-01-01", "2026-10-11"))
    assert '"hl": ["2026-09-24", "2026-10-09"]' in ytd


def test_strategy_page_uses_shared_chart():
    from engine.web.ph_leaderboard import detail_html
    ser = _series()
    h = detail_html({"id": 1}, {"is_backtest": False}, {"series": ser, "trades": []})
    assert "pc-data-lb-eq-1" in h and "Plotly.newPlot('lb-eq-__SID__'" not in h


def test_live_panel_labels_and_rows():
    from engine.web.ph_pnl import _live_spy_panel
    perf = {"started": "2026-09-24", "start_equity": 2725.59, "account_pnl": 94.02,
            "account_return_pct": 3.4495, "spy_start": 767.29, "spy": 778.57,
            "spy_return_pct": 1.47, "excess_pct": 1.98, "strategy_pnl": 86.33, "closed_trades": 12}
    h = _live_spy_panel({"linked": True, "perf": perf, "curves": {"series": _series()}}, "mtd")
    assert "since start" not in h and "Live run started" not in h
    assert "Inception" in h and "Account since inception" in h and "SPY since inception" in h
    assert "data-period='mtd'" in h and "data-period='ytd'" in h and "data-period='inception'" in h
    assert "Excess vs SPY" in h and "+3.45%" in h
    assert "deposits and withdrawals are excluded" in h and "are included." not in h.split("pre-existing")[0][-5:]
    assert "dash-live-equity-chart" in h


def test_three_charts_from_same_series():
    from engine.reporting.perf_chart import risk_series
    s = _series()
    r = risk_series(s)
    assert len(r["drawdown_pct"]) == len(s["dates"]) == len(r["daily_return_pct"])
    # deposit day: daily return is the TWR step, not +71%
    assert abs(r["daily_return_pct"][-1] - ((4819.61 - 2000) / 2808.58 - 1) * 100) < 1e-3
    assert max(r["daily_return_pct"]) < 5 and min(r["drawdown_pct"]) <= 0
    assert all(v <= 0 for v in r["spy_drawdown_pct"] if v is not None)
    assert abs(r["spy_daily_return_pct"][-1] - (778.57 / 774.30 - 1) * 100) < 1e-3
    h = chart_html("z", s)
    assert "id='z-dd'" in h and "id='z-dr'" in h and "SPY drawdown %" in h and "SPY daily %" in h
    assert "id='z-dr'" not in chart_html("z", s, daily=False)


def test_all_surfaces_render_three_charts():
    from engine.web.ph_leaderboard import detail_html
    from engine.web.ph_live_account import _curves_section
    from engine.web.ph_pnl import _live_spy_panel, _paper_chart
    s = _series()
    pages = [detail_html({"id": 1}, {"is_backtest": False}, {"series": s, "trades": []}),
             _curves_section({"series": s}),
             _live_spy_panel({"linked": True, "perf": {"started": "2026-09-24"}, "curves": {"series": s}}),
             _paper_chart({"performance": s}, "MTD")]
    for h in pages:
        assert h.count("data-perf-chart='1'") == 1 and "-dd'" in h and "-dr'" in h
        assert "Plotly.newPlot('lb-dd-" not in h  # old leaderboard-only JS is gone
