from datetime import date

from engine.reporting.annualize import tooltip, annualize, trading_days_between, nyse_holidays, fmt_ann


def test_simple_and_compound():
    a = annualize(6.0, 126)
    assert abs(a["simple_pct"] - 12.0) < 1e-9
    assert abs(a["compound_pct"] - ((1.06 ** 2) - 1) * 100) < 1e-9
    a = annualize(1.0, 21, min_days=1)
    assert abs(a["simple_pct"] - 12.0) < 1e-9


def test_short_periods_are_not_annualised():
    # v0.42.0: headline = CAGR, only from 60 trading days; before that n/a + total.
    a = annualize(3.4495, 12)
    assert a["annualised_pct"] is None and a["short_period"]
    assert fmt_ann(a) == "n/a (<60d)"
    assert "Not annualised" in tooltip(a)
    b = annualize(5.0, 63)
    assert b["short_period"] is False
    assert abs(b["annualised_pct"] - (1.05 ** (252 / 63) - 1) * 100) < 1e-9


def test_guard_zero_days():
    a = annualize(5.0, 0)
    assert a["simple_pct"] is None and fmt_ann(a) == "—"
    assert annualize(None, 10)["simple_pct"] is None


def test_trading_days():
    # Oct 2026: Thu 1 .. Wed 7 -> 5 trading days
    assert trading_days_between(date(2026, 10, 1), date(2026, 10, 7)) == 5
    assert trading_days_between(date(2026, 10, 3), date(2026, 10, 4)) == 0
    assert date(2026, 4, 3) in nyse_holidays(2026)  # Good Friday
    assert date(2026, 7, 3) in nyse_holidays(2026)  # July 4 observed
    assert trading_days_between(date(2025, 1, 1), date(2025, 12, 31)) == 251  # rule-based (2025 actual 250 incl. ad-hoc Jan 9 closure)


def test_dashboard_period_annualized_counts_completed_days():
    from datetime import datetime, timezone
    from engine.reporting.pnl_dashboard import period_annualized
    pre_open = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)   # 01:00 ET Wed
    post_close = datetime(2026, 10, 7, 21, 0, tzinfo=timezone.utc)  # 17:00 ET Wed
    assert period_annualized("mtd", 1.0, pre_open)["days"] == 4
    assert period_annualized("mtd", 1.0, post_close)["days"] == 5
    assert period_annualized("mtd", 1.0, datetime(2026, 10, 1, 5, tzinfo=timezone.utc))["simple_pct"] is None


def test_since_start_annualized_uses_run_start(monkeypatch):
    from datetime import datetime, timezone
    from engine.reporting import pnl_dashboard as pd
    monkeypatch.setattr(pd, "_strategy_run", lambda *a, **k: {
        "run_id": "r1", "config": {"started": "2026-09-24", "start_equity": 1000.0}})
    now = datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)  # after close ET
    a = pd.since_start_annualized("u", {"account_id": "live:123", "equity": 1031.0}, now)
    assert a["basis"] == "since_start" and a["start_date"] == "2026-09-24"
    assert a["days"] == 9
    assert abs(a["return_pct"] - 3.1) < 1e-9
    assert abs(a["simple_pct"] - 3.1 * 252 / 9) < 1e-9 and a["short_period"]  # hint only


def test_ann_metric_label_since_start():
    from engine.web.ph_pnl import _ann_metric
    h = _ann_metric({"annualized": {**annualize(3.1, 9), "basis": "since_start",
                                    "start_date": "2026-09-24"}}, "MTD")
    assert "since inception · 9d" in h and "n/a" in h
    h = _ann_metric({"annualized": {**annualize(10.98, 164), "basis": "since_start"}}, "MTD")
    assert "+17.3" in h


def test_email_headline_since_start():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "dlr", pathlib.Path(__file__).parents[1] / "scripts" / "daily_live_report.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    h = m._ann_block({"annualized": {"since_start": {**annualize(10.98, 164)}}})
    assert "Annualised return (since start · 164d)" in h and "CAGR" in h
    short = m._ann_block({"annualized": {"since_start": {**annualize(3.1, 9)}}})
    assert "Annualised return (since start" not in short
