from datetime import date

from engine.reporting.annualize import annualize, trading_days_between, nyse_holidays, fmt_ann


def test_simple_and_compound():
    a = annualize(1.0, 21)
    assert abs(a["simple_pct"] - 12.0) < 1e-9
    assert abs(a["compound_pct"] - ((1.01 ** 12) - 1) * 100) < 1e-9


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
