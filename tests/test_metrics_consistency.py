"""v0.42.0: one metrics definition across pages + guardrails."""
from datetime import date

import pytest

from engine import metrics as M
from engine.leaderboard import perf
from engine.reporting.annualize import annualize, fmt_ann
from engine.reporting.cash_flows import phantom_flow, twr_pct


RUN = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "config": {"started": "2026-09-24", "start_equity": 2725.59, "start_spy": 667.29},
    "results": {"latest": {"strategy_return_pct": 3.16, "spy_return_pct": 1.0},
                "daily": {"2026-10-08": {"equity": 2800.0, "spy": 672.0},
                          "2026-10-09": {"equity": 2819.36, "spy": 673.1}}},
}


# --------------------------------------------------------------- annualisation definition
def test_spy_2016_2026_cagr_is_13_to_14_pct():
    # SPY total return 2016-01-04 → 2026-01-02 ≈ +266% over ~2516 trading days.
    c = M.cagr_pct(266.0, 2516)
    assert 13.0 <= c <= 14.2
    assert M.spy_benchmark_issue(266.0, 2516) is None


def test_spy_check_catches_simple_annualisation():
    # simple ×252/d of the same window would read ~26.6%/yr → outside SPY bounds
    simple = 266.0 * 252 / 2516
    assert simple > 25
    assert M.spy_benchmark_issue(((1 + simple / 100) ** (2516 / 252) - 1) * 100, 2516)


def test_annualisation_any_length_flags_short_track():
    a = annualize(3.44, 12)
    assert a["annualised_pct"] is not None and a["short_period"]
    assert fmt_ann(a).endswith("*")
    assert M.cagr_pct(3.44, 1) is not None and M.cagr_pct(3.44, 0) is None
    assert M.guard("t", 3.44, a["annualised_pct"], 12) == a["annualised_pct"]


def test_annualize_headline_is_cagr():
    a = annualize(608.3, 2708)
    assert a["annualised_pct"] == pytest.approx(19.98, abs=0.05)


@pytest.mark.parametrize("tot,days", [(-100.0, 164), (-40.0, 100), (12.0, 70), (500.0, 2000)])
def test_sanity_sign_and_bounds(tot, days):
    c = M.cagr_pct(tot, days)
    assert not M.sanity_issues(tot, c, days)
    assert c >= -100 and abs(c) <= M.MAX_ABS_ANNUALISED_PCT


def test_guard_rejects_the_old_minus_153():
    # old dashboard: -100% simple-annualised over 164 days = -153.66%
    assert M.sanity_issues(-100.0, -153.66, 164)
    assert M.guard("t", -100.0, -153.66, 164) is None
    assert M.guard("t", 5.0, -3.0, 100) is None          # sign mismatch
    assert M.guard("t", 5.0, 9.0, 30) == 9.0             # short track: shown (noisy note)
    assert M.guard("t", 40.0, 5000.0, 10) == 5000.0      # short track: no magnitude cap


# --------------------------------------------------------------- phantom deposit (root cause)
def test_phantom_initial_deposit_is_ignored():
    start = date(2026, 2, 14)
    rows = [{"date": date(2026, 2, 17), "amount": 10000.0}]
    pts = [(date(2026, 2, 17), 10010.0), (date(2026, 2, 18), 10050.0)]
    ret, _ = twr_pct(start, 10000.0, pts, rows)
    assert ret == pytest.approx(0.5, abs=0.01)
    assert phantom_flow(10000.0, 10010.0, 10000.0)
    assert not phantom_flow(10000.0, 20010.0, 10000.0)   # real deposit kept


# --------------------------------------------------------------- one source across pages
def _canon(today=date(2026, 10, 12)):
    return M.live_strategy_return(RUN, flows=[], today=today)


def test_leaderboard_equals_canonical():
    lb = perf.metrics_from_run(RUN, today=date(2026, 10, 12), flows=[])
    assert lb["return_pct"] == pytest.approx(_canon()["return_pct"])


def test_live_page_uses_canonical(monkeypatch):
    from engine.web import ph_runs
    c = _canon()
    monkeypatch.setattr(M, "live_return_for_user", lambda uid, run, today=None, ttl=0: c)
    html = ph_runs._live_row({"run_id": RUN["run_id"], "run_config": RUN["config"],
                              "run_results": RUN["results"], "status": "running",
                              "started_at": "2026-09-24"}, "u1")
    assert f"{c['return_pct']:+.2f}%" in html
    assert "+3.16%" not in html                             # stale runner snapshot no longer shown


def test_live_account_since_inception_uses_canonical():
    c = _canon()
    perf_block = {"account_return_pct": 3.66, "spy_return_pct": 1.2, "excess_pct": 2.46}
    out = M.apply_canonical_since_inception(perf_block, c, "live_account")
    assert out["account_return_pct"] == pytest.approx(c["return_pct"])
    assert out["account_return_pct_intraday"] == 3.66
    assert out["excess_pct"] == pytest.approx(out["account_return_pct"] - out["spy_return_pct"])


def test_check_consistency_logs_mismatch(caplog):
    assert M.check_consistency("x", {"a": 3.44, "b": 3.44})
    assert not M.check_consistency("x", {"a": 3.16, "b": 3.66})
    assert "METRICS_MISMATCH" in caplog.text
    assert M.recent_mismatches()[-1]["name"] == "x"


# --------------------------------------------------------------- backtests + reaper
def test_backtest_figures_fallback():
    f = M.backtest_figures({"total_return": 36.71, "sharpe_ratio": 8.11, "sortino_ratio": 1.8e15})
    assert f["total_return"] == 36.71 and f["sharpe_ratio"] == 8.11 and not f["flags"]
    assert M.backtest_figures({"sharpe_ratio": 40})["flags"]


def test_reaper_never_touches_live():
    from engine import runs_reaper as R
    assert all("live" not in modes for modes, _, _ in R.RULES)
    sql = R.build_sql(False)
    assert "mode <> 'live'" in sql and "completed_at = NOW()" in sql
    assert R.build_sql(True).lstrip().startswith("SELECT")
