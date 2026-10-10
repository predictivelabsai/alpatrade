"""Deposits / withdrawals are not P&L: day / MTD / YTD / since-start and the leaderboard
exclude external cash flows (engine/reporting/cash_flows.py). Scenario mirrors the
2026-10-09 $2,000 instant-ACH deposit (CSD) on the live account."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from engine.brokers import alpaca_live_readonly as ro
from engine.leaderboard import perf
from engine.reporting import cash_flows as cf

DEPOSIT = {"activity_type": "CSD", "date": "2026-10-09", "net_amount": "2000", "status": "executed",
           "description": "type: instant_ach, transfer_id: b29c1438-39a0-4cb9-b24a-6dfb25d6b561, direction: INCOMING",
           "id": "20261009000000000::c219"}
WITHDRAWAL = {"activity_type": "CSW", "date": "2026-09-15", "net_amount": "-500", "status": "executed"}
FILL = {"activity_type": "FILL", "date": "2026-10-09", "net_amount": "999"}


def test_flow_rows_and_window():
    rows = cf.flow_rows([DEPOSIT, WITHDRAWAL, FILL, {**DEPOSIT, "status": "canceled"}])
    assert [r["type"] for r in rows] == ["CSD", "CSW"]
    assert cf.net_flows(rows, date(2026, 10, 1), date(2026, 10, 9)) == 2000
    assert cf.net_flows(rows, date(2026, 10, 9), date(2026, 10, 9)) == 0   # in baseline already
    assert cf.net_flows(rows, None, date(2026, 10, 9)) == 1500


def test_adjusted_pnl_deposit_is_not_profit():
    pnl, pct = cf.adjusted_pnl(4819.34, 2745.36, 2000)
    assert pnl == pytest.approx(73.98)
    assert pct == pytest.approx(73.98 / 4745.36 * 100)
    assert cf.adjusted_pnl(4819.34, 2745.36, 0)[0] == pytest.approx(2073.98)  # the old bug
    assert cf.adjusted_pnl(None, 1, 0) == (None, None)


def test_adjust_day_summary():
    s = {"equity": 4819.34, "last_equity": 2808.58, "day_pl": 2010.76}
    out = cf.adjust_day(s, cf.flow_rows([DEPOSIT]), date(2026, 10, 9))
    assert out["day_pl"] == pytest.approx(10.76) and out["day_net_deposits"] == 2000
    assert cf.adjust_day(s, None, date(2026, 10, 9))["cash_flows_ok"] is False
    assert cf.prev_weekday(date(2026, 10, 12)) == date(2026, 10, 9)  # Monday -> Friday


def test_readonly_client_cash_flows_only():
    calls = []

    class H:
        def get(self, url, headers=None, params=None, timeout=None):
            calls.append((url, params))
            return SimpleNamespace(status_code=200, json=lambda: [DEPOSIT])
    c = ro.LiveReadOnlyClient("AK1234567890", "SK1234567890123", http=H())
    assert c.get_cash_flows(after="2026-09-30") == [DEPOSIT]
    assert calls[0][1]["activity_types"] == "CSD,CSW,JNLC"
    with pytest.raises(ro.LiveReadOnlyError):
        c._get("/v2/account/activities", {"activity_types": "FILL"})
    with pytest.raises(ro.LiveReadOnlyError):
        c._get("/v2/account/activities", {})


def test_dashboard_live_mtd_excludes_deposit(monkeypatch):
    from engine.reporting import pnl_dashboard as pd
    ts = [int(datetime(2026, 10, d, 4, tzinfo=timezone.utc).timestamp()) for d in (1, 8)]

    class C:
        def __init__(self, *a, **k): pass
        def snapshot(self):
            return {"account": {"equity": "4819.34", "last_equity": "2808.58", "cash": "3320.02",
                                "buying_power": "3320.02"}, "positions": [], "orders": []}
        def get_portfolio_history(self, *a, **k):
            return {"timestamp": ts, "equity": [2745.36, 2808.58]}
        def get_cash_flows(self, after, until=None):
            return [DEPOSIT, WITHDRAWAL]
    monkeypatch.setattr(ro, "LiveReadOnlyClient", C)
    monkeypatch.setattr("engine.live_accounts.get_live_account_credentials",
                        lambda uid, acct=None: {"api_key": "k", "secret_key": "s", "account_number": "885504372"})
    monkeypatch.setattr(pd, "period_bounds", lambda p, now=None: (
        datetime(2026, 10, 1, 4, tzinfo=timezone.utc), datetime(2026, 10, 9, 21, tzinfo=timezone.utc)))
    a = pd._one_live_account("u", {"account_id": "live:885504372", "account_name": "x",
                                   "account_number": "885504372"}, "mtd")
    assert a["period_pnl"] == pytest.approx(73.98)
    assert a["net_deposits"] == 2000 and a["cash_flows_ok"] is True
    agg = pd._aggregate([a], "mtd")
    assert agg["period_pnl"] == pytest.approx(73.98) and agg["net_deposits"] == 2000


RUN = {"run_id": "r1",
       "config": {"started": "2026-09-24", "start_equity": 2725.59, "start_spy": 767.29},
       "results": {"daily": {"2026-09-24": {"equity": 2725.59, "spy": 767.29},
                             "2026-10-08": {"equity": 2808.58, "spy": 774.30},
                             "2026-10-09": {"equity": 4819.34, "spy": 775.00}}}}


def test_leaderboard_time_weighted_excludes_deposit():
    raw = perf.metrics_from_run(RUN, today=date(2026, 10, 9))  # no flow data: old ratio
    assert raw["return_pct"] == pytest.approx((4819.34 / 2725.59 - 1) * 100)  # +76.8%
    m = perf.metrics_from_run(RUN, today=date(2026, 10, 9), flows=cf.flow_rows([DEPOSIT]))
    expect = ((2808.58 / 2725.59) * ((4819.34 - 2000) / 2808.58) - 1) * 100
    assert m["return_pct"] == pytest.approx(expect)
    assert m["return_pct"] < 4
    assert m["alpha_pct"] == pytest.approx(m["return_pct"] - (775.00 / 767.29 - 1) * 100)
    assert m["annualised_pct"] is not None and m["annualised_short"]  # 12 sessions < 63: hint only
    assert m["net_deposits"] == 2000
    assert "Short period" in perf.annualised_tip(m)
    assert perf.rank_key(m)[1] == 0  # still ranked as a live strategy with figures


def test_daily_live_email_day_pnl_excludes_deposit(monkeypatch):
    import tests.test_daily_live_report as t
    from scripts import daily_live_report as rep
    dep = {**DEPOSIT, "date": "2026-09-25", "net_amount": "150"}

    class H(t.FakeHTTP):
        def get(self, url, headers=None, params=None, timeout=None):
            if url.endswith("/v2/account/activities"):
                self.calls.append(("/v2/account/activities", params))
                return SimpleNamespace(status_code=200, json=lambda: [dep])
            return super().get(url, headers, params, timeout)
    for k, v in {"live_run": lambda uid, acct=None: t.RUN, "runner_trades": lambda rid: t.RTRADES,
                 "_db_ok": lambda: True, "spy_close": lambda day, run: 612.0,
                 "dip_signals": lambda *a: []}.items():
        monkeypatch.setattr(rep, k, v)
    monkeypatch.setattr("engine.reporting.live_perf.equity_curves", lambda *a, **k: {})
    d = rep.gather(t._client(H()), t.TARGET, now=t.SAT)
    # equity 10150 vs prior close 10000 with a $150 deposit on the day -> $0 P&L
    assert d["day_deposits"] == 150
    assert d["day_pnl"] == pytest.approx(0.0)
    assert d["perf"]["net_deposits"] == 150
    assert d["perf"]["account_pnl"] == pytest.approx(10150 - 10000 - 150)


def test_twr_ignores_deposit_day():
    from datetime import date
    from engine.reporting.cash_flows import twr_pct
    rows = [{"date": date(2026, 10, 9), "amount": 2000.0, "type": "CSD", "description": ""}]
    pts = [(date(2026, 10, 8), 2808.58), (date(2026, 10, 9), 4819.21)]
    ret, dep = twr_pct(date(2026, 10, 7), 2808.58, pts, rows)
    assert dep == 2000.0
    assert abs(ret - (4819.21 - 2000 - 2808.58) / 2808.58 * 100) < 1e-9
